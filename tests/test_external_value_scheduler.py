import unittest

from scheduler.autonomous_scheduler import (
    _candidate,
    _externalize_candidate,
    build_context,
    load_state,
    policy,
    schedule_cycle,
)


class EngineeringValueSchedulerTests(unittest.TestCase):
    def test_current_queue_is_engineering_first(self):
        state,receipt=schedule_cycle(load_state(),build_context(),at="2026-09-29T20:00:00Z")
        selected=receipt["selected_work"]
        self.assertTrue(selected)
        p=policy()
        self.assertFalse(p["commercial_speculation_enabled"])
        self.assertTrue(all(w["external_milestone"] in {"ENGINEERING_RELIABILITY","ENGINEERING_IMPROVEMENT"} for w in selected))
        self.assertTrue(all(w["value_lane"] in {"ENGINEERING_BLOCKER","ENGINEERING_IMPROVEMENT"} for w in selected))
        self.assertFalse(any(w["assigned_agent_id"]=="AGT-COMMERCIAL-ANALYST" for w in selected))
        self.assertEqual(
            [p["value_lane_precedence"][w["value_lane"]] for w in selected],
            sorted(p["value_lane_precedence"][w["value_lane"]] for w in selected),
        )
        self.assertEqual(len(state["work_items"]),len(selected))

    def test_retired_owner_publish_gate_disappears(self):
        _,receipt=schedule_cycle(load_state(),build_context(),at="2026-09-29T20:00:00Z")
        owner=[w for w in receipt["blocked_work"] if w["source_ref"].startswith("OACT-")]
        self.assertEqual(owner,[])

    def test_hunter_supply_routes_to_engineering_improvement_not_commercial_demand(self):
        context=build_context()
        supply=_candidate(
            "HUNT","SUPPLY-ONLY",["PRJ-000"],"AGT-HUNTER","PUBLIC_HUNT","OBSERVE","MEDIUM",
            reason="Synthetic GitHub supply discovery.",evidence_refs=["github:public/example@"+("a"*40)],
        )
        out=_externalize_candidate(supply,context)
        self.assertEqual(out["external_milestone"],"ENGINEERING_IMPROVEMENT")
        self.assertEqual(out["value_lane"],"ENGINEERING_IMPROVEMENT")

    def test_internal_test_routes_to_reliability_even_with_legacy_publish_reference(self):
        context=build_context()
        generic=_candidate(
            "TEST","INTERNAL-ONLY",["PRJ-000"],"AGT-TESTER","REGRESSION_VALIDATION","EXPERIMENT","HIGH",
            reason="Synthetic internal test.",evidence_refs=["test:internal-only"],
        )
        out=_externalize_candidate(generic,context)
        self.assertEqual(out["external_milestone"],"ENGINEERING_RELIABILITY")
        self.assertEqual(out["value_lane"],"ENGINEERING_BLOCKER")
        bound=_candidate(
            "TEST","LEGACY-PUBLISH-BLOCKER",["PRJ-000"],"AGT-TESTER","REGRESSION_VALIDATION","EXPERIMENT","HIGH",
            reason="Historical publish blocker.",evidence_refs=["test:publish","external-milestone:PUBLISH_PRODUCT"],
        )
        rebound=_externalize_candidate(bound,context)
        self.assertEqual(rebound["external_milestone"],"ENGINEERING_RELIABILITY")
        self.assertEqual(rebound["value_lane"],"ENGINEERING_BLOCKER")


if __name__=="__main__":
    unittest.main()
