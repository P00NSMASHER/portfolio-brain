import unittest

from operations.value_loop import (
    build_signal_snapshot,
    build_value_loop_snapshot,
    classify_technical_outcome,
    investment_credit_allowed,
    primary_operator_view,
    technical_routing_credit_allowed,
)


class ValueLoopTests(unittest.TestCase):
    def test_technical_verified_is_routing_credit_not_business_investment(self):
        outcome={"value_status":"VALUE_OUTCOME_VERIFIED","evidence_state":"VERIFIED"}
        evidence_class=classify_technical_outcome(outcome)
        self.assertEqual(evidence_class,"TECHNICAL_VERIFIED")
        self.assertTrue(technical_routing_credit_allowed(evidence_class))
        self.assertFalse(investment_credit_allowed(evidence_class))
        self.assertTrue(investment_credit_allowed("MARKET_VERIFIED"))
        self.assertTrue(investment_credit_allowed("REVENUE_VERIFIED"))

    def test_current_value_loop_points_at_real_external_publish_milestone(self):
        snapshot=build_value_loop_snapshot()
        self.assertEqual(snapshot["money_earned_usd"],0.0)
        self.assertEqual(snapshot["closest_external_milestone"],"PUBLISH_PRODUCT")
        self.assertEqual(snapshot["current_blocker"],"OWNER_PUBLISH_REQUIRED")
        self.assertEqual(len(snapshot["owner_action_queue"]),1)
        action=snapshot["owner_action_queue"][0]
        self.assertEqual(action["source_ref"],"SKU-001")
        self.assertEqual(action["external_milestone"],"PUBLISH_PRODUCT")
        self.assertEqual(action["price_usd"],3.99)
        self.assertEqual(action["package"],"Quiz_Reward_Engine_v1.0.zip")
        self.assertIn("OWNER ACTION REQUIRED: Publish SKU-001",action["instruction"])

    def test_runtime_qa_only_exists_because_it_blocks_publish(self):
        snapshot=build_value_loop_snapshot()
        refs={row["source_ref"]:row for row in snapshot["blocking_work"]}
        self.assertEqual(set(refs),{"SKU-002","SKU-003"})
        for row in refs.values():
            self.assertEqual(row["value_lane"],"INTERNAL_BLOCKER")
            self.assertEqual(row["external_milestone"],"PUBLISH_PRODUCT")
            self.assertIn("external-milestone:PUBLISH_PRODUCT",row["evidence_refs"])

    def test_github_supply_is_never_demand_or_investment_credit(self):
        signals=build_signal_snapshot(hunter_proposal_state={
            "proposals":[{"proposal_id":"HXP-1"},{"proposal_id":"HXP-2"}]
        })
        self.assertFalse(signals["github_supply_creates_demand"])
        self.assertEqual(len(signals["supply_signals"]),2)
        self.assertTrue(all(row["signal_role"]=="SUPPLY" for row in signals["supply_signals"]))
        self.assertTrue(all(row["investment_credit"] is False for row in signals["supply_signals"]))
        # Current checked-in commercial observation is OBSERVED, not VERIFIED.
        self.assertEqual(signals["verified_demand_count"],0)
        self.assertEqual(signals["investment_credit_signal_count"],0)

    def test_primary_operator_view_is_exactly_six_business_questions(self):
        view=primary_operator_view()
        self.assertEqual(set(view),{
            "money_earned",
            "active_external_experiment",
            "closest_external_milestone",
            "current_blocker",
            "action_required_from_owner",
            "last_verified_customer_or_market_signal",
        })


if __name__=="__main__":
    unittest.main()
