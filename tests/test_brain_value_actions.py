"""Delivery-readiness action packets: test source pinning and no false value."""
import copy
import unittest

from brain.core import BrainError
from brain.pr_intelligence import _candidate_from_list, _exact_checks
from brain.value_actions import build_action_packets

RET = "P00NSMASHER/github-value-hunt-ledger"
FAC = "P00NSMASHER/x402-product-factory"
A, B = "a" * 40, "b" * 40


def pr(repo, number, head, title, branch, base="main",
       when="2026-10-14T00:00:00Z"):
    return {
        "number": number, "title": title, "state": "open", "draft": True,
        "updated_at": when,
        "html_url": f"https://github.com/{repo}/pull/{number}",
        "head": {"sha": head, "ref": branch,
                 "repo": {"full_name": repo}},
        "base": {"ref": base, "repo": {"full_name": repo}},
    }


def selected(repo, project):
    if project == "retally":
        rows = [
            pr(repo, 460, A, "RETALLY Lab M55 signed journal replay",
               "m55", "m54", "2026-10-14T00:59:00Z"),
            pr(repo, 329, B, "RETALLY first-customer controls and onboarding",
               "first-customer", "main", "2026-10-13T20:00:00Z"),
            pr(repo, 343, A, "Cross-shipment invoice ID reuse review",
               "invoice", "main", "2026-10-13T19:00:00Z"),
        ]
    else:
        rows = [
            pr(repo, 43, B,
               "Automate evidence-backed app ideas and rehearse private deployments",
               "ideas-and-deploy", "factory/base", "2026-10-14T00:30:00Z"),
            pr(repo, 35, A, "Connect buyer research and attested demand",
               "buyer", "factory/base", "2026-10-13T19:00:00Z"),
            pr(repo, 37, A, "Continuously replenish researched app ideas",
               "ideas", "factory/base", "2026-10-13T20:00:00Z"),
        ]
    record = _candidate_from_list(rows, repo, project, "main")
    outcome = _exact_checks(
        {"total_count": 1, "check_runs": [{
            "id": 123,
            "head_sha": record["head_sha"],
            "status": "completed", "conclusion": "success",
        }]}, record["head_sha"],
    )
    record["checks"] = outcome
    record["status"] = "PR_AND_CHECKS_OBSERVED"
    record["production_merge_authority"] = False
    record["payment_or_external_contact_authority"] = False
    record["buyer_value_verified"] = False
    return record


def priorities(retally=None, factory=None):
    return [
        {
            "project_id": "retally", "repository": RET,
            "observed_source_sha": A,
            "active_pr_review": retally if retally is not None
                                else selected(RET, "retally"),
        },
        {
            "project_id": "product-factory", "repository": FAC,
            "observed_source_sha": A,
            "active_pr_review": factory if factory is not None
                                else selected(FAC, "product-factory"),
        },
    ]


