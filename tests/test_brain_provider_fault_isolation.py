"""Synthetic isolated repository-failure recovery with a global safety breaker.

All tests use a fake GET adapter; no provider calls, credentials, PR merges,
network access, production updates, or writes to original SQLite.
"""
import copy
import json
import unittest

from brain.adapters import GitHub
from brain.core import BrainError
from brain.investigate import investigate
from brain.sidecar import summarize
from brain.review import review_packet
from test_brain_investigate import report, Transport, REPO, OTHER, THIRD, SOURCE, NOW


class SelectiveFailureTransport(Transport):
    def __init__(self, *, fail_repo=OTHER, code="SOURCE_API_404",
                 stage="metadata"):
        super().__init__()
        self.fail_repo = fail_repo
        self.code = code
        self.stage = stage

    def __call__(self, path):
        chunks = path.split("/")
        repo = "/".join(chunks[2:4])
        stage_hit = (
            self.stage == "metadata" and len(chunks) == 4
            or self.stage == "checks" and "/check-runs?" in path
            or self.stage == "branch" and "/branches/" in path
        )
        if repo == self.fail_repo and stage_hit:
            self.calls.append(path)
            raise BrainError(self.code + ": PRIVATE_API_DIAGNOSTIC_SENTINEL")
        return super().__call__(path)


def run_case(*, code="SOURCE_API_404", stage="metadata", repos=(OTHER, REPO, THIRD),
             provider=None, before_requests=0, limit=3, stop_requested=None):
    provider = provider or SelectiveFailureTransport(code=code, stage=stage)
    api = GitHub(transport=provider)
    api.requests = before_requests
    source = report(*repos)
    before = copy.deepcopy(source)
    receipt = investigate(
        source, api=api, now=NOW, max_investigations=limit,
        stop_requested=stop_requested,
    )
    assert source == before
    return receipt, provider, api


