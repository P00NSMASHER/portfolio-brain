"""Main-only Git backend capacity proof must never mutate real state."""
import unittest
from pathlib import Path

YAML=Path(__file__).resolve().parents[1]/".github/workflows/state-capacity-qualification.yml"

class BackendCapacityCanaryTests(unittest.TestCase):
    def test_only_trusted_main_push_may_write_canary(self):
        text=YAML.read_text(encoding="utf-8")
        self.assertIn("github.event_name == 'push'",text)
        self.assertIn("github.ref == 'refs/heads/main'",text)
        self.assertIn("github.repository == 'P00NSMASHER/portfolio-brain'",text)
        self.assertIn("github.event_name != 'push'",text)
        self.assertEqual(text.count("      contents: write"),1)
        self.assertNotIn("pull_request_target:",text)
        self.assertNotIn("--force",text)
        self.assertNotIn("HEAD:refs/heads/brain-state-v2",text)

    def test_exact_source_separate_branch_and_replay(self):
        text=YAML.read_text(encoding="utf-8")
        self.assertIn("brain-capacity-canary-180mb-20261105",text)
        self.assertIn("needs: backend-canary-publish",text)
        self.assertIn("minimum_bytes=180_000_000",text)
        self.assertIn("BACKEND_CAPACITY_READBACK_MISMATCH",text)
        self.assertIn("production_data_verified=False",text)
        self.assertIn("retention-days: 90",text)
        self.assertNotIn("id-token: write",text)

if __name__=="__main__":
    unittest.main()
