import hashlib
import io
import json
import unittest
import zipfile
from datetime import datetime, timedelta, timezone

from acceptance.step23_delivery_qualification import (
    CANARY_NAME,
    CANARY_PATH,
    derive_fixed_arm,
    derive_qualification,
    validate_native_clock_canary,
)

SHA="a"*40
BASE=datetime(2026,10,6,0,0,tzinfo=timezone.utc)
END=datetime(2026,10,7,0,0,tzinfo=timezone.utc)


def row(i=1,minute=1,**changes):
    created=BASE+timedelta(minutes=minute)
    value={
        "id":i,"name":CANARY_NAME,"path":CANARY_PATH,
        "head_branch":"main","head_sha":SHA,"event":"schedule",
        "status":"completed","conclusion":"success","run_attempt":1,
        "created_at":created.isoformat().replace("+00:00","Z"),
        "updated_at":(created+timedelta(minutes=1)).isoformat().replace("+00:00","Z"),
    }
    value.update(changes)
    return value


def clock_zip(receipt):
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,"w",zipfile.ZIP_DEFLATED) as z:
        z.writestr("schedule_clock_receipt.json",json.dumps(receipt))
    return buf.getvalue()


class FakeAPI:
    def __init__(self,run,receipt):
        self.run=run
        self.raw=clock_zip(receipt)
        self.digest="sha256:"+hashlib.sha256(self.raw).hexdigest()
    def get(self,path):
        return {
            "total_count":1,
            "artifacts":[{
                "id":77,
                "name":f"portfolio-schedule-clock-{self.run['id']}-{self.run.get('run_attempt',1)}",
                "expired":False,
                "digest":self.digest,
                "workflow_run":{"id":self.run["id"],"head_sha":SHA,"head_branch":"main"},
            }],
        }
    def bytes(self,path):
        return self.raw


class QualificationTests(unittest.TestCase):
    def test_missing_native_clock_canary_does_not_arm(self):
        result=derive_qualification([],SHA,BASE,END,soak_duration_seconds=3600)
        self.assertFalse(result["qualified"])
        self.assertEqual(result["status"],"PREQUALIFYING")
        self.assertEqual(result["missing_workflows"],[CANARY_NAME])

    def test_one_native_clock_canary_arms_without_eight_independent_crons(self):
        result=derive_qualification([row()],SHA,BASE,END,soak_duration_seconds=3600)
        self.assertTrue(result["qualified"])
        self.assertEqual(result["selected"][CANARY_NAME]["run_id"],1)
        self.assertEqual(set(result["selected"]),{CANARY_NAME})

    def test_unrelated_target_schedule_does_not_substitute_for_clock_canary(self):
        other=row(name="runtime-hourly-sync",path=".github/workflows/runtime-hourly-sync.yml")
        self.assertFalse(derive_qualification([other],SHA,BASE,END,soak_duration_seconds=3600)["qualified"])

    def test_wrong_event_sha_branch_path_or_failure_never_qualifies(self):
        for change in (
            {"event":"workflow_dispatch"},{"head_sha":"b"*40},{"head_branch":"feature"},
            {"path":"wrong"},{"status":"in_progress","conclusion":None},{"conclusion":"failure"},
        ):
            with self.subTest(change=change):
                self.assertFalse(
                    derive_qualification([row(**change)],SHA,BASE,END,soak_duration_seconds=3600)["qualified"]
                )

    def test_prebaseline_success_is_ignored(self):
        before=row()
        before["created_at"]=(BASE-timedelta(minutes=1)).isoformat().replace("+00:00","Z")
        before["updated_at"]=BASE.isoformat().replace("+00:00","Z")
        self.assertFalse(derive_qualification([before],SHA,BASE,END,soak_duration_seconds=3600)["qualified"])

    def test_start_delay_and_quarter_round_leave_margin(self):
        result=derive_qualification([row(minute=7)],SHA,BASE,END,start_delay_minutes=30,soak_duration_seconds=3600)
        start=datetime.fromisoformat(result["soak_start"].replace("Z","+00:00"))
        completed=datetime.fromisoformat(row(minute=7)["updated_at"].replace("Z","+00:00"))
        self.assertGreaterEqual(start-completed,timedelta(minutes=30))
        self.assertEqual(start.minute%15,0)

    def test_late_canary_refuses_incomplete_soak_horizon(self):
        result=derive_qualification(
            [row(minute=22*60)],SHA,BASE,END,start_delay_minutes=30,soak_duration_seconds=2*3600
        )
        self.assertFalse(result["qualified"])
        self.assertEqual(result["status"],"QUALIFICATION_TOO_LATE")

    def test_native_clock_artifact_is_cryptographically_bound(self):
        run=row(i=44)
        receipt={
            "status":"PASS","authority_granted":False,"dispatch_authority_effect":"NONE",
            "main_sha":SHA,"source_head_sha":SHA,"source_run_id":44,
            "source_workflow":CANARY_NAME,"source_event":"schedule",
            "reducer_wake":{"action":"REDUCER_CURRENT"},
        }
        evidence=validate_native_clock_canary(FakeAPI(run,receipt),run,SHA)
        self.assertEqual(evidence["run_id"],44)
        self.assertEqual(evidence["clock_status"],"PASS")
        self.assertEqual(evidence["dispatch_authority_effect"],"NONE")

    def test_daemon_or_fabricated_source_cannot_satisfy_native_canary(self):
        run=row(i=45)
        receipt={
            "status":"PASS","authority_granted":False,"dispatch_authority_effect":"NONE",
            "main_sha":SHA,"source_head_sha":SHA,"source_run_id":45,
            "source_workflow":"portfolio-schedule-clock-daemon","source_event":"schedule",
            "reducer_wake":{"action":"REDUCER_CURRENT"},
        }
        with self.assertRaisesRegex(RuntimeError,"SOURCE_NOT_NATIVE_SCHEDULE"):
            validate_native_clock_canary(FakeAPI(run,receipt),run,SHA)

    def test_owner_fixed_arm_helper_remains_strict(self):
        start=datetime(2026,10,6,7,30,tzinfo=timezone.utc)
        result=derive_fixed_arm(SHA,BASE,start,END)
        self.assertTrue(result["qualified"])
        self.assertEqual(result["status"],"QUALIFIED_FIXED")
        with self.assertRaisesRegex(RuntimeError,"NOT_QUARTER_HOUR"):
            derive_fixed_arm(SHA,BASE,BASE+timedelta(minutes=7),END)


if __name__=="__main__":
    unittest.main()
