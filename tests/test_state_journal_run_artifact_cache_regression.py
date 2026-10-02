import unittest

from runtime.artifact_state import ArtifactRestoreError
from state_journal.transport import GitHubReader


class RunArtifactCacheRegressionTests(unittest.TestCase):
    def test_run_artifact_listing_is_reused_after_discovery_within_request_budget(self):
        reader = object.__new__(GitHubReader)
        requests = []
        artifacts = [{"id": 12, "name": "portfolio-state-event-v2-101"}]

        def get(suffix):
            requests.append(suffix)
            if len(requests) > 1:
                raise ArtifactRestoreError("artifact API request budget exceeded")
            return {"total_count": len(artifacts), "artifacts": artifacts}

        reader.get = get
        discovered = reader._run_artifacts(101)
        reused = reader._run_artifacts(101)

        self.assertEqual(discovered, artifacts)
        self.assertEqual(reused, artifacts)
        self.assertEqual(
            requests,
            ["/actions/runs/101/artifacts?per_page=100"],
        )


if __name__ == "__main__":
    unittest.main()
