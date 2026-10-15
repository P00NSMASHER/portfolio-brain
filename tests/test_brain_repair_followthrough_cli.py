"""Offline continuation CLI: private artifacts and replay safety."""
import json
import stat
import tempfile
import unittest
from pathlib import Path

from brain.core import BrainError
from brain.repair_autonomy import repair_batch
from brain.repair_followthrough_cli import _safe_json, main
from test_brain_repair_autonomy import fixture


class RepairFollowthroughCLITests(unittest.TestCase):
    def test_private_restart_receipt_and_replay(self):
        with tempfile.TemporaryDirectory() as root:
            place = Path(root)
            q = place / "queue.json"
            q.write_text(json.dumps(repair_batch(fixture())))
            first = place / "run-one"
            self.assertEqual(main([
                "--current", str(q), "--cycle", "7",
                "--output", str(first),
            ]), 0)
            report = json.loads((first / "report.json").read_text())
            self.assertEqual(report["status"], "UNFINISHED_REPAIRS_TO_CONTINUE")
            self.assertEqual(len(report["next_history"]), 5)
            self.assertTrue(all(x["state"] == "OBSERVED"
                                for x in report["next_history"]))
            self.assertEqual(stat.S_IMODE(first.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE((first/"report.json").stat().st_mode), 0o600)
            previous = place / "previous.json"
            previous.write_text(json.dumps(report["next_history"]))
            second = place / "run-two"
            self.assertEqual(main([
                "--current", str(q), "--history", str(previous),
                "--cycle", "9", "--output", str(second),
            ]), 0)
            resumed = json.loads((second / "report.json").read_text())
            self.assertTrue(any(x["next_operation"] ==
                "RESUME_STALLED_OWNER_CHECK_PR_AND_LOGS"
                for x in resumed["actions"]))
            self.assertFalse(resumed["merge_or_deployment_authority"])
            third = place / "run-from-report"
            self.assertEqual(main([
                "--current", str(q), "--history", str(first / "report.json"),
                "--cycle", "9", "--output", str(third),
            ]), 0)
            replayed = json.loads((third / "report.json").read_text())
            self.assertEqual(replayed["next_history"], resumed["next_history"])
            self.assertEqual(replayed["unfinished_count"], 5)

    def test_duplicate_json_keys_fail_closed(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)/"duplicate.json"
            p.write_text('{"state":"CLAIMED","state":"MERGED"}')
            with self.assertRaises(BrainError):
                _safe_json(p)

    def test_output_alias_input_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)/"report.json"
            p.write_text(json.dumps(repair_batch(fixture())))
            with self.assertRaises(BrainError):
                main(["--current",str(p),"--cycle","1","--output",str(p)])

    def test_output_report_is_not_a_live_or_paid_claim(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)/"current.json"
            p.write_text(json.dumps(repair_batch(fixture())))
            output=Path(root)/"receipt"
            main(["--current",str(p),"--cycle","0","--output",str(output)])
            j=json.loads((output/"report.json").read_text())
            self.assertIs(j["real_buyer_or_revenue_verified"], False)
            self.assertFalse(j["merge_or_deployment_authority"])
            self.assertTrue(j["independent_gate_required"])
            self.assertEqual(j["technical_main_verified_count"],0)


if __name__=="__main__":
    unittest.main()
