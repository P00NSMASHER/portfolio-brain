import unittest
from unittest.mock import patch

from acceptance.step23_prearm_cleanup import _cancel_and_wait, leaked_title, stale_non_schedule_blocker


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

    def test_force_cancel_must_reach_terminal_state_when_jobs_exist(self):
        class API:
            def __init__(self):
                self.posts=[]
                self.deletes=[]
            def post(self,path):
                self.posts.append(path)
                return 202
            def get(self,path):
                if "/jobs?" in path:
                    return {"total_count":1,"jobs":[{"id":99}]}
                return {"status":"queued"}
            def delete(self,path):
                self.deletes.append(path)
                return 204

        api=API()
        with patch("acceptance.step23_prearm_cleanup.time.sleep",return_value=None):
            with self.assertRaisesRegex(RuntimeError,"did not stop after force-cancel"):
                _cancel_and_wait(api,19,"stale pre-arm blocker")
        self.assertEqual(
            api.posts,
            ["/actions/runs/19/cancel","/actions/runs/19/force-cancel"],
        )
        self.assertEqual(api.deletes,[])

    def test_force_cancel_jobless_queued_zombie_is_deleted_and_verified_gone(self):
        class API:
            def __init__(self):
                self.posts=[]
                self.deletes=[]
                self.requests=[]
            def post(self,path):
                self.posts.append(path)
                return 202
            def get(self,path):
                if "/jobs?" in path:
                    return {"total_count":0,"jobs":[]}
                return {"status":"queued"}
            def delete(self,path):
                self.deletes.append(path)
                return 204
            def request(self,path,method="GET"):
                self.requests.append((path,method))
                return 404,b""

        api=API()
        with patch("acceptance.step23_prearm_cleanup.time.sleep",return_value=None):
            mode=_cancel_and_wait(api,20,"stale pre-arm blocker")
        self.assertEqual(mode,"DELETE_JOBLESS_QUEUE")
        self.assertEqual(
            api.posts,
            ["/actions/runs/20/cancel","/actions/runs/20/force-cancel"],
        )
        self.assertEqual(api.deletes,["/actions/runs/20"])
        self.assertEqual(api.requests,[("/actions/runs/20","GET")])

    def test_force_cancel_never_deletes_in_progress_run_even_without_jobs(self):
        class API:
            def __init__(self):
                self.deletes=[]
            def post(self,path):
                return 202
            def get(self,path):
                if "/jobs?" in path:
                    raise AssertionError("jobs must not be queried for in-progress run")
                return {"status":"in_progress"}
            def delete(self,path):
                self.deletes.append(path)
                return 204

        api=API()
        with patch("acceptance.step23_prearm_cleanup.time.sleep",return_value=None):
            with self.assertRaisesRegex(RuntimeError,"did not stop after force-cancel"):
                _cancel_and_wait(api,21,"stale pre-arm blocker")
        self.assertEqual(api.deletes,[])

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


    def test_undeletable_jobless_zombie_remains_blocking(self):
        class API:
            def post(self,path):
                return 202
            def get(self,path):
                if "/jobs?" in path:
                    return {"total_count":0,"jobs":[]}
                if "/artifacts?" in path:
                    return {"total_count":0,"artifacts":[]}
                return {"status":"queued"}
            def delete(self,path):
                return 403

        with patch("acceptance.step23_prearm_cleanup.time.sleep",return_value=None):
            with self.assertRaisesRegex(
                RuntimeError,
                "could not delete stale pre-arm blocker queued zombie run 20: 403",
            ):
                _cancel_and_wait(API(),20,"stale pre-arm blocker")

    def test_jobless_queued_run_with_artifact_is_never_deleted(self):
        class API:
            def __init__(self):
                self.deletes=[]
            def post(self,path):
                return 202
            def get(self,path):
                if "/jobs?" in path:
                    return {"total_count":0,"jobs":[]}
                if "/artifacts?" in path:
                    return {"total_count":1,"artifacts":[{"id":99}]}
                return {"status":"queued"}
            def delete(self,path):
                self.deletes.append(path)
                return 204

        api=API()
        with patch("acceptance.step23_prearm_cleanup.time.sleep",return_value=None):
            with self.assertRaisesRegex(RuntimeError,"did not stop after force-cancel"):
                _cancel_and_wait(api,20,"stale pre-arm blocker")
        self.assertEqual(api.deletes,[])

    def test_temporary_admin_cleanup_workflow_is_absent(self):
        from pathlib import Path

        root=Path(__file__).resolve().parents[1]
        self.assertFalse((root/".github/workflows/step23-admin-zombie-cleanup.yml").exists())


if __name__=="__main__":
    unittest.main()
