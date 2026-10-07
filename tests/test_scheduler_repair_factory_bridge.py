from legacy.workflow_archive import legacy_workflow_path
import tempfile
import unittest
from pathlib import Path

from repair.autonomous_repair import request_from_scheduler_work
from repair.repair_engine import failure_to_task
from software_factory.github_executor import GitHubExecutor
from software_factory.scheduler_repair_bridge import (
    start_factory_repair,
    submit_factory_candidate,
    verify_factory_candidate,
)
from software_factory.software_factory import hashv


class FakeTransport:
    def __init__(self, base_sha="a" * 40):
        self.calls = []
        self.head = base_sha
        self.tree = "b" * 40
        self.n = 0

    def __call__(self, method, url, payload=None):
        self.calls.append((method, url, payload))
        if method == "POST" and url.endswith("/git/refs"):
            self.head = payload["sha"]
            return {"ref": payload["ref"], "object": {"sha": self.head}}
        if method == "GET" and "/git/ref/heads/" in url:
            return {"object": {"sha": self.head}}
        if method == "GET" and "/git/commits/" in url:
            return {"sha": self.head, "tree": {"sha": self.tree}}
        if method == "POST" and url.endswith("/git/blobs"):
            self.n += 1
            return {"sha": f"{self.n:040x}"}
        if method == "POST" and url.endswith("/git/trees"):
            self.n += 1
            self.tree = f"{self.n:040x}"
            return {"sha": self.tree}
        if method == "POST" and url.endswith("/git/commits"):
            self.n += 1
            self.head = f"{self.n:040x}"
            return {"sha": self.head}
        if method == "PATCH" and "/git/refs/heads/" in url:
            self.head = payload["sha"]
            return {"object": {"sha": self.head}}
        if method == "POST" and url.endswith("/pulls"):
            return {
                "number": 77,
                "html_url": "https://example.invalid/pr/77",
                "head": {"sha": self.head},
            }
        raise AssertionError((method, url, payload))


def scheduler_request(base_sha="a" * 40):
    failure = {
        "schema_version": "1.0.0",
        "failure_id": "RFAIL-FACTORY-BRIDGE-0001",
        "source_type": "FAILURE_PACKET",
        "project_ids": ["PRJ-000"],
        "target_repository_id": "REPO-008",
        "target_paths": ["learning/continuous_learning.py"],
        "failure_class": "REGRESSION",
        "observation": "controlled governed-factory bridge acceptance",
        "reproduction_steps": ["run controlled bridge fixture"],
        "evidence_refs": ["test:scheduler-repair-factory-bridge"],
        "regression_test_requirement": "Preserve deterministic normalization behavior.",
        "evidence_state": "VERIFIED",
        "sensitive_material_involved": False,
        "benchmark_contaminated": False,
        "reported_at": "2026-09-30T13:30:00Z",
    }
    task = failure_to_task(failure)
    work = {"work_type": "REPAIR", "source_ref": task["repair_task_id"]}
    return request_from_scheduler_work(work, {"tasks": [task]}, base_sha=base_sha)


