import tempfile
import unittest
from pathlib import Path

from repair.autonomous_repair import request_from_scheduler_work
from repair.repair_engine import failure_to_task
from software_factory.github_executor import GitHubExecutor
from software_factory.scheduler_repair_bridge import start_factory_repair, submit_factory_candidate
from software_factory.software_factory import SoftwareFactoryError, hashv


class FakeTransport:
    def __init__(self, base_sha):
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
        raise AssertionError((method, url, payload))


def scheduler_request():
    failure = {
        "schema_version": "1.0.0",
        "failure_id": "RFAIL-VALIDATION-BASE-0001",
        "source_type": "FAILURE_PACKET",
        "project_ids": ["PRJ-000"],
        "target_repository_id": "REPO-008",
        "target_paths": ["learning/continuous_learning.py"],
        "failure_class": "REGRESSION",
        "observation": "validation base identity must match admitted base",
        "reproduction_steps": ["submit a validation receipt with its base SHA"],
        "evidence_refs": ["test:scheduler-repair-validation-base"],
        "regression_test_requirement": "Preserve validation base identity.",
        "evidence_state": "VERIFIED",
        "sensitive_material_involved": False,
        "benchmark_contaminated": False,
        "reported_at": "2026-09-30T13:30:00Z",
    }
    task = failure_to_task(failure)
    work = {"work_type": "REPAIR", "source_ref": task["repair_task_id"]}
    return request_from_scheduler_work(work, {"tasks": [task]}, base_sha="a" * 40)


class SchedulerRepairValidationBaseTests(unittest.TestCase):
    def _prepare(self, root):
        request = scheduler_request()
        transport = FakeTransport(request["base_sha"])
        executor = GitHubExecutor("token", transport=transport)
        db_path = root / "factory.sqlite3"
        candidate_root = root / "candidate"
        (candidate_root / "learning").mkdir(parents=True)
        (candidate_root / "learning" / "continuous_learning.py").write_text(
            "def normalize_marker(value):\n    return value.strip().upper()\n",
            encoding="utf-8",
        )
        start_factory_repair(
            request,
            db_path=db_path,
            attempt_id="validation-base",
            executor=executor,
            now=100,
        )
        validation = {
            "request_id": request["request_id"],
            "fingerprint": request["fingerprint"],
            "base_sha": request["base_sha"],
            "changed_paths": ["learning/continuous_learning.py"],
            "diff_hash": hashv({"candidate": "validation-base"}),
        }
        return request, transport, executor, db_path, candidate_root, validation

    def test_rejects_mismatched_base_before_candidate_commit_or_pr(self):
        with tempfile.TemporaryDirectory() as td:
            request, transport, executor, db_path, candidate_root, validation = self._prepare(Path(td))
            validation["base_sha"] = "c" * 40
            calls_before_submission = list(transport.calls)

            with self.assertRaisesRegex(SoftwareFactoryError, "base SHA mismatch"):
                submit_factory_candidate(
                    request,
                    validation,
                    test_log=b"builder tests PASS\n",
                    candidate_root=candidate_root,
                    db_path=db_path,
                    attempt_id="validation-base",
                    executor=executor,
                    now=101,
                )

        self.assertEqual(transport.calls, calls_before_submission)
        self.assertFalse(any(url.endswith("/pulls") for _, url, _ in transport.calls))

    def test_matching_base_still_submits_candidate_for_independent_review(self):
        with tempfile.TemporaryDirectory() as td:
            request, transport, executor, db_path, candidate_root, validation = self._prepare(Path(td))

            submitted = submit_factory_candidate(
                request,
                validation,
                test_log=b"builder tests PASS\n",
                candidate_root=candidate_root,
                db_path=db_path,
                attempt_id="validation-base",
                executor=executor,
                now=101,
            )

        self.assertEqual(
            submitted["status"],
            "CANDIDATE_SUBMITTED_AWAITING_INDEPENDENT_FACTORY_REVIEW",
        )
        self.assertTrue(any(url.endswith("/git/commits") for _, url, _ in transport.calls))
        self.assertFalse(any(url.endswith("/pulls") for _, url, _ in transport.calls))
        self.assertFalse(submitted["pr_created"])


if __name__ == "__main__":
    unittest.main()
