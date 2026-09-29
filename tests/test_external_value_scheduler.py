import unittest

from scheduler.autonomous_scheduler import (
    _candidate,
    _externalize_candidate,
    build_context,
    load_state,
    policy,
    schedule_cycle,
)


class ExternalValueSchedulerTests(unittest.TestCase):
    def test_current_queue_has_external_milestones_and_value_lane_order(self):
        state,receipt=schedule_cycle(
            load_state(),
            build_context(),
            at="2026-09-29T20:00:00Z",
        )
        selected=receipt["selected_work"]
        self.assertTrue(selected)
        p=policy()
        self.assertTrue(all(w["external_milestone"] in p["external_milestones"] for w in selected))
        self.assertTrue(all(w["value_lane"] in p["value_lane_precedence"] for w in selected))
        self.assertEqual(
            [p["value_lane_precedence"][w["value_lane"]] for w in selected],
            sorted(p["value_lane_precedence"][w["value_lane"]] for w in selected),
        )
        self.assertTrue(receipt["suppressed_no_external_milestone"])
        self.assertEqual(len(state["work_items"]),len(selected))

    def test_owner_publish_gate_is_blocked_not_falsely_completed(self):
        _,receipt=schedule_cycle(load_state(),build_context(),at="2026-09-29T20:00:00Z")
        owner=[w for w in receipt["blocked_work"] if w["source_ref"].startswith("OACT-")]
        self.assertEqual(len(owner),1)
        self.assertEqual(owner[0]["value_lane"],"EXTERNAL_VALUE_BLOCKER")
        self.assertEqual(owner[0]["external_milestone"],"PUBLISH_PRODUCT")
        self.assertIn("OWNER_ACTION_REQUIRED",owner[0]["hard_blockers"])
        self.assertEqual(owner[0]["state"],"BLOCKED_APPROVAL")

    def test_supply_only_hunter_candidate_cannot_enter_queue(self):
        context=build_context()
        supply=_candidate(
            "HUNT","SUPPLY-ONLY",["PRJ-000"],"AGT-HUNTER","PUBLIC_HUNT","OBSERVE","MEDIUM",
            reason="Synthetic GitHub supply discovery.",evidence_refs=["github:public/example@"+("a"*40)],
        )
        self.assertIsNone(_externalize_candidate(supply,context))

    def test_internal_work_requires_explicit_external_milestone_binding(self):
        context=build_context()
        generic=_candidate(
            "TEST","INTERNAL-ONLY",["PRJ-000"],"AGT-TESTER","REGRESSION_VALIDATION","EXPERIMENT","HIGH",
            reason="Synthetic internal test.",evidence_refs=["test:internal-only"],
        )
        self.assertIsNone(_externalize_candidate(generic,context))
        bound=_candidate(
            "TEST","PUBLISH-BLOCKER",["PRJ-000"],"AGT-TESTER","REGRESSION_VALIDATION","EXPERIMENT","HIGH",
            reason="Synthetic publish blocker.",evidence_refs=["test:publish","external-milestone:PUBLISH_PRODUCT"],
        )
        out=_externalize_candidate(bound,context)
        self.assertEqual(out["external_milestone"],"PUBLISH_PRODUCT")
        self.assertEqual(out["value_lane"],"INTERNAL_BLOCKER")


if __name__=="__main__":
    unittest.main()
