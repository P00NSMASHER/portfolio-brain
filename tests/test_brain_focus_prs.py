"""Synthetic and hostile exact-PR action-intelligence regression coverage."""
import unittest

from brain.core import BrainError
from brain.pr_intelligence import (
    _candidate_from_list, _exact_checks, observe_priority_prs,
)
from brain.projects import FOCUS

SHA_A, SHA_B = "a" * 40, "b" * 40
RET = "P00NSMASHER/github-value-hunt-ledger"
FACT = "P00NSMASHER/x402-product-factory"


def pr(repo, number, sha, ref, base, *, title=None,
       updated="2026-10-14T00:20:00Z", draft=True):
    return {
        "number": number, "state": "open", "draft": draft,
        "title": title if title is not None else
                 ("RETALLY journal acceptance" if repo == RET else "Factory build"),
        "updated_at": updated,
        "html_url": f"https://github.com/{repo}/pull/{number}",
        "head": {"repo": {"full_name": repo}, "sha": sha, "ref": ref},
        "base": {"repo": {"full_name": repo}, "ref": base},
    }


def check(id, sha, conclusion="success", status="completed"):
    return {"id": id, "head_sha": sha,
            "conclusion": conclusion, "status": status}


class Adapter:
    def __init__(self, requests=20, bad_sha=False):
        self.requests = requests
        self.paths = []
        self.bad_sha = bad_sha

    def get(self, path):
        self.paths.append(path)
        self.requests += 1
        if "/pulls?" in path and RET in path:
            return [
                pr(RET, 460, SHA_A, "research/m55", "research/m54"),
                pr(RET, 458, SHA_B, "research/m54", "research/m53",
                   updated="2026-10-13T23:00:00Z"),
                pr(RET, 399, SHA_B, "social", "main", title="Unrelated asset",
                   updated="2026-10-14T00:59:00Z"),
            ]
        if "/pulls?" in path and FACT in path:
            return [
                pr(FACT, 42, SHA_B, "factory/cycle", "factory/inventory"),
                pr(FACT, 41, SHA_A, "factory/inventory", "factory/quote",
                   updated="2026-10-13T23:00:00Z"),
            ]
        if "/check-runs?" in path:
            sha = path.split("/commits/", 1)[1].split("/", 1)[0]
            entries = ([check(1, sha), check(2, sha, "skipped")]
                       if RET in path else [check(1, sha), check(2, sha)])
            if self.bad_sha:
                entries[1]["head_sha"] = "f" * 40
            return {"total_count": 2, "check_runs": entries}
        raise AssertionError("unexpected endpoint")


def sources():
    return {repo: {"repository": repo, "head_sha": SHA_A,
                   "default_branch": "main"} for repo in (RET, FACT)}


