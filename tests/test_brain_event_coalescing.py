"""Unchanged-source state suppression must preserve immutable historical facts."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from brain.core import Store, BrainError
from brain.adapters import event
from brain.state_archive import pack, restore
from tests.test_brain_v2 import SHA, NOW, REPOSITORY, payload


class BoundedObservationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.store = Store(self.root / "state.sqlite", visibility="PUBLIC")
        self.addCleanup(self.store.close)

    def observe(self, at, data=None, source=SHA, window=21600):
        item = event("repository", REPOSITORY,
                     payload() if data is None else data, source, now=at)
        self.store.submit([item], now=at, coalesce_seconds=window)
        self.store.drain()

    def count(self):
        return self.store.db.execute("SELECT count(*) FROM events").fetchone()[0]

    def test_unchanged_samples_coalesce_without_refreshing_source_time(self):
        self.observe(NOW)
        self.observe("2026-10-07T22:00:00Z")
        self.assertEqual(self.count(), 1)
        self.assertEqual(self.store.coalesced_events, 1)
        self.assertEqual(self.store._verified_events()[1], 1)
        body = self.store.db.execute("SELECT body FROM events").fetchone()[0]
        self.assertIn(NOW, body)
        self.assertNotIn("22:00:00", body)

    def test_changed_data_never_suppressed_and_latest_change_wins(self):
        self.observe(NOW)
        changed = dict(payload(), open_issues=4)
        self.observe("2026-10-07T21:30:00Z", changed)
        self.observe("2026-10-07T21:31:00Z")
        self.assertEqual(self.count(), 3)

    def test_rolled_back_batch_does_not_credit_suppressed_observations(self):
        self.observe(NOW)
        same = event("repository", REPOSITORY, payload(), SHA,
                     now="2026-10-07T21:30:00Z")
        conflicting = event("repository", REPOSITORY,
                            dict(payload(), open_issues=4), SHA, now=NOW)
        with self.assertRaisesRegex(BrainError, "AMBIGUOUS_OBSERVATION"):
            self.store.submit([same, conflicting],
                              now="2026-10-07T21:30:00Z",
                              coalesce_seconds=21600)
        self.assertEqual(self.store.coalesced_events, 0)
        self.assertEqual(self.count(), 1)

    def test_source_change_and_six_hour_expiry_preserve_updates(self):
        self.observe(NOW)
        self.observe("2026-10-07T21:15:00Z", source="b"*40)
        self.observe("2026-10-08T03:16:00Z", source="b"*40)
        self.assertEqual(self.count(), 3)

    def test_default_behavior_remains_append_only(self):
        self.observe(NOW, window=0)
        self.observe("2026-10-07T21:01:00Z", window=0)
        self.assertEqual(self.count(), 2)

    def test_user_feedback_never_coalesced(self):
        self.assertNotIn("feedback", {"repository", "candidate", "experiment"})

    def test_archive_roundtrip_keeps_exact_canonical_chain(self):
        self.observe(NOW)
        self.observe("2026-10-07T21:01:00Z")
        old = self.store._verified_events()
        self.store.close()
        self.addCleanup(lambda: None)
        archive_root = self.root / "archive"
        archive_root.mkdir()
        (archive_root / "state.sqlite").write_bytes(
            (self.root / "state.sqlite").read_bytes())
        packed = pack(archive_root)
        self.assertFalse((archive_root / "state.sqlite").exists())
        restored = restore(archive_root)
        self.assertEqual(restored["raw_sha256"], packed["raw_sha256"])
        with sqlite3.connect(archive_root / "state.sqlite") as db:
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone(), ("ok",))
        replay = Store(archive_root / "state.sqlite", visibility="PUBLIC")
        try:
            self.assertEqual(replay._verified_events(), old)
        finally:
            replay.close()

    def test_reject_unbounded_suppression_window(self):
        with self.assertRaisesRegex(ValueError, "COALESCE_WINDOW_INVALID"):
            self.observe(NOW, window=21601)


if __name__ == "__main__":
    unittest.main()
