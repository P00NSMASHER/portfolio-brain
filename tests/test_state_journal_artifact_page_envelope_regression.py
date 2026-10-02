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
