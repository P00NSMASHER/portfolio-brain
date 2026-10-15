"""Provider auto-collection with private, replayable owner receipts."""
import json
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from brain.core import BrainError
from brain.repair_provider import main as collect_main
from brain.repair_followthrough_cli import main as continue_main
from test_brain_repair_provider import rig, A, RET


class RepairProviderCliTests(unittest.TestCase):
    def test_original_source_to_next_owner_cycle_without_handcrafted_evidence(self):
        queue, provider = rig()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            current = root / "work.json"
            current.write_text(json.dumps(queue))
            artifact = root / "original-provider"
            with patch("brain.repair_provider.github_transport",
                       return_value=provider):
                self.assertEqual(collect_main([
                    "--current", str(current), "--output", str(artifact)
                ]), 0)
            packet = json.loads((artifact / "report.json").read_text())
            self.assertEqual(packet["scope"],
                             "ORIGINAL_GITHUB_READ_ONLY_REPAIR_PROOFS")
            self.assertEqual(packet["observed_pr_count"], 5)
            self.assertEqual(packet["requests_used"], 12)
            self.assertEqual(len(packet["source_checks"]), 5)
            self.assertTrue(all(x["status"] ==
                "EXACT_HEAD_TECHNICAL_CHECKS_GREEN_NOT_RELEASE"
                for x in packet["source_checks"]))
            self.assertEqual(stat.S_IMODE(artifact.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(
                (artifact / "report.json").stat().st_mode), 0o600)
            nxt = root / "owner-next"
            self.assertEqual(continue_main([
                "--current", str(current),
                "--provider", str(artifact / "report.json"),
                "--cycle", "123",
                "--output", str(nxt),
            ]), 0)
            state = json.loads((nxt / "report.json").read_text())
            self.assertEqual(state["unfinished_count"], 5)
            self.assertEqual(len(state["next_history"]), 5)
            self.assertTrue(all(p["state"] == "CI_GREEN"
                                for p in state["next_history"]))
            self.assertEqual(state["original_ci_bound_actions"],5)
            self.assertFalse(state["merge_or_deployment_authority"])

    def test_original_prior_report_recovers_unsampled_work_without_reasking(self):
        work, original_provider = rig()
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            current=root/"work.json"
            current.write_text(json.dumps(work))
            history = root / "prior.json"
            from brain.repair_followthrough import follow_through
            old=follow_through(work,cycle=101)
            history.write_text(json.dumps(old))
            with patch("brain.repair_provider.github_transport",
                       return_value=original_provider):
                outcome=root/"facts"
                self.assertEqual(collect_main([
                    "--current",str(current),"--previous",str(history),
                    "--output",str(outcome)
                ]),0)
            packet=json.loads((outcome/"report.json").read_text())
            self.assertEqual(packet["observed_pr_count"],5)
            self.assertEqual(packet["unsampled_due_to_job_limit"],0)

    def test_forged_provider_envelope_is_rejected_by_owner_replay(self):
        queue, provider = rig()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            current = root / "current.json"
            current.write_text(json.dumps(queue))
            forged = root / "provider.json"
            forged.write_text(json.dumps({
                "scope": "DANGEROUS_AUTO_MERGE",
                "proofs": [],
                "automatic_merge_or_deployment_authority": True,
                "customer_or_external_action_authority": True,
                "original_api_response_not_signed": False,
            }))
            with self.assertRaises(BrainError):
                continue_main([
                    "--current", str(current),
                    "--provider", str(forged), "--cycle", "3",
                    "--output", str(root/"reject")
                ])

    def test_no_github_token_fails_before_real_network_calls(self):
        queue, _ = rig()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            file = root / "queue.json"
            file.write_text(json.dumps(queue))
            with patch.dict("os.environ", {"GITHUB_TOKEN": ""}):
                with self.assertRaises(BrainError):
                    collect_main(["--current", str(file),
                                  "--output", str(root/"receipt")])

if __name__=="__main__":
    unittest.main()
