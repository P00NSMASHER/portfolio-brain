import unittest

from state_journal.transport import GitHubReader


def artifact(artifact_id, created_at):
    return {
        "id": artifact_id,
        "name": f"artifact-{artifact_id}",
        "expired": False,
        "created_at": created_at,
        "workflow_run": {
            "id": 100000 + artifact_id,
            "head_branch": "main",
            "head_sha": "a" * 40,
        },
    }


class ArtifactScanBoundaryRegressionTests(unittest.TestCase):
    def test_full_page_scan_may_stop_after_crossing_requested_time_boundary(self):
        reader = object.__new__(GitHubReader)
        page1 = [artifact(3000 - i, "2026-09-30T02:20:00Z") for i in range(100)]
        page2 = [artifact(2000, "2026-09-30T02:10:00Z")] + [
            artifact(1999 - i, "2026-09-30T02:09:00Z") for i in range(99)
        ]
        pages = {1: page1, 2: page2}
        calls = []

        def get(suffix):
            calls.append(suffix)
            page = int(suffix.rsplit("=", 1)[1])
            return {"artifacts": pages.get(page, [])}

        reader.get = get
        rows = reader.list_recent_artifacts("2026-09-30T02:10:00Z", max_pages=2)

        self.assertEqual(len(calls), 2)
        self.assertEqual(len(rows), 101)
        self.assertTrue(all(row["created_at"] >= "2026-09-30T02:10:00Z" for row in rows))


if __name__ == "__main__":
    unittest.main()
