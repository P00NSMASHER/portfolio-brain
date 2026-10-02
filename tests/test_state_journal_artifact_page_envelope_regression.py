"""Regression coverage for page-envelope ordering in artifact scans."""
import unittest
from datetime import datetime, timezone

from state_journal.transport import GitHubReader


def artifact(artifact_id: int, created_at: str) -> dict:
    return {"id": artifact_id, "created_at": created_at}


class ArtifactPageEnvelopeRegressionTests(unittest.TestCase):
    def _reader(self, pages):
        reader = object.__new__(GitHubReader)
        calls = []

        def get(suffix):
            calls.append(suffix)
            page = int(suffix.rsplit("=", 1)[1])
            return {"artifacts": pages.get(page, [])}

        reader.get = get
        return reader, calls

    def test_within_page_jitter_preserves_monotonic_page_envelope_proof(self):
        page1 = [
            artifact(1, "2026-10-02T12:30:00Z"),
            artifact(2, "2026-10-02T12:28:00Z"),
            artifact(3, "2026-10-02T12:29:00Z"),
        ] + [
            artifact(10 + index, "2026-10-02T12:28:30Z")
            for index in range(97)
        ]
        page2 = [
            artifact(200, "2026-10-02T12:27:00Z"),
            artifact(201, "2026-10-02T12:25:00Z"),
            artifact(202, "2026-10-02T12:26:00Z"),
        ] + [
            artifact(210 + index, "2026-10-02T12:25:30Z")
            for index in range(97)
        ]
        reader, calls = self._reader({1: page1, 2: page2})
        rows, complete, ordering_proven, oldest = reader._scan_recent_artifacts(
            "2026-10-02T10:00:00Z", max_pages=2
        )
        self.assertFalse(complete)
        self.assertTrue(ordering_proven)
        self.assertEqual(oldest, datetime(2026, 10, 2, 12, 25, tzinfo=timezone.utc))
        self.assertEqual(len(rows), 200)
        self.assertEqual(len(calls), 2)


    def test_duplicate_offset_drift_does_not_create_false_page_inversion(self):
        page1 = [
            artifact(1 + index, f"2026-10-02T12:{59-index//2:02d}:{30 if index % 2 else 0:02d}Z")
            for index in range(100)
        ]
        # Simulate ten new artifacts arriving between page requests: the next
        # offset page repeats the tail of page 1, then continues with older rows.
        duplicates = page1[-10:]
        page2 = duplicates + [
            artifact(1000 + index, "2026-10-02T11:55:00Z")
            for index in range(90)
        ]
        reader, _ = self._reader({1: page1, 2: page2})
        rows, complete, ordering_proven, _ = reader._scan_recent_artifacts(
            "2026-10-02T10:00:00Z", max_pages=2
        )
        self.assertFalse(complete)
        self.assertTrue(ordering_proven)
        self.assertEqual(len(rows), 190)

    def test_unseen_cross_page_inversion_still_fails_closed(self):
        page1 = [
            artifact(1 + index, "2026-10-02T12:28:00Z")
            for index in range(100)
        ]
        page2 = [
            artifact(9999, "2026-10-02T12:29:00Z"),
        ] + [
            artifact(201 + index, "2026-10-02T12:27:00Z")
            for index in range(99)
        ]
        reader, _ = self._reader({1: page1, 2: page2})
        _, complete, ordering_proven, _ = reader._scan_recent_artifacts(
            "2026-10-02T10:00:00Z", max_pages=2
        )
        self.assertFalse(complete)
        self.assertFalse(ordering_proven)

    def test_cross_page_envelope_inversion_remains_fail_closed(self):
        page1 = [
            artifact(1 + index, "2026-10-02T12:28:00Z")
            for index in range(100)
        ]
        page2 = [
            artifact(200, "2026-10-02T12:29:00Z"),
        ] + [
            artifact(201 + index, "2026-10-02T12:27:00Z")
            for index in range(99)
        ]
        reader, _ = self._reader({1: page1, 2: page2})
        _, complete, ordering_proven, _ = reader._scan_recent_artifacts(
            "2026-10-02T10:00:00Z", max_pages=2
        )
        self.assertFalse(complete)
        self.assertFalse(ordering_proven)


if __name__ == "__main__":
    unittest.main()
