"""Guard the x402 gateway's read-only GitHub Actions workflow."""
import re
import unittest
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/x402-gateway-ci.yml"

class X402GatewayWorkflowSecurityTests(unittest.TestCase):
    def test_exact_immutable_dependencies_and_credential_free_checkout(self):
        source = WORKFLOW.read_text(encoding="utf-8")
        self.assertRegex(source, r"actions/checkout@[a-f0-9]{40}")
        self.assertRegex(source, r"actions/setup-node@[a-f0-9]{40}")
        self.assertIn("persist-credentials: false", source)
        self.assertNotRegex(source, r"uses: actions/[a-z-]+@v\d+")
        self.assertIn("node-version: '20'", source)

    def test_read_only_token_and_no_cancellation_of_main_evidence(self):
        source = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("permissions:\n  contents: read", source)
        self.assertNotIn("contents: write", source)
        self.assertIn("concurrency:", source)
        self.assertIn("github.event.pull_request.number || github.ref", source)
        self.assertIn("cancel-in-progress: ${{ github.event_name == 'pull_request' }}", source)
        self.assertIn("pull_request:", source)
        self.assertIn("'feat/x402-unified-gateway'", source)
        self.assertIn("      - run: npm run check", source)
        self.assertIn("      - run: npm test", source)

if __name__ == "__main__":
    unittest.main()
