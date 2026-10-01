import base64
import json
import unittest
from pathlib import Path

from acceptance.step22_controlled_fault import TARGET_PATH, build_plan
from acceptance.step22_controlled_fault_target import acceptance_value
from repair.autonomous_repair import validate_request

ROOT = Path(__file__).resolve().parents[1]


class Step22ControlledFaultTests(unittest.TestCase):
    def test_fixture_is_nonproduction_baseline(self):
        self.assertEqual(acceptance_value(), "BASELINE")
        self.assertEqual(TARGET_PATH, "acceptance/step22_controlled_fault_target.py")
        runtime_text = "\n".join(
            p.read_text(encoding="utf-8", errors="ignore")
            for p in (ROOT / "runtime").glob("*.py")
        )
        self.assertNotIn("step22_controlled_fault_target", runtime_text)

    def test_plan_is_fail_closed_and_repair_policy_compatible(self):
        sha = "a" * 40
        plan = build_plan(sha, at="2026-09-30T20:30:00Z")
        self.assertEqual(plan["status"], "CONTROLLED_FAULT_DETECTED")
        self.assertEqual(plan["fault_mechanism"], "CONTROLLED_REPRODUCIBLE_FIXTURE")
        self.assertFalse(plan["production_main_damaged"])
        self.assertTrue(plan["fault_reversible"])
        self.assertFalse(plan["authority_granted"])
        self.assertFalse(plan["canonical_state_mutated"])
        self.assertEqual(plan["base_sha"], sha)
        self.assertEqual(plan["target_path"], TARGET_PATH)
        self.assertEqual(plan["observed_value"], "BASELINE")
        self.assertEqual(plan["required_repaired_value"], "CANDIDATE")

        request = plan["request"]
        validate_request(request)
        self.assertEqual(request["source_kind"], "SCHEDULER_REPAIR_TASK")
        self.assertEqual(request["base_sha"], sha)
        self.assertEqual(request["target_paths"], [TARGET_PATH])
        self.assertIn("NEW", request["regression_requirement"])
        decoded = json.loads(base64.b64decode(plan["request_b64"]).decode("utf-8"))
        self.assertEqual(decoded, request)
        self.assertTrue(plan["fault_receipt_hash"].startswith("sha256:"))

    def test_workflow_has_no_merge_or_default_branch_write_authority(self):
        text = (ROOT / ".github" / "workflows" / "step22-controlled-repair-acceptance.yml").read_text()
        self.assertIn("actions: write", text)
        self.assertIn("contents: read", text)
        self.assertIn("pull-requests: read", text)
        self.assertNotIn("contents: write", text)
        self.assertNotIn("pull-requests: write", text)
        self.assertIn("persist-credentials: false", text)
        self.assertIn("portfolio-autonomous-repair.yml", text)
        self.assertNotIn("gh pr merge", text)
        self.assertNotIn("/merge", text)
        self.assertIn("[step22-fault]", text)
        self.assertIn("REMOTE_MAIN", text)


if __name__ == "__main__":
    unittest.main()
