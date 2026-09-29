"""Actual local subprocess tests using only the trusted source fixtures below.

These tests exercise build behavior. They do not pretend the injected runner is
Docker, a live provider call, independent verification, or a downstream rollout.
"""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from software_factory.candidate_worker import (
    BuildError, DockerRunner, build_candidate, digest, load_snapshot, object_hash,
    safe_path, validate_task,
)


SOURCE = b'def parse_count(value):\n    return int(value)\n'
REGRESSION = '''import unittest
from parser import parse_count

class Regression(unittest.TestCase):
    def test_boolean_is_not_a_count(self):
        with self.assertRaises(ValueError, msg="BOOLEAN_COUNT_MUST_BE_REJECTED"):
            parse_count(True)

    def test_valid_count(self):
        self.assertEqual(parse_count("7"), 7)
'''
EXISTING = b'''import unittest
from parser import parse_count
class Existing(unittest.TestCase):
    def test_zero(self):
        self.assertEqual(parse_count("0"), 0)
'''


def task_fixture():
    return {"schema_version": 1, "driver": "exact-replacement-v1", "task_id": "BUILD-TEST-1",
            "source_ref": "RPR-TRUSTED-FIXTURE", "project_id": "PRJ-000",
            "repository": "P00NSMASHER/portfolio-brain", "base_sha": "a" * 40,
            "timeout_seconds": 5, "test_path": "tests/test_build_regression.py",
            "test_source": REGRESSION, "baseline_failure_marker": "BOOLEAN_COUNT_MUST_BE_REJECTED",
            "edits": [{"path": "parser.py", "source_sha256": digest(SOURCE),
                       "before": "    return int(value)",
                       "after": '    if isinstance(value, bool):\n        raise ValueError("boolean count")\n    return int(value)'}]}


def snapshot_fixture():
    return {"parser.py": SOURCE, "tests/test_existing.py": EXISTING}


