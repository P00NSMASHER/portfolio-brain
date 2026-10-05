import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import unquote

from acceptance import step23_live_collect as collector


def run_row(i, created, conclusion="success"):
    return {
        "id": i,
        "name": "portfolio-state-reducer",
        "head_sha": "a" * 40,
        "event": "schedule",
        "status": "completed",
        "conclusion": conclusion,
        "created_at": created.isoformat(),
        "updated_at": created.isoformat(),
    }


class FakeGH:
    def __init__(self, rows, total_count=None):
        self.rows = rows
        self.total_count = len(rows) if total_count is None else total_count
        self.paths = []

    def get(self, path):
        self.paths.append(path)
        return {"workflow_runs": self.rows, "total_count": self.total_count}


class ScheduledSoakObserverTests(unittest.TestCase):
    def test_live_observer_uses_a_finite_budget_for_polling_and_traceable_artifacts(self):
        with patch.object(collector, "BudgetedHTTP", Mock()) as http:
            collector.GH("owner/repo", "token")
        http.assert_called_once_with("token", max_requests=200, retries=0, backoff=0)

    def test_bounded_schedule_query_is_single_snapshot_and_start_filtered(self):
        at = datetime(2026, 10, 5, 20, 0, tzinfo=timezone.utc)
        rows = [run_row(2, at + timedelta(minutes=2)), run_row(1, at + timedelta(minutes=1))]
        gh = FakeGH(rows)
        grouped = collector.scheduled_runs(gh, {"portfolio-state-reducer"}, "a" * 40, at)
        self.assertEqual([r["id"] for r in grouped["portfolio-state-reducer"]], [1, 2])
        self.assertEqual(len(gh.paths), 1)
        self.assertIn("created=", gh.paths[0])
        self.assertIn(">=2026-10-05T20:00:00Z", unquote(gh.paths[0]))

    def test_bounded_window_cap_is_blocking(self):
        at = datetime(2026, 10, 5, 20, 0, tzinfo=timezone.utc)
        gh = FakeGH([run_row(1, at)], total_count=101)
        with self.assertRaisesRegex(RuntimeError, "one-page cap"):
            collector.scheduled_runs(gh, {"portfolio-state-reducer"}, "a" * 40, at)

    def test_all_real_failures_are_counted_in_order(self):
        at = datetime(2026, 10, 5, 20, 0, tzinfo=timezone.utc)
        grouped = {"portfolio-state-reducer": [
            run_row(1, at + timedelta(minutes=1), "failure"),
            run_row(2, at + timedelta(minutes=2)),
            run_row(3, at + timedelta(minutes=3), "timed_out"),
        ]}
        resets = collector.find_real_resets(grouped)
        self.assertEqual(len(resets), 2)
        self.assertIn("run 1", resets[0][1])
        self.assertIn("run 3", resets[1][1])
        self.assertEqual(collector.find_real_reset(grouped), resets[-1])

    def test_artifact_wrong_head_or_changed_bytes_cannot_be_used(self):
        raw = b"immutable ZIP bytes"
        artifact = {
            "id": 7,
            "name": "portfolio-canonical-shadow-state",
            "expired": False,
            "digest": "sha256:" + sha256(raw).hexdigest(),
            "workflow_run": {"id": 11, "head_sha": "b" * 40, "head_branch": "main"},
        }
        gh = Mock()
        gh.get.return_value = {"total_count": 1, "artifacts": [artifact]}
        gh.bytes.return_value = raw
        with self.assertRaisesRegex(RuntimeError, "source identity mismatch"):
            collector.select_artifact(gh, "portfolio-state-reducer", 11, "a" * 40)
        artifact["workflow_run"]["head_sha"] = "a" * 40
        gh.bytes.return_value = raw + b"changed"
        with self.assertRaisesRegex(RuntimeError, "digest mismatch"):
            collector.select_artifact(gh, "portfolio-state-reducer", 11, "a" * 40)

    def test_single_observation_waits_without_creating_pass_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = root / "config.json"
            cfg.write_text(json.dumps({
                "exact_main_sha": "a" * 40,
                "soak_start": collector.iso_now(),
                "required_workflows": ["portfolio-state-reducer"],
                "required_handler_types": ["REPAIR"],
                "required_successes_per_workflow": 3,
                "max_soak_duration_seconds": 3600,
            }))
            meta, receipt = root / "meta.json", root / "receipt.json"
            argv = ["collect", "--config", str(cfg), "--output-meta", str(meta),
                    "--output-receipt", str(receipt), "--once"]
            with patch.dict("os.environ", {"GITHUB_TOKEN": "test", "GITHUB_REPOSITORY": "test/repo"}), \
                 patch("sys.argv", argv), \
                 patch.object(collector.GH, "get", return_value={"commit": {"sha": "a" * 40}}), \
                 patch.object(collector, "pending_event_count", return_value=0), \
                 patch.object(collector, "scheduled_runs", return_value={"portfolio-state-reducer": []}):
                collector.main()
            self.assertEqual(json.loads(meta.read_text())["status"], "WAITING_FOR_SCHEDULED_CYCLES")
            self.assertFalse(json.loads(meta.read_text())["acceptance_complete"])
            self.assertFalse(receipt.exists())


if __name__ == "__main__":
    unittest.main()
