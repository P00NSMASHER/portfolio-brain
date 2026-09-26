import io
import json
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path

from runtime.artifact_restore import InvalidStateArtifact, restore_latest_valid_state

ROOT=Path(__file__).resolve().parents[1]


def artifact(member, body, *, duplicate=False):
    out=io.BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore",UserWarning)
        with zipfile.ZipFile(out,"w") as archive:
            archive.writestr(member,body)
            if duplicate:
                archive.writestr(member,body)
    return out.getvalue()


class ArtifactStateIntegrityTests(unittest.TestCase):
    def test_all_persistent_restorers_use_shared_validated_atomic_restore(self):
        for relative in [
            "runtime/artifact_state.py","cost_governor/artifact_state.py",
            "scheduler/artifact_state.py","notifications/artifact_state.py",
            "hunting/artifact_state.py",
        ]:
            body=(ROOT/relative).read_text()
            self.assertIn("from runtime.artifact_restore import restore_latest_valid_state",body,relative)
            self.assertIn("restore_latest_valid_state(",body,relative)
            self.assertNotIn("write_bytes(",body,relative)

    def state(self,sequence=1,state_id="portfolio-runtime-state"):
        return json.dumps({"schema_version":"1.0.0","state_id":state_id,"sequence":sequence}).encode()

    def candidates(self):
        return {"artifacts":[
            {"id":2,"name":"portfolio-runtime-state","created_at":"2026-09-26T17:00:00Z","expires_at":"2026-10-26T17:00:00Z","archive_download_url":"new","workflow_run":{"id":20,"head_sha":"2"*40}},
            {"id":1,"name":"portfolio-runtime-state","created_at":"2026-09-26T16:00:00Z","expires_at":"2026-10-26T16:00:00Z","archive_download_url":"old","workflow_run":{"id":10,"head_sha":"1"*40}},
        ]}

    def restore(self,data,payloads,output,metadata_output=None):
        return restore_latest_valid_state(data,current_run="99",download=payloads.__getitem__,output=output,member_name="runtime_state.json",expected_state_id="portfolio-runtime-state",max_archive_bytes=10000,max_state_bytes=1000,metadata_output=metadata_output)

    def test_corrupt_newest_falls_back_to_newest_valid_predecessor(self):
        with tempfile.TemporaryDirectory() as td:
            output=Path(td)/"runtime_state.json"
            status=self.restore(self.candidates(),{"new":b"not-a-zip","old":artifact("runtime_state.json",self.state(4))},output)
            self.assertEqual(status,"RESTORED_AFTER_REJECTING_1_INVALID")
            self.assertEqual(json.loads(output.read_text())["sequence"],4)

    def test_metadata_receipt_points_to_exact_valid_artifact(self):
        with tempfile.TemporaryDirectory() as td:
            output=Path(td)/"runtime_state.json"
            metadata=Path(td)/"restore.json"
            status=self.restore(self.candidates(),{"new":b"bad","old":artifact("runtime_state.json",self.state(9))},output,metadata)
            self.assertEqual(status,"RESTORED_AFTER_REJECTING_1_INVALID")
            receipt=json.loads(metadata.read_text())
            self.assertEqual(receipt["artifact_id"],1)
            self.assertEqual(receipt["source_run_id"],10)
            self.assertEqual(receipt["source_head_sha"],"1"*40)
            self.assertEqual(receipt["artifact_created_at"],"2026-09-26T16:00:00Z")

    def test_identity_mismatch_and_duplicate_member_are_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            output=Path(td)/"runtime_state.json"
            bad_identity=artifact("runtime_state.json",self.state(state_id="attacker-state"))
            duplicate=artifact("runtime_state.json",self.state(),duplicate=True)
            with self.assertRaises(InvalidStateArtifact):
                self.restore(self.candidates(),{"new":bad_identity,"old":duplicate},output)
            self.assertFalse(output.exists())

    def test_current_run_and_expired_artifacts_are_ignored(self):
        data={"artifacts":[
            {"id":3,"created_at":"2026-09-26T18:00:00Z","archive_download_url":"current","workflow_run":{"id":99}},
            {"id":2,"created_at":"2026-09-26T17:00:00Z","archive_download_url":"expired","expired":True,"workflow_run":{"id":20}},
            {"id":1,"created_at":"2026-09-26T16:00:00Z","archive_download_url":"valid","workflow_run":{"id":10}},
        ]}
        with tempfile.TemporaryDirectory() as td:
            output=Path(td)/"runtime_state.json"
            status=self.restore(data,{"valid":artifact("runtime_state.json",self.state(7))},output)
            self.assertEqual(status,"RESTORED")
            self.assertEqual(json.loads(output.read_text())["sequence"],7)


if __name__=="__main__":unittest.main()
