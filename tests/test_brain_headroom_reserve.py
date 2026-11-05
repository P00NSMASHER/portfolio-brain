"""Lossless canonical-state safeguards for low verified raw headroom.

Only recomputable PASS report copies are eligible for shorter retention.
Original events, attempts, ledger, latest-per-source and every non-PASS
report remain unmodified, with historical Git state snapshots preserved.
"""
import hashlib
import json
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

from brain.core import digest
from brain import state_maintenance as maint
from tests import test_brain_soak_v3 as fixtures


class HeadroomReserveTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.StateTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.source = self.fixture.path
        with sqlite3.connect(self.source) as db:
            for ident in range(2, 161):
                body = {"status": "FAIL" if ident in (3, 90) else "PASS",
                        "detail": "derived" * 210, "identifier": ident}
                db.execute(
                    "INSERT INTO reports VALUES(?,?,?,?,?,?,?)",
                    (ident, 1, self.fixture.chain, fixtures.SHA,
                     "2026-10-08T02:00:00Z", json.dumps(body), digest(body)),
                )

    def snapshot(self):
        with sqlite3.connect(self.source) as db:
            return {
                "failures": db.execute(
                    "SELECT id FROM reports WHERE json_extract(body,'$.status') != 'PASS'"
                    " ORDER BY id"
                ).fetchall(),
                "events": db.execute("SELECT * FROM events").fetchall(),
                "ledger": db.execute("SELECT * FROM ledger").fetchall(),
                "attempts": (db.execute("SELECT * FROM attempts").fetchall()
                             if db.execute("SELECT 1 FROM sqlite_schema WHERE type='table' AND name='attempts'").fetchone()
                             else []),
            }

    def compact_at_headroom(self, headroom):
        size = self.source.stat().st_size
        return maint.maintain_within_verified_capacity(
            self.source, trigger_bytes=1, verified_raw_bytes=size + headroom,
            keep_recent=128,
        )

    def test_low_headroom_compacts_more_pass_reports_preserving_original_proofs(self):
        before = self.snapshot()
        result = self.compact_at_headroom(12 * 1024 * 1024)
        after = self.snapshot()
        self.assertTrue(result["compacted"])
        self.assertEqual(result["retained_recent_report_target"], 64)
        self.assertIn("VERIFIED_RAW_HEADROOM_RESERVE", result["compaction_reasons"])
        self.assertEqual(before, after)
        with sqlite3.connect(self.source) as db:
            ids = [x[0] for x in db.execute("SELECT id FROM reports ORDER BY id")]
            self.assertIn(3, ids)  # Historical failure never discarded.
            self.assertIn(90, ids)  # Newer failure never discarded.
            self.assertIn(160, ids)  # Latest per source remains.
            self.assertNotIn(20, ids)  # Only old redundant PASS copies removed.
            self.assertGreaterEqual(len(ids), 64)
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_low_compressed_headroom_selects_64_without_falsifying_history(self):
        before = self.snapshot()
        source_hash = hashlib.sha256(self.source.read_bytes()).hexdigest()
        # Exercise measured compressed pressure without changing the original
        # durable image or weakening source/ledger integrity checks.
        with patch.object(
            maint, 'COMPACTION_TRIGGER_COMPRESSED_BYTES', 1
        ), patch.object(
            maint, 'COMPRESSED_HEADROOM_RETENTION_TRIGGER_BYTES',
            maint.VERIFIED_PRODUCTION_COMPRESSED_BYTES + 1
        ):
            result = maint.maintain_within_verified_capacity(self.source)
        self.assertTrue(result['compacted'])
        self.assertEqual(result['retained_recent_report_target'], 64)
        self.assertIn('VERIFIED_COMPRESSED_HEADROOM_RESERVE',
                      result['compaction_reasons'])
        self.assertEqual(self.snapshot(), before)
        self.assertGreater(result['reclaimed_raw_bytes'], 0)
        self.assertGreaterEqual(result['reclaimed_compressed_bytes'], 0)
        self.assertNotEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(),
                            source_hash)
        with sqlite3.connect(self.source) as db:
            old_failures = [x[0] for x in db.execute(
                "SELECT id FROM reports WHERE json_extract(body,'$.status')!='PASS'"
            )]
            self.assertIn(3, old_failures)
            self.assertIn(90, old_failures)
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')

    def test_normal_headroom_preserves_existing_128_recent_reports(self):
        self.compact_at_headroom(18 * 1024 * 1024)
        with sqlite3.connect(self.source) as db:
            ids = {row[0] for row in db.execute("SELECT id FROM reports")}
        self.assertIn(33, ids)
        self.assertIn(160, ids)
        self.assertNotIn(20, ids)

    def test_exact_threshold_does_not_narrow_retention(self):
        result = self.compact_at_headroom(16 * 1024 * 1024)
        self.assertEqual(result["retained_recent_report_target"], 128)
        self.assertNotIn("VERIFIED_RAW_HEADROOM_RESERVE", result["compaction_reasons"])

    def test_explicit_stricter_owner_retention_not_relaxed(self):
        size = self.source.stat().st_size
        result = maint.maintain_within_verified_capacity(
            self.source, trigger_bytes=1, verified_raw_bytes=size + 12 * 1024 * 1024,
            keep_recent=16,
        )
        self.assertEqual(result["retained_recent_report_target"], 16)
        self.assertNotIn("VERIFIED_RAW_HEADROOM_RESERVE", result["compaction_reasons"])

    def test_invalid_raw_bound_fails_without_touching_original_source(self):
        original = hashlib.sha256(self.source.read_bytes()).hexdigest()
        with self.assertRaises(ValueError):
            maint.maintain_within_verified_capacity(
                self.source, trigger_bytes=1, verified_raw_bytes=2, keep_recent=128,
            )
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), original)
        self.assertEqual(list(self.source.parent.glob(".capacity-*.sqlite")), [])


if __name__ == "__main__":
    unittest.main()
