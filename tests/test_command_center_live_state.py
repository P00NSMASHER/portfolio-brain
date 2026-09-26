import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import dashboard.live_state_bridge as bridge


class LiveStateBridgeTests(unittest.TestCase):
    def fake_restorer(self, name, created_at, run_id, sequence=7):
        def restore(*args, **kwargs):
            output = kwargs.get("output") or args[0]
            metadata_output = kwargs.get("metadata_output")
            if metadata_output is None and len(args) > 1:
                metadata_output = args[1]
            output = Path(output)
            metadata_output = Path(metadata_output)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps({
                "schema_version":"1.0.0",
                "state_id":f"portfolio-{name}-state",
                "sequence":sequence,
                "updated_at":created_at,
            })+"\n")
            metadata_output.parent.mkdir(parents=True, exist_ok=True)
            metadata_output.write_text(json.dumps({
                "schema_version":"1.0.0",
                "restore_status":"RESTORED",
                "artifact_id":run_id + 1000,
                "artifact_name":f"portfolio-{name}-state",
                "artifact_created_at":created_at,
                "artifact_expires_at":"2026-10-26T18:00:00Z",
                "source_run_id":run_id,
                "source_head_sha":str(run_id).zfill(40)[-40:],
            })+"\n")
            return "RESTORED"
        return restore

    def test_bridge_labels_live_and_stale_sources_with_exact_run(self):
        now=datetime(2026,9,26,18,0,tzinfo=timezone.utc)
        restorers={
            "runtime":self.fake_restorer("runtime","2026-09-26T17:30:00Z",101),
            "scheduler":self.fake_restorer("scheduler","2026-09-26T17:20:00Z",102),
            "hunter":self.fake_restorer("hunter","2026-09-26T09:00:00Z",103),
            "cost":self.fake_restorer("cost-governor","2026-09-26T17:45:00Z",104),
            "notifications":self.fake_restorer("notification","2026-09-26T17:00:00Z",105),
        }
        with tempfile.TemporaryDirectory() as td, patch.dict(bridge.RESTORERS,restorers,clear=True):
            root=Path(td)
            receipt=bridge.build_live_state(output_dir=root/"live",receipt_path=root/"receipt.json",now=now)
        self.assertEqual(receipt["bridge_status"],"DEGRADED")
        self.assertEqual(receipt["sources"]["runtime"]["status"],"LIVE")
        self.assertEqual(receipt["sources"]["scheduler"]["status"],"LIVE")
        self.assertEqual(receipt["sources"]["hunter"]["status"],"STALE")
        self.assertEqual(receipt["sources"]["cost"]["status"],"LIVE")
        self.assertEqual(receipt["sources"]["notifications"]["status"],"LIVE")
        self.assertEqual(receipt["sources"]["scheduler"]["source_run_id"],102)
        self.assertEqual(receipt["sources"]["scheduler"]["artifact_created_at"],"2026-09-26T17:20:00Z")

    def test_no_artifacts_fall_back_explicitly(self):
        def missing(*args, **kwargs):
            return "NO_PRIOR_ARTIFACT"
        restorers={name:missing for name in bridge.RESTORERS}
        now=datetime(2026,9,26,18,0,tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as td, patch.dict(bridge.RESTORERS,restorers,clear=True):
            root=Path(td)
            receipt=bridge.build_live_state(output_dir=root/"live",receipt_path=root/"receipt.json",now=now)
            self.assertTrue((root/"live"/"runtime_state.json").exists())
            self.assertTrue((root/"live"/"scheduler_state.json").exists())
        self.assertEqual(receipt["bridge_status"],"FALLBACK")
        self.assertTrue(all(x["status"]=="FALLBACK" for x in receipt["sources"].values()))
        self.assertTrue(all(x["source_run_id"] is None for x in receipt["sources"].values()))


if __name__=="__main__":
    unittest.main()
