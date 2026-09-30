"""Regression coverage for runtime observation branch selection."""
import os
import unittest
from unittest.mock import patch

from runtime.state import advance_cycle, bootstrap_state, canonical_hash, cycle_id_for
from state_journal.contracts import Conflict, REPOSITORY, digest
from state_journal.events import make_change, make_event
from state_journal.github_reducer import reduce_from_provider
from state_journal.reducer import checkpoint, make_snapshot
from state_journal.transport import EVENT_PREFIX

CURRENT = "b" * 40
STALE = "a" * 40
RUNTIME_PROOFS = {}


def runtime_observation(state, repository_id, at, *, current_sha=None):
    cursor = state["repositories"][repository_id]["cursor_sha"]
    observations = [{
        "repository_id": repository_id,
        "status": "CHANGED" if current_sha else "UNCHANGED",
        "source_ref": "main",
        "prior_sha": cursor,
        "current_sha": current_sha or cursor,
        "observed_at": at,
    }]
    receipt = {
        "schema_version": "1.0.0",
        "cycle_id": cycle_id_for(
            state, mode="observe", target_repository_id=repository_id,
            observations=observations,
        ),
        "mode": "observe",
        "started_at": at,
        "finished_at": at,
        "status": "PASS",
        "reason": None,
        "observations": observations,
        "api_requests": 1,
    }
    receipt["receipt_hash"] = canonical_hash(receipt)
    updated = advance_cycle(state, receipt)
    RUNTIME_PROOFS[digest(updated)] = {"cycle_receipt": receipt}
    return updated


def observation_event(run_id, source_sha, before, after):
    return make_event(
        "runtime-worker", run_id, source_sha,
        [make_change(
            "runtime", before, after,
            proofs=RUNTIME_PROOFS[digest(after)],
        )],
        run_attempt=1,
    )


def provider(event, artifact_id):
    return {
        "kind": "GITHUB_ACTIONS",
        "repository": REPOSITORY,
        "artifact_id": artifact_id,
        "archive_digest": "sha256:" + f"{artifact_id:064x}"[-64:],
        "source_run_id": int(event["run_id"]),
        "source_run_attempt": 1,
        "source_sha": event["source_sha"],
        "workflow_id": 45,
        "workflow_path": ".github/workflows/runtime-event-observe.yml",
        "source_conclusion": "success",
        "event_hash": event["event_hash"],
        "job_id": artifact_id + 100,
    }


class RuntimeParityRegressionTests(unittest.TestCase):
    def test_unrelated_repo_observation_is_not_dropped_as_superseded(self):
        base_runtime = bootstrap_state(now="2026-09-30T08:00:00Z")
        stale_after = runtime_observation(
            base_runtime, "REPO-001", "2026-09-30T08:01:00Z"
        )
        current_after = runtime_observation(
            base_runtime, "REPO-002", "2026-09-30T08:02:00Z",
            current_sha="c" * 40,
        )
        stale = observation_event("101", STALE, base_runtime, stale_after)
        current = observation_event("102", CURRENT, base_runtime, current_after)
        events = [(stale, provider(stale, 11)), (current, provider(current, 12))]
        artifacts = [
            {
                "id": source["artifact_id"],
                "name": f"{EVENT_PREFIX}{event['run_id']}-runtime-worker-{event['source_sha']}-1",
                "expired": False,
                "digest": source["archive_digest"],
                "workflow_run": {
                    "id": int(event["run_id"]),
                    "head_branch": "main",
                    "head_sha": event["source_sha"],
                },
            }
            for event, source in events
        ]
        by_id = {source["artifact_id"]: (event, source) for event, source in events}

        class Reader:
            def list_recent_journal_artifacts(self, *_args, **_kwargs):
                return artifacts

            def list_recent_artifacts(self, *_args, **_kwargs):
                return artifacts

            def event(self, artifact, _upload_steps):
                return by_id[artifact["id"]]

            def get(self, suffix):
                if suffix == f"/compare/{STALE}...{CURRENT}":
                    return {"merge_base_commit": {"sha": STALE}, "status": "ahead"}
                raise AssertionError("unexpected API request: " + suffix)

        base = checkpoint({"runtime": base_runtime}, {"runtime": "fixture:runtime"})
        snapshot = make_snapshot(base, [], sequence=7, evidence={})
        with patch("state_journal.github_reducer.restore_snapshot", return_value=snapshot), \
             patch.dict(os.environ, {"GITHUB_SHA": CURRENT}, clear=False), \
             self.assertRaises(Conflict):
            reduce_from_provider(
                Reader(), since="2026-09-30T00:00:00Z",
                current_run="999", upload_steps={},
            )


if __name__ == "__main__":
    unittest.main()
