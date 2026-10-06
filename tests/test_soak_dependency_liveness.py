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
    def exercise(self, *, event="schedule", covered=True, snapshot=True, archived=False,
                 pending=None, known_ids=None, **changes):
        run = {
            "id": 501, "name": "portfolio-state-reducer", "head_branch": "main",
            "event": event, "status": "completed", "conclusion": "success",
            "created_at": "2026-10-05T22:10:00Z",
            "updated_at": "2026-10-05T22:11:00Z",
        }
        run.update(changes)
        if pending is None:
            pending = [{"id": 91, "created_at": "2026-10-05T22:09:00Z"}]
        if known_ids is None:
            known_ids = {91} if covered else set()
        state = {"evidence": {"runtime": [
            {"kind": "GITHUB_ACTIONS", "artifact_id": artifact_id}
            for artifact_id in sorted(known_ids)
        ]}}
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
                "test-token", policy, pending,
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

    def test_queued_reducer_created_before_pending_event_can_unblock(self):
        result, _ = self.exercise(
            created_at="2026-10-05T22:08:00Z",
            updated_at="2026-10-05T22:10:00Z",
        )
        self.assertEqual(result[1]["evidence"]["runtime"][0]["artifact_id"], 91)

    def test_queued_reducer_still_requires_every_pending_artifact(self):
        pending = [
            {"id": 91, "created_at": "2026-10-05T22:09:00Z"},
            {"id": 92, "created_at": "2026-10-05T22:09:30Z"},
        ]
        with self.assertRaisesRegex(Exception, "STALE_CANONICAL_STATE_REDUCTION_TIMEOUT"):
            self.exercise(
                created_at="2026-10-05T22:08:00Z", pending=pending, known_ids={91},
            )
        result, _ = self.exercise(
            created_at="2026-10-05T22:08:00Z", pending=pending, known_ids={91, 92},
        )
        self.assertEqual(len(result[1]["evidence"]["runtime"]), 2)

    def test_reducer_completed_before_latest_pending_event_is_rejected(self):
        pending = [
            {"id": 91, "created_at": "2026-10-05T22:09:00Z"},
            {"id": 92, "created_at": "2026-10-05T22:09:30Z"},
        ]
        with self.assertRaisesRegex(Exception, "STALE_CANONICAL_STATE_REDUCTION_TIMEOUT"):
            self.exercise(
                created_at="2026-10-05T22:08:00Z",
                updated_at="2026-10-05T22:09:15Z",
                pending=pending, known_ids={91, 92},
            )

    def test_reducer_without_completion_time_is_rejected(self):
        for value in (None, "", "not-a-timestamp", "2026-10-05T22:11:00", 123):
            with self.subTest(updated_at=value), self.assertRaisesRegex(
                Exception, "STALE_CANONICAL_STATE_REDUCTION_TIMEOUT"
            ):
                self.exercise(updated_at=value)

    def test_completion_at_event_timestamp_can_unblock_with_coverage(self):
        result, _ = self.exercise(
            created_at="2026-10-05T22:08:00Z", updated_at="2026-10-05T22:09:00Z",
        )
        self.assertIsNotNone(result[1])

    def test_completion_offsets_are_compared_as_instants(self):
        result, _ = self.exercise(
            created_at="2026-10-05T22:08:00Z", updated_at="2026-10-05T18:10:00-04:00",
        )
        self.assertIsNotNone(result[1])
        with self.assertRaisesRegex(Exception, "STALE_CANONICAL_STATE_REDUCTION_TIMEOUT"):
            self.exercise(
                created_at="2026-10-05T22:07:00Z", updated_at="2026-10-05T23:08:00+01:00",
            )

    def test_pending_event_without_valid_time_is_rejected(self):
        for value in (None, "not-a-timestamp", "2026-10-05T22:09:00"):
            with self.subTest(created_at=value), self.assertRaisesRegex(
                Exception, "Pending-event creation time missing or invalid"
            ):
                self.exercise(pending=[{"id": 91, "created_at": value}])

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
        window = __import__("json").loads((ROOT / "operations/STEP23_DELIVERY_WINDOW.json").read_text())
        for cron in window["temporary_crons"]["portfolio-state-reducer"]:
            self.assertIn(f'cron: "{cron}"', text)

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
