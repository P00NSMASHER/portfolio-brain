"""Fresh Git replay, real subprocess fixture tests, and hostile artifact controls."""
import copy
import json
from pathlib import Path
import subprocess
import shutil
import tempfile
import unittest
from unittest.mock import patch

from software_factory.candidate_worker import BuildError, build_candidate, digest, object_hash
from software_factory.candidate_replay import read_json, replay_candidate
try:
    from .test_candidate_worker import snapshot_fixture, task_fixture, trusted_fixture_runner
except ImportError:
    from test_candidate_worker import snapshot_fixture, task_fixture, trusted_fixture_runner


class CandidateReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.fixture.cleanup)
        root = Path(cls.fixture.name)
        cls.repo = root / "source"
        cls.repo.mkdir()
        cls.source = snapshot_fixture()
        cls.task = task_fixture()
        def git(*args):
            return subprocess.check_output(["git", "-C", str(cls.repo), *args], stderr=subprocess.DEVNULL)
        git("init")
        git("config", "user.name", "Trusted Fixture")
        git("config", "user.email", "fixture@example.invalid")
        git("remote", "add", "origin", "https://github.com/P00NSMASHER/portfolio-brain.git")
        for path, raw in cls.source.items():
            dest = cls.repo / path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(raw)
        git("add", "."); git("commit", "-m", "trusted fixture")
        cls.task["base_sha"] = git("rev-parse", "HEAD").decode().strip()
        cls.approved_hash = object_hash(cls.task)
        cls.seed_build = root / "build"
        cls.seed_receipt = build_candidate(cls.task, approved_hash=cls.approved_hash,
                                          snapshot=cls.source, runner=trusted_fixture_runner, output_dir=cls.seed_build)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.task = copy.deepcopy(type(self).task)
        self.build = self.root / "build"
        shutil.copytree(self.seed_build, self.build)
        self.output = self.root / "replay"
        self.receipt = copy.deepcopy(self.seed_receipt)

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.repo), *args], stderr=subprocess.DEVNULL)

    def replay(self, runner=trusted_fixture_runner):
        return replay_candidate(self.task, approved_hash=self.approved_hash, checkout=self.repo,
                                artifact_dir=self.build, runner=runner, output_dir=self.output)

    def rehash_receipt(self, edit=None):
        row = json.loads((self.build / "build_receipt.json").read_text())
        if edit:
            edit(row)
        row.pop("receipt_hash")
        row["receipt_hash"] = object_hash(row)
        (self.build / "build_receipt.json").write_text(json.dumps(row))

    def test_actual_patch_replay_creates_real_git_commit_and_factory_handoff(self):
        head = self.git("rev-parse", "HEAD")
        result = self.replay()
        self.assertEqual(result["status"], "REPLAY_PASSED_AWAITING_INDEPENDENT_REVIEW")
        self.assertEqual([r["exit_code"] for r in result["replay_tests"]], [1, 0, 0])
        self.assertEqual([r["test_count"] for r in result["replay_tests"]], [2, 2, 3])
        self.assertFalse(result["independent_verification"])
        self.assertFalse(result["remote_submission_performed"])
        self.assertEqual(result["delivered_improvements"], 0)
        work = read_json(self.output, "factory_work.json")
        self.assertEqual(work["state"], "VERIFYING")
        self.assertIsNone(work["verification_id"])
        self.assertIsNone(work["pr_number"])
        self.assertEqual(work["commit_sha"], result["candidate_commit_sha"])
        self.assertEqual(self.git("rev-parse", "HEAD"), head)
        self.assertEqual(self.git("status", "--porcelain"), b"")
        raw = (self.output / "candidate_commit.txt").read_bytes()
        import hashlib
        self.assertEqual(hashlib.sha1(b"commit " + str(len(raw)).encode() + b"\0" + raw).hexdigest(),
                         result["candidate_commit_sha"])
        clone = self.root / "restore"
        subprocess.run(["git", "clone", str(self.output / "candidate.bundle"), str(clone)],
                       check=True, capture_output=True)
        self.assertEqual(subprocess.check_output(["git", "-C", str(clone), "rev-parse", "HEAD"], text=True).strip(),
                         result["candidate_commit_sha"])
        self.assertEqual(subprocess.check_output(["git", "-C", str(clone), "rev-parse", "HEAD^"], text=True).strip(),
                         self.task["base_sha"])
        for name in ("factory_branch_action.json", "factory_commit_action.json"):
            packet = read_json(self.output, name)
            self.assertEqual(packet["action_hash"], object_hash({k: v for k, v in packet.items() if k != "action_hash"}))
            self.assertNotEqual(packet["branch_name"], "main")
        self.assertFalse((self.output / "factory_pr_action.json").exists())

    def test_forged_patch_rehashed_but_not_tested_is_rejected(self):
        path = self.build / "candidate.patch"
        path.write_bytes(path.read_bytes().replace(b'raise ValueError("boolean count")', b'raise ValueError("wrong behavior")'))
        self.rehash_receipt(lambda r: r.update(patch_sha256=digest(path.read_bytes())))
        with self.assertRaisesRegex(BuildError, "applied patch differs"):
            self.replay()
        self.assertFalse(self.output.exists())

    def test_unaccounted_mode_change_is_rejected(self):
        path = self.build / "candidate.patch"
        path.write_bytes(path.read_bytes() + b"diff --git a/tests/test_existing.py b/tests/test_existing.py\nold mode 100644\nnew mode 100755\n")
        self.rehash_receipt(lambda r: r.update(patch_sha256=digest(path.read_bytes())))
        with self.assertRaisesRegex(BuildError, "file modes"):
            self.replay()

    def test_changed_candidate_bytes_are_rejected_even_with_unchanged_receipt(self):
        files = read_json(self.build, "candidate_files.json")
        files["parser.py"] = "def parse_count(value): return 7\n"
        (self.build / "candidate_files.json").write_text(json.dumps(files))
        with self.assertRaisesRegex(BuildError, "file bytes"):
            self.replay()

    def test_modified_regression_artifact_is_rejected(self):
        files = read_json(self.build, "candidate_files.json")
        files[self.task["test_path"]] = "# disabled tests\n"
        (self.build / "candidate_files.json").write_text(json.dumps(files))
        with self.assertRaisesRegex(BuildError, "file bytes"):
            self.replay()

    def test_rehashed_authority_upgrade_is_rejected(self):
        self.rehash_receipt(lambda r: r.update(independent_verification=True))
        with self.assertRaisesRegex(BuildError, "cannot grant authority"):
            self.replay()

    def test_wrong_task_identity_is_rejected(self):
        self.rehash_receipt(lambda r: r.update(task_id="OTHER"))
        with self.assertRaisesRegex(BuildError, "identity mismatch"):
            self.replay()

    def test_wrong_base_is_rejected(self):
        self.rehash_receipt(lambda r: r.update(base_sha="b" * 40))
        with self.assertRaisesRegex(BuildError, "identity mismatch"):
            self.replay()

    def test_wrong_source_tree_is_rejected(self):
        self.rehash_receipt(lambda r: r.update(source_tree_hash="sha256:" + "0" * 64))
        with self.assertRaisesRegex(BuildError, "source tree mismatch"):
            self.replay()

    def test_wrong_candidate_tree_is_rejected(self):
        self.rehash_receipt(lambda r: r.update(candidate_tree_hash="sha256:" + "0" * 64))
        with self.assertRaisesRegex(BuildError, "candidate tree/paths"):
            self.replay()

    def test_missing_log_cannot_be_replaced_by_hash(self):
        (self.build / "candidate_suite.log").unlink()
        with self.assertRaisesRegex(BuildError, "artifact member"):
            self.replay()

    def test_rehashed_test_count_is_checked_against_log(self):
        self.rehash_receipt(lambda r: r["tests"][2].update(test_count=999))
        with self.assertRaisesRegex(BuildError, "count mismatch"):
            self.replay()

    def test_changed_log_is_rejected(self):
        (self.build / "candidate_suite.log").write_bytes(b"Ran 3 tests in 0s\nOK\n")
        with self.assertRaisesRegex(BuildError, "log digest"):
            self.replay()

    def test_skipped_tests_do_not_count_as_success(self):
        path = self.build / "candidate_suite.log"
        path.write_bytes(path.read_bytes().replace(b"\nOK\n", b"\nOK (skipped=1)\n"))
        self.rehash_receipt(lambda r: r["tests"][2].update(log_sha256=digest(path.read_bytes())))
        with self.assertRaisesRegex(BuildError, "without skips"):
            self.replay()

    def test_artifact_cannot_change_test_command(self):
        self.rehash_receipt(lambda r: r["tests"][2].update(command=["python", "-c", "pass"]))
        with self.assertRaisesRegex(BuildError, "command mismatch"):
            self.replay()

    def test_duplicate_json_is_rejected(self):
        path = self.build / "candidate_files.json"
        path.write_text('{"parser.py":"one", "parser.py":"two"}')
        with self.assertRaisesRegex(BuildError, "duplicate JSON"):
            self.replay()

    def test_nonfinite_json_is_rejected(self):
        (self.build / "build_receipt.json").write_text('{"model_cost_usd":NaN}')
        with self.assertRaisesRegex(BuildError, "nonfinite"):
            self.replay()

    def test_linked_artifact_member_is_rejected(self):
        file = self.build / "candidate.patch"
        file.rename(self.root / "outside.patch")
        file.symlink_to(self.root / "outside.patch")
        with self.assertRaisesRegex(BuildError, "linked artifact"):
            self.replay()

    def test_successful_old_logs_cannot_override_failed_fresh_replay(self):
        calls = []
        def changed_environment(root, argv, timeout):
            calls.append(argv)
            result = trusted_fixture_runner(root, argv, timeout)
            if len(calls) == 3:
                result["exit_code"] = 1
            return result
        with self.assertRaisesRegex(BuildError, "did not pass"):
            self.replay(runner=changed_environment)
        self.assertEqual(len(calls), 3)
        self.assertFalse(self.output.exists())

    def test_replay_cannot_mutate_test_files(self):
        def mutate(root, argv, timeout):
            result = trusted_fixture_runner(root, argv, timeout)
            (root / "tests/test_existing.py").write_text("# altered\n")
            return result
        with self.assertRaises(BuildError):
            self.replay(runner=mutate)
        self.assertFalse(self.output.exists())

    def test_replay_timeout_does_not_create_handoff(self):
        def timeout(*args):
            return {"exit_code": 0, "timed_out": True}
        with self.assertRaisesRegex(BuildError, "timed out"):
            self.replay(runner=timeout)
        self.assertFalse(self.output.exists())

    def test_output_cannot_be_overwritten(self):
        self.output.mkdir()
        with self.assertRaisesRegex(BuildError, "refusing overwrite"):
            self.replay()

    def test_task_hash_must_still_match_separate_contract(self):
        self.task["edits"][0]["after"] += "\n# changed"
        with self.assertRaisesRegex(BuildError, "approved hash"):
            self.replay()

    def test_factory_restrictions_still_apply(self):
        from software_factory import software_factory
        actual_policy = software_factory.policy
        def restricted_policy():
            result = actual_policy()
            result["forbidden_candidate_paths"].append("parser.py")
            return result
        with patch.object(software_factory, "policy", side_effect=restricted_policy):
            with self.assertRaisesRegex(ValueError, "forbidden path"):
                self.replay()
        self.assertFalse(self.output.exists())

    def test_candidate_replay_has_no_remote_executor(self):
        import inspect
        import software_factory.candidate_replay as replay
        body = inspect.getsource(replay)
        self.assertNotIn("GitHubExecutor(", body)
        self.assertNotIn(".verify(", body)
        self.assertNotIn('run("push"', body)


if __name__ == "__main__":
    unittest.main()
