"""Regression coverage for recovering journal events outside the snapshot overlap."""
import unittest
from unittest.mock import patch

from agents.heartbeat_state import heartbeat, seed_state
from state_journal.events import make_change, make_event
from state_journal.github_reducer import reduce_from_provider
from state_journal.reducer import checkpoint
from state_journal.transport import EVENT_PREFIX, SNAPSHOT_ARTIFACT, GitHubReader


SHA = "a" * 40


def producer_event(before, after, run_id):
    return make_event(
        "runtime-worker",
        run_id,
        SHA,
        [make_change("heartbeat", before, after)],
    )


class MissingPredecessorRecoveryTests(unittest.TestCase):
    def test_expanded_discovery_includes_terminal_runs_before_snapshot_overlap(self):
        reader = object.__new__(GitHubReader)
        reducer_runs = [
            {
                "id": 202,
                "created_at": "2026-09-30T22:00:00Z",
                "head_branch": "main",
                "status": "completed",
                "conclusion": "success",
            },
            {
                "id": 201,
                "created_at": "2026-09-30T21:00:00Z",
                "head_branch": "main",
                "status": "completed",
                "conclusion": "success",
            },
        ]
        old_producer_run = {
            "id": 101,
            "created_at": "2026-09-30T18:00:00Z",
            "updated_at": "2026-09-30T18:05:00Z",
            "head_branch": "main",
            "status": "completed",
            "conclusion": "success",
        }
        event_artifact = {
            "id": 11,
            "name": f"{EVENT_PREFIX}101-runtime-worker-{SHA}-1",
            "created_at": "2026-09-30T18:06:00Z",
        }
        reader._workflow_runs_since = lambda workflow, _since, *, max_pages: (
            reducer_runs if workflow == "portfolio-state-reducer.yml" else [old_producer_run]
        )
        reader._run_artifacts = lambda run_id: (
            [{
                "id": run_id,
                "name": SNAPSHOT_ARTIFACT,
                "created_at": "2026-09-30T22:01:00Z",
                "expired": False,
            }]
            if run_id in {201, 202}
            else [event_artifact]
        )

        with patch(
            "state_journal.transport.WORKFLOW_PRODUCERS",
            {"runtime-hourly-sync": "runtime-worker"},
        ):
            bounded_rows = reader.list_recent_journal_artifacts("2026-09-30T00:00:00Z")
            rows = reader.list_recent_journal_artifacts(
                "2026-09-30T00:00:00Z",
                include_pre_snapshot_runs=True,
            )

        self.assertNotIn(event_artifact, bounded_rows)
        self.assertIn(event_artifact, rows)

    def test_missing_predecessor_retries_with_pre_snapshot_producer_history(self):
        initial = seed_state()
        intermediate = heartbeat(
            initial,
            agent_ids=["AGT-DATA-STEWARD"],
            activity_kind="RUNTIME_OBSERVATION",
            source_workflow="runtime-worker",
            source_run_id="101",
            at="2026-09-30T12:00:00Z",
        )
        final = heartbeat(
            intermediate,
            agent_ids=["AGT-HUNTER"],
            activity_kind="RUNTIME_OBSERVATION",
            source_workflow="runtime-worker",
            source_run_id="102",
            at="2026-09-30T12:00:01Z",
        )
        predecessor = producer_event(initial, intermediate, "101")
        dependent = producer_event(intermediate, final, "102")
        checkpoint_doc = checkpoint({"heartbeat": initial}, {"heartbeat": "fixture:heartbeat"})

        def artifact(run_id, event):
            return {
                "id": int(run_id),
                "name": f"{EVENT_PREFIX}{run_id}-runtime-worker-{SHA}-1",
                "created_at": f"2026-09-30T12:00:0{int(run_id) - 101}Z",
                "expired": False,
                "workflow_run": {"head_branch": "main"},
                "event": event,
            }

        rows = {
            "101": artifact("101", predecessor),
            "102": artifact("102", dependent),
        }

        class Reader:
            def __init__(self):
                self.history_scans = []

            def list_recent_journal_artifacts(
                self, _since, *, explicit_run_ids=(), include_pre_snapshot_runs=False
            ):
                self.history_scans.append(include_pre_snapshot_runs)
                visible = [rows["102"]]
                if include_pre_snapshot_runs:
                    visible.insert(0, rows["101"])
                return visible

            def event(self, meta, _upload_steps):
                event = meta["event"]
                return event, {
                    "kind": "FIXTURE",
                    "event_hash": event["event_hash"],
                    "fixture_id": "fixture:late-predecessor",
                }

        reader = Reader()
        state, receipt = reduce_from_provider(
            reader,
            since="2026-09-30T00:00:00Z",
            current_run="999",
            upload_steps={},
            explicit_checkpoint=checkpoint_doc,
        )

        self.assertEqual(reader.history_scans, [False, True])
        self.assertEqual(state["projection"]["states"]["heartbeat"], final)
        self.assertEqual(set(state["projection"]["event_ids"]), {predecessor["event_id"], dependent["event_id"]})
        self.assertEqual(receipt["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
