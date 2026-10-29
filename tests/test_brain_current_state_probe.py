"""Read-only binary/ledger/report replay and failure labeling tests."""
import hashlib
import json
import shutil
import sqlite3
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from brain.adapters import event
from brain.core import Store, utcnow
from soak_v3.audit import EvidenceError
from soak_v3.current_state_probe import verify_source_state
from soak_v3.remote_probe import GitHubReadOnly

SHA = "a"*40
STATE = "b"*40
PARENT = "c"*40
MANIFEST = "d"*40


class PublicOriginalSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db = self.root/"real-original.sqlite"
        now = utcnow()
        store = Store(self.db, visibility="PUBLIC")
        repo = "P00NSMASHER/portfolio-brain"
        payload = {
            "repository": repo, "head_sha": SHA, "default_branch": "main",
            "checks": [], "open_issues": 0,
            "source_ref": f"https://github.com/{repo}/commit/{SHA}",
        }
        store.submit([event("repository",repo,payload,SHA,now=now)],now=now)
        store.drain()
        self.report = store.report(SHA, now=now)
        store.close()
        self.original_hash = hashlib.sha256(self.db.read_bytes()).hexdigest()

    class Provider:
        def __init__(self, sha):
            self.sha = sha
            self.calls = []
        def json(self, path):
            self.calls.append(path)
            if path == "/branches/main":
                return {"commit":{"sha":self.sha}}
            raise AssertionError("No other remote reads authorized in fixture")

    def make_original_git_stub(self, *, parent=PARENT):
        def stub(api, *, state_commit, target):
            if state_commit != STATE:
                raise EvidenceError("STATE_ID_MISMATCH")
            shutil.copyfile(self.db,target)
            return {
                "state_parent": parent,
                "raw_image_sha256": self.original_hash,
                "raw_size": len(self.db.read_bytes()),
                "chunk_count": 3,
                "manifest_git_blob_sha": MANIFEST,
                "soak_pass": False,
            }
        return stub

    def test_independent_sqlite_and_full_projection_replay_no_soak_claim(self):
        remote=self.Provider(SHA)
        with patch("soak_v3.current_state_probe.verify_original_state",
                   side_effect=self.make_original_git_stub()):
            result=verify_source_state(
                remote,state_commit=STATE,source_sha=SHA,
                expected_parent=PARENT,
                expected_sequence=self.report["state_sequence"],
                expected_chain=self.report["canonical_hash"],
            )
        self.assertEqual(result["status"],
                         "ORIGINAL_BINARY_AND_PROJECTION_VERIFIED_NOT_SOAK_PASS")
        self.assertTrue(result["canonical_event_id_verified"])
        self.assertTrue(result["deterministic_report_replay_verified"])
        self.assertFalse(result["six_hour_soak_accepted"])
        self.assertFalse(result["automatic_origin_verified"])
        self.assertEqual(result["state_chunks"], 3)
        self.assertEqual(result["state_bytes_sha256"], self.original_hash)
        self.assertEqual(remote.calls, ["/branches/main","/branches/main"])
        self.assertEqual(hashlib.sha256(self.db.read_bytes()).hexdigest(),
                         self.original_hash)

    def test_wrong_parent_never_accepted(self):
        with patch("soak_v3.current_state_probe.verify_original_state",
                   side_effect=self.make_original_git_stub(parent="e"*40)):
            with self.assertRaisesRegex(EvidenceError,"REMOTE_GIT_STATE_PARENT_MISMATCH"):
                verify_source_state(
                    self.Provider(SHA),state_commit=STATE,source_sha=SHA,
                    expected_parent=PARENT,
                    expected_sequence=1,expected_chain=self.report["canonical_hash"],
                )

    def test_expected_chain_mismatch_cannot_be_approved(self):
        with patch("soak_v3.current_state_probe.verify_original_state",
                   side_effect=self.make_original_git_stub()):
            with self.assertRaisesRegex(EvidenceError,"STATE_CANONICAL_HASH_MISMATCH"):
                verify_source_state(
                    self.Provider(SHA),state_commit=STATE,source_sha=SHA,
                    expected_parent=PARENT,
                    expected_sequence=1,expected_chain="f"*64,
                )

    def test_main_drift_blocks_even_with_reproducible_original_bytes(self):
        with self.assertRaisesRegex(EvidenceError,"CURRENT_MAIN_SOURCE_MISMATCH"):
            verify_source_state(
                self.Provider("f"*40),state_commit=STATE,source_sha=SHA,
                expected_parent=PARENT,
                expected_sequence=1,expected_chain=self.report["canonical_hash"],
            )

    def test_modified_original_event_id_rejected_before_report_replay(self):
        with sqlite3.connect(self.db) as db:
            row = db.execute("SELECT body FROM events LIMIT 1").fetchone()
            changed = json.loads(row[0])
            changed["id"] = "repository:forged"
            body = json.dumps(changed, sort_keys=True,
                              separators=(",", ":"), ensure_ascii=False)
            changed_hash=hashlib.sha256(body.encode()).hexdigest()
            db.execute("UPDATE events SET id=?,body=?,hash=?",
                       (changed["id"],body,changed_hash))
        self.original_hash = hashlib.sha256(self.db.read_bytes()).hexdigest()
        with patch("soak_v3.current_state_probe.verify_original_state",
                   side_effect=self.make_original_git_stub()):
            with self.assertRaisesRegex(EvidenceError,"STATE_CANONICAL_EVENT_ID_INVALID"):
                verify_source_state(
                    self.Provider(SHA),state_commit=STATE,source_sha=SHA,
                    expected_parent=PARENT,
                    expected_sequence=1,expected_chain=self.report["canonical_hash"],
                )

    def test_remote_reader_default_budget_is_not_bypassed(self):
        api = GitHubReadOnly("",transport=lambda path:b"{}",max_calls=12)
        for index in range(12):
            api.get(f"/repos/example/sample-{index}")
        with self.assertRaisesRegex(EvidenceError,"API_CALL_BUDGET"):
            api.get("/repos/example/over-budget")
        with self.assertRaisesRegex(EvidenceError,"API_CALL_BOUND_INVALID"):
            GitHubReadOnly("",transport=lambda _:b"{}",max_calls=657)


if __name__ == "__main__":
    unittest.main()
