"""One-off V6 versus immutable V5 production-state compatibility audit.

AUDIT ONLY / DO NOT MERGE. A GitHub Foundation pull-request runner downloads
a pinned original Git state snapshot, validates the raw immutable bytes and
ledger, and tests V6 replay/migration exclusively on a disposable local copy.
Never write to live state, main, provider, scheduler, or acceptance records.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
from urllib.parse import quote

STATE_COMMIT = "f914e7e53586bfca035d313b4d30126891ceac86"
STATE_BLOB = "ed263b9bc5271d9fb61bb6736e110a1c9ddc38e2"
STATE_BYTES = 42897408
SOURCE_SHA = "3fb0bb0dcc28f961033d782260c31f36ed78eb71"
ASSEMBLED_V6_SHA = "9d91e79981cfe229fb6615cabeda71ed29f64d2d"
GITHUB_REPO = "P00NSMASHER/portfolio-brain"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def verify_snapshot(path):
    """Verify actual raw SQLite bytes using a new read-only connection."""
    data = Path(path).read_bytes()
    assert len(data) == STATE_BYTES, "raw state byte count mismatched"
    git_sha = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\x00" + data).hexdigest()
    assert git_sha == STATE_BLOB, "original Git blob digest mismatched"
    sha256 = hashlib.sha256(data).hexdigest()

    uri = "file:" + quote(str(Path(path).resolve()), safe="/") + "?mode=ro&immutable=1"
    with sqlite3.connect(uri, uri=True) as db:
        db.row_factory = sqlite3.Row
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok", "integrity_check failed"
        assert db.execute("PRAGMA foreign_key_check").fetchall() == [], "foreign key violation"
        meta = dict(db.execute("SELECT key,value FROM meta"))
        assert meta.get("schema_version") == "2" and meta.get("visibility") == "PUBLIC", "state schema or visibility changed"

        rows = db.execute("SELECT e.seq,e.id,e.body,e.hash,e.status,e.received_at,"
                          "l.prev_hash,l.chain_hash FROM events e LEFT JOIN ledger l ON l.seq=e.seq "
                          "ORDER BY e.seq").fetchall()
        assert rows, "empty state unexpectedly"
        assert db.execute("SELECT count(*) FROM ledger").fetchone()[0] == len(rows), "orphan/missing ledger"
        assert db.execute("SELECT count(*) FROM events WHERE status='PENDING'").fetchone()[0] == 0, "pending events"
        watermark = db.execute("SELECT seq FROM sqlite_sequence WHERE name='events'").fetchone()
        assert watermark and watermark[0] == len(rows), "deleted event tail"

        previous = "0" * 64
        events = []
        from brain.core import validate_event, analyze_events
        for index, row in enumerate(rows, 1):
            assert row["seq"] == index and row["status"] == "APPLIED", "event gap/unapplied"
            event = json.loads(row["body"])
            assert row["id"] == event["id"], "durable ID mismatch"
            assert row["hash"] == digest(event), "event digest mismatch"
            validate_event(event, row["received_at"], legacy_replay=True)
            assert row["prev_hash"] == previous, "ledger chain parent mismatch"
            previous = digest({"seq":index, "event_hash":row["hash"], "previous":previous})
            assert row["chain_hash"] == previous, "ledger chain digest mismatch"
            events.append(event)

        report_row = db.execute("SELECT * FROM reports ORDER BY id DESC LIMIT 1").fetchone()
        assert report_row is not None, "no durable report"
        report = json.loads(report_row["body"])
        assert digest(report) == report_row["hash"], "report digest mismatch"
        assert report_row["seq"] == len(rows), "stale report sequence"
        assert report_row["chain_hash"] == previous, "stale report chain"
        assert report_row["source_sha"] == SOURCE_SHA, "report bound to another source"
        rebuilt = analyze_events(events, now=report_row["created_at"], max_age=172800)
        rebuilt.update(source_sha=report_row["source_sha"], state_sequence=report_row["seq"],
                       canonical_hash=report_row["chain_hash"], pending_events=0,
                       generated_at=report_row["created_at"])
        assert rebuilt == report and report["status"] == "PASS", (
            "V6_REPLAY_DRIFT: existing V5 report does not match V6 projection"
        )
        assert report["canonical_hash"] == previous and report["state_sequence"] == len(rows)

        # No mutation is possible through the original read-only/immutable
        # connection. Exercise Store's real report API ONLY on a throwaway
        # independently copied database, never against the source snapshot.
        with tempfile.TemporaryDirectory(prefix="brain-v6-disposable-db-") as staging:
            duplicate = Path(staging) / "disposable.sqlite"
            shutil.copyfile(path, duplicate)
            from brain.core import Store
            store = Store(duplicate, visibility="PUBLIC")
            try:
                legacy = store.read_report(SOURCE_SHA, now=report_row["created_at"])
                assert legacy == report, "V6_READER_DRIFT: V5 report rejected"
                # The V6 candidate source has NOT been promoted; this is a
                # simulated projection only. Real scheduled cycles must
                # establish any future V6 production acceptance.
                candidate = store.report(
                    ASSEMBLED_V6_SHA, now=report_row["created_at"]
                )
                assert candidate["status"] == "PASS", "V6_REPORT_BLOCKED"
                assert candidate["state_sequence"] == len(rows)
                assert candidate["canonical_hash"] == previous
                persisted = store.read_report(
                    ASSEMBLED_V6_SHA, now=report_row["created_at"]
                )
                assert persisted == candidate, "V6_NEW_REPORT_REPLAY_DRIFT"
                assert candidate["repository_changes"] == report["repository_changes"], (
                    "V6_LIVE_SNAPSHOT_COMPARISON_DRIFT"
                )
                changed = len(candidate["repository_changes"])
                stale_baselines = sum(
                    item["evidence_quality"] == "ACTUAL_STALE_BASELINE"
                    for item in candidate["repository_changes"]
                )
            finally:
                store.close()
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == sha256, (
            "original immutable snapshot bytes changed"
        )
        return {"snapshot_commit":STATE_COMMIT,"git_blob_sha1":git_sha,"raw_sha256":sha256,
                "size":len(data),"source_sha":SOURCE_SHA,"events":len(rows),
                "canonical_hash":previous,"pending":0,"sqlite_integrity":"PASS",
                "foreign_keys":"PASS","canonical_ledger":"PASS","v5_report_replay_under_v6":"PASS",
                "v6_disposable_report_replay":"PASS","comparisons":changed,
                "stale_baselines_in_frozen_snapshot":stale_baselines,
                "v6_candidate_sha":ASSEMBLED_V6_SHA,
                "production_accepted":False}


class PinnedIndependentV6StateCompat(unittest.TestCase):
    @unittest.skipUnless(
        os.getenv("GITHUB_WORKFLOW") == "foundation-ci"
        and os.getenv("GITHUB_EVENT_NAME") == "pull_request"
        and os.getenv("GITHUB_REPOSITORY") == GITHUB_REPO,
        "one-off Foundation PR audit only (never scheduled production)",
    )
    def test_original_v5_state_replays_under_v6_without_mutation(self):
        with tempfile.TemporaryDirectory(prefix="brain-v6-compat-audit-") as tmp:
            proc = subprocess.run(
                ["git", "fetch", "--no-tags", "--depth=1", "origin", STATE_COMMIT],
                capture_output=True, text=True, timeout=120, check=False)
            self.assertEqual(proc.returncode, 0, "pinned historical state fetch failed")
            pinned = subprocess.run(["git", "rev-parse", "FETCH_HEAD"], capture_output=True,
                                    text=True, timeout=10, check=True).stdout.strip()
            self.assertEqual(pinned, STATE_COMMIT)
            path = Path(tmp) / "readonly_state.sqlite"
            with path.open("wb") as out:
                proc = subprocess.run(["git", "show", "FETCH_HEAD:state.sqlite"], stdout=out,
                                      stderr=subprocess.PIPE, timeout=120, check=False)
            self.assertEqual(proc.returncode, 0, "original raw SQLite extraction failed")
            receipt = verify_snapshot(path)
            print("BRAIN_V6_ORIGINAL_STATE_COMPAT=" + canonical(receipt), flush=True)
            self.assertTrue(receipt["events"] > 0)


if __name__ == "__main__":
    unittest.main()