class FocusSourceTests(unittest.TestCase):
    def test_two_pr_lists_before_two_sha_bound_ci_checks_within_24_gets(self):
        api = Adapter()
        result = observe_priority_prs(api, sources(), review_contracts=FOCUS)
        self.assertEqual(api.requests, 24)
        self.assertEqual(len(api.paths), 4)
        self.assertTrue(all("/pulls?" in p for p in api.paths[:2]))
        self.assertTrue(all("/check-runs?" in p for p in api.paths[2:]))
        retally, factory = result["retally"], result["product-factory"]
        self.assertEqual((retally["pr_number"], retally["sampled_parent_pr"]),
                         (460, 458))
        self.assertEqual((factory["pr_number"], factory["sampled_parent_pr"]),
                         (42, 41))
        self.assertTrue(retally["draft"] and factory["draft"])
        self.assertTrue(retally["stacked_on_nondefault_branch"])
        self.assertEqual(retally["checks"]["status"],
                         "SKIPPED_CHECKS_NOT_ACCEPTANCE")
        self.assertEqual(factory["checks"]["status"],
                         "CHECKS_GREEN_NOT_RELEASE_OR_BUSINESS_ACCEPTANCE")
        for record in result.values():
            self.assertFalse(record["production_merge_authority"])
            self.assertFalse(record["payment_or_external_contact_authority"])
            self.assertFalse(record["buyer_value_verified"])

    def test_full_budget_skips_both_without_network_access(self):
        api = Adapter(requests=24)
        report = observe_priority_prs(api, sources(), review_contracts=FOCUS)
        self.assertEqual(api.paths, [])
        self.assertEqual({p["status"] for p in report.values()},
                         {"REQUEST_BUDGET_UNAVAILABLE"})

    def test_one_remaining_get_cannot_invent_exact_head_ci(self):
        api = Adapter(requests=23)
        report = observe_priority_prs(api, sources(), review_contracts=FOCUS)
        self.assertEqual(api.requests, 24)
        self.assertEqual(report["retally"]["status"],
                         "PR_OBSERVED_CHECKS_UNVERIFIED")
        self.assertFalse(report["retally"]["checks"]["complete_single_page"])
        self.assertEqual(report["product-factory"]["status"],
                         "REQUEST_BUDGET_UNAVAILABLE")

    def test_missing_app_factory_source_cannot_be_filled_by_retally(self):
        api = Adapter()
        report = observe_priority_prs(
            api, {RET: sources()[RET]}, review_contracts=FOCUS,
        )
        self.assertEqual(report["product-factory"]["status"],
                         "SOURCE_UNOBSERVED")
        self.assertEqual(api.requests, 22)

    def test_adverse_incomplete_skipped_and_good_are_distinct(self):
        for conclusion, status, expected in [
            ("failure", "completed", "ADVERSE_CHECKS_OBSERVED"),
            ("skipped", "completed", "SKIPPED_CHECKS_NOT_ACCEPTANCE"),
            (None, "queued", "INCOMPLETE_CHECKS_OBSERVED"),
            ("success", "completed",
             "CHECKS_GREEN_NOT_RELEASE_OR_BUSINESS_ACCEPTANCE"),
        ]:
            with self.subTest(conclusion=conclusion, status=status):
                got = _exact_checks({"total_count": 1, "check_runs": [
                    check(4, SHA_A, conclusion, status),
                ]}, SHA_A)
                self.assertEqual(got["status"], expected)

    def test_wrong_commit_duplicate_id_and_second_page_refuse_green(self):
        for page in [
            {"total_count": 1, "check_runs": [check(1, SHA_B)]},
            {"total_count": 2, "check_runs": [
                check(1, SHA_A), check(1, SHA_A)]},
            {"total_count": 101, "check_runs": []},
            {"total_count": 2, "check_runs": [check(1, SHA_A)]},
        ]:
            with self.subTest(page=page):
                with self.assertRaises(BrainError):
                    _exact_checks(page, SHA_A)

    def test_unverifiable_check_page_preserves_candidacy_but_not_acceptance(self):
        reports = observe_priority_prs(
            Adapter(bad_sha=True), sources(), review_contracts=FOCUS,
        )
        for value in reports.values():
            self.assertEqual(value["status"], "PR_OBSERVED_CHECKS_UNVERIFIED")
            self.assertFalse(value["checks"]["complete_single_page"])
            self.assertFalse(value["buyer_value_verified"])

    def test_forged_url_fork_timestamp_and_duplicate_row_do_not_consume_candidate(self):
        fork = pr(RET, 3, SHA_B, "fork", "main")
        fork["head"]["repo"]["full_name"] = "attacker/repo"
        fake = pr(RET, 4, SHA_B, "fake", "main")
        fake["html_url"] = "https://evil.invalid"
        badtime = pr(RET, 5, SHA_B, "badtime", "main")
        badtime["updated_at"] = "2026-99-99T00:00:00Z"
        clean = pr(RET, 8, SHA_A, "clean", "main")
        review = _candidate_from_list(
            [fork, fake, badtime, clean, dict(clean)], RET, "retally", "main",
        )
        self.assertEqual(review["discarded_rows"], 4)
        self.assertEqual(review["pr_number"], 8)
        self.assertEqual(review["pr_url"],
                         "https://github.com/P00NSMASHER/github-value-hunt-ledger/pull/8")

    def test_title_is_untrusted_filter_only_and_never_rendered(self):
        value = _candidate_from_list([
            pr(RET, 8, SHA_A, "unsafe", "main",
               title="RETALLY <script>external instruction</script>"),
        ], RET, "retally", "main")
        self.assertNotIn("script", str(value))
        self.assertNotIn("external instruction", str(value))

    def test_first_customer_and_invoice_transfer_outrank_incremental_labs(self):
        rows = [
            pr(RET, 460, SHA_A, "research/m55", "research/m54",
               title="RETALLY Lab M55 journal replay",
               updated="2026-10-14T00:59:00Z"),
            pr(RET, 343, SHA_B, "safe/review", "main",
               title="Portfolio Brain transfer: review cross-shipment invoice ID reuse",
               updated="2026-10-13T22:00:00Z"),
            pr(RET, 329, SHA_B, "retally/first", "main",
               title="RETALLY first-customer controls and onboarding",
               updated="2026-10-13T20:00:00Z"),
        ]
        report = _candidate_from_list(rows, RET, "retally", "main")
        self.assertEqual(report["pr_number"], 329)
        self.assertEqual(report["opportunity_theme"], "FIRST_CUSTOMER_CONTROLS")
        top = report["ranked_opportunities"]
        self.assertEqual([x["pr_number"] for x in top], [329, 343, 460])
        self.assertTrue(all(x["buyer_value_verified"] is False for x in top))
        self.assertTrue(all(x["measured_revenue"] is None for x in top))

    def test_dual_idea_deployment_outranks_recent_unverified_factory_build(self):
        rows = [
            pr(FACT, 37, SHA_A, "factory/ideas", "factory/base",
               title="Continuously replenish researched app ideas",
               updated="2026-10-14T02:30:00Z"),
            pr(FACT, 43, SHA_B, "factory/idea-deploy", "factory/base",
               title="Automate evidence-backed app ideas and rehearse private deployments",
               updated="2026-10-14T01:00:00Z"),
            pr(FACT, 35, SHA_A, "factory/buyer", "factory/base",
               title="Connect buyer research and attested demand",
               updated="2026-10-13T19:00:00Z"),
        ]
        report = _candidate_from_list(rows, FACT, "product-factory", "main")
        self.assertEqual(report["pr_number"], 43)
        self.assertEqual([x["opportunity_theme"]
                          for x in report["ranked_opportunities"]],
                         ["IDEA_TO_DEPLOYMENT", "BUYER_VALIDATION", "IDEA_QUALITY"])
        self.assertEqual(report["ranking_basis"],
                         "FIXED_TITLE_HEURISTIC_NO_CUSTOMER_OR_ROI_EVIDENCE")

    def test_keyword_repetition_does_not_fabricate_higher_buyer_impact(self):
        one = _candidate_from_list([
            pr(FACT, 50, SHA_B, "new", "main",
               title="Automate evidence-backed app ideas and private deployments"),
        ], FACT, "product-factory", "main")
        repeated = _candidate_from_list([
            pr(FACT, 51, SHA_B, "newer", "main",
               title="Automate ideas ideas ideas deployments deployments"),
        ], FACT, "product-factory", "main")
        self.assertEqual(one["heuristic_relevance"], repeated["heuristic_relevance"])

    def test_retally_ignores_more_recent_unrelated_ledger_pr(self):
        review = _candidate_from_list([
            pr(RET, 12, SHA_B, "unrelated", "main",
               title="PermitPlate", updated="2026-10-14T00:59:00Z"),
            pr(RET, 11, SHA_A, "retally", "main",
               title="RETALLY M55", updated="2026-10-14T00:20:00Z"),
        ], RET, "retally", "main")
        self.assertEqual(review["pr_number"], 11)


if __name__ == "__main__":
    unittest.main()
