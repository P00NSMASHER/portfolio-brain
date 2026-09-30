import io
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from hunting.downstream_lifecycle import load_seed_state
from hunting.lifecycle_artifact_state import restore


class HunterLifecycleArtifactRestoreTests(unittest.TestCase):
    def test_restore_accepts_workflow_upload_artifact_path_layout(self):
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr(
                "out/hunter_lifecycle_state.json",
                json.dumps(load_seed_state()).encode("utf-8"),
            )
            bundle.writestr("out/hunter_lifecycle_report.json", b"{}")
            bundle.writestr("live/hunter_lifecycle_restore_receipt.json", b"{}")

        listing = {
            "artifacts": [{
                "id": 123,
                "name": "portfolio-hunter-lifecycle-state",
                "created_at": "2026-09-30T19:00:00Z",
                "expires_at": "2026-10-30T19:00:00Z",
                "archive_download_url": "https://api.github.com/archive",
                "workflow_run": {
                    "id": 456,
                    "head_branch": "main",
                    "head_sha": "a" * 40,
                },
            }]
        }
        responses = iter([
            io.BytesIO(json.dumps(listing).encode("utf-8")),
            io.BytesIO(archive.getvalue()),
        ])

        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "hunter_lifecycle_state.json"
            metadata = Path(temp_dir) / "restore_receipt.json"
            with patch.dict(os.environ, {
                "GITHUB_TOKEN": "test-token",
                "GITHUB_REPOSITORY": "P00NSMASHER/portfolio-brain",
                "GITHUB_RUN_ID": "789",
                "GITHUB_REF_NAME": "main",
            }):
                with patch(
                    "hunting.lifecycle_artifact_state.open_url",
                    side_effect=lambda *_a, **_kw: next(responses),
                ):
                    status = restore(output, metadata)

            self.assertEqual(status, "RESTORED")
            self.assertEqual(json.loads(output.read_text()), load_seed_state())
            self.assertEqual(json.loads(metadata.read_text())["artifact_id"], 123)


if __name__ == "__main__":
    unittest.main()
