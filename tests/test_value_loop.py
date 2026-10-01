import copy
import unittest

from operations.value_loop import (
    build_signal_snapshot,
    build_value_loop_snapshot,
    load,
    classify_technical_outcome,
    investment_credit_allowed,
    primary_operator_view,
    technical_routing_credit_allowed,
)


class ValueLoopTests(unittest.TestCase):
    def test_only_technical_verified_has_active_routing_credit(self):
        outcome={"value_status":"VALUE_OUTCOME_VERIFIED","evidence_state":"VERIFIED"}
        evidence_class=classify_technical_outcome(outcome)
        self.assertEqual(evidence_class,"TECHNICAL_VERIFIED")
        self.assertTrue(technical_routing_credit_allowed(evidence_class))
        self.assertFalse(investment_credit_allowed(evidence_class))
        self.assertFalse(investment_credit_allowed("MARKET_VERIFIED"))
        self.assertFalse(investment_credit_allowed("REVENUE_VERIFIED"))

    def test_retired_factory_creates_no_publish_or_owner_work(self):
        snapshot=build_value_loop_snapshot()
        self.assertEqual(snapshot["money_earned_usd"],0.0)
        self.assertIsNone(snapshot["active_external_experiment"])
        self.assertIsNone(snapshot["closest_external_milestone"])
        self.assertIsNone(snapshot["current_blocker"])
        self.assertEqual(snapshot["owner_action_queue"],[])
        self.assertEqual(snapshot["blocking_work"],[])

    def test_historical_marketplace_state_cannot_reactivate_retired_factory(self):
        factory=copy.deepcopy(load("operations/MICRO_PRODUCT_FACTORY.json"))
        factory["published_count"]=1
        factory["verified_sales_count"]=1
        factory["verified_revenue_usd"]=3.99
        snapshot=build_value_loop_snapshot(factory=factory)
        self.assertEqual(snapshot["owner_action_queue"],[])
        self.assertEqual(snapshot["blocking_work"],[])
        self.assertIsNone(snapshot["active_external_experiment"])
        self.assertIsNone(snapshot["closest_external_milestone"])

    def test_github_supply_is_never_demand_or_investment_credit(self):
        signals=build_signal_snapshot(hunter_proposal_state={
            "proposals":[{"proposal_id":"HXP-1"},{"proposal_id":"HXP-2"}]
        })
        self.assertFalse(signals["github_supply_creates_demand"])
        self.assertEqual(len(signals["supply_signals"]),2)
        self.assertTrue(all(row["signal_role"]=="SUPPLY" for row in signals["supply_signals"]))
        self.assertTrue(all(row["investment_credit"] is False for row in signals["supply_signals"]))
        self.assertEqual(signals["investment_credit_signal_count"],0)

    def test_primary_operator_view_shape_remains_backward_compatible(self):
        view=primary_operator_view()
        self.assertEqual(set(view),{
            "money_earned",
            "active_external_experiment",
            "closest_external_milestone",
            "current_blocker",
            "action_required_from_owner",
            "last_verified_customer_or_market_signal",
        })
        self.assertIsNone(view["active_external_experiment"])
        self.assertIsNone(view["closest_external_milestone"])
        self.assertIsNone(view["current_blocker"])
        self.assertIsNone(view["action_required_from_owner"])


if __name__=="__main__":
    unittest.main()
