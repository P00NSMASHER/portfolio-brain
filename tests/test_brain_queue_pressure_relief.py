"""Source-bounded queue pressure fixes; never lose genuine repair work."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zlib

from brain.core import digest
from brain.v9.batch_queue import BatchFault, BatchQueue, PROJECTS


START = datetime(2026, 10, 31, 12, tzinfo=timezone.utc)


def tick(n):
    return (START + timedelta(seconds=n)).isoformat(timespec="seconds").replace("+00:00", "Z")


def candidate(number, *, project="research-labs", priority=3, fingerprint=None):
    return dict(
        project_id=project, repository=PROJECTS[project], owner="research-provenance",
        source_sha=f"{number:040x}",
        fingerprint=fingerprint or digest({"distinct_issue": number}),
        path="repository-observation", priority=priority,
    )


class PressureReliefTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "batch.sqlite"
        self.max_work = patch("brain.v9.batch_queue.MAX_WORK", 8)
        self.max_work.start()
        self.queue = BatchQueue(self.db)

    def tearDown(self):
        self.queue.close()
        self.max_work.stop()
        self.temp.cleanup()

    def seed(self, *, n=7, priority=3):
        return [self.queue.observe(candidate(i + 1, priority=priority), now=tick(i))
                for i in range(n)]

    def test_archives_distinct_clean_old_heads_before_saturation(self):
        ids = self.seed()
        result = self.queue.observe(candidate(9), now=tick(9))
        snapshot = self.queue.snapshot()["work"]
        self.assertEqual(set(snapshot), {result})
        self.assertEqual(len(snapshot), 1)
        archived = self.queue.db.execute(
            "SELECT body FROM batch_archive ORDER BY slot"
        ).fetchall()
        self.assertEqual(len(archived), 1)
        raw = zlib.decompress(archived[0][0])
        history = json.loads(raw)
        self.assertEqual(set(history["retired"]), set(ids))
        self.assertEqual(len(history["events"]), 7)
        checkpoint = self.queue.checkpoint()
        self.assertEqual(checkpoint["sequence"], 8)
        self.queue.close()
        self.queue = BatchQueue(self.db)
        self.assertEqual(self.queue.checkpoint(), checkpoint)
        self.assertEqual(set(self.queue.snapshot()["work"]), {result})

    def test_inconclusive_unclaimed_source_is_reobserved_without_erasing_history(self):
        ids = self.seed(priority=2)
        fresh = self.queue.observe(candidate(9, priority=2), now=tick(9))
        self.assertEqual(set(self.queue.snapshot()["work"]), {fresh})
        archived = self.queue.db.execute("SELECT body FROM batch_archive").fetchone()[0]
        self.assertEqual(set(json.loads(zlib.decompress(archived))["retired"]), set(ids))
        self.assertEqual(self.queue.checkpoint()["sequence"], 8)

    def test_claimed_diagnosed_and_evidenced_rows_never_retired(self):
        ids = self.seed()
        token = self.queue.claim(ids[0], "research-provenance", now=tick(7))
        self.queue.advance(ids[0], token, "DIAGNOSED", evidence_sha="a" * 64,
                           now=tick(8))
        fresh = self.queue.observe(candidate(9), now=tick(9))
        survivors = self.queue.snapshot()["work"]
        self.assertEqual(set(survivors), {ids[0], fresh})
        self.assertEqual(survivors[ids[0]]["stage"], "DIAGNOSED")
        self.assertEqual(survivors[ids[0]]["evidence"], ["a" * 64])
        self.assertIsNotNone(survivors[ids[0]]["claim"])

    def test_adverse_observations_with_distinct_evidence_cannot_disappear(self):
        ids = self.seed(priority=1)
        item8 = self.queue.observe(candidate(8, priority=1), now=tick(8))
        checkpoint = self.queue.checkpoint()
        with self.assertRaisesRegex(BatchFault, "WORK_CAPACITY_RECONCILIATION_REQUIRED"):
            self.queue.observe(candidate(9, priority=1), now=tick(9))
        self.assertEqual(self.queue.checkpoint(), checkpoint)
        self.assertEqual(set(self.queue.snapshot()["work"]), set(ids) | {item8})

    def test_other_project_cannot_consume_retirement_budget(self):
        ids = self.seed()
        # Unrelated project is not an exact, source-replaced research observation.
        extra = self.queue.observe(candidate(9, project="portfolio-brain"),
                                   now=tick(9))
        self.assertEqual(set(self.queue.snapshot()["work"]), set(ids) | {extra})
        with self.assertRaisesRegex(BatchFault, "WORK_CAPACITY_RECONCILIATION_REQUIRED"):
            self.queue.observe(candidate(10, project="abvm"), now=tick(10))

    def test_original_matching_fingerprint_is_still_retired_safely(self):
        original = self.queue.observe(candidate(1, priority=1), now=tick(1))
        for i in range(2, 8):
            self.queue.observe(candidate(i, priority=1), now=tick(i))
        duplicate_semantics = candidate(9, priority=1,
                                        fingerprint=digest({"distinct_issue": 1}))
        result = self.queue.observe(duplicate_semantics, now=tick(9))
        self.assertNotIn(original, self.queue.snapshot()["work"])
        self.assertIn(result, self.queue.snapshot()["work"])

    def test_archive_write_cap_failure_is_rollback_not_silent_loss(self):
        ids = self.seed()
        before = self.queue.checkpoint()
        with patch("brain.v9.batch_queue.MAX_ARCHIVE_SEGMENTS", 0):
            with self.assertRaisesRegex(BatchFault,
                                        "ARCHIVE_CAPACITY_RECONCILIATION_REQUIRED"):
                self.queue.observe(candidate(9), now=tick(9))
        self.assertEqual(before, self.queue.checkpoint())
        self.assertEqual(set(ids), set(self.queue.snapshot()["work"]))


if __name__ == "__main__":
    unittest.main()
