import copy
import io
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from dashboard.history_state import validate_state
from runtime.artifact_restore import InvalidStateArtifact, restore_latest_valid_state
from state_journal.contracts import digest
from state_journal.legacy import restore_domain


def archive(state):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as bundle:
        bundle.writestr("history_state.json", json.dumps(state).encode())
    return output.getvalue()


class LegacyForkParityTests(unittest.TestCase):
    def test_reducer_projection_disambiguates_equal_sequence_legacy_artifacts(self):
        expected = {
            "schema_version": "1.0.0",
            "state_id": "portfolio-command-center-history",
            "sequence": 1,
            "updated_at": "2026-09-30T10:00:00Z",
            "points": [],
        }
        divergent = copy.deepcopy(expected)
        divergent["updated_at"] = "2026-09-30T10:01:00Z"
        validate_state(expected)
        validate_state(divergent)
        payloads = {
            "expected": archive(expected),
            "divergent": archive(divergent),
        }
        artifacts = {
            "artifacts": [
                {
                    "id": 2,
                    "created_at": "2026-09-30T10:02:00Z",
                    "archive_download_url": "divergent",
                    "workflow_run": {
                        "id": 12,
                        "head_branch": "main",
                        "head_sha": "b" * 40,
                    },
                },
                {
                    "id": 1,
                    "created_at": "2026-09-30T10:01:00Z",
                    "archive_download_url": "expected",
                    "workflow_run": {
                        "id": 11,
                        "head_branch": "main",
                        "head_sha": "a" * 40,
                    },
                },
            ]
        }

        def restore_history(output, metadata_output):
            return restore_latest_valid_state(
                artifacts,
                current_run="99",
                expected_head_branch="main",
                download=payloads.__getitem__,
                output=output,
                member_name="history_state.json",
                expected_state_id="portfolio-command-center-history",
                max_archive_bytes=10000,
                max_state_bytes=5000,
                validator=validate_state,
                metadata_output=metadata_output,
            )

        class Reader:
            def __init__(self, *_args, **_kwargs):
                pass

            def get(self, _suffix):
                return {"status": "completed", "conclusion": "success"}

        with tempfile.TemporaryDirectory() as temp, patch.dict(
            os.environ,
            {
                "GITHUB_TOKEN": "test-token",
                "GITHUB_RUN_ID": "99",
                "GITHUB_REF_NAME": "main",
            },
        ), patch("state_journal.legacy.GitHubReader", Reader), patch.dict(
            "state_journal.legacy.RESTORERS", {"history": restore_history}
        ):
            restored, source = restore_domain(
                Path(temp),
                "history",
                Path(temp) / "work",
                expected_state=expected,
            )

        self.assertEqual(restored, expected)
        self.assertIn("artifact=1", source)
        self.assertEqual(digest(restored), digest(expected))
        with tempfile.TemporaryDirectory() as rejected:
            output = Path(rejected) / "history_state.json"
            with self.assertRaisesRegex(
                InvalidStateArtifact,
                "conflicting state artifacts at highest sequence",
            ):
                restore_history(output, Path(rejected) / "metadata.json")
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
