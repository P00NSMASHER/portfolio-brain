"""Completed repair regressions must reopen without widening authority."""
import copy
import unittest
from brain.core import BrainError, digest
from brain.repair_followthrough import follow_through
from brain.repair_provider import collect_original_proofs, apply_original_ci_to_owner_queue
from test_brain_repair_followthrough import active, prior, receipt, getwork
from test_brain_repair_provider import rig, pr_for, original_checks, MAIN
from test_brain_repair_autonomy import B


class VerifiedRepairRegressionTests(unittest.TestCase):
    def test_active_verified_record_reopens_on_fresh_adverse_main(self):
        queue = active()
        work = getwork(queue, "retally")
        proof = receipt(work)
        proof["main_checks"][0]["conclusion"] = "failure"
        plan = follow_through(queue, cycle=11,
            history=[prior(work, "MAIN_TECHNICALLY_VERIFIED")],
            provider_receipts=[proof])
        task = next(x for x in plan["actions"] if x["dedupe_key"] == work["dedupe_key"])
        self.assertEqual(task["next_operation"], "REVERIFY_PREVIOUSLY_VERIFIED_MAIN")
        row = next(x for x in plan["next_history"] if x["dedupe_key"] == work["dedupe_key"])
        self.assertEqual(row["state"], "OBSERVED")
        self.assertFalse(task["technical_main_source_verified"])
        self.assertFalse(plan["merge_or_deployment_authority"])

    def test_archived_verified_record_cannot_hide_fresh_adverse_proof(self):
        queue = active()
        work = getwork(queue, "retally")
        queue["actions"] = []
        proof = receipt(work)
        proof["main_checks"][0]["conclusion"] = "failure"
        plan = follow_through(queue, cycle=11,
            history=[prior(work, "MAIN_TECHNICALLY_VERIFIED")],
            provider_receipts=[proof])
        self.assertEqual(plan["selected_count"], 1)
        self.assertEqual(plan["archived_verified_count"], 0)
        self.assertEqual(plan["next_history"][0]["state"], "OBSERVED")
        self.assertEqual(plan["actions"][0]["next_operation"], "REVERIFY_PREVIOUSLY_VERIFIED_MAIN")
        self.assertFalse(plan["actions"][0]["live_deployment_verified"])

    def test_advanced_main_requests_verification_without_claiming_regression_cause(self):
        queue = active()
        work = getwork(queue, "retally")
        queue["actions"] = []
        plan = follow_through(queue, cycle=11,
            history=[prior(work, "MAIN_TECHNICALLY_VERIFIED")],
            provider_receipts=[receipt(work, main=B)])
        self.assertEqual(plan["selected_count"], 1)
        self.assertEqual(plan["actions"][0]["provider_status"],
                         "MERGED_ANCESTRY_TO_LATEST_MAIN_NOT_VERIFIED")
        self.assertFalse(plan["actions"][0]["technical_main_source_verified"])

    def test_cross_source_receipt_for_archived_record_is_rejected(self):
        queue = active()
        work = getwork(queue, "retally")
        queue["actions"] = []
        with self.assertRaises(BrainError):
            follow_through(queue, cycle=11,
                history=[prior(work, "MAIN_TECHNICALLY_VERIFIED")],
                provider_receipts=[receipt(work, sha=B)])

    def test_quiet_archived_repair_is_rechecked_and_reopened_from_original_provider(self):
        queue, api = rig()
        work = queue["actions"][0]
        repo, number = work["repository"], work["candidate_pr_number"]
        queue["actions"] = []
        api.put(repo, f"/pulls/{number}", pr_for(repo, number, merged=True, merge=MAIN))
        api.put(repo, f"/commits/{MAIN}/check-runs?per_page=100", original_checks(repo, MAIN))
        api.payloads[(repo, f"/commits/{MAIN}/check-runs?per_page=100")]["check_runs"][0]["conclusion"] = "failure"
        history = [prior(work, "MAIN_TECHNICALLY_VERIFIED")]
        proof = collect_original_proofs(queue, prior=history, transport=api)
        self.assertEqual(proof["observed_pr_count"], 1)
        self.assertEqual(proof["requests_used"], 4)
        plan = follow_through(queue, cycle=11, history=history, provider_receipts=proof["proofs"])
        plan = apply_original_ci_to_owner_queue(plan, proof["source_checks"])
        self.assertEqual(plan["actions"][0]["next_operation"], "REVERIFY_PREVIOUSLY_VERIFIED_MAIN")
        self.assertEqual(plan["next_history"][0]["state"], "OBSERVED")
        self.assertFalse(plan["real_buyer_or_revenue_verified"])

    def test_busy_queue_reserves_bounded_recheck_without_starving_unfinished_work(self):
        queue, api = rig()
        work = copy.deepcopy(queue["actions"][0])
        work["candidate_pr_number"] = 999
        work["source_head_sha"] = B
        work["dedupe_key"] = digest({"project": work["project_id"], "repository": work["repository"],
                                    "pr": 999, "theme": work["opportunity_theme"]})
        work["exact_evidence_key"] = digest({"dedupe": work["dedupe_key"], "head_sha": B,
                                            "ci": work["source_ci_status"]})
        old = prior(work, "MAIN_TECHNICALLY_VERIFIED")
        repo = work["repository"]
        api.put(repo, "/pulls/999", pr_for(repo, 999, sha=B, merged=True, merge=MAIN))
        api.put(repo, f"/commits/{B}/check-runs?per_page=100", original_checks(repo, B))
        api.put(repo, f"/commits/{MAIN}/check-runs?per_page=100", original_checks(repo, MAIN))
        seen = []
        for sequence in range(12):
            result = collect_original_proofs(queue, prior=[old], transport=api,
                max_jobs=1, max_requests=4, selection_sequence=sequence)
            self.assertLessEqual(result["requests_used"], 4)
            seen.append(result["proofs"][0]["pr_number"])
        self.assertEqual(seen[5], 999)
        self.assertEqual(seen[11], 999)
        self.assertEqual(set(seen[:5]), {x["candidate_pr_number"] for x in queue["actions"]})
        self.assertNotEqual(seen[6], 999)
