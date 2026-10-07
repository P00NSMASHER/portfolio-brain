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
