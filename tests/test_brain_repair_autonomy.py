"""Bounded repair-controller regressions; all data is synthetic."""
import copy
import unittest

from brain.core import BrainError
from brain.repair_autonomy import repair_batch

RET = "P00NSMASHER/github-value-hunt-ledger"
FAC = "P00NSMASHER/x402-product-factory"
A = "a" * 40
B = "b" * 40
GREEN = "CHECKS_GREEN_NOT_RELEASE_OR_BUSINESS_ACCEPTANCE"


def candidate(repo, number, theme, relevance, ci, base):
    return {
        "source_pr_number": number,
        "source_repository": repo,
        "source_pr_url": f"https://github.com/{repo}/pull/{number}",
        "source_head_sha": A,
        "theme": theme,
        "heuristic_relevance": relevance,
        "source_ci_status": ci,
        "candidate_draft": True,
        "base_branch": base,
        "relevance_not_verified_value": True,
        "buyer_value_verified": False,
        "production_release_approved": False,
        "downstream_mutation_authority": False,
        "external_message_or_payment_authority": False,
        "before_value": None,
        "after_value": None,
        "measured_improvement": None,
        "verification_steps": [
            "Reproduce original fault from source-pinned negative fixtures.",
            "Repeat all exact-head CI and independent source-review tests.",
        ],
        "required_release_gate": "Independent release gate and real customer permissions.",
        "required_proof_artifact": "source_bound_validation_receipt",
    }


def project(pid, repo, candidates):
    return {
        "project_id": pid,
        "repository": repo,
        "measurement_claim": "NONE_ESTABLISHED",
        "verified_revenue": None,
        "actionable_review_packets": candidates,
    }


def fixture():
    return {
        "scope": "READ_ONLY_CROSS_PROJECT_IMPROVEMENT_QUEUE",
        "verified_revenue": None,
        "autonomous_downstream_writes": False,
        "evidence_to_action_packets": [
            project("retally", RET, [
                candidate(RET, 329, "FIRST_CUSTOMER_CONTROLS", 96, GREEN, "main"),
                candidate(RET, 343, "RECOVERY_ACCURACY", 88,
                          "NOT_CHECKED_IN_PRIORITY_SAMPLE", "main"),
                candidate(RET, 460, "SECURITY_CONTINUITY", 78,
                          "NOT_CHECKED_IN_PRIORITY_SAMPLE", "research/m54"),
            ]),
            project("product-factory", FAC, [
                candidate(FAC, 43, "IDEA_TO_DEPLOYMENT", 96, GREEN, "stack"),
                candidate(FAC, 35, "BUYER_VALIDATION", 95,
                          "NOT_CHECKED_IN_PRIORITY_SAMPLE", "stack"),
                candidate(FAC, 37, "IDEA_QUALITY", 84,
                          "NOT_CHECKED_IN_PRIORITY_SAMPLE", "stack"),
            ]),
        ],
    }


