"""Regression coverage for non-dominant exact-main runtime observations."""
import os
import unittest
from unittest.mock import patch

from runtime.state import bootstrap_state
from state_journal.contracts import JournalError, REPOSITORY, digest
from state_journal.events import make_change, make_event
from state_journal.github_reducer import reduce_from_provider
from state_journal.reducer import checkpoint, make_snapshot
from state_journal.transport import EVENT_PREFIX
from test_state_journal import RUNTIME_PROOFS, runtime_tick

CURRENT = "b" * 40
STALE = "a" * 40


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


def runtime_event(run_id, source_sha, before, after):
    return make_event(
        "runtime-worker",
        run_id,
        source_sha,
        [make_change("runtime", before, after, proofs=RUNTIME_PROOFS[digest(after)])],
        run_attempt=1,
    )


class RuntimeForkParityRegressionTests(unittest.TestCase):
    def test_exact_main_observation_cannot_discard_a_newer_stale_source_fork(self):
        before = bootstrap_state(now="2026-09-30T08:00:00Z")
        stale_after = runtime_tick(before, rid="REPO-001", at="2026-09-30T08:02:00Z")
        current_after = runtime_tick(before, rid="REPO-001", at="2026-09-30T08:01:00Z")
        stale = runtime_event("101", STALE, before, stale_after)
        current = runtime_event("102", CURRENT, before, current_after)
        rows = [
            (11, stale, provider(stale, 11)),
            (12, current, provider(current, 12)),
        ]
        artifacts = [
            {
                "id": artifact_id,
                "name": f"{EVENT_PREFIX}{event['run_id']}-runtime-worker-{event['source_sha']}-1",
                "expired": False,
                "digest": source["archive_digest"],
                "workflow_run": {
                    "id": int(event["run_id"]),
                    "head_branch": "main",
                    "head_sha": event["source_sha"],
                },
            }
            for artifact_id, event, source in rows
        ]
        mapping = {artifact["id"]: (event, source) for artifact, (_, event, source) in zip(artifacts, rows)}

        class Reader:
            def list_recent_journal_artifacts(self, *_args, **_kwargs):
                return artifacts

            def list_recent_artifacts(self, *_args, **_kwargs):
                return artifacts

            def event(self, artifact, _upload_steps):
                return mapping[artifact["id"]]

            def get(self, suffix):
                if suffix == f"/compare/{STALE}...{CURRENT}":
                    return {"merge_base_commit": {"sha": STALE}, "status": "ahead"}
                raise AssertionError("unexpected API request: " + suffix)

        base = checkpoint({"runtime": before}, {"runtime": "fixture:runtime"})
        snapshot = make_snapshot(base, [], sequence=7, evidence={})
        with patch("state_journal.github_reducer.restore_snapshot", return_value=snapshot), \
             patch("state_journal.github_reducer.load_active_manifest", return_value=None), \
             patch.dict(os.environ, {"GITHUB_SHA": CURRENT}, clear=False), \
             self.assertRaisesRegex(JournalError, "does not subsume"):
            reduce_from_provider(
                Reader(),
                since="2026-09-30T00:00:00Z",
                current_run="999",
                upload_steps={},
            )


if __name__ == "__main__":
    unittest.main()