class SchedulerRepairFactoryBridgeTests(unittest.TestCase):
    def test_scheduler_repair_flows_branch_commit_test_verification_and_pr_without_merge(self):
        request = scheduler_request()
        transport = FakeTransport(request["base_sha"])
        executor = GitHubExecutor("token", transport=transport)

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db = root / "factory.sqlite3"
            candidate = root / "candidate"
            (candidate / "learning").mkdir(parents=True)
            (candidate / "tests").mkdir(parents=True)
            (candidate / "learning" / "continuous_learning.py").write_text(
                "def normalize_marker(value):\n    return value.strip().upper()\n",
                encoding="utf-8",
            )
            (candidate / "tests" / "test_auto_factory_bridge.py").write_text(
                "def test_marker():\n    assert 'x'.upper() == 'X'\n",
                encoding="utf-8",
            )

            started = start_factory_repair(
                request,
                db_path=db,
                attempt_id="36700000123",
                executor=executor,
                now=100,
            )
            self.assertEqual(started["status"], "BRANCH_READY")
            self.assertTrue(started["branch_name"].startswith("factory/auto-repair-"))
            self.assertFalse(started["merge_authority_granted"])

            validation = {
                "schema_version": "1.0.0",
                "request_id": request["request_id"],
                "fingerprint": request["fingerprint"],
                "base_sha": request["base_sha"],
                "changed_paths": [
                    "learning/continuous_learning.py",
                    "tests/test_auto_factory_bridge.py",
                ],
                "test_paths": ["tests/test_auto_factory_bridge.py"],
                "implementation_paths": ["learning/continuous_learning.py"],
                "changed_lines": 4,
                "diff_hash": hashv({"fixture": "candidate"}),
                "merge_authority_granted": False,
                "deployment_authority_granted": False,
            }
            submitted = submit_factory_candidate(
                request,
                validation,
                test_log=b"builder compile PASS\nbuilder operating mode PASS\nbuilder regressions PASS\n",
                candidate_root=candidate,
                db_path=db,
                attempt_id="36700000123",
                executor=executor,
                now=101,
            )
            self.assertEqual(
                submitted["status"],
                "CANDIDATE_SUBMITTED_AWAITING_INDEPENDENT_FACTORY_REVIEW",
            )
            self.assertFalse(submitted["independent_factory_verified"])
            self.assertFalse(submitted["pr_created"])
            self.assertFalse(any(
                method == "POST" and url.endswith("/pulls")
                for method, url, _payload in transport.calls
            ))

            final = verify_factory_candidate(
                request,
                independent_test_log=b"fresh isolated regressions PASS\noperating mode PASS\n",
                expected_commit_sha=submitted["candidate_commit_sha"],
                db_path=db,
                attempt_id="36700000123",
                executor=executor,
                now=102,
            )

        self.assertEqual(final["status"], "PR_OPEN")
        self.assertTrue(final["independent_factory_verified"])
        self.assertEqual(final["pr_number"], 77)
        self.assertTrue(final["technical_candidate_tested"])
        self.assertFalse(final["foundation_success"])
        self.assertFalse(final["hosted_independent_success"])
        self.assertFalse(final["market_verified"])
        self.assertFalse(final["revenue_verified"])
        self.assertFalse(final["merge_authority_granted"])
        self.assertFalse(final["deployment_authority_granted"])

        pull_calls = [row for row in transport.calls if row[0] == "POST" and row[1].endswith("/pulls")]
        self.assertEqual(len(pull_calls), 1)
        body = pull_calls[0][2]["body"]
        self.assertIn("REPAIR_SOURCE_REF:" + request["source_ref"], body)
        self.assertIn("AUTO_REPAIR_FINGERPRINT:" + request["fingerprint"], body)
        self.assertIn("Factory merge authority: NONE", body)
        self.assertIn("portfolio-phase1-gate", body)
        self.assertFalse(any("/merge" in url for _, url, _ in transport.calls))

    def test_workflow_prevents_python_bytecode_from_contaminating_candidate_diff(self):
        root = Path(__file__).resolve().parents[1]
        workflow = (legacy_workflow_path(root / ".github/workflows/portfolio-autonomous-repair.yml")).read_text()
        self.assertIn('PYTHONDONTWRITEBYTECODE: "1"', workflow)
        self.assertIn("python -m repair.autonomous_repair validate-diff", workflow)
        self.assertIn("software_factory.scheduler_repair_bridge submit", workflow)

    def test_workflow_excludes_scratch_before_candidate_accounting(self):
        root = Path(__file__).resolve().parents[1]
        workflow = (legacy_workflow_path(root / ".github/workflows/portfolio-autonomous-repair.yml")).read_text()
        scratch = "printf '%s\\n' '/repair/out/' >> .git/info/exclude"
        self.assertIn(scratch, workflow)
        self.assertLess(workflow.index(scratch), workflow.index("mkdir -p repair/out"))
        self.assertLess(workflow.index(scratch), workflow.index("validate-diff"))

    def test_workflow_bounds_failed_builder_correction_to_exactly_one_retry(self):
        root = Path(__file__).resolve().parents[1]
        workflow = (legacy_workflow_path(root / ".github/workflows/portfolio-autonomous-repair.yml")).read_text()
        initial = workflow.index("id: prepush")
        prompt = workflow.index("Prepare one bounded correction prompt")
        correction = workflow.index("Apply one bounded correction")
        revalidate = workflow.index("Revalidate corrected repair")
        corrected_tests = workflow.index("Run corrected deterministic pre-push verification")
        submit = workflow.index("Submit scheduler candidate through software factory")
        self.assertIn("_sanitize_failure_log", workflow)
        self.assertIn("steps.prepush.outputs.passed != 'true'", workflow)
        self.assertIn("exactly one correction pass", workflow)
        self.assertIn("Do not modify any test file that existed at the admitted base SHA.", workflow)
        self.assertIn("There is no further repair retry.", workflow)
        self.assertEqual(workflow.count("--no-ask-user"), 2)
        self.assertEqual(workflow.count("- name: Apply one bounded correction"), 1)
        self.assertLess(initial, prompt)
        self.assertLess(prompt, correction)
        self.assertLess(correction, revalidate)
        self.assertLess(revalidate, corrected_tests)
        self.assertLess(corrected_tests, submit)
    def test_workflow_separates_builder_from_network_disabled_factory_review(self):
        root = Path(__file__).resolve().parents[1]
        workflow = (legacy_workflow_path(root / ".github/workflows/portfolio-autonomous-repair.yml")).read_text()
        self.assertIn("software_factory.scheduler_repair_bridge submit", workflow)
        self.assertIn("  factory-review:", workflow)
        self.assertIn("software_factory.scheduler_repair_bridge verify", workflow)
        self.assertIn("--network none", workflow)
        self.assertIn("persist-credentials: false", workflow)
        self.assertNotIn("scheduler_repair_bridge finalize", workflow)
        self.assertLess(
            workflow.index("scheduler_repair_bridge submit"),
            workflow.index("  factory-review:"),
        )
        self.assertLess(
            workflow.index("Run fresh independent factory regressions without network or credentials"),
            workflow.index("Record independent factory PASS and open protected PR"),
        )


if __name__ == "__main__":
    unittest.main()
