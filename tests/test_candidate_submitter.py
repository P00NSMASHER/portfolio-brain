import base64
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from urllib.error import HTTPError

from software_factory.candidate_submitter import submit_candidate
from software_factory.candidate_worker import BuildError, digest, object_hash
from software_factory.software_factory import hashv


BASE = "1" * 40
LOCAL = "2" * 40
REMOTE = "3" * 40
TREE = "4" * 40
BRANCH = "factory/build-auto-fixture/attempt-1"
REPO = "P00NSMASHER/portfolio-brain"
FILES = {
    "src/module.py": "VALUE = 2\n",
    "tests/test_factory_generated_fixture.py": "import unittest\n",
}


def packet(operation, *, files=None, expected=None, message=None):
    core = {
        "schema_version": "1.0.0",
        "operation": operation,
        "factory_work_id": "BUILD-AUTO-FIXTURE",
        "repository_full_name": REPO,
        "default_branch": "main",
        "branch_name": BRANCH,
        "base_sha": BASE,
        "expected_head_sha": expected,
        "files": files or [],
        "commit_message": message,
        "pr_title": None,
        "pr_body": None,
    }
    action_id = "SFA-" + object_hash(core).split(":", 1)[1][:20].upper()
    body = {"action_id": action_id, **core}
    return {**body, "action_hash": hashv(body)}


def replay_fixture(root: Path):
    encoded = [{
        "path": path,
        "content_b64": base64.b64encode(text.encode()).decode(),
        "content_sha256": digest(text.encode()),
    } for path, text in FILES.items()]
    branch = packet("CREATE_BRANCH")
    commit = packet("COMMIT_CANDIDATE", files=encoded, expected=BASE,
                    message="Candidate repair: BUILD-AUTO-FIXTURE")
    work = {
        "work_id": "BUILD-AUTO-FIXTURE",
        "state": "VERIFYING",
        "verification_id": None,
        "pr_number": None,
        "branch_name": BRANCH,
        "commit_sha": LOCAL,
        "diff_hash": "sha256:" + "5" * 64,
    }
    replay = {
        "status": "REPLAY_PASSED_AWAITING_INDEPENDENT_REVIEW",
        "task_id": "BUILD-AUTO-FIXTURE",
        "task_hash": "sha256:" + "6" * 64,
        "source_ref": "RTASK-SUBMIT-FIXTURE",
        "repository": REPO,
        "base_sha": BASE,
        "candidate_commit_sha": LOCAL,
        "candidate_git_tree_sha": TREE,
        "patch_sha256": work["diff_hash"],
        "changed_paths": sorted(FILES),
        "branch_packet_hash": branch["action_hash"],
        "commit_packet_hash": commit["action_hash"],
        "independent_verification": False,
        "remote_submission_performed": False,
        "production_changed": False,
        "merge_authorized": False,
        "deployment_authorized": False,
    }
    root.mkdir(parents=True)
    for name, value in [
        ("replay_receipt.json", replay),
        ("factory_work.json", work),
        ("factory_branch_action.json", branch),
        ("factory_commit_action.json", commit),
        ("candidate_files.json", FILES),
    ]:
        (root / name).write_text(json.dumps(value))
    return replay, branch, commit, work


class FakeExecutor:
    def __init__(self):
        self.head = None
        self.branch_writes = 0
        self.commit_writes = 0
        self.tree = TREE
        self.remote_paths = set(FILES)
        self.commit_message = "Candidate repair: BUILD-AUTO-FIXTURE"

    def transport(self, method, url, payload=None):
        if method == "GET" and "/git/ref/heads/" in url:
            if self.head is None:
                raise HTTPError(url, 404, "missing", {}, BytesIO(b""))
            return {"object": {"sha": self.head}}
        if method == "GET" and "/git/commits/" in url:
            if url.endswith(REMOTE):
                return {"sha": REMOTE, "parents": [{"sha": BASE}],
                        "tree": {"sha": self.tree}, "message": self.commit_message}
            raise HTTPError(url, 404, "missing", {}, BytesIO(b""))
        if method == "GET" and "/compare/" in url:
            return {"status": "ahead", "ahead_by": 1, "behind_by": 0,
                    "files": [{"filename": path} for path in sorted(self.remote_paths)]}
        raise AssertionError((method, url, payload))

    def execute(self, action):
        if action["operation"] == "CREATE_BRANCH":
            self.branch_writes += 1
            if self.head is not None:
                raise AssertionError("branch already exists")
            self.head = action["base_sha"]
            return {"ref": "refs/heads/" + action["branch_name"],
                    "object": {"sha": self.head}}
        if action["operation"] == "COMMIT_CANDIDATE":
            self.commit_writes += 1
            if self.head != action["expected_head_sha"]:
                raise AssertionError("head drift")
            self.head = REMOTE
            return {"sha": REMOTE, "tree": {"sha": self.tree},
                    "parents": [{"sha": BASE}], "message": action["commit_message"]}
        raise AssertionError("unexpected operation")


class CandidateSubmitterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "replay"
        replay_fixture(self.root)
        self.remote = FakeExecutor()

    def test_first_submission_writes_branch_and_candidate_once(self):
        receipt = submit_candidate(replay_dir=self.root, executor=self.remote)
        self.assertEqual(receipt["status"], "REMOTE_CANDIDATE_SUBMITTED")
        self.assertEqual(receipt["remote_commit_sha"], REMOTE)
        self.assertEqual(receipt["remote_tree_sha"], TREE)
        self.assertTrue(receipt["mutation_performed_this_run"])
        self.assertTrue(receipt["remote_candidate_present"])
        self.assertFalse(receipt["independent_verification"])
        self.assertFalse(receipt["pr_created"])
        self.assertEqual(self.remote.branch_writes, 1)
        self.assertEqual(self.remote.commit_writes, 1)

    def test_repeat_submission_reuses_exact_remote_candidate_without_writes(self):
        first = submit_candidate(replay_dir=self.root, executor=self.remote)
        second = submit_candidate(replay_dir=self.root, executor=self.remote)
        self.assertEqual(first["submission_key"], second["submission_key"])
        self.assertEqual(second["status"], "REMOTE_CANDIDATE_REUSED")
        self.assertFalse(second["mutation_performed_this_run"])
        self.assertEqual(self.remote.branch_writes, 1)
        self.assertEqual(self.remote.commit_writes, 1)

    def test_existing_base_branch_finishes_commit_without_recreating_branch(self):
        self.remote.head = BASE
        receipt = submit_candidate(replay_dir=self.root, executor=self.remote)
        self.assertEqual(receipt["status"], "REMOTE_CANDIDATE_SUBMITTED")
        self.assertEqual(self.remote.branch_writes, 0)
        self.assertEqual(self.remote.commit_writes, 1)

    def test_unrelated_existing_branch_fails_closed(self):
        self.remote.head = "9" * 40
        with self.assertRaises(BuildError):
            submit_candidate(replay_dir=self.root, executor=self.remote)
        self.assertEqual(self.remote.branch_writes, 0)
        self.assertEqual(self.remote.commit_writes, 0)

    def test_remote_tree_must_equal_replayed_candidate_tree(self):
        submit_candidate(replay_dir=self.root, executor=self.remote)
        self.remote.tree = "8" * 40
        with self.assertRaisesRegex(BuildError, "tree differs"):
            submit_candidate(replay_dir=self.root, executor=self.remote)

    def test_remote_changed_paths_must_be_exact(self):
        submit_candidate(replay_dir=self.root, executor=self.remote)
        self.remote.remote_paths.add("unexpected.py")
        with self.assertRaisesRegex(BuildError, "changed-path"):
            submit_candidate(replay_dir=self.root, executor=self.remote)

    def test_replay_cannot_claim_review_authority(self):
        path = self.root / "replay_receipt.json"
        replay = json.loads(path.read_text())
        replay["independent_verification"] = True
        path.write_text(json.dumps(replay))
        with self.assertRaisesRegex(BuildError, "grants authority"):
            submit_candidate(replay_dir=self.root, executor=self.remote)

    def test_tampered_action_packet_is_rejected_before_remote_access(self):
        path = self.root / "factory_commit_action.json"
        commit = json.loads(path.read_text())
        commit["commit_message"] = "tampered"
        path.write_text(json.dumps(commit))
        with self.assertRaisesRegex(BuildError, "packet hash"):
            submit_candidate(replay_dir=self.root, executor=self.remote)
        self.assertEqual(self.remote.branch_writes, 0)

    def test_candidate_packet_bytes_must_match_replay_manifest(self):
        path = self.root / "candidate_files.json"
        files = json.loads(path.read_text())
        files["src/module.py"] = "VALUE = 999\n"
        path.write_text(json.dumps(files))
        with self.assertRaisesRegex(BuildError, "packet bytes"):
            submit_candidate(replay_dir=self.root, executor=self.remote)

    def test_output_receipt_is_content_bound_and_cannot_be_overwritten(self):
        out = Path(self.temp.name) / "receipt.json"
        receipt = submit_candidate(replay_dir=self.root, executor=self.remote, output_path=out)
        stored = json.loads(out.read_text())
        self.assertEqual(stored, receipt)
        body = dict(stored); given = body.pop("receipt_hash")
        self.assertEqual(given, object_hash(body))
        with self.assertRaisesRegex(BuildError, "already exists"):
            submit_candidate(replay_dir=self.root, executor=self.remote, output_path=out)


if __name__ == "__main__":
    unittest.main()
