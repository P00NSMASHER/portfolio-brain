import unittest

from state_journal.transport import GitHubReader


class ArtifactScanAccumulationRegressionTests(unittest.TestCase):
    def test_recent_canonical_snapshot_bounds_full_repository_scan(self):
        reader = object.__new__(GitHubReader)
        snapshot = {
            "id": 9001,
            "name": "portfolio-canonical-shadow-state",
            "expired": False,
            "created_at": "2026-09-29T20:00:00Z",
            "workflow_run": {"id": 7001, "head_branch": "main", "head_sha": "a" * 40},
        }
        predecessor = {
            "id": 8001,
            "name": "portfolio-canonical-shadow-state",
            "expired": False,
            "created_at": "2026-09-29T19:59:00Z",
            "workflow_run": {"id": 7000, "head_branch": "main", "head_sha": "b" * 40},
        }
        newer = [
            {
                "id": 10000 + i,
                "name": f"new-{i}",
                "expired": False,
                "created_at": "2026-09-29T20:01:00Z",
                "workflow_run": {"id": 6000 + i, "head_branch": "main", "head_sha": "c" * 40},
            }
            for i in range(99)
        ]
        older = [
            {
                "id": 20000 + i,
                "name": f"old-{i}",
                "expired": False,
                "created_at": "2026-09-29T19:58:00Z",
                "workflow_run": {"id": 5000 + i, "head_branch": "main", "head_sha": "d" * 40},
            }
            for i in range(99)
        ]
        pages = {1: newer + [snapshot], 2: [predecessor] + older}
        calls = []

        def get(suffix):
            calls.append(suffix)
            page = int(suffix.rsplit("=", 1)[1])
            return {"artifacts": pages.get(page, [])}

        reader.get = get
        rows = reader.list_recent_artifacts("2026-09-29T16:35:30Z", max_pages=2)
        ids = {row["id"] for row in rows}
        self.assertIn(snapshot["id"], ids)
        self.assertIn(predecessor["id"], ids)
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
