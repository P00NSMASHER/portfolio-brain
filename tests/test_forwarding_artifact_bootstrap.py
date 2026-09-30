import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from runtime.forwarding_artifact_state import restore
from runtime.state import bootstrap_state, canonical_hash


def runtime_artifact(*, include_forwarding=False):
    now = "2026-09-30T00:00:00Z"
    receipt = {
        "schema_version": "1.0.0",
        "cycle_id": "disabled",
        "mode": "sync",
        "started_at": now,
        "finished_at": now,
        "status": "DISABLED",
        "reason": "test fixture",
        "observations": [],
        "api_requests": 0,
    }
    receipt["receipt_hash"] = canonical_hash(receipt)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("runtime_state.json", json.dumps(bootstrap_state(now=now)))
        archive.writestr("cycle_receipt.json", json.dumps(receipt))
        if include_forwarding:
            archive.writestr("project_forwarding_state.json", b"invalid state")
    return output.getvalue()


class ForwardingArtifactBootstrapTests(unittest.TestCase):
    def restore_artifact(self, artifact, output, metadata):
        listing = json.dumps({
            "artifacts": [{
                "id": 10,
                "name": "portfolio-runtime-state",
                "expired": False,
                "created_at": "2026-09-29T00:00:00Z",
                "archive_download_url": "https://example.test/archive",
                "workflow_run": {"id": 9, "head_branch": "main"},
            }]
        }).encode()

        def response(request, **_kwargs):
            return io.BytesIO(listing if request.full_url.endswith("/actions/artifacts?name=portfolio-runtime-state&per_page=100") else artifact)

        with patch.dict("os.environ", {
            "GITHUB_TOKEN": "test-token",
            "GITHUB_REPOSITORY": "owner/repo",
            "GITHUB_RUN_ID": "11",
            "GITHUB_REF_NAME": "main",
        }), patch("runtime.forwarding_artifact_state.open_url", side_effect=response):
            return restore(output, metadata)

    def test_valid_legacy_runtime_artifact_without_forwarding_ledger_bootstraps(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "project_forwarding_state.json"
            metadata = Path(directory) / "restore.json"

            status = self.restore_artifact(runtime_artifact(), output, metadata)

            self.assertEqual(status, "NO_PRIOR_FORWARDING_STATE")
            self.assertFalse(output.exists())
            self.assertEqual(json.loads(metadata.read_text())["restore_status"], status)

    def test_invalid_existing_forwarding_ledger_does_not_bootstrap(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "project_forwarding_state.json"
            metadata = Path(directory) / "restore.json"

            with self.assertRaisesRegex(ValueError, "no valid prior state artifact found"):
                self.restore_artifact(runtime_artifact(include_forwarding=True), output, metadata)

            self.assertFalse(output.exists())
            self.assertFalse(metadata.exists())


if __name__ == "__main__":
    unittest.main()
