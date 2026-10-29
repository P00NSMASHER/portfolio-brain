"""Trusted core workflow source review for v9 read-only durable bridge."""
import hashlib
import tempfile
import unittest
from pathlib import Path

from brain.core import BrainError
from brain.v8.authority import (
    REVIEWED_WORKFLOW_SHA256, WORKFLOW, runtime_authority,
)

class V9CoreBridgeAuthorityTests(unittest.TestCase):
    def test_exact_reviewed_workflow_and_scopes(self):
        source = WORKFLOW.read_text(encoding="utf-8")
        self.assertEqual(hashlib.sha256(source.encode("utf-8")).hexdigest(),
                         REVIEWED_WORKFLOW_SHA256)
        self.assertIn("python -m brain.v9.batch_cycle cycle", source)
        self.assertIn("--db state/state.sqlite", source)
        self.assertIn("--input /tmp/brain/projects/report.json", source)
        self.assertIn("--proof-manifest brain/v9/repair-proof.json", source)
        self.assertLess(source.index("python -m brain.v9.batch_cycle cycle"),
                        source.index("python -m brain.state_archive pack"))
        authority = runtime_authority()
        self.assertEqual(authority["workflow_sha256"], REVIEWED_WORKFLOW_SHA256)
        self.assertFalse(authority["provider_write_actions_verified"])
        self.assertFalse(authority["effective_permissions_verified"])
        self.assertEqual(authority["credential_scope"],
                         "BRAIN_REPOSITORY_WORKFLOW_TOKEN_ONLY")
        self.assertEqual(authority["workflow_declares"]["repository_default"],
                         {"contents": "read"})

    def test_any_unreviewed_workflow_mutation_fails_closed(self):
        original = WORKFLOW.read_text(encoding="utf-8")
        for attack in ("\\n  workflow_dispatch: \\n",
                       "\\n      contents: write\\n",
                       "\\n      - run: echo unreviewed-step\\n"):
            with self.subTest(attack=attack), self.assertRaisesRegex(
                    BrainError, "V8_AUTHORITY_WORKFLOW_REVIEW_REQUIRED"):
                runtime_authority(original + attack)

if __name__ == "__main__":
    unittest.main()
