"""Test provider-backed watchdog decisions without claiming a live soak."""
import unittest
from datetime import datetime, timedelta, timezone
from brain.watchdog import decide, verify_parent, ClockError

NOW=datetime(2026,10,8,4,tzinfo=timezone.utc)
SHA="a"*40

def stamp(t):
    return t.isoformat().replace("+00:00","Z")

def run(minutes, *, run_id=1, sha=SHA, status="completed", conclusion="success"):
    when=NOW-timedelta(minutes=minutes)
    return {"id":run_id,"path":".github/workflows/brain-cycle.yml",
            "event":"schedule","head_sha":sha,"head_branch":"main",
            "status":status,"conclusion":conclusion,
            "created_at":stamp(when-timedelta(seconds=5)),
            "updated_at":stamp(when)}

def inventory(*rows):
    return {"total_count":len(rows),"workflow_runs":list(rows)}

def parent(minutes=1):
    return {"id":500,"event":"schedule","name":"brain-clock-v2",
            "path":".github/workflows/brain-clock.yml",
            "head_branch":"main","head_sha":SHA,"run_attempt":1,
            "status":"in_progress","conclusion":None,
            "created_at":stamp(NOW-timedelta(minutes=minutes))}

class WatchdogTests(unittest.TestCase):
    def test_recent_success_prevents_duplicate_dispatch(self):
        self.assertEqual(decide(inventory(run(10)),SHA,now=NOW)["status"],"FRESH")
    def test_overdue_success_requests_real_core(self):
        result=decide(inventory(run(45)),SHA,now=NOW)
        self.assertTrue(result["dispatch"])
        self.assertFalse(result["soak_pass"])
    def test_recent_in_progress_is_not_duplicated(self):
        result=decide(inventory(run(2,status="in_progress",conclusion=None),run(50,run_id=2)),SHA,now=NOW)
        self.assertEqual(result["status"],"ACTIVE")
        self.assertFalse(result["dispatch"])
    def test_stale_queued_record_blocks_fail_closed(self):
        result=decide(inventory(run(25,status="queued",conclusion=None)),SHA,now=NOW)
        self.assertEqual(result["status"],"BLOCKED_STALE_ACTIVE")
    def test_other_sha_not_used_as_current_health(self):
        self.assertTrue(decide(inventory(run(1,sha="b"*40)),SHA,now=NOW)["dispatch"])
    def test_failed_cycle_not_laundered_into_success(self):
        result=decide(inventory(run(1,conclusion="failure")),SHA,now=NOW)
        self.assertEqual(result["status"],"DUE")
        self.assertEqual(result["recent_failed_run_ids"],[1])
    def test_empty_inventory_due(self):
        self.assertTrue(decide(inventory(),SHA,now=NOW)["dispatch"])
    def test_partial_or_duplicate_or_wrong_workflow_fails(self):
        truncated={"total_count":2,"workflow_runs":[run(1)]}
        repeated=inventory(run(2),run(4))
        wrong=run(2)
        wrong["path"]=".github/workflows/other.yml"
        for doc in (truncated,repeated,inventory(wrong)):
            with self.subTest(doc=doc),self.assertRaises(ClockError):
                decide(doc,SHA,now=NOW)
    def test_actual_scheduled_parent_never_implies_accepted_soak(self):
        result=verify_parent(parent(),SHA,500,"github-actions[bot]",now=NOW)
        self.assertEqual(result["kind"],"github_schedule")
        self.assertFalse(result["soak_pass"])
    def test_manual_actor_or_wrong_event_rejected(self):
        with self.assertRaises(ClockError):
            verify_parent(parent(),SHA,500,"P00NSMASHER",now=NOW)
        x=parent()
        x["event"]="workflow_dispatch"
        with self.assertRaises(ClockError):
            verify_parent(x,SHA,500,"github-actions[bot]",now=NOW)
    def test_stale_drift_and_retried_parent_rejected(self):
        for field,value in (("head_sha","b"*40),("run_attempt",2),("name","other"),("status","queued")):
            x=parent()
            x[field]=value
            with self.subTest(field=field),self.assertRaises(ClockError):
                verify_parent(x,SHA,500,"github-actions[bot]",now=NOW)
        with self.assertRaises(ClockError):
            verify_parent(parent(minutes=22),SHA,500,"github-actions[bot]",now=NOW)

if __name__=="__main__":
    unittest.main()
