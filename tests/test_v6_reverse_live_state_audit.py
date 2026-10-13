"""One-off immutable real-state V6 -> V5 -> V6 rollback rehearsal.

AUDIT ONLY / DO NOT MERGE. Execute only under a GitHub Foundation PR runner.
Read the exact original V5 state Git object. All simulated cutovers write to
one temporary local copy; neither source nor live state branches are touched.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from urllib.parse import quote

REPO = "P00NSMASHER/portfolio-brain"
V5_SHA = "3fb0bb0dcc28f961033d782260c31f36ed78eb71"
V6_SHA = "a0640492c8466b8b9977cc9d058c83a137522f3d"
ORIGINAL_STATE_COMMIT = "1ac02db80c4809095f8723b5ec8c0685a4984c2e"
ORIGINAL_BLOB = "d4a1556a6e47e6d817d8ae88d2d23c9b1dbf23ae"
ORIGINAL_BYTES = 47972352

# Block accidental evaluation against a changed production implementation.
V6_CODE_BLOBS = {
    "brain/core.py": "a8155fd06fdbfead31177474ca05b9291d56772e",
    "brain/changes.py": "81f3f7af69ac09ab34e1f115d6edbd452d03b3a4",
    "brain/render.py": "71d60232ee1ab4cb4f53dc8afe7f8aa827ead6b2",
}

OLD_SOURCE_RUNNER = r'''
import json
import sqlite3
import sys
from brain.core import BrainError, Store

path, source, v6_sha, phase, as_of, original_id = sys.argv[1:]
original_id = int(original_id)
store = Store(path, visibility="PUBLIC")
try:
    original = store.db.execute(
        "SELECT body,hash FROM reports WHERE id=?", (original_id,)
    ).fetchone()
    assert original is not None
    before_original = tuple(original)
    if phase == "before":
        result = store.read_report(source, now=as_of)
        assert result["source_sha"] == source and result["status"] == "PASS"
        print("V5_BEFORE_ROLLBACK=" + json.dumps({
            "source": source, "old_report_read": "PASS",
            "sequence": result["state_sequence"],
            "canonical_hash": result["canonical_hash"],
        }, sort_keys=True))
    elif phase == "after":
        # The latest V6-source report must not masquerade as V5 current
        # authority. Projected semantics may additionally differ.
        try:
            store.read_report(source, now=as_of)
        except BrainError as exc:
            assert str(exc).startswith((
                "SOURCE_SHA_CHANGED:",
                "STATE_CORRUPT: report does not match deterministic ledger replay",
            )), "unexpected old-reader failure class"
        else:
            raise AssertionError("V5 incorrectly accepted a V6-source report")
        rollback = store.report(source, now=as_of)
        assert rollback["status"] == "PASS"
        assert store.read_report(source, now=as_of) == rollback
        print("V5_REPLAY_AFTER_V6=" + json.dumps({
            "source": source, "new_report": "PASS",
            "old_source_read_fail_closed": True,
            "sequence": rollback["state_sequence"],
            "canonical_hash": rollback["canonical_hash"],
        }, sort_keys=True))
    else:
        raise AssertionError("unknown rehearsal phase")
    assert tuple(store.db.execute(
        "SELECT body,hash FROM reports WHERE id=?", (original_id,)
    ).fetchone()) == before_original, "original V5 report was rewritten"
finally:
    store.close()
'''


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    )


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def verified_snapshot(path):
    path = Path(path)
    assert path.stat().st_size == ORIGINAL_BYTES, "source byte count drift"
    git = hashlib.sha1()
    git.update(f"blob {ORIGINAL_BYTES}\0".encode())
    raw = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            git.update(chunk)
            raw.update(chunk)
    assert git.hexdigest() == ORIGINAL_BLOB, "source blob SHA-1 mismatch"

    uri = "file:" + quote(str(path.resolve()), safe="/") + "?mode=ro&immutable=1"
    with sqlite3.connect(uri, uri=True) as db:
        db.row_factory = sqlite3.Row
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert dict(db.execute("SELECT key,value FROM meta")).get("schema_version") == "2"
        assert dict(db.execute("SELECT key,value FROM meta")).get("visibility") == "PUBLIC"
        rows = db.execute(
            "SELECT e.seq,e.id,e.body,e.hash,e.status,e.received_at,"
            "l.prev_hash,l.chain_hash FROM events e "
            "LEFT JOIN ledger l ON l.seq=e.seq ORDER BY e.seq"
        ).fetchall()
        assert rows, "empty original durable authority"
        assert db.execute("SELECT count(*) FROM ledger").fetchone()[0] == len(rows)
        assert db.execute("SELECT count(*) FROM events WHERE status='PENDING'").fetchone()[0] == 0
        watermark = db.execute(
            "SELECT seq FROM sqlite_sequence WHERE name='events'"
        ).fetchone()
        assert watermark is not None and watermark[0] == len(rows)
        from brain.core import validate_event
        previous = "0" * 64
        for i, row in enumerate(rows, 1):
            assert row["seq"] == i and row["status"] == "APPLIED"
            event = json.loads(row["body"])
            assert row["id"] == event["id"]
            assert row["hash"] == digest(event)
            validate_event(event, row["received_at"], legacy_replay=True)
            assert row["prev_hash"] == previous
            previous = digest({
                "seq": i, "event_hash": row["hash"], "previous": previous,
            })
            assert row["chain_hash"] == previous
        original = db.execute(
            "SELECT id,source_sha,seq,chain_hash,created_at,body,hash "
            "FROM reports ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert original and original["source_sha"] == V5_SHA, "not the original V5 authority"
        assert original["seq"] == len(rows) and original["chain_hash"] == previous
        assert original["hash"] == digest(json.loads(original["body"]))
        assert json.loads(original["body"])["status"] == "PASS"
        return {
            "sha256": raw.hexdigest(),
            "canonical_hash": previous,
            "events": len(rows),
            "old_report_id": original["id"],
            "as_of": original["created_at"],
            "old_report_body": original["body"],
            "old_report_hash": original["hash"],
        }


def run_git(args, *, cwd=None, timeout=150):
    process = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True,
        timeout=timeout, check=False,
    )
    assert process.returncode == 0, "pinned Git source acquisition failed"
    return process.stdout.strip()


def run_v5(old_checkout, phase, clone, as_of, old_report_id):
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(old_checkout)
    p = subprocess.run(
        [sys.executable, "-c", OLD_SOURCE_RUNNER, str(clone), V5_SHA,
         V6_SHA, phase, as_of, str(old_report_id)],
        cwd=old_checkout, env=environment,
        capture_output=True, text=True, timeout=120, check=False,
    )
    assert p.returncode == 0, "independent V5 historical reader/rollback replay failed"
    assert ("V5_BEFORE_ROLLBACK=" if phase == "before" else "V5_REPLAY_AFTER_V6=") in p.stdout
    return p.stdout.strip()


class FrozenRealStateRollbackRehearsal(unittest.TestCase):
    @unittest.skipUnless(
        os.environ.get("GITHUB_WORKFLOW") == "foundation-ci"
        and os.environ.get("GITHUB_EVENT_NAME") == "pull_request"
        and os.environ.get("GITHUB_REPOSITORY") == REPO,
        "one-off nonproduction GitHub Foundation CI rehearsal only",
    )
    def test_real_v5_state_forward_v6_backward_v5_forward_v6(self):
        root = Path(__file__).resolve().parents[1]
        for rel, expected in V6_CODE_BLOBS.items():
            actual = run_git(["hash-object", rel], cwd=root, timeout=15)
            self.assertEqual(actual, expected, "candidate implementation drift")

        with tempfile.TemporaryDirectory(prefix="brain-v6-rollback-only-") as tmp:
            base = Path(tmp)
            run_git(
                ["fetch", "--no-tags", "--depth=1", "origin", ORIGINAL_STATE_COMMIT],
                cwd=root,
            )
            self.assertEqual(
                run_git(["rev-parse", "FETCH_HEAD"], cwd=root, timeout=15),
                ORIGINAL_STATE_COMMIT,
            )
            immutable = base / "original-state.sqlite"
            with immutable.open("wb") as output:
                p = subprocess.run(
                    ["git", "show", "FETCH_HEAD:state.sqlite"],
                    cwd=root, stdout=output, stderr=subprocess.PIPE,
                    timeout=150, check=False,
                )
            self.assertEqual(p.returncode, 0, "pinned source object unavailable")

            original = verified_snapshot(immutable)
            self.assertTrue(original["events"] > 0)
            run_git(
                ["fetch", "--no-tags", "--depth=1", "origin", V5_SHA],
                cwd=root,
            )
            old_checkout = base / "v5-source"
            run_git(
                ["worktree", "add", "--detach", str(old_checkout), V5_SHA],
                cwd=root,
            )

            clone = base / "simulated-transition.sqlite"
            shutil.copyfile(immutable, clone)
            event_ledger_original = None
            try:
                with sqlite3.connect(clone) as db:
                    event_ledger_original = (
                        list(db.execute("SELECT seq,id,hash,status FROM events ORDER BY seq")),
                        list(db.execute("SELECT seq,prev_hash,chain_hash FROM ledger ORDER BY seq")),
                    )
                old_read = run_v5(
                    old_checkout, "before", clone, original["as_of"], original["old_report_id"]
                )
                from brain.core import Store
                store = Store(clone, visibility="PUBLIC")
                try:
                    v6_report = store.report(V6_SHA, now=original["as_of"])
                    self.assertEqual(v6_report["status"], "PASS")
                    self.assertEqual(
                        store.read_report(V6_SHA, now=original["as_of"]),
                        v6_report,
                    )
                    self.assertEqual(
                        v6_report["canonical_hash"], original["canonical_hash"]
                    )
                    compare_count = len(v6_report["repository_changes"])
                    aged = sum(
                        row["evidence_quality"] == "ACTUAL_STALE_BASELINE"
                        for row in v6_report["repository_changes"]
                    )
                finally:
                    store.close()

                v5_rollback = run_v5(
                    old_checkout, "after", clone, original["as_of"], original["old_report_id"]
                )
                store = Store(clone, visibility="PUBLIC")
                try:
                    with self.assertRaisesRegex(
                        Exception, "SOURCE_SHA_CHANGED|deterministic ledger replay"
                    ):
                        store.read_report(V6_SHA, now=original["as_of"])
                    restored_v6 = store.report(V6_SHA, now=original["as_of"])
                    self.assertEqual(
                        restored_v6,
                        store.read_report(V6_SHA, now=original["as_of"]),
                    )
                    self.assertEqual(
                        restored_v6["canonical_hash"], original["canonical_hash"]
                    )
                    self.assertEqual(restored_v6["state_sequence"], original["events"])
                    self.assertEqual(restored_v6["repository_changes"], v6_report["repository_changes"])
                    self.assertEqual(
                        tuple(store.db.execute(
                            "SELECT body,hash FROM reports WHERE id=?",
                            (original["old_report_id"],),
                        ).fetchone()),
                        (original["old_report_body"], original["old_report_hash"]),
                    )
                    self.assertEqual(
                        list(store.db.execute("SELECT seq,id,hash,status FROM events ORDER BY seq")),
                        event_ledger_original[0],
                    )
                    self.assertEqual(
                        list(store.db.execute("SELECT seq,prev_hash,chain_hash FROM ledger ORDER BY seq")),
                        event_ledger_original[1],
                    )
                    stored_sources = [
                        x[0] for x in store.db.execute(
                            "SELECT source_sha FROM reports WHERE id>=? ORDER BY id",
                            (original["old_report_id"],),
                        )
                    ]
                    self.assertEqual(stored_sources, [V5_SHA, V6_SHA, V5_SHA, V6_SHA])
                finally:
                    store.close()
                self.assertEqual(verified_snapshot(immutable)["sha256"], original["sha256"])
                print("BRAIN_V6_V5_ROLLBACK_REHEARSAL=" + canonical({
                    "source_commit": ORIGINAL_STATE_COMMIT,
                    "git_blob_sha1": ORIGINAL_BLOB,
                    "original_raw_sha256": original["sha256"],
                    "bytes": ORIGINAL_BYTES,
                    "canonical_events": original["events"],
                    "canonical_hash": original["canonical_hash"],
                    "v5_original_read": "PASS",
                    "v6_forward_replay": "PASS",
                    "v5_fail_closed_then_rebuild": "PASS",
                    "v6_repeat_forward_replay": "PASS",
                    "preserved_original_report": True,
                    "preserved_events_ledger": True,
                    "original_binary_unchanged": True,
                    "repository_comparisons": compare_count,
                    "stale_baselines_in_actual_snapshot": aged,
                    "production_accepted": False,
                    "production_written": False,
                }), flush=True)
                self.assertIn("V5_BEFORE_ROLLBACK=", old_read)
                self.assertIn("V5_REPLAY_AFTER_V6=", v5_rollback)
            finally:
                run_git(
                    ["worktree", "remove", "--force", str(old_checkout)],
                    cwd=root, timeout=30,
                )


if __name__ == "__main__":
    unittest.main()
