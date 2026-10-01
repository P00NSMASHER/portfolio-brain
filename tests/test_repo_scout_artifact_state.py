import json
import tempfile
import unittest
from pathlib import Path

from hunting.repo_scout_artifact_state import restore_from_listing
from runtime.artifact_restore import InvalidStateArtifact


def artifact(*,created_at,run_id=100,head_branch="main"):
    return {
        "id":run_id,
        "name":"portfolio-hunter-state",
        "expired":False,
        "created_at":created_at,
        "archive_download_url":"https://example.invalid/artifact.zip",
        "workflow_run":{
            "id":run_id,
            "head_branch":head_branch,
            "head_sha":"a"*40,
        },
    }


class RepoScoutArtifactStateTests(unittest.TestCase):
    def test_first_run_without_prior_artifact_seeds_checked_in_state(self):
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/"state.json"
            meta=Path(td)/"meta.json"
            status=restore_from_listing(
                {"artifacts":[]},
                current_run="200",
                expected_head_branch="main",
                download=lambda _url:b"",
                output=out,
                metadata_output=meta,
            )
            self.assertEqual(status,"SEEDED_NO_PRIOR_ARTIFACT")
            state=json.loads(out.read_text())
            self.assertEqual(state["state_id"],"portfolio-repo-scout-intake-state")
            self.assertEqual(state["sequence"],0)
            self.assertEqual(json.loads(meta.read_text())["restore_status"],status)

    def test_legacy_pre_scout_artifacts_bootstrap_seed_when_member_never_existed(self):
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/"state.json"
            status=restore_from_listing(
                {"artifacts":[artifact(created_at="2026-09-30T20:00:00Z")]},
                current_run="200",
                expected_head_branch="main",
                download=lambda _url:b"legacy-artifact-without-scout-state",
                output=out,
            )
            self.assertEqual(status,"SEEDED_LEGACY_PRE_SCOUT_ARTIFACTS")
            self.assertEqual(json.loads(out.read_text())["sequence"],0)

    def test_post_feature_invalid_artifact_still_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/"state.json"
            with self.assertRaisesRegex(InvalidStateArtifact,"no valid prior state artifact found"):
                restore_from_listing(
                    {"artifacts":[artifact(created_at="2026-09-30T21:00:00Z")]},
                    current_run="200",
                    expected_head_branch="main",
                    download=lambda _url:b"corrupt-post-feature-artifact",
                    output=out,
                )
            self.assertFalse(out.exists())


if __name__=="__main__":
    unittest.main()
