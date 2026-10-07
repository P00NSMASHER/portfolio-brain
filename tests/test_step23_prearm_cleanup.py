import unittest
from unittest.mock import patch

from acceptance.step23_prearm_cleanup import (
    StuckAfterForceCancel, _cancel_and_wait, _delete_stuck_stale,
    leaked_title, purge, stale_non_schedule_blocker,
)


class PrearmCleanupTests(unittest.TestCase):
    def test_only_prearm_titles_with_secret_markers_are_selected(self):
        self.assertTrue(leaked_title("prearm-initial-drain-1-ghs_example"))
        self.assertTrue(leaked_title("prearm-run-1-github_pat_example"))
        self.assertFalse(leaked_title("prearm-run-123-initial-drain-1"))
        self.assertFalse(leaked_title("ordinary-ghs_example"))
        self.assertFalse(leaked_title(None))

    def test_normal_cancel_stops_without_force_cancel(self):
        class API:
            def __init__(self):
                self.posts=[]
            def post(self,path):
                self.posts.append(path)
                return 202
            def get(self,path):
                return {"status":"completed"}

        api=API()
        with patch("acceptance.step23_prearm_cleanup.time.sleep",return_value=None):
            mode=_cancel_and_wait(api,17,"stale pre-arm blocker")
        self.assertEqual(mode,"NORMAL_CANCEL")
        self.assertEqual(api.posts,["/actions/runs/17/cancel"])

    def test_stuck_normal_cancel_escalates_to_force_cancel(self):
        class API:
            def __init__(self):
                self.posts=[]
                self.reads=0
            def post(self,path):
                self.posts.append(path)
                return 202
            def get(self,path):
                self.reads+=1
                return {"status":"queued" if self.reads<=10 else "completed"}

        api=API()
        with patch("acceptance.step23_prearm_cleanup.time.sleep",return_value=None):
            mode=_cancel_and_wait(api,18,"stale pre-arm blocker")
        self.assertEqual(mode,"FORCE_CANCEL")
        self.assertEqual(
            api.posts,
            ["/actions/runs/18/cancel","/actions/runs/18/force-cancel"],
        )

    def test_force_cancel_must_reach_terminal_state(self):
        class API:
            def __init__(self):
                self.posts=[]
            def post(self,path):
                self.posts.append(path)
                return 202
            def get(self,path):
                return {"status":"queued"}

        api=API()
        with patch("acceptance.step23_prearm_cleanup.time.sleep",return_value=None):
            with self.assertRaisesRegex(RuntimeError,"did not stop after force-cancel"):
                _cancel_and_wait(api,19,"stale pre-arm blocker")
        self.assertEqual(
            api.posts,
            ["/actions/runs/19/cancel","/actions/runs/19/force-cancel"],
        )

    def test_force_cancel_zombie_can_be_deleted_only_with_zero_jobs(self):
        exact="a"*40
        row={
            "id":19,"head_branch":"main","head_sha":"b"*40,
            "path":".github/workflows/portfolio-state-reducer.yml",
            "status":"queued","event":"workflow_run",
        }
        class API:
            def __init__(self):
                self.deleted=[]
                self.request_reads=0
            def get(self,path):
                if path=="/actions/runs/19":
                    return dict(row)
                if path=="/actions/runs/19/jobs?per_page=100":
                    return {"total_count":0,"jobs":[]}
                raise AssertionError(path)
            def delete(self,path):
                self.deleted.append(path)
                return 204
            def request(self,path,method="GET"):
                self.request_reads+=1
                return 404,b""
        api=API()
        _delete_stuck_stale(api,row,exact)
        self.assertEqual(api.deleted,["/actions/runs/19"])
        self.assertEqual(api.request_reads,1)

    def test_zombie_with_jobs_still_fails_closed(self):
        exact="a"*40
        row={
            "id":20,"head_branch":"main","head_sha":"b"*40,
            "path":".github/workflows/portfolio-state-reducer.yml",
            "status":"queued","event":"workflow_run",
        }
        class API:
            def get(self,path):
                if path=="/actions/runs/20":
                    return dict(row)
                if path=="/actions/runs/20/jobs?per_page=100":
                    return {"total_count":1,"jobs":[{"id":99}]}
                raise AssertionError(path)
            def delete(self,path):
                raise AssertionError("delete must not run")
        with self.assertRaisesRegex(RuntimeError,"has jobs and cannot be deleted"):
            _delete_stuck_stale(API(),row,exact)

    def test_purge_tombstones_only_stale_non_schedule_zombie(self):
        exact="a"*40
        zombie={
            "id":21,"head_branch":"main","head_sha":"b"*40,
            "path":".github/workflows/portfolio-state-reducer.yml",
            "status":"queued","event":"workflow_run",
            "display_title":"portfolio-state-reducer",
        }
        scheduled={**zombie,"id":22,"event":"schedule"}
        class API:
            def __init__(self):
                self.requests=0
                self.deleted=[]
            def get(self,path):
                if path=="/branches/main":
                    return {"commit":{"sha":exact}}
                if path=="/actions/runs?branch=main&per_page=100&page=1":
                    return {"workflow_runs":[zombie,scheduled]}
                if path=="/actions/runs/21":
                    return dict(zombie)
                if path=="/actions/runs/21/jobs?per_page=100":
                    return {"total_count":0,"jobs":[]}
                raise AssertionError(path)
            def delete(self,path):
                self.deleted.append(path)
                return 204
            def request(self,path,method="GET"):
                return 404,b""
        api=API()
        with patch("acceptance.step23_prearm_cleanup._cancel_and_wait",
                   side_effect=StuckAfterForceCancel("still queued")):
            result=purge(api,exact_sha=exact)
        self.assertEqual(result["deleted_stale_run_ids"],[21])
        self.assertEqual(result["deleted_stale_count"],1)
        self.assertEqual(result["cancelled_stale_run_ids"],[])
        self.assertEqual(api.deleted,["/actions/runs/21"])

    def test_only_superseded_non_scheduled_writer_runs_are_stale_blockers(self):
        exact="a"*40
        base={
            "id":1,"head_branch":"main","head_sha":"b"*40,
            "path":".github/workflows/runtime-hourly-sync.yml",
            "status":"in_progress","event":"workflow_dispatch",
        }
        self.assertFalse(stale_non_schedule_blocker(base,exact))
        self.assertTrue(stale_non_schedule_blocker({**base,"event":"workflow_run"},exact))
        self.assertTrue(stale_non_schedule_blocker({**base,"event":"push"},exact))
        self.assertTrue(stale_non_schedule_blocker({
            **base,"event":"workflow_dispatch","display_title":"prearm-123-old-run"
        },exact))
        self.assertFalse(stale_non_schedule_blocker({**base,"event":"schedule"},exact))
        self.assertFalse(stale_non_schedule_blocker({**base,"head_sha":exact},exact))
        self.assertFalse(stale_non_schedule_blocker({**base,"status":"completed"},exact))
        self.assertFalse(stale_non_schedule_blocker({**base,"path":".github/workflows/foundation-ci.yml"},exact))


if __name__=="__main__":
    unittest.main()
