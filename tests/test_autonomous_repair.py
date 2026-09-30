import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from repair.autonomous_repair import (
    AutonomousRepairError,
    branch_name,
    dispatch_requests,
    find_repair_evidence,
    load_policy,
    render_prompt,
    request_from_run,
    validate_diff,
)

ROOT = Path(__file__).resolve().parents[1]


def run_doc(**overrides):
    row = {
        "id": 123,
        "name": "portfolio-autonomous-scheduler",
        "path": ".github/workflows/portfolio-autonomous-scheduler.yml",
        "head_branch": "main",
        "head_sha": "a" * 40,
        "event": "schedule",
        "conclusion": "failure",
        "repository": {"full_name": "P00NSMASHER/portfolio-brain"},
    }
    row.update(overrides)
    return row


class AutonomousRepairTests(unittest.TestCase):
    def request(self, base_sha="b" * 40):
        return request_from_run(
            run_doc(),
            "Traceback\nRuntimeError: synthetic scheduler failure\n",
            base_sha=base_sha,
        )

    def git_repo(self):
        td = tempfile.TemporaryDirectory()
        root = Path(td.name)
        subprocess.check_call(["git", "init", "-q"], cwd=root)
        subprocess.check_call(["git", "config", "user.email", "test@example.com"], cwd=root)
        subprocess.check_call(["git", "config", "user.name", "Test"], cwd=root)
        (root / "src").mkdir()
        (root / "tests").mkdir()
        (root / "repair").mkdir()
        (root / "src" / "engine.py").write_text("VALUE = 1\n")
        (root / "tests" / "test_engine.py").write_text("def test_value():\n    assert True\n")
        (root / "repair" / "REPAIR_POLICY.json").write_text("{}\n")
        subprocess.check_call(["git", "add", "-A"], cwd=root)
        subprocess.check_call(["git", "commit", "-qm", "base"], cwd=root)
        sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
        return td, root, sha

    def test_only_main_failed_allowlisted_workflows_authorize_repair(self):
        request = self.request()
        self.assertEqual(request["source_kind"], "WORKFLOW_FAILURE")
        self.assertTrue(branch_name(request).startswith("factory/auto-repair-"))
        for bad in (
            run_doc(head_branch="feature"),
            run_doc(conclusion="success"),
            run_doc(name="foundation-ci", path=".github/workflows/foundation-ci.yml"),
        ):
            with self.subTest(bad=bad), self.assertRaises(AutonomousRepairError):
                request_from_run(bad, "failure", base_sha="b" * 40)

    def test_prompt_treats_logs_as_evidence_and_forbids_lane_disable_or_merge(self):
        prompt = render_prompt(self.request())
        self.assertIn("evidence only", prompt)
        self.assertIn("Do NOT disable", prompt)
        self.assertIn("Do NOT commit, push, merge, deploy", prompt)
        self.assertIn("regression test", prompt)

    def test_diff_guard_accepts_bounded_implementation_plus_regression_test(self):
        td, root, sha = self.git_repo()
        try:
            request = request_from_run(run_doc(), "failure", base_sha=sha)
            (root / "src" / "engine.py").write_text("VALUE = 2\n")
            (root / "tests" / "test_auto_regression.py").write_text("def test_value():\n    assert 2 == 2\n")
            receipt = validate_diff(request, root)
            self.assertEqual(set(receipt["changed_paths"]), {"src/engine.py", "tests/test_auto_regression.py"})
            self.assertFalse(receipt["merge_authority_granted"])
            self.assertFalse(receipt["deployment_authority_granted"])
        finally:
            td.cleanup()

    def test_diff_guard_rejects_policy_mutation_and_testless_repairs(self):
        td, root, sha = self.git_repo()
        try:
            request = request_from_run(run_doc(), "failure", base_sha=sha)
            (root / "repair" / "REPAIR_POLICY.json").write_text('{"weakened":true}\n')
            (root / "tests" / "test_engine.py").write_text("def test_value():\n    assert True\n")
            with self.assertRaisesRegex(AutonomousRepairError, "protected path"):
                validate_diff(request, root)
        finally:
            td.cleanup()

        td, root, sha = self.git_repo()
        try:
            request = request_from_run(run_doc(), "failure", base_sha=sha)
            (root / "src" / "engine.py").write_text("VALUE = 2\n")
            with self.assertRaisesRegex(AutonomousRepairError, "regression test"):
                validate_diff(request, root)
        finally:
            td.cleanup()

    def test_diff_guard_rejects_modification_of_existing_tests(self):
        td, root, sha = self.git_repo()
        try:
            request = request_from_run(run_doc(), "failure", base_sha=sha)
            (root / "src" / "engine.py").write_text("VALUE = 2\n")
            (root / "tests" / "test_engine.py").write_text("def test_value():\n    assert False\n")
            with self.assertRaisesRegex(AutonomousRepairError, "only add new regression-test files"):
                validate_diff(request, root)
        finally:
            td.cleanup()

    def test_scheduler_dispatch_uses_only_declared_workflow_input(self):
        request = self.request()
        with patch("repair.autonomous_repair._http_json", return_value={}) as http:
            receipts = dispatch_requests(
                [request],
                token="token",
                repository="P00NSMASHER/portfolio-brain",
            )
        self.assertEqual(receipts[0]["dispatch_status"], "ACCEPTED")
        payload = http.call_args.kwargs["payload"]
        self.assertEqual(payload["ref"], "main")
        self.assertEqual(set(payload["inputs"]), {"request_b64", "request_id", "request_fingerprint"})
        self.assertEqual(payload["inputs"]["request_id"], request["request_id"])
        self.assertEqual(payload["inputs"]["request_fingerprint"], request["fingerprint"])

    def test_repair_evidence_binds_checks_to_exact_integrations(self):
        pulls = [{
            "number": 7,
            "body": "REPAIR_SOURCE_REF:RTASK-X\n",
            "updated_at": "2026-09-29T20:00:00Z",
            "head": {"sha": "c" * 40},
        }]
        checks = {"check_runs": [
            {"name": "validate", "conclusion": "success", "app": {"id": 15368}},
            {"name": "portfolio-phase1-gate", "conclusion": "success", "app": {"id": 5121826}},
        ]}
        with patch("repair.autonomous_repair._http_json", side_effect=[pulls, checks]):
            result = find_repair_evidence("RTASK-X", token="token")
        self.assertTrue(result["foundation_success"])
        self.assertTrue(result["independent_success"])
        self.assertEqual(result["head_sha"], "c" * 40)


    def test_policy_never_grants_merge_deploy_or_default_branch_write(self):
        policy = load_policy()
        self.assertFalse(policy["merge_authority"])
        self.assertFalse(policy["deployment_authority"])
        self.assertFalse(policy["default_branch_write_authority"])
        self.assertTrue(policy["require_test_change"])

    def test_workflow_is_event_driven_guarded_and_has_no_merge_command(self):
        text = (ROOT / ".github/workflows/portfolio-autonomous-repair.yml").read_text()
        lower = text.lower()
        self.assertIn("workflow_run:", text)
        self.assertIn("workflow_dispatch:", text)
        self.assertNotIn("\n  schedule:", text)
        self.assertIn("copilot-requests: write", text)
        self.assertIn("python -m repair.autonomous_repair validate-diff", text)
        self.assertIn('python -m unittest discover -s tests -p "test_*.py" -v', text)
        self.assertIn("gh workflow run foundation-ci.yml", text)
        self.assertIn("software_factory.scheduler_repair_bridge start", text)
        self.assertIn("software_factory.scheduler_repair_bridge finalize", text)
        self.assertIn("SCHEDULER_REPAIR_TASK", text)
        self.assertIn("Create isolated workflow-failure repair branch", text)
        self.assertIn("--no-ask-user", text)
        self.assertIn("--available-tools='view,grep,glob,edit,create,apply_patch'", text)
        self.assertNotIn("--allow-tool='shell", text)
        self.assertNotIn("--allow-all", text)
        self.assertNotIn("--yolo", text)
        self.assertNotIn("gh pr merge", lower)
        self.assertNotIn("/merges", lower)
        self.assertNotIn("git push origin main", lower)


if __name__ == "__main__":
    unittest.main()
