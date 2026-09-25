import copy,os,unittest
from unittest.mock import patch

from cost_governor.cost_governor import load_state as load_cost_state
from notifications.notification_engine import (
    build_signals,load_state,notification_cycle,policy,validate_alert_record
)

AT="2026-09-25T22:40:00Z"

def base_sources(dashboard_hash="sha256:"+"a"*64):
    return {
      "dashboard":{"snapshot_hash":dashboard_hash},
      "scheduler_receipt":{"blocked_work":[]},
      "scheduler_state":{"work_items":[]},
      "cost_state":load_cost_state(),
      "build_state":{"blockers":[]},
      "experiment_outcomes":[],
      "experiment_plans":[],
      "transfer_outcomes":[]
    }

class NotificationTests(unittest.TestCase):
    def test_current_state_emits_two_aggregated_human_attention_alerts(self):
        state,receipt=notification_cycle(load_state(),at=AT)
        self.assertEqual({x["kind"] for x in receipt["emitted_alerts"]},{"HUMAN_APPROVAL_QUEUE","OPEN_HUMAN_BLOCKERS"})
        self.assertEqual(len(receipt["emitted_alerts"]),2)
        self.assertTrue(all(x["severity"]=="HIGH" for x in receipt["emitted_alerts"]))
        self.assertTrue(all(x["authority_granted"] is False for x in receipt["emitted_alerts"]))
        self.assertEqual(receipt["active_alert_count"],2)

    def test_unchanged_alerts_are_deduplicated_within_cooldown(self):
        state,first=notification_cycle(load_state(),at=AT)
        state,second=notification_cycle(state,at="2026-09-25T23:40:00Z")
        self.assertEqual(len(first["emitted_alerts"]),2)
        self.assertEqual(second["emitted_alerts"],[])
        self.assertEqual(len(second["suppressed_fingerprints"]),2)

    def test_high_alerts_may_repeat_only_after_daily_cooldown(self):
        state,_=notification_cycle(load_state(),at=AT)
        state,receipt=notification_cycle(state,at="2026-09-26T23:41:00Z")
        self.assertEqual(len(receipt["emitted_alerts"]),2)

    def test_notification_kill_switch_blocks_cycle(self):
        with patch.dict(os.environ,{"PORTFOLIO_NOTIFICATION_DISABLED":"true"}):
            state,receipt=notification_cycle(load_state(),at=AT,sources=base_sources())
        self.assertEqual(receipt["status"],"DISABLED")
        self.assertEqual(state["sequence"],0)

    def test_cancelled_work_emits_failure_alert(self):
        src=base_sources()
        src["scheduler_state"]={"work_items":[{
          "state":"CANCELLED","scheduler_work_id":"SWORK-FAIL","fingerprint":"sha256:"+"1"*64,
          "project_ids":["PRJ-000"],"evidence_refs":["scheduler:test-failure"]
        }]}
        _,receipt=notification_cycle(load_state(),at=AT,sources=src)
        alert=next(x for x in receipt["emitted_alerts"] if x["kind"]=="AUTONOMOUS_WORK_FAILURE")
        self.assertEqual(alert["severity"],"HIGH")

    def test_persistent_failure_escalates_without_granting_authority(self):
        src=base_sources()
        src["scheduler_state"]={"work_items":[{
          "state":"CANCELLED","scheduler_work_id":"SWORK-FAIL","fingerprint":"sha256:"+"2"*64,
          "project_ids":["PRJ-000"],"evidence_refs":["scheduler:test-failure"]
        }]}
        state=load_state()
        for at in [AT,"2026-09-25T23:40:00Z","2026-09-26T00:40:00Z"]:
            state,receipt=notification_cycle(state,at=at,sources=src)
        failure=next(x for x in receipt["emitted_alerts"] if x["kind"]=="AUTONOMOUS_WORK_FAILURE")
        self.assertEqual(failure["severity"],"CRITICAL")
        self.assertFalse(failure["authority_granted"])

    def test_cost_hard_stop_is_critical(self):
        with patch("notifications.notification_engine.hard_stop_reason",return_value="CURRENT_DAY_RESERVATION_OVERAGE"):
            _,receipt=notification_cycle(load_state(),at=AT,sources=base_sources())
        alert=next(x for x in receipt["emitted_alerts"] if x["kind"]=="COST_HARD_STOP")
        self.assertEqual(alert["severity"],"CRITICAL")

    def test_unverified_outcome_does_not_alert(self):
        src=base_sources()
        src["experiment_plans"]=[{"experiment_id":"EXP-1","project_ids":["PRJ-001"]}]
        src["experiment_outcomes"]=[{
          "outcome_id":"OUT-1","experiment_id":"EXP-1","result":"FAILED","evidence_state":"OBSERVED",
          "evidence_ids":["EVD-1"],"event_ids":["EVT-1"],"provenance_refs":["test:outcome"]
        }]
        _,receipt=notification_cycle(load_state(),at=AT,sources=src)
        self.assertFalse(any(x["kind"].startswith("VERIFIED_") for x in receipt["emitted_alerts"]))

    def test_verified_negative_outcome_alerts(self):
        src=base_sources()
        src["experiment_plans"]=[{"experiment_id":"EXP-1","project_ids":["PRJ-001"]}]
        src["experiment_outcomes"]=[{
          "outcome_id":"OUT-1","experiment_id":"EXP-1","result":"FAILED","evidence_state":"VERIFIED",
          "evidence_ids":["EVD-1"],"event_ids":["EVT-1"],"provenance_refs":["test:outcome"]
        }]
        _,receipt=notification_cycle(load_state(),at=AT,sources=src)
        alert=next(x for x in receipt["emitted_alerts"] if x["kind"]=="VERIFIED_NEGATIVE_OUTCOME")
        self.assertEqual(alert["project_ids"],["PRJ-001"])

    def test_dashboard_change_requires_existing_baseline(self):
        state,first=notification_cycle(load_state(),at=AT,sources=base_sources("sha256:"+"a"*64))
        self.assertFalse(any(x["kind"]=="PORTFOLIO_STATE_CHANGED" for x in first["emitted_alerts"]))
        state,second=notification_cycle(state,at="2026-09-25T23:40:00Z",sources=base_sources("sha256:"+"b"*64))
        self.assertTrue(any(x["kind"]=="PORTFOLIO_STATE_CHANGED" for x in second["emitted_alerts"]))

    def test_alert_records_are_sanitized_closed_records(self):
        state,_=notification_cycle(load_state(),at=AT)
        for record in state["alert_records"]:
            validate_alert_record(record)
            self.assertNotIn("payload",record)
            self.assertNotIn("prompt",record)
            self.assertNotIn("customer",record)

    def test_policy_has_no_external_message_channel(self):
        channels=policy()["delivery_channels"]
        self.assertEqual(channels,["GITHUB_ACTIONS_ANNOTATION","GITHUB_STEP_SUMMARY"])

if __name__=="__main__":unittest.main()
