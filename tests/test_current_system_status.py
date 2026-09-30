import unittest
from operations.render_current_system_status import OUTPUT,render

class CurrentSystemStatusTests(unittest.TestCase):
    def test_generated_status_matches_authoritative_configuration(self):
        self.assertTrue(OUTPUT.exists())
        self.assertEqual(OUTPUT.read_text(encoding="utf-8"),render())

    def test_status_does_not_falsely_close_audit_remediation(self):
        text=render()
        self.assertIn("does **not** mark issue #210 steps complete",text)
        self.assertIn("App 5121826",text)
        self.assertIn("No second Hunter exists",text)
        readme=(OUTPUT.parents[1]/"README.md").read_text(encoding="utf-8")
        architecture=(OUTPUT.parent/"ARCHITECTURE_CONTRACT.md").read_text(encoding="utf-8")
        self.assertIn("issue #210 is a separate acceptance track",readme)
        self.assertIn("Current architecture reconciliation — 2026-09-30",architecture)
        self.assertIn("docs/CURRENT_SYSTEM_STATUS.md",architecture)

if __name__=="__main__":unittest.main()
