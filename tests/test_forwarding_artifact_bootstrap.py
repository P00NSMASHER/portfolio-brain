import io
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from runtime.artifact_restore import InvalidStateArtifact
from runtime.forwarding_artifact_state import restore
from runtime.project_forwarding import seed_state
from runtime.state import bootstrap_state, canonical_hash


def legacy_runtime_artifact(*, forwarding_state=None):
    at="2026-09-30T14:00:00Z"
    receipt={
        "schema_version":"1.0.0","cycle_id":"disabled","mode":"sync",
        "started_at":at,"finished_at":at,"status":"DISABLED",
        "reason":"test fixture","observations":[],"api_requests":0,
    }
    receipt["receipt_hash"]=canonical_hash(receipt)
    out=io.BytesIO()
    with zipfile.ZipFile(out,"w") as archive:
        archive.writestr("runtime_state.json",json.dumps(bootstrap_state(now=at)))
        archive.writestr("cycle_receipt.json",json.dumps(receipt))
        if forwarding_state is not None:
            archive.writestr("project_forwarding_state.json",forwarding_state)
    return out.getvalue()


class ForwardingArtifactBootstrapTests(unittest.TestCase):
    def restore_artifact(self, archive, output, metadata):
        data={
            "artifacts":[{
                "id":17,"name":"portfolio-runtime-state",
                "created_at":"2026-09-30T13:00:00Z","expires_at":"2026-10-30T13:00:00Z",
                "archive_download_url":"https://example.test/artifact",
                "workflow_run":{"id":16,"head_branch":"main","head_sha":"a"*40},
            }]
        }

        def open_url(request,timeout):
            if request.full_url.endswith("/actions/artifacts?name=portfolio-runtime-state&per_page=100"):
                return io.BytesIO(json.dumps(data).encode())
            return io.BytesIO(archive)

        with patch.dict(os.environ,{
            "GITHUB_TOKEN":"test-token","GITHUB_REPOSITORY":"P00NSMASHER/portfolio-brain",
            "GITHUB_RUN_ID":"99","GITHUB_REF_NAME":"main",
        },clear=True), patch("runtime.forwarding_artifact_state.open_url",side_effect=open_url), \
             patch("runtime.forwarding_artifact_state.time.sleep"):
            return restore(output,metadata)

    def test_legacy_runtime_artifact_bootstraps_forwarding_ledger_from_seed(self):
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)/"project_forwarding_state.json"
            metadata=Path(directory)/"restore.json"

            status=self.restore_artifact(legacy_runtime_artifact(),output,metadata)

            self.assertEqual(status,"SEEDED_FROM_LEGACY_RUNTIME_ARTIFACT")
            self.assertEqual(json.loads(output.read_text()),seed_state())
            self.assertEqual(json.loads(metadata.read_text())["artifact_id"],17)

    def test_invalid_forwarding_ledger_does_not_fall_back_to_seed(self):
        bad_state=json.dumps({
            "schema_version":"1.0.0","state_id":"wrong-state","sequence":0,
            "updated_at":None,"delivered_keys":[],"recent_deliveries":[],
        }).encode()
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)/"project_forwarding_state.json"

            with self.assertRaisesRegex(InvalidStateArtifact,"no valid prior state artifact"):
                self.restore_artifact(
                    legacy_runtime_artifact(forwarding_state=bad_state),
                    output,Path(directory)/"restore.json",
                )

            self.assertFalse(output.exists())


if __name__=="__main__":
    unittest.main()