def trusted_fixture_runner(root, argv, timeout):
    # No production source, model code, credentials or network operations here.
    env = {"PATH": os.environ.get("PATH", ""), "PYTHONDONTWRITEBYTECODE": "1",
           "PYTHONHASHSEED": "0"}
    result = subprocess.run([sys.executable, *argv[1:]], cwd=root, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
    return {"exit_code": result.returncode, "output": result.stdout,
            "timed_out": False, "output_limit_exceeded": False,
            "runtime": "trusted-unit-fixture-subprocess", "image_id": None}


class CandidateWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / "proof"
        self.task = task_fixture()
        self.snapshot = snapshot_fixture()

    def build(self, runner=trusted_fixture_runner, **kwargs):
        return build_candidate(self.task, approved_hash=object_hash(self.task), snapshot=self.snapshot,
                               runner=runner, output_dir=self.output, **kwargs)

    def test_real_failure_patch_and_success_are_measured(self):
        receipt = self.build()
        self.assertEqual([r["exit_code"] for r in receipt["tests"]], [1, 0, 0])
        self.assertEqual([r["test_count"] for r in receipt["tests"]], [2, 2, 3])
        self.assertFalse(receipt["independent_verification"])
        self.assertFalse(receipt["production_changed"])
        self.assertEqual(receipt["model_calls"], 0)
        self.assertEqual(receipt["patch_sha256"], digest((self.output / "candidate.patch").read_bytes()))
        for row in receipt["tests"]:
            self.assertEqual(row["log_sha256"], digest((self.output / (row["stage"] + ".log")).read_bytes()))
        self.assertEqual(json.loads((self.output / "build_receipt.json").read_text()), receipt)

    def test_patch_applies_to_original_tree(self):
        self.build()
        checkout = Path(self.temp.name) / "apply"
        checkout.mkdir()
        for path, raw in self.snapshot.items():
            file = checkout / path
            file.parent.mkdir(exist_ok=True)
            file.write_bytes(raw)
        result = subprocess.run(["git", "apply", "--check", str(self.output / "candidate.patch")],
                                cwd=checkout, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_patch_handles_missing_final_newline(self):
        self.snapshot["parser.py"] = SOURCE.rstrip(b"\n")
        self.task["edits"][0]["source_sha256"] = digest(self.snapshot["parser.py"])
        self.test_patch_applies_to_original_tree()

    def test_repository_metadata_is_retained_but_not_editable(self):
        self.snapshot[".github/workflows/ci.yml"] = b"name: existing-ci\n"
        self.build()
        self.assertNotIn(".github/workflows/ci.yml", json.loads((self.output / "candidate_files.json").read_text()))

    def test_unapproved_task_cannot_execute(self):
        with self.assertRaisesRegex(BuildError, "approved hash"):
            build_candidate(self.task, approved_hash="sha256:" + "0" * 64, snapshot=self.snapshot,
                            runner=lambda *a: self.fail("must not run"), output_dir=self.output)

    def test_source_drift_cannot_execute(self):
        self.snapshot["parser.py"] += b"# new revision\n"
        with self.assertRaisesRegex(BuildError, "source content drift"):
            self.build(runner=lambda *a: self.fail("must not run"))

    def test_noop_is_rejected(self):
        self.task["edits"][0]["after"] = self.task["edits"][0]["before"]
        with self.assertRaisesRegex(BuildError, "no-op"):
            self.build()

    def test_ambiguous_edit_is_rejected(self):
        self.snapshot["parser.py"] = SOURCE + SOURCE
        self.task["edits"][0]["source_sha256"] = digest(self.snapshot["parser.py"])
        with self.assertRaisesRegex(BuildError, "ambiguous"):
            self.build()

    def test_wrong_fix_fails_not_green(self):
        self.task["edits"][0]["after"] = "    return int(value) + 1"
        with self.assertRaisesRegex(BuildError, "candidate tests failed"):
            self.build()
        self.assertFalse(self.output.exists())

    def test_successful_baseline_is_not_a_reproduced_bug(self):
        self.task["test_source"] = self.task["test_source"].replace("parse_count(True)", "parse_count('bad')")
        with self.assertRaisesRegex(BuildError, "expected assertion failure"):
            self.build()

    def test_baseline_import_error_is_not_a_reproduced_bug(self):
        self.task["test_source"] = REGRESSION.replace("from parser import", "from missing_module import")
        with self.assertRaisesRegex(BuildError, "expected assertion failure"):
            self.build()

    def test_suite_failure_rejects_candidate(self):
        self.snapshot["tests/test_existing.py"] = EXISTING.replace(b'parse_count("0"), 0', b'parse_count("0"), 99')
        with self.assertRaisesRegex(BuildError, "candidate tests failed"):
            self.build()

    def test_timeout_is_not_success(self):
        def timeout(*args):
            return {"exit_code": 0, "timed_out": True, "output_limit_exceeded": False, "output": b"OK"}
        with self.assertRaisesRegex(BuildError, "timed out"):
            self.build(runner=timeout)

    def test_no_tests_is_not_success(self):
        def empty(*args):
            return {"exit_code": 0, "timed_out": False, "output_limit_exceeded": False, "output": b"Ran 0 tests in 0s\nOK\n"}
        with self.assertRaisesRegex(BuildError, "no executed unittest"):
            self.build(runner=empty)

    def test_output_limit_is_enforced(self):
        def overflow(*args):
            return {"exit_code": 0, "timed_out": False, "output_limit_exceeded": True, "output": b"OK"}
        with self.assertRaisesRegex(BuildError, "output limit"):
            self.build(runner=overflow)

    def test_test_mutation_is_rejected(self):
        def mutate(root, argv, timeout):
            result = trusted_fixture_runner(root, argv, timeout)
            (root / "parser.py").write_bytes(SOURCE + b"# mutation\n")
            return result
        with self.assertRaises(BuildError):
            self.build(runner=mutate)

    def test_overwriting_evidence_is_rejected(self):
        self.output.mkdir()
        with self.assertRaisesRegex(BuildError, "refusing evidence overwrite"):
            self.build()

    def test_existing_test_cannot_be_replaced(self):
        self.task["test_path"] = "tests/test_existing.py"
        with self.assertRaisesRegex(BuildError, "already exists"):
            self.build()

    def test_editing_tests_is_forbidden(self):
        self.task["edits"][0]["path"] = "tests/test_existing.py"
        with self.assertRaisesRegex(BuildError, "cannot edit tests"):
            self.build()

    def test_portable_path_guards(self):
        for path in ["../x", "/x", "a//b", "a/./b", "a\\..\\x", "C:/x", ".git/config", ".github/workflows/x", "x/.env", "x\ny"]:
            with self.subTest(path=path), self.assertRaises(BuildError):
                safe_path(path)

    def test_mutable_image_tag_is_rejected(self):
        with self.assertRaisesRegex(BuildError, "immutable"):
            DockerRunner("python:latest")

    def test_missing_docker_does_not_fall_back_to_host(self):
        with patch("shutil.which", return_value=None), self.assertRaisesRegex(BuildError, "unavailable"):
            DockerRunner("sha256:" + "a" * 64)

    def test_snapshot_loads_exact_git_commit_not_working_tree(self):
        repo = Path(self.temp.name) / "repo"
        repo.mkdir()
        def git(*args):
            return subprocess.check_output(["git", "-C", str(repo), *args], stderr=subprocess.DEVNULL).decode().strip()
        git("init"); git("config", "user.email", "fixture@example.invalid"); git("config", "user.name", "Fixture")
        git("remote", "add", "origin", "https://github.com/P00NSMASHER/portfolio-brain.git")
        (repo / "parser.py").write_bytes(SOURCE)
        git("add", "parser.py"); git("commit", "-m", "trusted fixture")
        self.task["base_sha"] = git("rev-parse", "HEAD")
        (repo / "parser.py").write_bytes(b"uncommitted drift\n")
        self.assertEqual(load_snapshot(repo, self.task), {"parser.py": SOURCE})
        self.task["repository"] = "someone/else"
        with self.assertRaisesRegex(BuildError, "repository mismatch"):
            load_snapshot(repo, self.task)


if __name__ == "__main__":
    unittest.main()
