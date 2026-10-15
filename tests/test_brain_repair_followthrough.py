"""Regression tests for non-dropping owner repair continuation."""
import copy
import unittest

from brain.core import BrainError, digest
from brain.repair_autonomy import repair_batch
from brain.repair_followthrough import follow_through
from test_brain_repair_autonomy import A, B, FAC, RET, fixture


def active():
    return repair_batch(fixture())


def prior(work, state="CLAIMED", cycle=10, attempts=0):
    return {
        "dedupe_key": work["dedupe_key"],
        "exact_evidence_key": work["exact_evidence_key"],
        "repository": work["repository"],
        "owner_task": work["owner_task"],
        "pr_number": work["candidate_pr_number"],
        "head_sha": work["source_head_sha"],
        "state": state,
        "last_progress_cycle": cycle,
        "source_revision_attempts": attempts,
    }


def receipt(work, *, repo=None, sha=None, merged=True, main=None,
            checks=None):
    source = work["repository"] if repo is None else repo
    merge = "c" * 40
    required = (("release-gate", "freight") if source == RET
                else ("test", "browser", "manufacturing"))
    if checks is None:
        checks = [
            {"id": i + 1, "name": name, "head_sha": merge,
             "app_id": 15368, "status": "completed", "conclusion": "success"}
            for i, name in enumerate(required)
        ]
    return {
        "repository": source,
        "pr_number": work["candidate_pr_number"],
        "source_head_sha": work["source_head_sha"] if sha is None else sha,
        "pr_state": "closed" if merged else "open",
        "merged": merged,
        "merge_commit_sha": merge if merged else None,
        "current_main_sha": merge if main is None else main,
        "main_checks": checks,
    }


def getwork(queue, project):
    return next(x for x in queue["actions"] if x["project_id"] == project)