class RepairControllerTests(unittest.TestCase):
    def test_five_actions_are_ranked_not_just_listed(self):
        result = repair_batch(fixture())
        self.assertEqual(result["actionable_count"], 6)
        self.assertEqual(result["selected_count"], 5)
        self.assertEqual(result["deferred_due_to_batch_bound"], 1)
        self.assertEqual(result["actions"][0]["stage"], "ESTABLISH_EXACT_SOURCE_CI")
        self.assertEqual(result["actions"][-1]["stage"],
                         "RECONCILE_STACK_AND_INDEPENDENT_TEST")
        self.assertFalse(result["authority_to_merge_or_deploy"])
        self.assertIsNone(result["verified_revenue"])

    def test_task_owner_is_different_from_independent_gate(self):
        result = repair_batch(fixture())
        for item in result["actions"]:
            self.assertNotEqual(item["owner_task"], item["independent_gate_owner"])
            self.assertTrue(item["code_fix_without_new_user_prompt"])
            self.assertTrue(item["negative_and_acceptance_tests"])
            self.assertTrue(item["required_release_gate"])
            self.assertEqual(len(item["exact_evidence_key"]), 64)
            self.assertFalse(item["safe_automatic_merge_authority"])
            self.assertFalse(item["financial_or_external_contact_authority"])
            self.assertFalse(item["production_delivered"])

    def test_adverse_ci_beats_work_scored_more_recent(self):
        doc = fixture()
        row = doc["evidence_to_action_packets"][0]["actionable_review_packets"][0]
        row["source_ci_status"] = "ADVERSE_CHECKS_OBSERVED"
        first = repair_batch(doc)["actions"][0]
        self.assertEqual(first["candidate_pr_number"], 329)
        self.assertEqual(first["stage"], "REPAIR_EXACT_SOURCE_CI")

    def test_unchanged_exact_evidence_is_deduplicated_without_losing_future_work(self):
        first = repair_batch(fixture())
        evidence = [x["exact_evidence_key"] for x in first["actions"]]
        second = repair_batch(fixture(), previous_evidence=evidence)
        self.assertEqual(second["suppressed_duplicate_count"], 5)
        self.assertEqual(second["selected_count"], 1)
        done = repair_batch(fixture(), previous_evidence=evidence + [
            second["actions"][0]["exact_evidence_key"]
        ])
        self.assertEqual(done["status"], "NO_NEW_SOURCE_BOUND_TECHNICAL_ACTION")
        self.assertEqual(done["selected_count"], 0)
        self.assertEqual(done["suppressed_duplicate_count"], 6)

    def test_exact_head_change_reopens_same_issue_identity(self):
        doc = fixture()
        first = repair_batch(doc)
        original = next(x for x in first["actions"]
                        if x["candidate_pr_number"] == 343)
        new = copy.deepcopy(doc)
        new["evidence_to_action_packets"][0]["actionable_review_packets"][1]["source_head_sha"] = B
        second = repair_batch(new, previous_evidence=[
            original["exact_evidence_key"]
        ])
        revised = next(x for x in second["actions"] if x["candidate_pr_number"] == 343)
        self.assertEqual(revised["dedupe_key"], original["dedupe_key"])
        self.assertNotEqual(revised["exact_evidence_key"], original["exact_evidence_key"])

    def test_unknown_project_and_forged_pr_identity_fail_closed(self):
        for key, wrong in (
            ("source_pr_number", True),
            ("source_pr_url", "https://evil.test/claim"),
            ("source_head_sha", "not-a-sha"),
            ("source_repository", FAC),
            ("theme", "CUSTOMER_PAYMENT_AUTHORIZED"),
            ("heuristic_relevance", 999),
            ("candidate_draft", "true"),
            ("source_ci_status", "PRODUCTION_ACCEPTED"),
        ):
            doc = fixture()
            doc["evidence_to_action_packets"][0]["actionable_review_packets"][0][key] = wrong
            with self.subTest(key=key), self.assertRaises(BrainError):
                repair_batch(doc)

    def test_cannot_elevate_payment_or_release_permissions(self):
        for key, wrong in (
            ("buyer_value_verified", True),
            ("production_release_approved", True),
            ("downstream_mutation_authority", True),
            ("external_message_or_payment_authority", True),
            ("before_value", 1),
            ("after_value", 2),
            ("measured_improvement", 3),
        ):
            doc = fixture()
            doc["evidence_to_action_packets"][0]["actionable_review_packets"][0][key] = wrong
            with self.subTest(key=key), self.assertRaises(BrainError):
                repair_batch(doc)

    def test_no_source_means_explicit_missing_evidence_not_fabricated_repair(self):
        doc = fixture()
        for project in doc["evidence_to_action_packets"]:
            project["actionable_review_packets"] = []
        result = repair_batch(doc)
        self.assertEqual(result["selected_count"], 0)
        self.assertEqual(len(result["missing"]), 2)
        self.assertFalse(result["authority_to_merge_or_deploy"])

    def test_duplicate_claims_and_prior_receipt_input_are_strictly_validated(self):
        doc = fixture()
        items = doc["evidence_to_action_packets"][0]["actionable_review_packets"]
        items[1] = copy.deepcopy(items[0])
        with self.assertRaises(BrainError):
            repair_batch(doc)
        for value in (-1, 0, 6, True, "3"):
            with self.assertRaises(BrainError):
                repair_batch(fixture(), max_batch=value)
        for value in ([1], ["not-a-hash"], "bad"):
            with self.assertRaises(BrainError):
                repair_batch(fixture(), previous_evidence=value)


    def test_overflow_slot_alternates_to_prevent_source_starvation(self):
        even = repair_batch(fixture(), cycle_index=100)
        odd = repair_batch(fixture(), cycle_index=101)
        self.assertEqual(even["selected_count"], 5)
        self.assertEqual(odd["selected_count"], 5)
        self.assertEqual(even["rotated_overflow_index"], 4)
        self.assertEqual(odd["rotated_overflow_index"], 5)
        ids = lambda row: {x["dedupe_key"] for x in row["actions"]}
        self.assertEqual(len(ids(even) | ids(odd)), 6)
        self.assertEqual(len(ids(even) & ids(odd)), 4)
        self.assertEqual(even["rotation_rule"],
                         "HIGHEST_PRIORITY_N_MINUS_ONE_PLUS_ONE_FAIR_OVERFLOW_SLOT")
        self.assertFalse(even["authority_to_merge_or_deploy"])
        self.assertFalse(odd["authority_to_merge_or_deploy"])

    def test_single_action_budget_eventually_samples_every_source(self):
        reports=[repair_batch(fixture(), max_batch=1, cycle_index=index)
                 for index in range(6)]
        self.assertEqual(
            len({r["actions"][0]["dedupe_key"] for r in reports}), 6
        )
        self.assertTrue(all(r["max_actions_per_run"] == 1 for r in reports))
        self.assertTrue(all(not r["authority_to_merge_or_deploy"]
                            for r in reports))

    def test_rotation_index_does_not_accept_fake_or_negative_sequences(self):
        for value in (-1, True, "0", None, 2**63):
            with self.subTest(value=value), self.assertRaises(BrainError):
                repair_batch(fixture(), cycle_index=value)



if __name__ == "__main__":
    unittest.main()
