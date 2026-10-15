"""Private CLI checkpoints for delivery and outcome learning."""
import json
from pathlib import Path
import stat
import tempfile
import unittest

from brain.core import BrainError
from brain.repair_delivery import main as delivery_cli
from brain.repair_outcome_learning import main as learning_cli
from test_brain_repair_delivery import fixture, FIXTURE
from test_brain_repair_outcome_learning import episode
from test_brain_repair_autonomy import fixture as portfolio_fixture


class RepairPipelineCLIContract(unittest.TestCase):
    def test_delivery_review_consumes_exact_bundle_without_git_writes(self):
        patch, pr, files, checks = fixture()
        body = {
            "patch": patch, "original_source": FIXTURE, "pr": pr,
            "file_hashes": files, "candidate_checks": checks,
            "main_sha": None, "main_checks": None,
        }
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            bundle=root/"source.json"
            bundle.write_text(json.dumps(body))
            out=root/"decision"
            self.assertEqual(delivery_cli(["--bundle",str(bundle),
                                           "--output",str(out)]),0)
            data=json.loads((out/"report.json").read_text())
            self.assertEqual(data["status"],
                             "SAFE_SOURCE_VERIFIED_FOR_GUARDED_OWNER_ACTION")
            self.assertFalse(data["merge_or_release_authority_granted"])
            self.assertFalse(data["live_service_verified"])
            self.assertEqual(stat.S_IMODE(out.stat().st_mode),0o700)
            self.assertEqual(stat.S_IMODE((out/"report.json").stat().st_mode),0o600)

    def test_learning_replays_real_source_checks_and_reranks_only_matching_theme(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            observations=root/"episodes.json"
            observations.write_text(json.dumps([
                episode(i,"pass") for i in range(3)
            ]))
            project=portfolio_fixture()
            project["evidence_to_action_packets"][1]["actionable_review_packets"][2][
                "theme"]="AUTOMATION_RELIABILITY"
            project_path=root/"portfolio.json"
            project_path.write_text(json.dumps(project))
            out=root/"next"
            self.assertEqual(learning_cli([
                "--episodes",str(observations),
                "--project-report",str(project_path),
                "--output",str(out),
            ]),0)
            data=json.loads((out/"report.json").read_text())
            row=data["prioritized_owner_repair_actions"]["actions"]
            selected=next(x for x in row if x["candidate_pr_number"]==37)
            self.assertEqual(selected["learned_technical_priority_delta"],5)
            self.assertFalse(data["production_release_authority"])
            self.assertIsNone(data["verified_business_revenue"])

    def test_external_forged_revenue_or_wrong_json_cannot_generate_learning_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            p=root/"bad.json"
            item=episode(0,"pass")
            item["verified_revenue"]=1
            p.write_text(json.dumps([item]))
            with self.assertRaises(BrainError):
                learning_cli(["--episodes",str(p),
                              "--output",str(root/"blocked")])
            p.write_text('[{"field":1,"field":2}]')
            with self.assertRaises(BrainError):
                learning_cli(["--episodes",str(p),
                              "--output",str(root/"blocked")])


if __name__ == "__main__":
    unittest.main()
