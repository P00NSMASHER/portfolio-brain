import unittest

from acceptance.step23_prearm_cleanup import leaked_title, stale_non_schedule_blocker


class PrearmCleanupTests(unittest.TestCase):
    def test_only_prearm_titles_with_secret_markers_are_selected(self):
        self.assertTrue(leaked_title("prearm-initial-drain-1-ghs_example"))
        self.assertTrue(leaked_title("prearm-run-1-github_pat_example"))
        self.assertFalse(leaked_title("prearm-run-123-initial-drain-1"))
        self.assertFalse(leaked_title("ordinary-ghs_example"))
        self.assertFalse(leaked_title(None))

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
