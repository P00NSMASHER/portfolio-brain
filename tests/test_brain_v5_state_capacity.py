"""V5-only SQLite capacity checks: original-byte replay, never acceptance.

All SQLite files here are synthetic. Even a passing 28+ MB local replay
does not authenticate a provider state commit or establish six-hour V5 PASS.
"""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from soak_v3.audit import (
    EvidenceError, V3_SQLITE_MAX_BYTES, V5_SQLITE_MAX_BYTES,
    digest, verify_sqlite, verify_v5_sqlite,
)

SOURCE = "a" * 40
OTHER_SOURCE = "f" * 40
DATE = "2026-10-10T21:54:28Z"


class V5SQLiteCapacityTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="brain-v5-state-cap-")
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)
        self.path = self.folder / "state.sqlite"
        db = sqlite3.connect(self.path)
        try:
            db.executescript("""
                CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE events(
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    id TEXT UNIQUE NOT NULL,
                    body TEXT NOT NULL,
                    hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    received_at TEXT NOT NULL
                );
                CREATE TABLE ledger(
                    seq INTEGER PRIMARY KEY,
                    prev_hash TEXT NOT NULL,
                    chain_hash TEXT NOT NULL
                );
                CREATE TABLE reports(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    seq INTEGER NOT NULL,
                    chain_hash TEXT NOT NULL,
                    source_sha TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    body TEXT NOT NULL,
                    hash TEXT NOT NULL
                );
            """)
            db.execute("INSERT INTO meta VALUES('schema_version','2')")
            db.execute("INSERT INTO meta VALUES('visibility','PUBLIC')")
            observed = {
                "id": "repository:test", "visibility": "PUBLIC",
                "kind": "repository", "key": "test", "source_sha": SOURCE,
                "observed_at": DATE, "data_kind": "ACTUAL", "payload": {},
            }
            observed_hash = digest(observed)
            self.chain = digest({
                "seq": 1, "event_hash": observed_hash, "previous": "0" * 64
            })
            db.execute(
                "INSERT INTO events VALUES(?,?,?,?,?,?)",
                (1, observed["id"], json.dumps(observed), observed_hash,
                 "APPLIED", DATE),
            )
            db.execute(
                "INSERT INTO ledger VALUES(?,?,?)", (1, "0" * 64, self.chain)
            )
            report = {
                "status": "PASS", "source_sha": SOURCE, "pending_events": 0,
                "state_sequence": 1, "canonical_hash": self.chain,
            }
            db.execute(
                "INSERT INTO reports VALUES(?,?,?,?,?,?,?)",
                (1, 1, self.chain, SOURCE, DATE,
                 json.dumps(report), digest(report)),
            )
            db.commit()
        finally:
            db.close()

    def grow_to_v5_size(self):
        # Genuine October 10 state was 28,778,496 bytes. A real >25 MB
        # SQLite page allocation, not a sparse invalid file, exercises the
        # same checksum, integrity, event-chain and report replay as V3.
        db = sqlite3.connect(self.path)
        try:
            db.execute("CREATE TABLE synthetic_padding(payload BLOB NOT NULL)")
            db.execute(
                "INSERT INTO synthetic_padding VALUES(zeroblob(?))",
                (28_700_000,),
            )
            db.commit()
        finally:
            db.close()
        size = self.path.stat().st_size
        self.assertGreater(size, V3_SQLITE_MAX_BYTES)
        self.assertLess(size, V5_SQLITE_MAX_BYTES)
        self.assertGreater(size, 28_000_000)
        return size

    def kwargs(self):
        return {
            "expected_sequence": 1,
            "expected_chain": self.chain,
            "expected_source": SOURCE,
        }

    def test_small_valid_state_remains_compatible_with_v3_and_v5(self):
        self.assertEqual(verify_sqlite(self.path, **self.kwargs())["status"], "PASS")
        self.assertEqual(verify_v5_sqlite(self.path, **self.kwargs())["status"], "PASS")
        self.assertEqual(V3_SQLITE_MAX_BYTES, 25_000_000)
        self.assertEqual(V5_SQLITE_MAX_BYTES, 64_000_000)

    def test_real_sized_sqlite_passes_only_the_bounded_v5_reader(self):
        size = self.grow_to_v5_size()
        with self.assertRaisesRegex(EvidenceError, "STATE_SIZE_INVALID"):
            verify_sqlite(self.path, **self.kwargs())
        original = self.path.read_bytes()
        original_sha = hashlib.sha256(original).hexdigest()
        original_mtime = self.path.stat().st_mtime_ns
        result = verify_v5_sqlite(self.path, **self.kwargs())
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["sha256"], original_sha)
        self.assertEqual(result["sequence"], 1)
        self.assertEqual(result["canonical_hash"], self.chain)
        self.assertEqual(result["source_sha"], SOURCE)
        self.assertEqual(result["pending_events"], 0)
        self.assertEqual(self.path.stat().st_size, size)
        self.assertEqual(self.path.stat().st_mtime_ns, original_mtime)

    def test_over_v5_limit_is_rejected_before_file_open(self):
        sparse = self.folder / "too-large.sqlite"
        with sparse.open("wb") as target:
            target.truncate(V5_SQLITE_MAX_BYTES + 1)
        with patch.object(
            Path, "open", side_effect=AssertionError("unbounded file was read")
        ):
            with self.assertRaisesRegex(EvidenceError, "STATE_SIZE_INVALID"):
                verify_v5_sqlite(sparse, **self.kwargs())

    def test_changed_size_between_stat_and_read_fails_closed(self):
        # The integrity checker must not parse bytes different in size from
        # the file it measured before opening.
        with patch.object(Path, "open", return_value=io.BytesIO(b"short")):
            with self.assertRaisesRegex(
                EvidenceError, "STATE_SIZE_CHANGED_DURING_READ"
            ):
                verify_v5_sqlite(self.path, **self.kwargs())

    def test_v5_source_binding_cannot_be_relabelled(self):
        self.grow_to_v5_size()
        altered = dict(self.kwargs(), expected_source=OTHER_SOURCE)
        with self.assertRaisesRegex(EvidenceError, "STATE_REPORT_SOURCE_INVALID"):
            verify_v5_sqlite(self.path, **altered)

    def test_v5_broken_ledger_remains_invalid_even_under_larger_limit(self):
        self.grow_to_v5_size()
        db = sqlite3.connect(self.path)
        try:
            db.execute("UPDATE ledger SET chain_hash=?", ("e" * 64,))
            db.commit()
        finally:
            db.close()
        with self.assertRaisesRegex(EvidenceError, "STATE_CHAIN_DIGEST_INVALID"):
            verify_v5_sqlite(self.path, **self.kwargs())

    def test_v5_pending_events_remain_disqualifying(self):
        self.grow_to_v5_size()
        db = sqlite3.connect(self.path)
        try:
            db.execute("UPDATE events SET status='PENDING'")
            db.commit()
        finally:
            db.close()
        with self.assertRaisesRegex(EvidenceError, "STATE_PENDING_EVENTS"):
            verify_v5_sqlite(self.path, **self.kwargs())

    def test_v5_cli_is_read_only_and_never_terminal_acceptance(self):
        self.grow_to_v5_size()
        before_hash = hashlib.sha256(self.path.read_bytes()).hexdigest()
        manifest = self.folder / "state-manifest.json"
        manifest.write_text(json.dumps({
            "path": str(self.path), "source_sha": SOURCE,
            "state_sequence": 1, "canonical_hash": self.chain,
        }))
        command = [
            sys.executable, "-m", "soak_v3", "state-v5",
            "--manifest", str(manifest),
        ]
        result = subprocess.run(command, capture_output=True, text=True, timeout=45)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        receipt = json.loads(result.stdout)
        self.assertEqual(receipt["scope"], "NONAUTHORITATIVE_EVIDENCE_INSPECTION")
        self.assertEqual(receipt["result"]["status"], "PASS")
        self.assertEqual(receipt["result"]["sha256"], before_hash)
        self.assertNotIn("production_accepted", receipt["result"])
        self.assertNotIn("soak_completed", receipt["result"])
        legacy = list(command)
        legacy[3] = "state"
        old = subprocess.run(legacy, capture_output=True, text=True, timeout=45)
        self.assertEqual(old.returncode, 1)
        self.assertEqual(json.loads(old.stdout)["status"], "BLOCKED")
        self.assertIn("STATE_SIZE_INVALID", old.stdout)
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(),
                         before_hash)


if __name__ == "__main__":
    unittest.main()
