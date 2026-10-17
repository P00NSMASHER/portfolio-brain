"""Independent negative controls for deterministic unattended code repairs."""
from __future__ import annotations

import copy
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from brain.core import BrainError
from brain.repair_patch_executor import (
    CHECKOUT, NODE, apply_to_isolated_worktree, generate, main as repair_cli,
)

REPO = "P00NSMASHER/x402-product-factory"
PATH = ".github/workflows/factory-ci.yml"
FIXTURE = (
    "name: Factory read only CI\n"
    "on:\n"
    "  pull_request:\n"
    "permissions:\n"
    "  contents: read\n"
    "jobs:\n"
    "  test:\n"
    "    runs-on: ubuntu-latest\n"
    "    steps:\n"
    "      - uses: actions/checkout@v4\n"
    "      - uses: actions/setup-node@v4\n"
    "      - run: npm test\n"
)


def request(contents=FIXTURE, **changes):
    doc = {
        "schema_version": 1, "repository": REPO,
        "source_head_sha": "a" * 40,
        "path": PATH,
        "original_sha256": hashlib.sha256(contents.encode()).hexdigest(),
        "repair_kind": "READONLY_CI_CHECKOUT_HARDENING",
        "independent_gate_required": True,
    }
    doc.update(changes)
    return doc


