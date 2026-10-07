import unittest
from unittest.mock import patch

from acceptance import step23_preflight as preflight


class FakeAPI:
    def __init__(self,repo,token):
        self.requests=0
    def main_sha(self):
        return "a"*40


class Step23PreflightTests(unittest.TestCase):
    def test_required_workflow_inventory_is_exactly_eight(self):
        self.assertEqual({name for name,_ in preflight.WORKFLOWS},{
            "portfolio-state-reducer","runtime-hourly-sync","portfolio-autonomous-scheduler",
            "hunter-autonomous-cycle","agent-heartbeat-sweep","portfolio-cost-watchdog",
            "portfolio-notification-cycle","command-center-pages",
        })

    def test_preflight_has_zero_step23_acceptance_credit_and_drains_after_every_producer(self):
        calls=[]
        def fake_dispatch(api,name,file,sha,timeout_seconds=1200):
            calls.append((name,file,sha))
            return {"workflow":name,"workflow_file":file,"run_id":len(calls),
                    "event":"workflow_dispatch","head_sha":sha,"conclusion":"success"}
        with patch.object(preflight,"API",FakeAPI), \
             patch.object(preflight,"dispatch_and_wait",side_effect=fake_dispatch), \
             patch.object(preflight,"wait_pending_zero",return_value=0):
            result=preflight.run_preflight("owner/repo","token","a"*40)
        self.assertEqual(result["status"],"PASS")
        self.assertFalse(result["acceptance_credit"])
        self.assertEqual(result["run_event_required"],"workflow_dispatch")
        self.assertEqual(len(result["required_workflow_runs"]),8)
        self.assertEqual(len(result["reducer_catchup_runs"]),7)
        self.assertEqual(result["pending_events_final"],0)
        self.assertTrue(all(row["event"]=="workflow_dispatch" for row in result["required_workflow_runs"]))


if __name__=="__main__":
    unittest.main()
