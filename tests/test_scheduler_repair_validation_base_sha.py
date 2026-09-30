import tempfile
import unittest
from pathlib import Path

from repair.autonomous_repair import request_from_scheduler_work
from repair.repair_engine import failure_to_task
from software_factory.github_executor import GitHubExecutor
from software_factory.scheduler_repair_bridge import (
    factory_work_id,
    start_factory_repair,
    submit_factory_candidate,
)
from software_factory.software_factory import SoftwareFactory, SoftwareFactoryError, hashv


class FakeTransport:
    def __init__(self, base_sha):
        self.calls = []
        self.head = base_sha
        self.tree = "b" * 40

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
            return {"sha": "c" * 40}
        if method == "POST" and url.endswith("/git/trees"):
            self.tree = "d" * 40
            return {"sha": self.tree}
        if method == "POST" and url.endswith("/git/commits"):
            self.head = "e" * 40
            return {"sha": self.head}
        if method == "PATCH" and "/git/refs/heads/" in url:
            self.head = payload["sha"]
            return {"object": {"sha": self.head}}
        raise AssertionError((method, url, payload))


def scheduler_request():
    failure = {
        "schema_version": "1.0.0",
        "failure_id": "RFAIL-VALIDATION-BASE-SHA-0001",
        "source_type": "FAILURE_PACKET",
        "project_ids": ["PRJ-000"],
        "target_repository_id": "REPO-008",
        "target_paths": ["learning/continuous_learning.py"],
        "failure_class": "REGRESSION",
        "observation": "validation must match the admitted factory base",
        "reproduction_steps": ["run validation base SHA regression"],
        "evidence_refs": ["test:scheduler-repair-validation-base-sha"],
        "regression_test_requirement": "Reject validation from a different base SHA.",
        "evidence_state": "VERIFIED",
        "sensitive_material_involved": False,
        "benchmark_contaminated": False,
        "reported_at": "2026-09-30T13:30:00Z",
    }
    task = failure_to_task(failure)
    work = {"work_type": "REPAIR", "source_ref": task["repair_task_id"]}
    return request_from_scheduler_work(work, {"tasks": [task]}, base_sha="a" * 40)


class SchedulerRepairValidationBaseShaTests(unittest.TestCase):
    def _setup_candidate(self, root):
        request = scheduler_request()
        transport = FakeTransport(request["base_sha"])
        executor = GitHubExecutor("token", transport=transport)
        db = root / "factory.sqlite3"
        candidate = root / "candidate"
        (candidate / "learning").mkdir(parents=True)
        (candidate / "learning" / "continuous_learning.py").write_text("VALUE = 1\n", encoding="utf-8")
        start_factory_repair(
            request,
            db_path=db,
            attempt_id="validation-base",
            executor=executor,
            now=100,
        )
        validation = {
            "request_id": request["request_id"],
            "fingerprint": request["fingerprint"],
            "base_sha": request["base_sha"],
            "changed_paths": ["learning/continuous_learning.py"],
            "diff_hash": hashv({"candidate": "fixture"}),
        }
        return request, validation, transport, executor, db, candidate

    def test_mismatched_validation_base_is_rejected_before_commit_or_pr(self):
        with tempfile.TemporaryDirectory() as td:
            request, validation, transport, executor, db, candidate = self._setup_candidate(Path(td))
            validation["base_sha"] = "f" * 40

            with self.assertRaisesRegex(SoftwareFactoryError, "base SHA mismatch"):
                submit_factory_candidate(
                    request,
                    validation,
                    test_log=b"builder tests PASS\n",
                    candidate_root=candidate,
                    db_path=db,
                    attempt_id="validation-base",
                    executor=executor,
                    now=101,
                )

            self.assertFalse(any(
                method == "POST" and url.endswith(("/git/commits", "/pulls"))
                for method, url, _payload in transport.calls
            ))
            sf = SoftwareFactory(db)
            try:
                work_id = factory_work_id(request, "validation-base")
                self.assertEqual(sf.get(work_id)["state"], "RUNNING")
            finally:
                sf.close()

    def test_matching_validation_base_allows_candidate_submission(self):
        with tempfile.TemporaryDirectory() as td:
            request, validation, transport, executor, db, candidate = self._setup_candidate(Path(td))

            receipt = submit_factory_candidate(
                request,
                validation,
                test_log=b"builder tests PASS\n",
                candidate_root=candidate,
                db_path=db,
                attempt_id="validation-base",
                executor=executor,
                now=101,
            )

            self.assertEqual(receipt["status"], "CANDIDATE_SUBMITTED_AWAITING_INDEPENDENT_FACTORY_REVIEW")
            self.assertEqual(receipt["base_sha"], request["base_sha"])
            self.assertTrue(any(
                method == "POST" and url.endswith("/git/commits")
                for method, url, _payload in transport.calls
            ))
            self.assertFalse(any(
                method == "POST" and url.endswith("/pulls")
                for method, url, _payload in transport.calls
            ))


if __name__ == "__main__":
    unittest.main()
