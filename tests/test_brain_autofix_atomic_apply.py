"""Adversarial tests: repair staging must stay inside a clean isolated repo."""
from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from brain.core import BrainError
from brain.repair_patch_executor import (
    CHECKOUT, apply_to_isolated_worktree, generate,
)

REPOSITORY = "P00NSMASHER/x402-product-factory"
PATH = ".github/workflows/factory-ci.yml"
ORIGINAL = (
    "name: Factory CI\n"
    "on:\n"
    "  pull_request:\n"
    "permissions:\n"
    "  contents: read\n"
    "jobs:\n"
    "  test:\n"
    "    runs-on: ubuntu-latest\n"
    "    steps:\n"
    "      - uses: actions/checkout@v4\n"
    "      - run: echo safe\n"
)


def _git(root, *args):
    return subprocess.run(
        ["git", *args], cwd=root, check=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    ).stdout.strip()


def _workspace(home, *, linked_parent=False):
    root = Path(home) / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "local-test@example.org")
    _git(root, "config", "user.name", "Offline Local Test")
    (root / "tests").mkdir()
    (root / "tests" / ".keep").write_text("keep\n")
    if linked_parent:
        outside = Path(home) / "outside"
        (outside / "workflows").mkdir(parents=True)
        (root / ".github").symlink_to(outside, target_is_directory=True)
        target = outside / "workflows/factory-ci.yml"
    else:
        target = root / PATH
        target.parent.mkdir(parents=True)
    target.write_text(ORIGINAL)
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "seed")
    head = _git(root, "rev-parse", "HEAD")
    request = {
        "schema_version": 1, "repository": REPOSITORY,
        "source_head_sha": head, "path": PATH,
        "original_sha256": hashlib.sha256(ORIGINAL.encode()).hexdigest(),
        "repair_kind": "READONLY_CI_CHECKOUT_HARDENING",
        "independent_gate_required": True,
    }
    patch = generate(request, ORIGINAL.encode())
    return root, target, patch


class AtomicIsolatedRepairTests(unittest.TestCase):
    def test_clean_isolated_source_is_replaced_with_regression_and_original_mode(self):
        with tempfile.TemporaryDirectory() as folder:
            root, target, patch = _workspace(folder)
            original_mode = target.stat().st_mode & 0o777
            before = _git(root, "rev-parse", "HEAD")
            result = apply_to_isolated_worktree(root, patch)
            self.assertEqual(result["status"], "ISOLATED_CODE_AND_TEST_EDITED_AWAITING_CI")
            self.assertIn(CHECKOUT, target.read_text())
            self.assertEqual(target.stat().st_mode & 0o777, original_mode)
            self.assertTrue((root / patch["test_path"]).is_file())
            self.assertEqual(_git(root, "rev-parse", "HEAD"), before)
            self.assertFalse(list(target.parent.glob(".brain-autofix-*")))
            self.assertFalse(result["merged"])
            self.assertFalse(result["deployed"])

    def test_symlinked_source_parent_cannot_escape_isolated_repository(self):
        with tempfile.TemporaryDirectory() as folder:
            root, target, patch = _workspace(folder, linked_parent=True)
            # The leaf itself is a plain file. This was incorrectly permitted
            # by the previous target.is_symlink() leaf-only check.
            self.assertTrue(target.is_file())
            self.assertFalse(target.is_symlink())
            with self.assertRaisesRegex(BrainError, "AUTOFIX_PARENT_PATH_UNSAFE"):
                apply_to_isolated_worktree(root, patch)
            self.assertEqual(target.read_text(), ORIGINAL)
            self.assertFalse((root / patch["test_path"]).exists())
            self.assertEqual(_git(root, "status", "--porcelain"), "")

    def test_interrupted_atomic_replace_cleans_stage_and_keeps_original_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            root, target, patch = _workspace(folder)
            with mock.patch("brain.repair_patch_executor.os.replace",
                            side_effect=OSError("injected failed rename")) as rename:
                with self.assertRaisesRegex(
                        BrainError, "AUTOFIX_ISOLATED_FILE_WRITE_FAILED"):
                    apply_to_isolated_worktree(root, patch)
                rename.assert_called_once()
            self.assertEqual(target.read_bytes(), ORIGINAL.encode())
            self.assertFalse((root / patch["test_path"]).exists())
            self.assertFalse(list(target.parent.glob(".brain-autofix-*")))
            self.assertEqual(_git(root, "status", "--porcelain"), "")

    def test_dirty_worktree_still_fails_closed_before_creating_stage(self):
        with tempfile.TemporaryDirectory() as folder:
            root, target, patch = _workspace(folder)
            (root / "tests" / "already_modified.txt").write_text("dirty")
            with self.assertRaisesRegex(BrainError, "AUTOFIX_WORKTREE_NOT_CLEAN"):
                apply_to_isolated_worktree(root, patch)
            self.assertEqual(target.read_text(), ORIGINAL)
            self.assertFalse(list(target.parent.glob(".brain-autofix-*")))


if __name__ == "__main__":
    unittest.main()
