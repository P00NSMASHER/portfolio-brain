"""Actual CI learning adjusts only matching, noncritical recipe priorities."""
from __future__ import annotations
import copy
import unittest

from brain.core import BrainError
from brain.repair_autonomy import repair_batch
from test_brain_repair_autonomy import fixture, FAC
from test_brain_repair_outcome_learning import episode


def work_fixture():
    doc=fixture()
    row=doc["evidence_to_action_packets"][1]["actionable_review_packets"][2]
    row["theme"]="AUTOMATION_RELIABILITY"
    return doc


def chosen(result):
    return next(x for x in result["actions"] if x["candidate_pr_number"]==37)


class OutcomePrioritizationTests(unittest.TestCase):
    def test_trusted_three_real_technical_successes_boundedly_adjust_routing(self):
        before=repair_batch(work_fixture())
        after=repair_batch(work_fixture(),
                           outcome_episodes=[episode(i,"pass") for i in range(3)])
        self.assertEqual(chosen(after)["urgency"]-chosen(before)["urgency"],5)
        self.assertEqual(chosen(after)["learned_technical_priority_delta"],5)
        self.assertEqual(after["replayed_repair_learning"]["projects"][FAC]
                         ["resolved_independent_technical_samples"],3)
        self.assertFalse(after["authority_to_merge_or_deploy"])

    def test_evidence_of_failed_repairs_reduces_theme_urgency_but_not_other_work(self):
        before=repair_batch(work_fixture())
        after=repair_batch(work_fixture(),outcome_episodes=[
            episode(0,"fail"),episode(1,"fail"),episode(2,"pass"),
        ])
        self.assertEqual(chosen(after)["urgency"],chosen(before)["urgency"]-3)
        old=next(x for x in before["actions"] if x["candidate_pr_number"]==43)
        new=next(x for x in after["actions"] if x["candidate_pr_number"]==43)
        self.assertEqual(old["urgency"],new["urgency"])
        self.assertFalse(after["real_buyer_outcomes_verified"])

    def test_two_successes_or_pending_drafts_do_not_change_any_score(self):
        result=repair_batch(work_fixture(),outcome_episodes=[
            episode(0,"pass"),episode(1,"pending"),episode(2,"pass"),
        ])
        self.assertTrue(all(x["learned_technical_priority_delta"]==0
                            for x in result["actions"]))

    def test_failed_source_ci_remains_p0_even_when_older_recipe_has_weak_track_record(self):
        doc=work_fixture()
        doc["evidence_to_action_packets"][1]["actionable_review_packets"][2][
            "source_ci_status"]="ADVERSE_CHECKS_OBSERVED"
        result=repair_batch(doc,outcome_episodes=[
            episode(0,"fail"),episode(1,"fail"),episode(2,"fail"),
        ])
        self.assertEqual(chosen(result)["urgency"],100)
        self.assertEqual(chosen(result)["learned_technical_priority_delta"],0)
        self.assertEqual(result["actions"][0]["candidate_pr_number"],37)

    def test_rejects_self_asserted_customer_success_as_learning_input(self):
        row=episode(0,"pass")
        row["revenue"]=100000
        with self.assertRaises(BrainError):
            repair_batch(work_fixture(),outcome_episodes=[row])


if __name__=="__main__":
    unittest.main()