class OwnerFollowThroughTests(unittest.TestCase):
    def test_first_run_prepares_real_next_work_without_extra_authority(self):
        result = follow_through(active(), cycle=10)
        self.assertEqual(result["status"], "UNFINISHED_REPAIRS_TO_CONTINUE")
        self.assertEqual(result["selected_count"], 5)
        self.assertEqual(result["unfinished_count"], 5)
        self.assertEqual(result["technical_main_verified_count"], 0)
        self.assertEqual(len(result["next_history"]), 5)
        self.assertTrue(all(row["state"] == "OBSERVED"
                            for row in result["next_history"]))
        self.assertFalse(result["merge_or_deployment_authority"])
        self.assertTrue(result["independent_gate_required"])
        self.assertTrue(all(x["next_operation"] == "CLAIM_AND_REPRODUCE"
                            for x in result["actions"]))
        self.assertTrue(all(x["live_deployment_verified"] is False
                            for x in result["actions"]))

    def test_unchanged_in_progress_work_never_silently_disappears(self):
        work = getwork(active(), "retally")
        old = prior(work, cycle=10)
        now = follow_through(active(), cycle=11, history=[old])
        task = next(x for x in now["actions"]
                    if x["dedupe_key"] == work["dedupe_key"])
        self.assertEqual(task["next_operation"],
                         "CONTINUE_EXISTING_OWNER_PR_NOT_ANOTHER_PR")
        later = follow_through(active(), cycle=12, history=[old])
        task = next(x for x in later["actions"]
                    if x["dedupe_key"] == work["dedupe_key"])
        self.assertEqual(task["next_operation"],
                         "RESUME_STALLED_OWNER_CHECK_PR_AND_LOGS")

    def test_patch_ci_independent_and_delivery_are_separate_stages(self):
        work = getwork(active(), "product-factory")
        expected = {
            "CI_RED": "PATCH_EXACT_FAILED_REGRESSION",
            "PATCHED": "VERIFY_PATCH_AT_NEW_EXACT_HEAD",
            "CI_GREEN": "GET_SEPARATE_INDEPENDENT_GATE",
            "INDEPENDENT_GREEN": "RECHECK_REAL_RELEASE_HOLDS_AND_MAIN",
            "DELIVERY_REQUESTED": "VERIFY_PROTECTED_MERGE_AND_ACTUAL_MAIN",
            "BLOCKED_EXTERNAL": "PRESERVE_EXTERNAL_HOLD_FIX_NEXT",
        }
        for state, action in expected.items():
            with self.subTest(state=state):
                plan = follow_through(active(), cycle=10,
                    history=[prior(work, state=state)])
                found = next(x for x in plan["actions"]
                             if x["dedupe_key"] == work["dedupe_key"])
                self.assertEqual(found["next_operation"], action)
                self.assertFalse(found["technical_main_source_verified"])

    def test_ci_red_retry_bound_requires_reproducible_failure_escalation(self):
        work = getwork(active(), "retally")
        h = prior(work, state="CI_RED", attempts=2)
        plan = follow_through(active(), cycle=12, history=[h])
        task = next(x for x in plan["actions"]
                    if x["dedupe_key"] == work["dedupe_key"])
        self.assertEqual(task["next_operation"],
                         "ESCALATE_REPRODUCIBLE_FAILURE_WITH_LOGS")

    def test_changed_sha_reopens_same_canonical_owner(self):
        previous = active()
        work = getwork(previous, "retally")
        snapshot = prior(work)
        next_run = copy.deepcopy(previous)
        new = next(x for x in next_run["actions"]
                   if x["dedupe_key"] == work["dedupe_key"])
        new["source_head_sha"] = B
        new["exact_evidence_key"] = digest({
            "dedupe": new["dedupe_key"], "head_sha": B,
            "ci": new["source_ci_status"],
        })
        plan = follow_through(next_run, cycle=11, history=[snapshot])
        item = next(x for x in plan["actions"]
                    if x["dedupe_key"] == work["dedupe_key"])
        self.assertEqual(item["next_operation"],
                         "RECHECK_CHANGED_SOURCE_AND_CI")

    def test_missing_open_pr_does_not_close_original_work(self):
        work = getwork(active(), "product-factory")
        queue = copy.deepcopy(active())
        queue["actions"] = []
        plan = follow_through(queue, cycle=13,
                              history=[prior(work, state="CI_GREEN")])
        self.assertEqual(plan["carried_forward_count"], 1)
        self.assertEqual(plan["selected_count"], 1)
        self.assertEqual(plan["actions"][0]["next_operation"],
                         "REOBSERVE_UNFINISHED_PR_ABSENT_FROM_OPEN_SAMPLE")

    def test_closed_source_candidate_stays_without_main_checks(self):
        work = getwork(active(), "retally")
        pr = receipt(work, checks=[])
        result = follow_through(active(), cycle=10, provider_receipts=[pr])
        task = next(x for x in result["actions"]
                    if x["dedupe_key"] == work["dedupe_key"])
        self.assertEqual(task["provider_status"], "MERGED_MAIN_CHECKS_MISSING")
        self.assertFalse(task["technical_main_source_verified"])

    def test_current_main_exact_required_checks_only_prove_technical_source(self):
        work = getwork(active(), "retally")
        plan = follow_through(active(), cycle=11,
                              provider_receipts=[receipt(work)])
        task = next(x for x in plan["actions"]
                    if x["dedupe_key"] == work["dedupe_key"])
        self.assertTrue(task["technical_main_source_verified"])
        self.assertEqual(task["next_operation"],
                         "MAIN_TECHNICAL_SOURCE_VERIFIED_REVIEW_RUNTIME_SEPARATELY")
        self.assertFalse(task["live_deployment_verified"])
        self.assertFalse(task["financial_or_external_action_authorized"])
        self.assertEqual(plan["technical_main_verified_count"], 1)

    def test_provider_merge_can_close_disappeared_pr_only_with_proof(self):
        work = getwork(active(), "product-factory")
        queue = copy.deepcopy(active())
        queue["actions"] = []
        result = follow_through(queue, cycle=15,
                    history=[prior(work, "DELIVERY_REQUESTED")],
                    provider_receipts=[receipt(work)])
        self.assertEqual(result["carried_forward_count"], 1)
        self.assertEqual(result["technical_main_verified_count"], 1)
        self.assertTrue(result["actions"][0]["technical_main_source_verified"])

    def test_cross_commit_fake_app_skipped_and_partial_checks_fail_closed(self):
        work = getwork(active(), "product-factory")
        versions = [
            ("WRONG_SHA", dict(main=B)),
            ("MISSING_CHECKS", dict(checks=[])),
            ("UNMERGED", dict(merged=False)),
        ]
        for name, kwargs in versions:
            with self.subTest(name=name):
                proof = receipt(work, **kwargs)
                result = follow_through(active(), cycle=11,
                                        provider_receipts=[proof])
                found = next(x for x in result["actions"]
                             if x["dedupe_key"] == work["dedupe_key"])
                self.assertFalse(found["technical_main_source_verified"])
        forged = receipt(work)
        forged["main_checks"][0]["app_id"] = 123
        self.assertFalse(next(x for x in follow_through(active(), cycle=11,
                   provider_receipts=[forged])["actions"]
                   if x["dedupe_key"] == work["dedupe_key"]
                   )["technical_main_source_verified"])
        forged = receipt(work)
        forged["main_checks"][0]["conclusion"] = "skipped"
        self.assertFalse(next(x for x in follow_through(active(), cycle=11,
                   provider_receipts=[forged])["actions"]
                   if x["dedupe_key"] == work["dedupe_key"]
                   )["technical_main_source_verified"])

    def test_stale_wrong_provider_pr_and_history_owner_rejected(self):
        work = getwork(active(), "retally")
        bad = receipt(work, sha=B)
        with self.assertRaises(BrainError):
            follow_through(active(), cycle=11, provider_receipts=[bad])
        h = prior(work)
        h["owner_task"] = "UNTRUSTED_AUTONOMOUS_BUYER_CONTACT"
        with self.assertRaises(BrainError):
            follow_through(active(), cycle=11, history=[h])

    def test_duplicate_future_and_unbounded_states_rejected(self):
        work = getwork(active(), "retally")
        p = prior(work)
        for case in ([p, p], [dict(p, last_progress_cycle=99)],
                     [dict(p, source_revision_attempts=3)],
                     [dict(p, state="PAYMENT_APPROVED")]):
            with self.subTest(case=case), self.assertRaises(BrainError):
                follow_through(active(), cycle=11, history=case)
        for batch in (0, 6, True, "5"):
            with self.assertRaises(BrainError):
                follow_through(active(), cycle=10, max_batch=batch)

    def test_untrusted_current_owner_or_extra_merge_privilege_denied(self):
        for k, value in (
            ("owner_task", "Wrong Owner"),
            ("independent_gate_owner", "Wrong gate"),
            ("project_id", "finance"),
            ("safe_automatic_merge_authority", True),
            ("code_fix_without_new_user_prompt", False),
        ):
            q = copy.deepcopy(active())
            q["actions"][0][k] = value
            with self.subTest(field=k), self.assertRaises(BrainError):
                follow_through(q, cycle=10)

    def test_external_hold_persists_as_explicit_work_without_false_retry(self):
        work = getwork(active(), "retally")
        history = [prior(work, state="BLOCKED_EXTERNAL")]
        p = follow_through(active(), cycle=42, history=history)
        task = next(x for x in p["actions"]
                    if x["dedupe_key"] == work["dedupe_key"])
        self.assertEqual(task["next_operation"],
                         "PRESERVE_EXTERNAL_HOLD_FIX_NEXT")
        self.assertFalse(task["live_deployment_verified"])

    def test_delivered_main_history_is_preserved_without_reopening_work(self):
        work = getwork(active(), "retally")
        prior_source = prior(work, state="MAIN_TECHNICALLY_VERIFIED")
        q = copy.deepcopy(active())
        q["actions"] = []
        plan = follow_through(q, cycle=15, history=[prior_source])
        self.assertEqual(plan["selected_count"], 0)
        self.assertEqual(plan["status"], "NO_UNFINISHED_ACTION_OBSERVED")
        self.assertEqual(plan["archived_verified_count"], 1)
        self.assertEqual(plan["next_history"], [prior_source])

    def test_missing_external_human_gate_stays_recorded_but_not_retried(self):
        work = getwork(active(), "retally")
        q = copy.deepcopy(active())
        q["actions"] = []
        plan = follow_through(q, cycle=15,
                              history=[prior(work, state="BLOCKED_EXTERNAL")])
        self.assertEqual(plan["selected_count"], 1)
        self.assertEqual(plan["actions"][0]["next_operation"],
                         "PRESERVE_EXTERNAL_HOLD_FIX_NEXT")
        self.assertEqual(plan["next_history"][0]["state"], "BLOCKED_EXTERNAL")

    def test_immutable_evidence_hash_cannot_be_substituted(self):
        q = copy.deepcopy(active())
        q["actions"][0]["exact_evidence_key"] = "f"*64
        with self.assertRaises(BrainError):
            follow_through(q, cycle=10)

    def test_source_movement_can_reopen_previous_external_hold(self):
        q = copy.deepcopy(active())
        work = getwork(q, "retally")
        prior_hold = prior(work, state="BLOCKED_EXTERNAL")
        mutable = next(x for x in q["actions"]
                       if x["dedupe_key"] == work["dedupe_key"])
        mutable["source_head_sha"] = B
        mutable["exact_evidence_key"] = digest({
            "dedupe": mutable["dedupe_key"], "head_sha": B,
            "ci": mutable["source_ci_status"],
        })
        result = follow_through(q, cycle=11, history=[prior_hold])
        found = next(x for x in result["actions"]
                     if x["dedupe_key"] == work["dedupe_key"])
        self.assertEqual(found["next_operation"], "RECHECK_CHANGED_SOURCE_AND_CI")
        row = next(x for x in result["next_history"]
                   if x["dedupe_key"] == work["dedupe_key"])
        self.assertEqual(row["state"], "OBSERVED")


if __name__ == "__main__":
    unittest.main()
