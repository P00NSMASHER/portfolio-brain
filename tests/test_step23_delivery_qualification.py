import unittest
from datetime import datetime, timedelta, timezone
from acceptance.step23_delivery_qualification import REQUIRED, derive_qualification, derive_fixed_arm

SHA="a"*40
BASE=datetime(2026,10,6,0,0,tzinfo=timezone.utc)
END=datetime(2026,10,6,5,0,tzinfo=timezone.utc)

def row(name,i,minute=1,**changes):
    created=BASE+timedelta(minutes=minute)
    value={
      "id":i,"name":name,"path":REQUIRED[name],"head_branch":"main","head_sha":SHA,
      "event":"schedule","status":"completed","conclusion":"success",
      "created_at":created.isoformat(),"updated_at":(created+timedelta(minutes=1)).isoformat(),
    }
    value.update(changes)
    return value

class QualificationTests(unittest.TestCase):
    def all_rows(self,base_minute=1):
        return [row(name,i+1,base_minute+i) for i,name in enumerate(REQUIRED)]

    def test_missing_workflow_does_not_arm(self):
        result=derive_qualification(self.all_rows()[:-1],SHA,BASE,END)
        self.assertFalse(result["qualified"])
        self.assertEqual(result["status"],"PREQUALIFYING")

    def test_all_native_successes_arm_deterministically(self):
        rows=self.all_rows()
        a=derive_qualification(rows,SHA,BASE,END)
        b=derive_qualification(rows+[row(next(iter(REQUIRED)),99,minute=50)],SHA,BASE,END)
        self.assertTrue(a["qualified"])
        self.assertEqual(a["soak_start"],b["soak_start"])
        self.assertTrue(a["soak_start"].endswith(":00Z"))
        self.assertEqual(datetime.fromisoformat(a["soak_start"].replace("Z","+00:00")).minute%15,0)

    def test_wrong_event_sha_branch_path_or_failure_never_qualifies(self):
        base=self.all_rows()
        name=list(REQUIRED)[0]
        for change in (
            {"event":"workflow_dispatch"},{"head_sha":"b"*40},{"head_branch":"feature"},
            {"path":"wrong"},{"status":"in_progress","conclusion":None},{"conclusion":"failure"},
        ):
            rows=[dict(r) for r in base]
            rows[0].update(change)
            with self.subTest(change=change):
                self.assertFalse(derive_qualification(rows,SHA,BASE,END)["qualified"])

    def test_prebaseline_success_is_ignored(self):
        rows=self.all_rows()
        rows[0]["created_at"]=(BASE-timedelta(minutes=1)).isoformat()
        rows[0]["updated_at"]=BASE.isoformat()
        self.assertFalse(derive_qualification(rows,SHA,BASE,END)["qualified"])

    def test_start_delay_and_quarter_round_leave_registration_margin(self):
        result=derive_qualification(self.all_rows(base_minute=7),SHA,BASE,END,start_delay_minutes=30)
        start=datetime.fromisoformat(result["soak_start"].replace("Z","+00:00"))
        latest=max(datetime.fromisoformat(r["updated_at"]) for r in self.all_rows(base_minute=7))
        self.assertGreaterEqual(start-latest,timedelta(minutes=30))
        self.assertEqual(start.minute%15,0)

    def test_late_qualification_refuses_to_start_in_incomplete_horizon(self):
        rows=self.all_rows(base_minute=240)
        result=derive_qualification(rows,SHA,BASE,END,start_delay_minutes=30)
        self.assertFalse(result["qualified"])
        self.assertEqual(result["status"],"QUALIFICATION_TOO_LATE")

    def test_owner_fixed_arm_preserves_strict_one_hour_window(self):
        start=datetime(2026,10,6,4,0,tzinfo=timezone.utc)
        result=derive_fixed_arm(SHA,BASE,start,END)
        self.assertTrue(result["qualified"])
        self.assertEqual(result["status"],"QUALIFIED_FIXED")
        self.assertEqual(result["soak_start"],"2026-10-06T04:00:00Z")
        self.assertEqual(result["soak_deadline"],"2026-10-06T05:00:00Z")
        self.assertEqual(result["selected"],{})

    def test_owner_fixed_arm_rejects_early_or_nonquarter_start(self):
        with self.assertRaisesRegex(RuntimeError,"BEFORE_REGISTRATION"):
            derive_fixed_arm(SHA,BASE+timedelta(minutes=10),BASE+timedelta(minutes=5),END)
        with self.assertRaisesRegex(RuntimeError,"NOT_QUARTER_HOUR"):
            derive_fixed_arm(SHA,BASE,BASE+timedelta(minutes=7),END)

if __name__=="__main__": unittest.main()
