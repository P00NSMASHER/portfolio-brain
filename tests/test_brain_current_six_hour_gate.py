"""Six-hour source window must not inherit the historical two-hour PASS shape."""
import copy
from datetime import datetime, timezone, timedelta
import unittest

from soak_v3.audit import REQUIRED_STEPS, EvidenceError
from soak_v3.current_six_hour_gate import (
    SIX_HOURS, NINETY_MINUTES, inspect_current_window,
)

SHA = "a"*40
FIRST = "b"*40
START = datetime(2026, 10, 15, 18, 0, tzinfo=timezone.utc)


def iso(t):
    return t.isoformat().replace("+00:00", "Z")


def run(i):
    finished = START+timedelta(hours=i)
    after = format(i+1, "040x")
    before = FIRST if i == 0 else format(i, "040x")
    return {
        "run_id": i+1000, "attempt": 1, "source_sha": SHA,
        "event": "workflow_dispatch", "started_at":iso(finished-timedelta(minutes=1)),
        "completed_at":iso(finished), "status":"completed",
        "conclusion":"success",
        "steps":{step:"success" for step in REQUIRED_STEPS},
        "artifact":{"status":"PASS","state_sequence":100+i,"canonical_hash":format(i+1,"064x")},
        "state":{"status":"PASS","parent":before,"commit":after,
                 "sequence":100+i,"canonical_hash":format(i+1,"064x")},
        "external_clock":{
            "kind":"cloudflare_cron_v1","source_sha":SHA,
            "provider_cron_verified":True,"signed_origin_verified":True,
            "core_receipt_verified":True,"state_verified":True,
        },
    }


def window(records, *, now=None, census=True):
    return inspect_current_window(
        records, source_sha=SHA, current_main=SHA,
        first_state_parent=FIRST,
        started_at=iso(START-timedelta(minutes=1)),
        deadline_at=iso(START+timedelta(hours=8)),
        now=iso(now or START+timedelta(hours=6,minutes=1)),
        original_run_inventory_complete=census,
    )


class SixHourNotProductionAcceptanceTests(unittest.TestCase):
    def test_exact_six_hours_only_qualifies_for_postvalidation_not_acceptance(self):
        result=window([run(i) for i in range(7)])
        self.assertEqual(result["status"],"PRE_POSTVALIDATION")
        self.assertEqual(result["span_seconds"],21600)
        self.assertEqual(result["evaluated_minimum_span_seconds"],SIX_HOURS)
        self.assertEqual(result["maximum_automatic_completion_gap_seconds"],NINETY_MINUTES)
        self.assertFalse(result["six_hour_soak_accepted"])
        self.assertFalse(result["independent_provider_origin_verified"])
        self.assertFalse(result["terminal_binary_replay_verified"])

    def test_historical_two_hour_window_cannot_qualify_current_source(self):
        result=window([run(i) for i in range(3)],
                      now=START+timedelta(hours=2,minutes=1))
        self.assertEqual(result["status"],"WAITING")
        self.assertEqual(result["reason"],"SOAK_DURATION_INCOMPLETE")
        self.assertFalse(result["six_hour_soak_accepted"])

    def test_missing_one_hourly_cycle_breaks_ninety_minute_gap(self):
        entries=[run(i) for i in range(7) if i!=3]
        result=window(entries)
        self.assertEqual(result["status"],"FAIL")
        self.assertEqual(result["reason"],"AUTOMATIC_DELIVERY_GAP_EXCEEDED")

    def test_unverified_cloudflare_origin_cannot_fill_scheduled_gap(self):
        entries=[run(i) for i in range(7)]
        entries[3]["external_clock"]["signed_origin_verified"]=False
        result=window(entries)
        self.assertEqual(result["reason"],"AUTOMATIC_DELIVERY_GAP_EXCEEDED")
        self.assertFalse(result["six_hour_soak_accepted"])

    def test_one_failed_core_poisoned_window(self):
        entries=[run(i) for i in range(7)]
        entries[4]["conclusion"]="failure"
        result=window(entries)
        self.assertEqual(result["reason"],"CORE_EXECUTION_FAILED")

    def test_missing_mandatory_step_remains_fail(self):
        entries=[run(i) for i in range(7)]
        entries[1]["steps"].pop("Evidence-bound deterministic experiment")
        result=window(entries)
        self.assertEqual(result["reason"],"MANDATORY_STEP_FAILED_OR_MISSING")

    def test_incomplete_inventory_is_not_accepted(self):
        result=window([run(i) for i in range(7)],census=False)
        self.assertEqual(result["reason"],"ORIGINAL_PROVIDER_INVENTORY_NOT_COMPLETE")
        self.assertFalse(result["six_hour_soak_accepted"])

    def test_unknown_retry_history_hard_blocked(self):
        entries=[run(i) for i in range(7)]
        entries[4]["attempt"]=2
        result=window(entries)
        self.assertEqual(result["reason"],"UNVERIFIED_RUN_ATTEMPT_CENSUS")
        self.assertFalse(result["six_hour_soak_accepted"])

    def test_wrong_source_fails_unchanged_main_guard(self):
        result=inspect_current_window(
            [run(i) for i in range(7)],
            source_sha=SHA,current_main="f"*40,first_state_parent=FIRST,
            started_at=iso(START-timedelta(minutes=1)),
            deadline_at=iso(START+timedelta(hours=8)),
            now=iso(START+timedelta(hours=6,minutes=1)),
            original_run_inventory_complete=True,
        )
        self.assertEqual(result["reason"],"MAIN_DRIFT")
        self.assertFalse(result["six_hour_soak_accepted"])

    def test_window_never_outputs_terminal_pass(self):
        for records in ([],[run(0)],[run(i) for i in range(7)]):
            result=window(records)
            self.assertNotEqual(result["status"],"PASS")
            self.assertFalse(result["six_hour_soak_accepted"])


if __name__=="__main__":
    unittest.main()
