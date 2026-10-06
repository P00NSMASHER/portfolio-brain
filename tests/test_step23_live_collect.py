import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from acceptance import step23_live_collect as collector


def run_row(i, created, conclusion="success"):
    return {"id": i, "name": "portfolio-state-reducer", "head_sha": "a" * 40,
            "event": "schedule", "head_branch": "main", "status": "completed", "conclusion": conclusion,
            "created_at": created.isoformat(), "updated_at": created.isoformat()}


class FakeGH:
    def __init__(self, pages, drift=False):
        self.pages = pages
        self.drift = drift
        self.page1_reads = 0

    def get(self, path):
        page = int(path.rsplit("page=", 1)[-1])
        if page == 1:
            self.page1_reads += 1
        rows = self.pages.get(page, [])
        if self.drift and page == 1 and self.page1_reads > 1:
            rows = rows[1:]
        return {"workflow_runs": rows}


class ScheduledSoakObserverTests(unittest.TestCase):
    def test_live_observer_uses_a_finite_budget_for_polling_and_traceable_artifacts(self):
        from unittest.mock import Mock
        with patch.object(collector, "BudgetedHTTP", Mock()) as http:
            collector.GH("owner/repo", "token")
        http.assert_called_once_with("token", max_requests=200, retries=0, backoff=0)

    def test_failure_on_second_page_is_not_hidden_by_newer_successes(self):
        at = datetime(2026, 10, 4, tzinfo=timezone.utc)
        first = [run_row(200-i, at-timedelta(minutes=i)) for i in range(100)]
        failed = run_row(99, at-timedelta(minutes=100), "failure")
        gh = FakeGH({1: first, 2: [failed]})
        grouped = collector.scheduled_runs(gh, {"portfolio-state-reducer"}, "a"*40, at-timedelta(days=1))
        self.assertEqual(len(grouped["portfolio-state-reducer"]), 101)
        self.assertIn("conclusion=failure", collector.find_real_reset(grouped)[1])

    def test_changed_page_one_cannot_produce_acceptance(self):
        at = datetime(2026, 10, 4, tzinfo=timezone.utc)
        gh = FakeGH({1: [run_row(1, at)]}, drift=True)
        with self.assertRaisesRegex(RuntimeError, "changed during pagination"):
            collector.scheduled_runs(gh, {"portfolio-state-reducer"}, "a"*40, at-timedelta(days=1))

    def test_page_bound_is_blocking(self):
        at = datetime(2026, 10, 4, tzinfo=timezone.utc)
        pages = {page: [run_row(3000-(page-1)*100-i, at-timedelta(seconds=(page-1)*100+i))
                        for i in range(100)] for page in range(1, 21)}
        with self.assertRaisesRegex(RuntimeError, "incomplete at page bound"):
            collector.scheduled_runs(FakeGH(pages), {"portfolio-state-reducer"}, "a"*40, at-timedelta(days=1))

    def test_artifact_wrong_head_or_changed_bytes_cannot_be_used(self):
        from hashlib import sha256
        from unittest.mock import Mock
        raw = b"immutable ZIP bytes"
        artifact = {"id": 7, "name": "portfolio-canonical-shadow-state", "expired": False,
                    "digest": "sha256:" + sha256(raw).hexdigest(),
                    "workflow_run": {"id": 11, "head_sha": "b"*40, "head_branch": "main"}}
        gh = Mock()
        gh.get.return_value = {"total_count": 1, "artifacts": [artifact]}
        gh.bytes.return_value = raw
        with self.assertRaisesRegex(RuntimeError, "source identity mismatch"):
            collector.select_artifact(gh, "portfolio-state-reducer", 11, "a"*40)
        artifact["workflow_run"]["head_sha"] = "a"*40
        gh.bytes.return_value = raw + b"changed"
        with self.assertRaisesRegex(RuntimeError, "digest mismatch"):
            collector.select_artifact(gh, "portfolio-state-reducer", 11, "a"*40)

    def test_single_observation_waits_without_creating_pass_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = root / "config.json"
            cfg.write_text(json.dumps({"exact_main_sha": "a"*40, "soak_start": collector.iso_now(),
                "required_workflows": ["portfolio-state-reducer"], "required_handler_types": ["REPAIR"],
                "required_successes_per_workflow": 3, "max_soak_duration_seconds": 3600}))
            meta, receipt = root / "meta.json", root / "receipt.json"
            argv = ["collect", "--config", str(cfg), "--output-meta", str(meta),
                    "--output-receipt", str(receipt), "--once"]
            with patch.dict("os.environ", {"GITHUB_TOKEN": "test", "GITHUB_REPOSITORY": "test/repo"}), \
                 patch("sys.argv", argv), patch.object(collector.GH, "get", return_value={"commit": {"sha": "a"*40}}), \
                 patch.object(collector, "pending_event_count", return_value=0), \
                 patch.object(collector, "scheduled_runs", return_value={"portfolio-state-reducer": []}):
                collector.main()
            self.assertEqual(json.loads(meta.read_text())["status"], "WAITING_FOR_SCHEDULED_CYCLES")
            self.assertFalse(json.loads(meta.read_text())["acceptance_complete"])
            self.assertFalse(receipt.exists())


if __name__ == "__main__":
    unittest.main()