class OpportunityToActionTests(unittest.TestCase):
    def test_produces_six_specific_review_packets_not_generic_recency_list(self):
        packets = build_action_packets(priorities())
        self.assertEqual([p["project_id"] for p in packets],
                         ["retally", "product-factory"])
        self.assertEqual([len(p["actionable_review_packets"]) for p in packets],
                         [3, 3])
        self.assertEqual([x["source_pr_number"]
                          for x in packets[0]["actionable_review_packets"]],
                         [329, 343, 460])
        self.assertEqual([x["source_pr_number"]
                          for x in packets[1]["actionable_review_packets"]],
                         [43, 35, 37])
        self.assertEqual(packets[0]["actionable_review_packets"][0]["theme"],
                         "FIRST_CUSTOMER_CONTROLS")
        self.assertEqual(packets[1]["actionable_review_packets"][0]["theme"],
                         "IDEA_TO_DEPLOYMENT")
        self.assertIn("invoice", packets[0]["actionable_review_packets"][0]
                      ["target_metric"])
        self.assertIn("rehearsal", packets[1]["actionable_review_packets"][0]
                      ["required_proof_artifact"])

    def test_every_packet_is_pinned_review_only_without_fabricated_roi(self):
        packets = build_action_packets(priorities())
        for project in packets:
            self.assertIsNone(project["verified_revenue"])
            self.assertEqual(project["measurement_claim"], "NONE_ESTABLISHED")
            for row in project["actionable_review_packets"]:
                self.assertTrue(row["source_pr_url"].startswith(
                    "https://github.com/" + project["repository"] + "/pull/"))
                self.assertEqual(len(row["source_head_sha"]), 40)
                self.assertIsNone(row["before_value"])
                self.assertIsNone(row["after_value"])
                self.assertIsNone(row["measured_improvement"])
                self.assertFalse(row["buyer_value_verified"])
                self.assertFalse(row["production_release_approved"])
                self.assertFalse(row["downstream_mutation_authority"])
                self.assertFalse(row["external_message_or_payment_authority"])
                self.assertTrue(row["verification_steps"])
                self.assertTrue(row["required_release_gate"])

    def test_green_ci_on_stacked_draft_still_demands_parent_review(self):
        p = build_action_packets(priorities())
        factory = p[1]["actionable_review_packets"][0]
        self.assertEqual(factory["action_gate"],
                         "STACK_DEPENDENCY_REVIEW_REQUIRED")
        self.assertEqual(factory["source_ci_status"],
                         "CHECKS_GREEN_NOT_RELEASE_OR_BUSINESS_ACCEPTANCE")
        self.assertEqual(p[0]["actionable_review_packets"][0]["action_gate"],
                         "INDEPENDENT_BEFORE_AFTER_TEST_REQUIRED")

    def test_skipped_checks_do_not_count_as_pass(self):
        review = selected(RET, "retally")
        review["checks"]["status"] = "SKIPPED_CHECKS_NOT_ACCEPTANCE"
        p = build_action_packets(priorities(retally=review))
        self.assertEqual(p[0]["actionable_review_packets"][0]["action_gate"],
                         "EXACT_SOURCE_CI_AND_PROVENANCE_REQUIRED")

    def test_adverse_checks_call_for_exact_head_repair(self):
        review = selected(RET, "retally")
        review["checks"]["status"] = "ADVERSE_CHECKS_OBSERVED"
        p = build_action_packets(priorities(retally=review))
        self.assertEqual(p[0]["actionable_review_packets"][0]["action_gate"],
                         "REPAIR_EXACT_SOURCE_CI_BEFORE_TESTING")

    def test_secondary_candidate_never_borrows_primary_head_ci(self):
        p = build_action_packets(priorities())
        self.assertEqual(p[0]["actionable_review_packets"][1]["source_ci_status"],
                         "NOT_CHECKED_IN_PRIORITY_SAMPLE")
        self.assertEqual(p[1]["actionable_review_packets"][1]["source_ci_status"],
                         "NOT_CHECKED_IN_PRIORITY_SAMPLE")

    def test_unobserved_source_returns_explicit_empty_actions(self):
        p = build_action_packets(priorities(retally={
            "status": "SOURCE_UNOBSERVED",
            "checks": {"status": "NOT_VERIFIED"},
        }))
        self.assertEqual(p[0]["actionable_review_packets"], [])
        self.assertEqual(p[0]["missing_evidence"], "NEEDS_SOURCE_PINNED_CANDIDATES")

    def test_wrong_repo_is_denied(self):
        x = priorities()
        x[0]["repository"] = FAC
        with self.assertRaises(BrainError):
            build_action_packets(x)

    def test_fake_provider_url_is_denied(self):
        x = priorities()
        x[0]["active_pr_review"]["ranked_opportunities"][0]["pr_url"] =             "https://evil.invalid/steal"
        with self.assertRaises(BrainError):
            build_action_packets(x)

    def test_fake_pr_sha_is_denied(self):
        x = priorities()
        x[1]["active_pr_review"]["ranked_opportunities"][0]["head_sha"] = "not a sha"
        with self.assertRaises(BrainError):
            build_action_packets(x)

    def test_out_of_range_heuristic_score_refused(self):
        x = priorities()
        x[1]["active_pr_review"]["ranked_opportunities"][0]["heuristic_relevance"] = 999
        with self.assertRaises(BrainError):
            build_action_packets(x)

    def test_duplicate_pr_in_ranked_candidates_is_denied(self):
        x = priorities()
        x[0]["active_pr_review"]["ranked_opportunities"][1]["pr_number"] = 329
        with self.assertRaises(BrainError):
            build_action_packets(x)

    def test_unrecognized_theme_cannot_invent_new_release_permission(self):
        x = priorities()
        x[0]["active_pr_review"]["ranked_opportunities"][0]["opportunity_theme"] =             "INJECT_RELEASE_APPROVED"
        p = build_action_packets(x)
        row = p[0]["actionable_review_packets"][0]
        self.assertIn("independent", row["required_release_gate"])
        self.assertFalse(row["production_release_approved"])
        self.assertFalse(row["downstream_mutation_authority"])

    def test_project_missing_or_duplicated_never_passes(self):
        x = priorities()
        with self.assertRaises(BrainError):
            build_action_packets(x[:1])
        x[1]["project_id"] = "retally"
        with self.assertRaises(BrainError):
            build_action_packets(x)


if __name__ == "__main__":
    unittest.main()