class SelectiveRepositoryFailureTests(unittest.TestCase):
    def test_one_missing_repository_does_not_blind_two_verified_good_repos(self):
        receipt, transport, api = run_case()
        self.assertEqual(receipt["status"], "INCOMPLETE_READ_ONLY_REVALIDATION")
        self.assertEqual(receipt["eligible_count"], 3)
        self.assertEqual(receipt["deferred_count"], 0)
        self.assertEqual(len(receipt["investigations"]), 3)
        self.assertEqual([r["repository"] for r in receipt["investigations"]],
                         [OTHER, REPO, THIRD])
        self.assertEqual([r["outcome"] for r in receipt["investigations"]], [
            "UNVERIFIED_READ_FAILED",
            "OBSERVED_CHECK_STATUS_NOT_ROOT_CAUSE",
            "OBSERVED_CHECK_STATUS_NOT_ROOT_CAUSE",
        ])
        self.assertEqual(receipt["investigations"][0]["provider_failure_scope"],
                         "REPOSITORY_LOCAL_EVIDENCE_UNAVAILABLE")
        self.assertEqual(receipt["requests_used"], 9)
        self.assertEqual(len(transport.calls), 9)
        self.assertEqual(api.requests, 9)
        self.assertEqual(receipt["github_mutations"], 0)
        self.assertEqual(receipt["paid_calls"], 0)
        self.assertFalse(receipt["root_cause_verified"])
        self.assertNotIn("PRIVATE_API_DIAGNOSTIC_SENTINEL", json.dumps(receipt))
        safe = summarize(receipt, SOURCE, *["success"] * 4)
        self.assertEqual(safe["status"], "PARTIAL_READ_ONLY")
        self.assertEqual(safe["checked"], 3)
        self.assertEqual(safe["repository_local_provider_failures"], 1)
        self.assertEqual(safe["provider_failure_hard_stops"], 0)
        self.assertEqual(safe["observed_outcomes"], {"STILL_ADVERSE": 2})
        self.assertNotIn("PRIVATE_API_DIAGNOSTIC_SENTINEL", str(safe))
        self.assertNotIn(OTHER, str(safe))

    def test_middle_repository_failure_still_checks_last_repo(self):
        receipt, transport, _ = run_case(
            provider=SelectiveFailureTransport(fail_repo=REPO))
        self.assertEqual(
            [x["outcome"] for x in receipt["investigations"]],
            ["OBSERVED_CHECK_STATUS_NOT_ROOT_CAUSE",
             "UNVERIFIED_READ_FAILED",
             "OBSERVED_CHECK_STATUS_NOT_ROOT_CAUSE"]
        )
        self.assertEqual(receipt["requests_used"], 9)
        self.assertEqual(receipt["deferred_count"], 0)
        self.assertEqual(len(transport.calls), 9)
        self.assertEqual(
            summarize(receipt, SOURCE, *["success"] * 4)["status"],
            "PARTIAL_READ_ONLY",
        )

    def test_all_three_repositories_unavailable_remains_incomplete(self):
        class AllMissing(Transport):
            def __call__(self, path):
                self.calls.append(path)
                raise BrainError("SOURCE_API_404: MASKED")
        provider = AllMissing()
        receipt, _, _ = run_case(provider=provider)
        self.assertEqual(receipt["eligible_count"], 3)
        self.assertEqual(receipt["deferred_count"], 0)
        self.assertEqual(receipt["requests_used"], 3)
        self.assertEqual(len(receipt["investigations"]), 3)
        self.assertTrue(all(x["outcome"] == "UNVERIFIED_READ_FAILED"
                            for x in receipt["investigations"]))
        safe = summarize(receipt, SOURCE, *["success"] * 4)
        self.assertEqual(safe["repository_local_provider_failures"], 3)
        self.assertEqual(safe["provider_failure_hard_stops"], 0)
        self.assertEqual(safe["status"], "PARTIAL_READ_ONLY")

    def test_partial_check_coverage_is_local_failure_without_other_data_loss(self):
        result, provider, _ = run_case(
            code="CHECK_COVERAGE_UNAVAILABLE", stage="checks"
        )
        self.assertEqual(result["status"], "INCOMPLETE_READ_ONLY_REVALIDATION")
        self.assertEqual(result["deferred_count"], 0)
        self.assertEqual(result["requests_used"], 11)
        self.assertEqual(len(provider.calls), 11)
        safe = summarize(result, SOURCE, *["success"] * 4)
        self.assertEqual(safe["repository_local_provider_failures"], 1)
        self.assertEqual(safe["observed_outcomes"], {"STILL_ADVERSE": 2})

    def test_source_advances_during_source_read_is_local_but_never_completed(self):
        result, provider, _ = run_case(
            code="SOURCE_REVISION_CHANGED", stage="branch"
        )
        self.assertEqual(result["status"], "INCOMPLETE_READ_ONLY_REVALIDATION")
        self.assertEqual(result["investigations"][0]["outcome"],
                         "UNVERIFIED_READ_FAILED")
        self.assertEqual(result["deferred_count"], 0)
        self.assertEqual(result["requests_used"], 10)
        self.assertEqual(len(provider.calls), 10)
        self.assertEqual(
            summarize(result, SOURCE, *["success"] * 4)["status"],
            "PARTIAL_READ_ONLY",
        )

    def test_known_api_403_rate_limit_and_transport_errors_fail_stop(self):
        for code in ("SOURCE_API_403", "SOURCE_API_429",
                     "SOURCE_READ_FAILED:TimeoutError",
                     "PRIVATE_INPUT_REFUSED_BY_PUBLIC_ADAPTER",
                     "SOURCE_API_500",
                     "PRIVATE_API_DIAGNOSTIC_SENTINEL"):
            with self.subTest(code=code):
                result, provider, _ = run_case(code=code)
                self.assertEqual(result["status"],
                                 "INCOMPLETE_READ_ONLY_REVALIDATION")
                self.assertEqual(len(result["investigations"]), 1)
                self.assertEqual(result["deferred_count"], 2)
                self.assertEqual(len(provider.calls), 1)
                self.assertEqual(
                    result["investigations"][0]["provider_failure_scope"],
                    "GLOBAL_OR_UNCLASSIFIED_STOP",
                )
                safe = summarize(result, SOURCE, *["success"] * 4)
                self.assertEqual(safe["provider_failure_hard_stops"], 1)
                self.assertEqual(safe["repository_local_provider_failures"], 0)
                self.assertEqual(safe["status"], "PARTIAL_READ_ONLY")
                self.assertNotIn("PRIVATE_API_DIAGNOSTIC_SENTINEL", str(safe))

    def test_unknown_local_code_prefix_cannot_enable_unsafe_continuation(self):
        receipt, provider, _ = run_case(code="SOURCE_API_4040")
        self.assertEqual(len(receipt["investigations"]), 1)
        self.assertEqual(receipt["deferred_count"], 2)
        self.assertEqual(len(provider.calls), 1)

    def test_budget_gates_remaining_repos_after_local_failure(self):
        receipt, provider, api = run_case(before_requests=6)
        self.assertEqual(receipt["status"], "REQUEST_BUDGET_DEFERRED")
        self.assertEqual(receipt["eligible_count"], 3)
        self.assertEqual(receipt["deferred_count"], 1)
        self.assertEqual(receipt["requests_used"], 5)
        self.assertEqual(api.requests, 11)
        self.assertEqual(len(provider.calls), 5)
        self.assertEqual([r["outcome"] for r in receipt["investigations"]],
                         ["UNVERIFIED_READ_FAILED",
                          "OBSERVED_CHECK_STATUS_NOT_ROOT_CAUSE"])
        self.assertEqual(
            summarize(receipt, SOURCE, *["success"] * 4)["status"],
            "PARTIAL_READ_ONLY",
        )

    def test_stop_requested_after_first_local_failure_aborts_remaining_reads(self):
        provider = SelectiveFailureTransport()
        receipt, provider, _ = run_case(
            provider=provider,
            stop_requested=lambda: bool(provider.calls),
        )
        self.assertEqual(receipt["status"], "STOPPED")
        self.assertEqual(receipt["deferred_count"], 2)
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(receipt["investigations"][0]["outcome"],
                         "UNVERIFIED_READ_FAILED")

    def test_even_after_local_failure_green_check_is_not_incident_closure(self):
        receipt, provider, _ = run_case()
        review = review_packet(receipt)
        self.assertEqual(review["deferred_repositories_not_inspected"], 0)
        self.assertEqual(len(review["items"]), 3)
        self.assertIs(review["execution_authority"], False)
        self.assertIs(review["incident_closed"], False)
        self.assertIs(review["root_cause_verified"], False)

    def test_malformed_failure_scope_is_blocked_from_public_output(self):
        receipt, _, _ = run_case()
        for value in ("AUTO_REPAIR_NOW", True, None):
            with self.subTest(value=value):
                changed = copy.deepcopy(receipt)
                changed["investigations"][0]["provider_failure_scope"] = value
                public = summarize(changed, SOURCE, *["success"] * 4)
                self.assertEqual(public["status"],
                                 "BLOCKED_NO_VERIFIED_INVESTIGATION")
                self.assertEqual(public["repository_local_provider_failures"], 0)
                self.assertEqual(public["provider_failure_hard_stops"], 0)

    def test_legacy_failure_without_scope_remains_conservative(self):
        result, _, _ = run_case()
        old = copy.deepcopy(result)
        old["investigations"] = old["investigations"][:1]
        old["deferred_count"] = 2
        del old["investigations"][0]["provider_failure_scope"]
        sanitized = summarize(old, SOURCE, *["success"] * 4)
        self.assertEqual(sanitized["status"], "PARTIAL_READ_ONLY")
        self.assertEqual(sanitized["repository_local_provider_failures"], 0)
        self.assertEqual(sanitized["provider_failure_hard_stops"], 0)


if __name__ == "__main__":
    unittest.main()
