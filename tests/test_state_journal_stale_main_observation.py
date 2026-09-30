"""Regression coverage for queued stale-main runtime observation forks."""
import os
import unittest
from unittest.mock import patch

from runtime.state import bootstrap_state
from state_journal.contracts import Conflict, REPOSITORY, digest
from state_journal.events import make_change, make_event
from state_journal.github_reducer import reduce_from_provider
from state_journal.reducer import checkpoint, make_snapshot
from state_journal.transport import EVENT_PREFIX
from test_state_journal import RUNTIME_PROOFS, runtime_tick

CURRENT = "b" * 40
STALE = "a" * 40
OTHER = "c" * 40


def provider(event, artifact_id):
    return {
        "kind": "GITHUB_ACTIONS",
        "repository": REPOSITORY,
        "artifact_id": artifact_id,
        "archive_digest": "sha256:" + f"{artifact_id:064x}"[-64:],
        "source_run_id": int(event["run_id"]),
        "source_run_attempt": event.get("run_attempt", 1),
        "source_sha": event["source_sha"],
        "workflow_id": 45,
        "workflow_path": ".github/workflows/runtime-event-observe.yml",
        "source_conclusion": "success",
        "event_hash": event["event_hash"],
        "job_id": artifact_id + 100,
    }


def event(run_id, source_sha, before, after):
    return make_event(
        "runtime-worker",
        run_id,
        source_sha,
        [make_change("runtime", before, after, proofs=RUNTIME_PROOFS[digest(after)])],
        run_attempt=1,
    )


class StaleMainObservationForkTests(unittest.TestCase):
    def setUp(self):
        self.runtime = bootstrap_state(now="2026-09-30T08:00:00Z")
        self.stale_after = runtime_tick(self.runtime, rid="REPO-001", at="2026-09-30T08:01:00Z")
        self.current_after = runtime_tick(self.runtime, rid="REPO-002", at="2026-09-30T08:02:00Z")
        self.stale = event("101", STALE, self.runtime, self.stale_after)
        self.current = event("102", CURRENT, self.runtime, self.current_after)
        base = checkpoint({"runtime": self.runtime}, {"runtime": "fixture:runtime"})
        self.snapshot = make_snapshot(base, [], sequence=7, evidence={})

    def reader(self, rows):
        mapping = {row[0]["id"]: (row[1], row[2]) for row in rows}

        class Reader:
            def list_recent_journal_artifacts(self, *args, **kwargs):
                return [row[0] for row in rows]

            def list_recent_artifacts(self, *args, **kwargs):
                return [row[0] for row in rows]

            def event(self, artifact, _upload_steps):
                return mapping[artifact["id"]]

            def get(self, suffix):
                if suffix == f"/compare/{STALE}...{CURRENT}":
                    return {"merge_base_commit": {"sha": STALE}, "status": "ahead"}
                raise AssertionError("unexpected API request: " + suffix)

        return Reader()

    def artifact(self, artifact_id, event):
        return {
            "id": artifact_id,
            "name": f"{EVENT_PREFIX}{event['run_id']}-runtime-worker-{event['source_sha']}-1",
            "expired": False,
            "digest": provider(event, artifact_id)["archive_digest"],
            "workflow_run": {"id": int(event["run_id"]), "head_branch": "main", "head_sha": event["source_sha"]},
        }

    def test_exact_current_main_observation_supersedes_ancestor_fork(self):
        rows = [
            (self.artifact(11, self.stale), self.stale, provider(self.stale, 11)),
            (self.artifact(12, self.current), self.current, provider(self.current, 12)),
        ]
        with patch("state_journal.github_reducer.restore_snapshot", return_value=self.snapshot), \
             patch.dict(os.environ, {"GITHUB_SHA": CURRENT}, clear=False):
            candidate, receipt = reduce_from_provider(
                self.reader(rows), since="2026-09-30T00:00:00Z",
                current_run="999", upload_steps={}
            )
        self.assertEqual(candidate["projection"]["states"]["runtime"], self.current_after)
        self.assertEqual(receipt["new_deliveries"], 1)
        self.assertEqual(receipt["superseded_stale_main_observation_count"], 1)
        superseded = receipt["superseded_stale_main_observations"][0]
        self.assertEqual(superseded["artifact_id"], 11)
        self.assertEqual(superseded["source_sha"], STALE)
        self.assertEqual(superseded["superseded_by_source_sha"], CURRENT)

    def test_no_exact_current_main_candidate_still_fails_closed(self):
        other = event("103", OTHER, self.runtime, self.current_after)
        rows = [
            (self.artifact(11, self.stale), self.stale, provider(self.stale, 11)),
            (self.artifact(13, other), other, provider(other, 13)),
        ]
        with patch("state_journal.github_reducer.restore_snapshot", return_value=self.snapshot), \
             patch.dict(os.environ, {"GITHUB_SHA": CURRENT}, clear=False), \
             self.assertRaises(Conflict):
            reduce_from_provider(
                self.reader(rows), since="2026-09-30T00:00:00Z",
                current_run="999", upload_steps={}
            )


if __name__ == "__main__":
    unittest.main()
