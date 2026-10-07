import unittest
from datetime import datetime,timezone
from operations.schedule_clock import ClockError,daemon_identity,due,execute

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
 def __init__(self,recent=None,reducer_runs=None,producer_runs=None):
  self.recent=recent or {}
  self.reducer_runs=reducer_runs if reducer_runs is not None else [{
    "id":700,"head_branch":"main","head_sha":MAIN,"status":"completed","conclusion":"success",
    "created_at":"2026-10-06T16:16:00Z","updated_at":"2026-10-06T16:16:30Z",
  }]
  self.producer_runs=producer_runs or {}
  self.calls=[];self.requests=0
 def call(self,path,method="GET",payload=None):
  self.calls.append((path,method,payload));self.requests+=1
  if method=="POST": return {}
  name=path.split("/actions/workflows/",1)[1].split("/runs?",1)[0]
  if name=="portfolio-state-reducer.yml" and "event=" not in path:
   return {"workflow_runs":self.reducer_runs}
  if "event=" in path:
   event=path.split("event=",1)[1].split("&",1)[0]
   return {"workflow_runs":self.recent.get((name,event),[])}
  return {"workflow_runs":self.producer_runs.get(name,[])}

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
  self.assertEqual(requested,["hourly","two"])
  self.assertFalse(result["authority_granted"])
 def test_recent_schedule_or_dispatch_dedupes(self):
  recent={("hourly.yml","schedule"):[{"id":9,"head_branch":"main","head_sha":MAIN,"created_at":"2026-10-06T16:10:00Z"}]}
  api=API(recent);result=execute(api,POLICY,SOURCE,MAIN)
  row=next(x for x in result["actions"] if x["workflow"]=="hourly")
  self.assertEqual(row["action"],"ALREADY_RAN_IN_SLOT")
  self.assertEqual(row["evidence_run_ids"],[9])
 def test_clock_wakes_reducer_when_producer_is_newer(self):
  reducers=[{
    "id":700,"head_branch":"main","head_sha":MAIN,"status":"completed","conclusion":"success",
    "created_at":"2026-10-06T16:00:00Z","updated_at":"2026-10-06T16:00:30Z",
  }]
  producers={"runtime-hourly-sync.yml":[{
    "id":44,"head_branch":"main","head_sha":MAIN,"status":"completed","conclusion":"success",
    "updated_at":"2026-10-06T16:05:00Z",
  }]}
  api=API(reducer_runs=reducers,producer_runs=producers)
  result=execute(api,POLICY,SOURCE,MAIN)
  self.assertEqual(result["reducer_wake"]["action"],"REDUCER_WAKE_REQUESTED")
  self.assertEqual(result["reducer_wake"]["reason"],"PRODUCER_NEWER_THAN_LATEST_REDUCER")
  self.assertEqual(result["reducer_wake"]["producer_run_ids"],[44])
  self.assertIn(
    ("/actions/workflows/portfolio-state-reducer.yml/dispatches","POST",{"ref":"main"}),
    api.calls,
  )
 def test_active_reducer_prevents_duplicate_wake(self):
  reducers=[{
    "id":701,"head_branch":"main","head_sha":MAIN,"status":"in_progress","conclusion":None,
    "created_at":"2026-10-06T16:16:00Z","updated_at":"2026-10-06T16:16:30Z",
  }]
  api=API(reducer_runs=reducers)
  result=execute(api,POLICY,SOURCE,MAIN)
  self.assertEqual(result["reducer_wake"]["action"],"REDUCER_ACTIVE")
  self.assertEqual(result["reducer_wake"]["evidence_run_ids"],[701])
  self.assertNotIn(
    ("/actions/workflows/portfolio-state-reducer.yml/dispatches","POST",{"ref":"main"}),
    api.calls,
  )
 def test_current_reducer_needs_no_wake(self):
  result=execute(API(),POLICY,SOURCE,MAIN)
  self.assertEqual(result["reducer_wake"]["action"],"REDUCER_CURRENT")
 def test_producer_completed_before_reducer_completion_is_covered(self):
  reducers=[{
    "id":700,"head_branch":"main","head_sha":MAIN,"status":"completed","conclusion":"success",
    "created_at":"2026-10-06T16:00:00Z","updated_at":"2026-10-06T16:10:00Z",
  }]
  producers={"runtime-hourly-sync.yml":[{
    "id":44,"head_branch":"main","head_sha":MAIN,"status":"completed","conclusion":"success",
    "updated_at":"2026-10-06T16:05:00Z",
  }]}
  result=execute(API(reducer_runs=reducers,producer_runs=producers),POLICY,SOURCE,MAIN)
  self.assertEqual(result["reducer_wake"]["action"],"REDUCER_CURRENT")
 def test_daily_reducer_target_dedupes_explicit_liveness_wake(self):
  reducers=[{
    "id":700,"head_branch":"main","head_sha":MAIN,"status":"completed","conclusion":"success",
    "created_at":"2026-10-06T03:50:00Z","updated_at":"2026-10-06T03:51:00Z",
  }]
  producers={"runtime-hourly-sync.yml":[{
    "id":44,"head_branch":"main","head_sha":MAIN,"status":"completed","conclusion":"success",
    "updated_at":"2026-10-06T04:05:00Z",
  }]}
  source={**SOURCE,"created_at":"2026-10-06T04:17:00Z"}
  targets=[
    {**target,"name":"portfolio-state-reducer","file":"portfolio-state-reducer.yml"}
    if target["name"]=="daily" else target
    for target in POLICY["target_workflows"]
  ]
  p={**POLICY,"target_workflows":targets}
  api=API(reducer_runs=reducers,producer_runs=producers)
  result=execute(api,p,source,MAIN)
  daily=next(x for x in result["actions"] if x["workflow"]=="portfolio-state-reducer")
  self.assertEqual(daily["action"],"REDUCER_ALREADY_WOKEN_OR_ACTIVE")
  reducer_posts=[call for call in api.calls if call[0]=="/actions/workflows/portfolio-state-reducer.yml/dispatches" and call[1]=="POST"]
  self.assertEqual(len(reducer_posts),1)
 def test_reducer_wake_counts_against_dispatch_budget(self):
  reducers=[{
    "id":700,"head_branch":"main","head_sha":MAIN,"status":"completed","conclusion":"success",
    "created_at":"2026-10-06T16:00:00Z","updated_at":"2026-10-06T16:00:30Z",
  }]
  producers={"runtime-hourly-sync.yml":[{
    "id":44,"head_branch":"main","head_sha":MAIN,"status":"completed","conclusion":"success",
    "updated_at":"2026-10-06T16:05:00Z",
  }]}
  p={**POLICY,"max_dispatches_per_tick":1}
  api=API(reducer_runs=reducers,producer_runs=producers)
  result=execute(api,p,SOURCE,MAIN)
  self.assertEqual(result["reducer_wake"]["action"],"REDUCER_WAKE_REQUESTED")
  self.assertEqual(result["actions"][0]["action"],"DISPATCH_BUDGET_EXHAUSTED")
  posts=[call for call in api.calls if call[1]=="POST"]
  self.assertEqual(posts,[("/actions/workflows/portfolio-state-reducer.yml/dispatches","POST",{"ref":"main"})])
 def test_wrong_source_event_fails_closed(self):
  with self.assertRaisesRegex(ClockError,"native schedule"):
   execute(API(),POLICY,{**SOURCE,"event":"workflow_dispatch"},MAIN)

if __name__=="__main__":unittest.main()
