import unittest

from state_journal.contracts import JournalError
from state_journal.github_reducer import snapshot_candidates
from state_journal.provider_quarantine import (
    QUARANTINED_REDUCER_RUNS,
    reducer_run_is_quarantined,
    require_quarantined_reducer_identity,
)
from state_journal.transport import SNAPSHOT_ARTIFACT


class ProviderQuarantineTests(unittest.TestCase):
    def test_exact_provider_identity_is_quarantined(self):
        run_id=37655516971
        row={"id":run_id, **{
            key:value
            for key,value in QUARANTINED_REDUCER_RUNS[run_id].items()
            if key!="reason"
        }}
        self.assertTrue(reducer_run_is_quarantined(run_id))
        self.assertEqual(
            require_quarantined_reducer_identity(row)["reason"],
            "GITHUB_PROVIDER_JOBLESS_QUEUE_GHOST",
        )

    def test_identity_drift_fails_closed(self):
        run_id=37655516971
        row={"id":run_id, **{
            key:value
            for key,value in QUARANTINED_REDUCER_RUNS[run_id].items()
            if key!="reason"
        }}
        row["head_sha"]="f"*40
        with self.assertRaisesRegex(JournalError,"identity changed"):
            require_quarantined_reducer_identity(row)

    def test_quarantined_reducer_can_never_become_snapshot_authority(self):
        ghost={
            "id":9001,
            "name":SNAPSHOT_ARTIFACT,
            "expired":False,
            "created_at":"2026-10-07T18:20:00Z",
            "workflow_run":{
                "id":37655516971,
                "head_branch":"main",
                "head_sha":"18f3e3d5a9b3b8c9a3e64e118a7cd487a3551edb",
            },
        }
        valid={
            "id":9000,
            "name":SNAPSHOT_ARTIFACT,
            "expired":False,
            "created_at":"2026-10-07T18:19:00Z",
            "workflow_run":{
                "id":37664825865,
                "head_branch":"main",
                "head_sha":"531b6a07894b8e0271b291d24cb6b002bc5f617e",
            },
        }
        self.assertEqual(snapshot_candidates([ghost,valid],current_run="999"),[valid])

    def test_quarantine_does_not_filter_unrelated_reducer_history(self):
        artifact={
            "id":9000,
            "name":SNAPSHOT_ARTIFACT,
            "expired":False,
            "created_at":"2026-10-07T18:19:00Z",
            "workflow_run":{
                "id":123456,
                "head_branch":"main",
                "head_sha":"a"*40,
            },
        }
        self.assertEqual(snapshot_candidates([artifact],current_run="999"),[artifact])


if __name__=="__main__":
    unittest.main()
