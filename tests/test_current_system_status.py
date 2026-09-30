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

if __name__=="__main__":unittest.main()
