"""PB08 fail-before controls for a shared 24-GET budget and v9 proof reservation."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from brain.__main__ import projects
from brain.adapters import GitHub, policy
from brain.core import BrainError
from brain.projects import extended_repositories
from brain.v9.batch_cycle import run_cycle
from brain.v9.batch_queue import BatchFault, BatchQueue

SHA = "a" * 40


def row(repo):
    return {
        "repository": repo, "head_sha": SHA, "default_branch": "main",
        "checks": [], "open_issues": 0,
        "source_ref": "https://github.com/" + repo + "/commit/" + SHA,
    }


class Store:
    visibility = "PUBLIC"

    def read_report(self, source):
        return {
            "schema_version": 2, "status": "PASS", "source_sha": source,
            "state_sequence": 20, "pending_events": 0,
            "repositories": [row(repo) for repo in policy()["repositories"]],
            "reuse_candidates": [], "learning": {"outcomes": [], "experiments": []},
        }


class FakeReadOnlyGitHub:
    """Every source costs four GETs; one each for two focused PR pages."""
    def __init__(self, cap):
        self.requests = 0
        self.cap = cap
        self.calls = []

    def observe(self, repository):
        self.calls.append(("observe", repository))
        if self.requests + 4 > self.cap:
            raise BrainError("REQUEST_BUDGET_EXHAUSTED")
        self.requests += 4
        return row(repository), False

    def get(self, path):
        if self.requests >= self.cap:
            raise BrainError("REQUEST_BUDGET_EXHAUSTED")
        self.requests += 1
        self.calls.append(("get", path))
        if "/pulls?state=open" in path:
            return []
        raise BrainError("ORIGINAL_PROOF_FIXTURE_UNAVAILABLE")


class PublicationReservationTests(unittest.TestCase):
    def test_adapters_native_bound_applies_to_retries_and_rejects_boolean(self):
        provider_calls = []
        def transport(path):
            provider_calls.append(path)
            return {"ok": True}
        api = GitHub(transport=transport, max_requests=14)
        api.requests = 13
        self.assertEqual(api.get("/repos/P00NSMASHER/portfolio-brain"), {"ok": True})
        with self.assertRaisesRegex(BrainError, "REQUEST_BUDGET_EXHAUSTED"):
            api.get("/repos/P00NSMASHER/portfolio-brain")
        self.assertEqual(api.requests, 14)
        self.assertEqual(len(provider_calls), 1)
        for invalid in (True, 0, 25, -1, 1.5):
            with self.subTest(value=invalid), self.assertRaises(BrainError):
                GitHub(transport=transport, max_requests=invalid)

    def test_real_git_hub_run_rotates_one_proof_budget_without_disabling_breadth(self):
        for run_number, expected_reserve, expected_cap in [(4, 10, 14), (5, 0, 24)]:
            with self.subTest(run_number=run_number):
                seen = []
                def create_api(**kwargs):
                    seen.append(kwargs)
                    return FakeReadOnlyGitHub(kwargs.get("max_requests", 24))
                with tempfile.TemporaryDirectory() as tmp, patch.dict(
                    os.environ, {"GITHUB_ACTIONS": "true",
                                 "GITHUB_WORKFLOW": "brain-cycle-v2",
                                 "GITHUB_RUN_NUMBER": str(run_number)}
                ), patch("brain.__main__.GitHub", side_effect=create_api):
                    result = projects(Store(), SHA, Path(tmp) / "report")
                self.assertEqual(len(seen), 1)
                self.assertEqual(seen[0]["max_requests"], expected_cap)
                self.assertEqual(result["operation"]["publication_reserved_gets"],
                                 expected_reserve)
                self.assertEqual(result["operation"]["project_request_ceiling"],
                                 expected_cap)
                self.assertLessEqual(result["operation"]["requests"], expected_cap)
                self.assertLessEqual(result["operation"]["requests"] + expected_reserve, 24)
                self.assertFalse(result["autonomous_downstream_writes"])
                if expected_reserve:
                    self.assertEqual(result["operation"]["original_repair_requests"], 0)
                    self.assertEqual(result["original_repair_proof"]["status"],
                                     "DEFERRED_TO_V9_PUBLICATION_READBACK")
                    self.assertTrue(result["missing_repositories"])
                else:
                    self.assertEqual(result["repository_count"], 8)
                    self.assertEqual(result["status"], "PASS")

    def test_v9_refuses_false_proof_reservation_before_durable_mutation(self):
        payload = {
            "schema_version": 1, "source_sha": SHA,
            "canonical_pending_events": 0,
            "operation": {
                "name": "projects", "requests": 20,
                "publication_reserved_gets": 10,
                "project_request_ceiling": 14,
            },
            "projects": [{
                "id": "abvm", "repository": "P00NSMASHER/abvmschoolstarworld",
                "repository_revision": "b" * 40,
                "source_check_state": "ADVERSE_CHECKS_OBSERVED",
            }],
        }
        with tempfile.TemporaryDirectory() as tmp:
            queue = BatchQueue(Path(tmp) / "state.sqlite")
            try:
                before = queue.checkpoint()
                with self.assertRaisesRegex(BatchFault, "CYCLE_GET_BUDGET_INVALID"):
                    run_cycle(payload, queue, source_sha=SHA, cycle=1,
                              now="2026-10-23T16:00:00Z")
                self.assertEqual(queue.checkpoint(), before)
            finally:
                queue.close()


if __name__ == "__main__":
    unittest.main()
