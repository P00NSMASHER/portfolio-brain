"""Publication failure codes: fail closed with fixed, non-sensitive evidence."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from brain.v9.batch_cycle import run_cycle
from brain.v9.batch_queue import BatchFault, BatchQueue
from brain.v9.publication_reader import PublicationReader

ROOT=Path(__file__).resolve().parents[1]
SOURCE="a"*40
NOW="2026-10-23T20:00:00Z"

def report():
    return {
        "schema_version": 1, "source_sha": SOURCE, "canonical_pending_events": 0,
        "operation": {"name": "projects", "requests": 14,
                      "publication_reserved_gets": 10,
                      "project_request_ceiling": 14},
        "projects": [{
            "id": "abvm", "repository": "P00NSMASHER/abvmschoolstarworld",
            "repository_revision": "b"*40,
            "source_check_state": "ADVERSE_CHECKS_OBSERVED",
        }],
    }

class OriginalReadbackReasonTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.queue=BatchQueue(Path(self.tmp.name)/"state.sqlite")
        self.spec=json.loads((ROOT/"brain/v9/repair-proof.json").read_text())
    def tearDown(self):
        self.queue.close()
        self.tmp.cleanup()

    def run_failed(self,exc):
        reader=PublicationReader(token="",max_gets=10)
        with patch.object(PublicationReader,"verify",side_effect=exc):
            return run_cycle(report(),self.queue,source_sha=SOURCE,cycle=1,
                             now=NOW,proof_spec=self.spec,reader=reader)

    def test_missing_original_quality_run_reports_stable_specific_reason(self):
        result=self.run_failed(BatchFault("PUBLICATION_ORIGINAL_RUN_MISSING"))
        self.assertEqual(result["provider_readback"]["status"],
                         "ORIGINAL_PUBLICATION_NOT_VERIFIED")
        self.assertEqual(result["provider_readback"]["failure_code"],
                         "PUBLICATION_ORIGINAL_RUN_MISSING")
        self.assertFalse(result["production_accepted"])
        self.assertEqual(result["total_project_gets"],14)
        self.assertEqual(result["provider_writes"],0)
        self.assertEqual(result["metrics"]["actual_live_verified"],0)
        self.assertEqual(self.queue.restore_drill()["status"],
                         "ISOLATED_RESTORE_REPLAY_PASSED")

    def test_unexpected_provider_string_never_enters_public_receipt(self):
        marker="UNTRUSTED_PROVIDER_TOKEN_MUST_NOT_PERSIST"
        result=self.run_failed(BatchFault(marker))
        self.assertEqual(result["provider_readback"]["status"],
                         "ORIGINAL_PUBLICATION_NOT_VERIFIED")
        self.assertEqual(result["provider_readback"]["failure_code"],
                         "PUBLICATION_FAILURE_UNCLASSIFIED")
        self.assertNotIn(marker,json.dumps(result))
        self.assertEqual(result["provider_writes"],0)

    def test_non_batch_transport_exception_has_no_user_data_leak(self):
        marker="UNTRUSTED_REMOTE_ERROR_TEXT_MUST_NOT_PERSIST"
        result=self.run_failed(OSError(marker))
        self.assertEqual(result["provider_readback"]["failure_code"],
                         "PUBLICATION_FAILURE_UNCLASSIFIED")
        self.assertNotIn(marker,json.dumps(result))
        self.assertEqual(result["metrics"]["actual_live_verified"],0)

if __name__=="__main__":
    unittest.main()