class DeterministicRepairTests(unittest.TestCase):
    def test_generates_real_workflow_patch_and_unique_source_regression(self):
        artifact = generate(request(), FIXTURE.encode())
        self.assertEqual(artifact["status"], "REVIEWED_REPAIR_AND_REGRESSION_READY")
        self.assertEqual(artifact["source_head_sha"], "a" * 40)
        self.assertEqual(artifact["steps"], [
            "PIN_CHECKOUT_ACTION", "DENY_PERSISTED_CREDENTIALS",
            "PIN_SETUP_NODE_ACTION",
        ])
        changed = artifact["changed_content"]
        self.assertIn(CHECKOUT, changed)
        self.assertIn(NODE, changed)
        self.assertIn("persist-credentials: false", changed)
        self.assertNotIn("actions/checkout@v4", changed)
        self.assertNotIn("actions/setup-node@v4", changed)
        self.assertTrue(artifact["test_path"].startswith("tests/test_readonly_checkout_"))
        self.assertFalse(artifact["merge_authority"])
        self.assertFalse(artifact["deployment_authority"])
        self.assertFalse(artifact["payment_or_external_contact_authority"])

    def test_failing_before_passing_after_generated_regression(self):
        artifact = generate(request(), FIXTURE.encode())
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            target = root / PATH
            test = root / artifact["test_path"]
            target.parent.mkdir(parents=True)
            test.parent.mkdir(parents=True)
            target.write_text(FIXTURE)
            test.write_text(artifact["test_content"])
            before = subprocess.run(
                [sys.executable, str(test)],
                capture_output=True, text=True, timeout=8,
            )
            self.assertNotEqual(before.returncode, 0)
            target.write_text(artifact["changed_content"])
            after = subprocess.run(
                [sys.executable, str(test)],
                capture_output=True, text=True, timeout=8,
            )
            self.assertEqual(after.returncode, 0, after.stderr)

    def test_actual_isolated_git_worktree_is_modified_not_pushed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(["git", "config", "user.email", "test@example.net"],
                           cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Local Test"],
                           cwd=root, check=True)
            target = root / PATH
            target.parent.mkdir(parents=True)
            (root / "tests").mkdir()
            target.write_text(FIXTURE)
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "seed"], cwd=root, check=True)
            head = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
            artifact = generate(request(source_head_sha=head), FIXTURE.encode())
            outcome = apply_to_isolated_worktree(root, artifact)
            self.assertEqual(outcome["status"], "ISOLATED_CODE_AND_TEST_EDITED_AWAITING_CI")
            self.assertEqual(len(outcome["paths"]), 2)
            self.assertEqual(head, subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=root, text=True).strip())
            self.assertIn("persist-credentials: false", target.read_text())
            generated = root / artifact["test_path"]
            self.assertTrue(generated.exists())
            execution = subprocess.run([sys.executable, str(generated)],
                                       text=True, capture_output=True, timeout=8)
            self.assertEqual(execution.returncode, 0, execution.stderr)
            with self.assertRaisesRegex(BrainError, "AUTOFIX_WORKTREE_NOT_CLEAN"):
                apply_to_isolated_worktree(root, artifact)

    def test_source_and_caller_authority_are_immutable(self):
        for key, value in (
            ("source_head_sha", "garbage"),
            ("original_sha256", "0" * 64),
            ("repository", "untrusted/repository"),
            ("path", "../.github/workflows/factory-ci.yml"),
            ("path", ".github/workflows/deploy-production.yml"),
            ("repair_kind", "ARBITRARY_SHELL_EXECUTION"),
            ("independent_gate_required", False),
        ):
            with self.subTest(key=key), self.assertRaises(BrainError):
                generate(request(**{key: value}), FIXTURE.encode())

    def test_no_privileged_or_third_party_workflow_edits(self):
        for fragment in (
            "  contents: write", "  pull-requests: write",
            "  id-token: write", "secrets.PROD_KEY",
            "  schedule:", "  workflow_dispatch:", "pull_request_target:",
            "  workflow_call:", "deploy", "curl https://example.org",
            "git push",
        ):
            text = FIXTURE + "\n" + fragment + "\n"
            with self.subTest(fragment=fragment), self.assertRaises(BrainError):
                generate(request(text), text.encode())

    def test_benign_deployment_label_allowed_only_for_original_permitplate_regression(self):
        fixture = FIXTURE.replace(
            "      - uses: actions/checkout@v4\n",
            "      - name: Verify public deployment boundary\n"
            "      - uses: actions/checkout@v4\n",
        )
        approved = request(
            fixture,
            repository="P00NSMASHER/permitplate-nyc",
            path=".github/workflows/permitplate-tests.yml",
        )
        patched = generate(approved, fixture.encode())
        self.assertIn("Verify public deployment boundary", patched["changed_content"])
        self.assertIn(CHECKOUT, patched["changed_content"])
        self.assertIn("persist-credentials: false", patched["changed_content"])

        # A similarly worded label in another repository remains forbidden.
        with self.assertRaisesRegex(BrainError, "AUTOFIX_PRIVILEGED"):
            generate(request(fixture), fixture.encode())

        # The exception never masks an executable deployment command.
        privileged = fixture + "      - run: ./deploy.sh\n"
        with self.assertRaisesRegex(BrainError, "AUTOFIX_PRIVILEGED"):
            generate(
                request(
                    privileged,
                    repository="P00NSMASHER/permitplate-nyc",
                    path=".github/workflows/permitplate-tests.yml",
                ),
                privileged.encode(),
            )

    def test_unclear_yaml_shape_is_not_autocorrected(self):
        samples = [
            FIXTURE.replace("  pull_request:\n", ""),
            FIXTURE.replace("permissions:\n  contents: read\n", ""),
            FIXTURE.replace("- uses: actions/checkout@v4",
                            "- uses: actions/checkout@v3"),
            FIXTURE.replace("      - uses: actions/setup-node@v4\n",
                            "      - uses: actions/checkout@v4\n"),
            FIXTURE.replace("      - uses: actions/checkout@v4\n",
                            "      - uses: actions/checkout@v4\n"
                            "        with:\n          fetch-depth: 0\n"),
            FIXTURE.replace("      - uses: actions/checkout@v4\n",
                            "      - uses: actions/checkout@v4\n"
                            "        with:\n          persist-credentials: true\n"),
        ]
        for source in samples:
            with self.subTest(source=source[-75:]), self.assertRaises(BrainError):
                generate(request(source), source.encode())

    def test_source_same_revision_different_bytes_fails(self):
        original = request()
        tampered = FIXTURE.replace("npm test", "npm run test")
        with self.assertRaisesRegex(BrainError, "AUTOFIX_EXACT_SOURCE_HASH_MISMATCH"):
            generate(original, tampered.encode())

    def test_idempotent_second_run_does_not_duplicate_credentials(self):
        artifact = generate(request(), FIXTURE.encode())
        changed = artifact["changed_content"]
        with self.assertRaises(BrainError):
            generate(request(changed), changed.encode())

    def test_no_actions_are_executed_on_bad_file_payload(self):
        for source in (b"\0" + FIXTURE.encode(), FIXTURE.encode() + b"\r",
                       b"\xff" + FIXTURE.encode(), b"hi"):
            with self.subTest(source=source[:5]), self.assertRaises(BrainError):
                generate(request(source.decode("utf-8", errors="replace")), source)

    def test_missing_git_checkout_is_not_treated_as_success(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            target = root / PATH
            target.parent.mkdir(parents=True)
            (root / "tests").mkdir()
            target.write_text(FIXTURE)
            artifact = generate(request(), FIXTURE.encode())
            with self.assertRaises((BrainError, subprocess.CalledProcessError)):
                apply_to_isolated_worktree(root, artifact)


    def test_cli_can_apply_complete_repair_to_isolated_uncommitted_branch(self):
        import json
        with tempfile.TemporaryDirectory() as folder:
            parent=Path(folder)
            root=parent/"source"
            root.mkdir()
            subprocess.run(["git","init","-q",str(root)],check=True)
            subprocess.run(["git","config","user.email","ci@example.net"],
                           cwd=root,check=True)
            subprocess.run(["git","config","user.name","Test Only"],
                           cwd=root,check=True)
            target=root/PATH
            target.parent.mkdir(parents=True)
            (root/"tests").mkdir()
            target.write_text(FIXTURE)
            subprocess.run(["git","add","."],cwd=root,check=True)
            subprocess.run(["git","commit","-qm","base"],cwd=root,check=True)
            head=subprocess.check_output(["git","rev-parse","HEAD"],
                                         cwd=root,text=True).strip()
            req=parent/"request.json"
            req.write_text(json.dumps(request(source_head_sha=head)))
            result_dir=parent/"result"
            code=repair_cli([
                "--request",str(req),"--source",str(target),
                "--apply-root",str(root),"--output",str(result_dir),
            ])
            self.assertEqual(code,0)
            data=json.loads((result_dir/"report.json").read_text())
            self.assertEqual(data["isolated_apply_receipt"]["status"],
                             "ISOLATED_CODE_AND_TEST_EDITED_AWAITING_CI")
            generated=root/data["test_path"]
            self.assertTrue(generated.is_file())
            self.assertIn(CHECKOUT,target.read_text())
            self.assertEqual(subprocess.run(
                [sys.executable,str(generated)],
                capture_output=True,timeout=8).returncode,0)
            self.assertEqual(head,subprocess.check_output(
                ["git","rev-parse","HEAD"],cwd=root,text=True).strip())


if __name__ == "__main__":
    unittest.main()
