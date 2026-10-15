"""Learning from real, independently checked repair outcomes (not revenue)."""
from __future__ import annotations
import copy
import unittest

from brain.core import BrainError
from brain.repair_outcome_learning import learn_from_repairs
from brain.repair_patch_executor import generate
from test_brain_repair_patch_executor import FIXTURE, request, REPO
from test_brain_repair_delivery import fixture as delivery_fixture

HEX = "123456789abcdef"


def episode(index, outcome):
    original = FIXTURE.replace(
        "name: Factory read only CI",
        f"name: Factory read only CI variant {index}",
    )
    base = HEX[index] * 40
    head = HEX[index + 5] * 40
    merge = HEX[index + 9] * 40
    patch = generate(request(original, source_head_sha=base),
                     original.encode())
    _, pr, _, checks = delivery_fixture()
    pr["number"] = 200 + index
    pr["base"]["sha"] = base
    pr["head"]["sha"] = head
    files = {
        patch["source_path"]: patch["changed_sha256"],
        patch["test_path"]: patch["test_sha256"],
    }
    for row in checks["check_runs"]:
        row["head_sha"] = head
    main = None
    main_checks = None
    if outcome == "pass":
        pr["state"] = "closed"
        pr["merged"] = True
        pr["merge_commit_sha"] = merge
        main = merge
        main_checks = copy.deepcopy(checks)
        for row in main_checks["check_runs"]:
            row["head_sha"] = merge
    elif outcome == "fail":
        pr["state"] = "closed"
        pr["merged"] = False
        checks["check_runs"][0]["conclusion"] = "failure"
    elif outcome == "pending":
        pr["draft"] = True
    else:
        raise AssertionError(outcome)
    return {
        "patch": patch, "original_source": original,
        "pr": pr, "file_hashes": files,
        "candidate_checks": checks, "main_sha": main,
        "main_checks": main_checks,
    }


class SourceValidatedLearningTests(unittest.TestCase):
    def test_insufficient_samples_do_not_influence_repair_priority(self):
        feedback = learn_from_repairs([episode(0, "pass"), episode(1, "pass")])
        row = feedback["projects"][REPO]
        self.assertEqual(row["technical_main_passes"], 2)
        self.assertEqual(row["priority_adjustment"], 0)
        self.assertFalse(row["priority_adjustment_enabled"])
        self.assertIsNone(row["actual_customer_value"])
        self.assertIsNone(row["human_hours_saved"])
        self.assertFalse(feedback["business_effect_measured"])
        self.assertEqual(feedback["synthetic_success_credit"], 0)

    def test_three_distinct_verified_technical_merges_enable_small_heuristic(self):
        feedback = learn_from_repairs([episode(i, "pass") for i in range(3)])
        row = feedback["projects"][REPO]
        self.assertEqual(row["resolved_independent_technical_samples"], 3)
        self.assertEqual(row["distinct_resolved_source_revisions"], 3)
        self.assertEqual(row["technical_main_passes"], 3)
        self.assertEqual(row["priority_adjustment"], 5)
        self.assertTrue(row["priority_adjustment_enabled"])
        self.assertIsNone(row["verified_revenue"])

    def test_failed_exact_source_checks_are_counted_but_not_as_customer_loss(self):
        examples = [episode(0, "fail"), episode(1, "fail"),
                    episode(2, "pass")]
        feedback = learn_from_repairs(examples)
        row = feedback["projects"][REPO]
        self.assertEqual(row["failed_actual_ci_attempts"], 2)
        self.assertEqual(row["technical_main_passes"], 1)
        self.assertEqual(row["priority_adjustment"], -3)
        self.assertIsNone(row["actual_customer_value"])

    def test_pending_drafts_do_not_count_as_failures(self):
        episodes = [episode(0, "pass"), episode(1, "pending"),
                    episode(2, "fail"), episode(3, "pending")]
        row = learn_from_repairs(episodes)["projects"][REPO]
        self.assertEqual(row["resolved_independent_technical_samples"], 2)
        self.assertEqual(row["unresolved_not_treated_as_failures"], 2)
        self.assertFalse(row["priority_adjustment_enabled"])

    def test_duplicate_prs_or_forged_independent_checks_fail_closed(self):
        x = episode(0, "pass")
        with self.assertRaises(BrainError):
            learn_from_repairs([x, copy.deepcopy(x)])
        y = episode(1, "pass")
        y["candidate_checks"]["check_runs"][-1]["app"]["id"] = 15368
        # A forged reviewer cannot manufacture technical source acceptance.
        feedback = learn_from_repairs([y])
        self.assertEqual(feedback["projects"][REPO]["technical_main_passes"], 0)
        self.assertEqual(feedback["projects"][REPO]["unresolved_not_treated_as_failures"], 1)

    def test_tampered_workflow_cannot_be_credited_by_self_asserted_hash(self):
        x = episode(0, "pass")
        x["patch"]["changed_content"] += "\n# skip security"
        import hashlib
        x["patch"]["changed_sha256"] = hashlib.sha256(
            x["patch"]["changed_content"].encode()).hexdigest()
        x["file_hashes"][x["patch"]["source_path"]] = x["patch"]["changed_sha256"]
        with self.assertRaises(BrainError):
            learn_from_repairs([x])

    def test_source_head_mismatch_and_extra_financial_outcome_are_denied(self):
        x = episode(0, "pass")
        x["pr"]["head"]["sha"] = "0" * 40
        with self.assertRaises(BrainError):
            learn_from_repairs([x])
        y = episode(0, "pass")
        y["verified_revenue"] = 500
        with self.assertRaises(BrainError):
            learn_from_repairs([y])

    def test_unknown_or_too_many_provider_inputs_are_refused(self):
        for bad in ([None], "none", [episode(0, "pass")] * 25):
            with self.assertRaises(BrainError):
                learn_from_repairs(bad)

    def test_empty_source_proofs_produce_no_false_business_value(self):
        result = learn_from_repairs([])
        self.assertEqual(result["total_original_episodes"], 0)
        self.assertTrue(all(x["priority_adjustment"] == 0
                            for x in result["projects"].values()))
        self.assertIsNone(result["verified_revenue"])
        self.assertFalse(result["authority_to_contact_pay_merge_or_deploy"])


if __name__ == "__main__":
    unittest.main()
