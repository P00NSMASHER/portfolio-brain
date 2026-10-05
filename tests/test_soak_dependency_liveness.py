"""Regression coverage for the actual reducer dependency used by soak producers."""
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from state_journal import production_reader as reader

ROOT = Path(__file__).resolve().parents[1]


class Clock:
    def __init__(self):
        self.value = 0.0

    def now(self):
        return self.value

    def sleep(self, seconds):
        self.value += seconds


class SoakDependencyLivenessTests(unittest.TestCase):
    def exercise(self, *, event="schedule", covered=True, snapshot=True, archived=False, **changes):
        run = {
            "id": 501, "name": "portfolio-state-reducer", "head_branch": "main",
            "event": event, "status": "completed", "conclusion": "success",
            "created_at": "2026-10-05T22:10:00Z",
        }
        run.update(changes)
        state = {"evidence": {"runtime": [
            {"kind": "GITHUB_ACTIONS", "artifact_id": 91}
        ] if covered else []}}
        fake = Mock()
        fake.get.side_effect = lambda path: {
            "workflow_runs": [] if "event=workflow_run" in path and event != "workflow_run" else [run]
        }
        fake.list_recent_journal_artifacts.return_value = [{"id": 91}]
        clock = Clock()
        policy = {"limits": {"max_read_requests": 100, "max_artifact_pages": 4},
                  "artifact_scan_start": "2026-10-05T00:00:00Z"}
        with patch.object(reader, "GitHubReader", return_value=fake), patch.object(
            reader, "restore_snapshot", return_value=state if snapshot else None
        ):
            result = reader._wait_for_reduction(
                "test-token", policy,
                [{"id": 91, "created_at": "2026-10-05T22:09:00Z"}],
                current_run="900", archived_ids={91} if archived else set(),
                timeout_seconds=2, poll_seconds=1, clock=clock.now, sleep=clock.sleep,
            )
        return result, fake

    def test_scheduled_reducer_can_unblock_a_producer(self):
        result, fake = self.exercise(event="schedule")
        self.assertEqual(result[1]["evidence"]["runtime"][0]["artifact_id"], 91)
        self.assertNotIn("event=workflow_run", fake.get.call_args.args[0])

    def test_reactive_reducer_still_unblocks_a_producer(self):
        result, _ = self.exercise(event="workflow_run")
        self.assertEqual(result[2], [{"id": 91}])

    def test_archived_pending_evidence_can_unblock(self):
        result, _ = self.exercise(covered=False, archived=True)
        self.assertIsNotNone(result[1])

    def test_success_without_pending_artifact_coverage_is_rejected(self):
        with self.assertRaisesRegex(Exception, "STALE_CANONICAL_STATE_REDUCTION_TIMEOUT"):
            self.exercise(covered=False)

    def test_absent_snapshot_is_rejected_even_with_archived_ids(self):
        with self.assertRaisesRegex(Exception, "STALE_CANONICAL_STATE_REDUCTION_TIMEOUT"):
            self.exercise(snapshot=False, archived=True)

    def test_failed_reducer_is_not_liveness_proof(self):
        with self.assertRaisesRegex(Exception, "STALE_CANONICAL_STATE_REDUCTION_TIMEOUT"):
            self.exercise(conclusion="failure")

    def test_running_reducer_is_not_liveness_proof(self):
        with self.assertRaisesRegex(Exception, "STALE_CANONICAL_STATE_REDUCTION_TIMEOUT"):
            self.exercise(status="in_progress", conclusion=None)

    def test_other_branch_cannot_unblock_production(self):
        with self.assertRaisesRegex(Exception, "STALE_CANONICAL_STATE_REDUCTION_TIMEOUT"):
            self.exercise(head_branch="feature/untrusted")

    def test_other_workflow_cannot_unblock_production(self):
        with self.assertRaisesRegex(Exception, "STALE_CANONICAL_STATE_REDUCTION_TIMEOUT"):
            self.exercise(name="other-workflow")

    def test_reducer_older_than_pending_event_is_rejected(self):
        with self.assertRaisesRegex(Exception, "STALE_CANONICAL_STATE_REDUCTION_TIMEOUT"):
            self.exercise(created_at="2026-10-05T22:08:00Z")

    def test_reactive_reducer_is_not_suppressed_during_soak(self):
        text = (ROOT / ".github/workflows/portfolio-state-reducer.yml").read_text()
        header = text.split("  reduce:\n", 1)[1].split("    runs-on:", 1)[0]
        self.assertNotIn("if:", header)
        self.assertIn("workflow_run:", text)
        self.assertIn("group: portfolio-state-reducer", text)
        self.assertIn("cancel-in-progress: false", text)
        self.assertIn("queue: max", text)
        self.assertNotIn("group: portfolio-state-writer-v1", text)
        self.assertIn('cron: "11 4 * * *"', text)
        self.assertNotIn(' 5 10 *', text)

    def test_notifications_restore_canonical_cost_before_evaluation(self):
        text = (ROOT / ".github/workflows/portfolio-notification-cycle.yml").read_text()
        restore = text.index("--domain cost --output cost_governor/live/cost_state.json")
        evaluate = text.index("python -m notifications.notification_engine")
        self.assertLess(restore, evaluate)
        step = text[:evaluate].split("      - name: Restore canonical cost state for notification evidence", 1)[1]
        self.assertIn("steps.workload.outputs.allowed == 'true'", step)
        self.assertIn("--metadata-output cost_governor/live/cost_restore.json", step)
        self.assertNotIn("continue-on-error", step)


if __name__ == "__main__":
    unittest.main()
