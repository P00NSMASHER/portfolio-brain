import unittest
from datetime import datetime,timezone
from operations.schedule_clock import ClockError,bind_dispatched_run,daemon_identity,due,execute

MAIN="a"*40
SOURCE={"id":1,"name":"verified-feedback-bootstrap","path":".github/workflows/verified-feedback-bootstrap.yml",
        "event":"schedule","head_branch":"main","head_sha":MAIN,"status":"completed",
        "created_at":"2026-10-06T16:17:00Z"}
POLICY={
 "clock_id":"test-clock","authority_class":"NONE","dispatch_authority_effect":"NONE",
 "source_workflows":[{"name":"verified-feedback-bootstrap","path":".github/workflows/verified-feedback-bootstrap.yml","events":["schedule"]}],
 "target_workflows":[
   {"name":"hourly","file":"hourly.yml","cadence":"HOURLY"},
   {"name":"two","file":"two.yml","cadence":"EVERY_2_HOURS"},
   {"name":"six","file":"six.yml","cadence":"EVERY_6_HOURS"},
   {"name":"daily","file":"daily.yml","cadence":"DAILY_04_UTC"},
 ],
 "dedupe_window_minutes":55,"max_dispatches_per_tick":8,"max_api_requests":60,
}
class API:
 def __init__(self,recent=None):
  self.recent=recent or {};self.calls=[];self.requests=0
 def call(self,path,method="GET",payload=None):
  self.calls.append((path,method,payload));self.requests+=1
  if method=="POST": return {}
  name=path.split("/actions/workflows/",1)[1].split("/runs?",1)[0]
  event=path.split("event=",1)[1].split("&",1)[0]
  return {"workflow_runs":self.recent.get((name,event),[])}

class ScheduleClockTests(unittest.TestCase):
 def test_self_schedule_source_is_trusted(self):
  own={**SOURCE,"name":"portfolio-schedule-delivery","path":".github/workflows/portfolio-schedule-delivery.yml"}
  p={**POLICY,"source_workflows":[
      {"name":"portfolio-schedule-delivery","path":".github/workflows/portfolio-schedule-delivery.yml","events":["schedule"]},
      *POLICY["source_workflows"],
  ]}
  result=execute(API(),p,own,MAIN,current_run_id=1)
  self.assertEqual(result["source_workflow"],"portfolio-schedule-delivery")
  self.assertEqual(result["source_event"],"schedule")
 def test_self_schedule_accepts_authenticated_inflight_current_run(self):
  own={**SOURCE,"name":"portfolio-schedule-delivery","path":".github/workflows/portfolio-schedule-delivery.yml",
       "status":"in_progress"}
  p={**POLICY,"source_workflows":[
      {"name":"portfolio-schedule-delivery","path":".github/workflows/portfolio-schedule-delivery.yml","events":["schedule"]},
      *POLICY["source_workflows"],
  ]}
  result=execute(API(),p,own,MAIN,current_run_id=1)
  self.assertEqual(result["source_workflow"],"portfolio-schedule-delivery")
 def test_stale_main_source_is_rejected(self):
  with self.assertRaisesRegex(ClockError,"exact current main"):
   execute(API(),POLICY,{**SOURCE,"head_sha":"b"*40},MAIN)
 def test_daemon_identity_requires_exact_main_active_parent_and_current_boundary(self):
  class DaemonAPI:
   def call(self,path,method="GET",payload=None):
    return {"id":88,"name":"portfolio-schedule-clock-daemon",
            "path":".github/workflows/portfolio-schedule-clock-daemon.yml",
            "event":"workflow_dispatch","head_branch":"main","head_sha":MAIN,
            "run_attempt":2,"status":"in_progress"}
  import time
  tick=(int(time.time())//600)*600
  row=daemon_identity(DaemonAPI(),88,2,MAIN,tick)
  self.assertEqual(row["id"],88)
  with self.assertRaisesRegex(ClockError,"exact current main"):
   daemon_identity(DaemonAPI(),88,2,"b"*40,tick)
  with self.assertRaisesRegex(ClockError,"recent aligned"):
   daemon_identity(DaemonAPI(),88,2,MAIN,tick-1800)
 def test_cadence(self):
  at=datetime(2026,10,6,16,17,tzinfo=timezone.utc)
  self.assertTrue(due("HOURLY",at));self.assertTrue(due("EVERY_2_HOURS",at))
  self.assertFalse(due("EVERY_6_HOURS",at));self.assertFalse(due("DAILY_04_UTC",at))
 def test_trusted_schedule_source_dispatches_due_only(self):
  api=API();result=execute(api,POLICY,SOURCE,MAIN)
  requested=[x["workflow"] for x in result["actions"] if x["action"]=="DISPATCH_REQUESTED"]
  self.assertEqual(requested,[])\n  self.assertEqual([x["workflow"] for x in result["actions"] if x["action"]=="DISPATCH_BOUND"],["hourly","two"])
  self.assertFalse(result["authority_granted"])
 def test_bound_dispatch_requires_exact_bot_current_main_run(self):
  target={"name":"hourly","file":"hourly.yml","cadence":"HOURLY"}
  api=API();api.dispatched.add("hourly.yml")
  row=bind_dispatched_run(api,target,MAIN,set(),datetime(2026,10,6,16,17,tzinfo=timezone.utc))
  self.assertEqual(row["head_sha"],MAIN)
  self.assertEqual(row["actor"]["login"],"github-actions[bot]")
 def test_recent_schedule_or_dispatch_dedupes(self):
  recent={("hourly.yml","schedule"):[{"id":9,"head_branch":"main","head_sha":MAIN,"created_at":"2026-10-06T16:10:00Z"}]}
  api=API(recent);result=execute(api,POLICY,SOURCE,MAIN)
  row=next(x for x in result["actions"] if x["workflow"]=="hourly")
  self.assertEqual(row["action"],"ALREADY_RAN_IN_SLOT")
  self.assertEqual(row["evidence_run_ids"],[9])
 def test_wrong_source_event_fails_closed(self):
  with self.assertRaisesRegex(ClockError,"native schedule"):
   execute(API(),POLICY,{**SOURCE,"event":"workflow_dispatch"},MAIN)

if __name__=="__main__":unittest.main()
