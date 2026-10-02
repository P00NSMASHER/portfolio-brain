import unittest

from runtime.artifact_state import ArtifactRestoreError
from state_journal.transport import GitHubReader


class RunArtifactCacheRegressionTests(unittest.TestCase):
    def test_publication_fallback_reuses_listing_discovered_for_the_run(self):
        reader = object.__new__(GitHubReader)
        calls = 0
        artifacts = [{"id": 12, "name": "portfolio-agent-heartbeat-state"}]

        def get(suffix):
            nonlocal calls
            calls += 1
            if calls > 1:
                raise ArtifactRestoreError("artifact API request budget exceeded")
            self.assertEqual(suffix, "/actions/runs/101/artifacts?per_page=100")
            return {"total_count": len(artifacts), "artifacts": artifacts}

        reader.get = get
        discovered = reader._run_artifacts(101)
        fallback = reader._run_artifacts(101)

        self.assertEqual(discovered, artifacts)
        self.assertEqual(fallback, artifacts)
        self.assertEqual(calls, 1)


if __name__ == "__main__":
    unittest.main()
