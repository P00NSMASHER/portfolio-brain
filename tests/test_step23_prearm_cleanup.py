import unittest

from acceptance.step23_prearm_cleanup import leaked_title


class PrearmCleanupTests(unittest.TestCase):
    def test_only_prearm_titles_with_secret_markers_are_selected(self):
        self.assertTrue(leaked_title("prearm-initial-drain-1-ghs_example"))
        self.assertTrue(leaked_title("prearm-run-1-github_pat_example"))
        self.assertFalse(leaked_title("prearm-run-123-initial-drain-1"))
        self.assertFalse(leaked_title("ordinary-ghs_example"))
        self.assertFalse(leaked_title(None))


if __name__=="__main__":
    unittest.main()
