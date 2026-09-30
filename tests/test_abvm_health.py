import unittest
from adapters.abvm_health import build_evidence,HEALTH_WORKFLOW_PATH

class AbvmHealthEvidenceTests(unittest.TestCase):
    def run_record(self,sha,*,run_id=22,number=8,status="completed",conclusion="success",branch="main",path=HEALTH_WORKFLOW_PATH):
        return {
          "id":run_id,"run_number":number,"run_attempt":1,"name":"ABVM Operational Health Dashboard",
          "path":path,"head_branch":branch,"head_sha":sha,"status":status,"conclusion":conclusion,
          "created_at":"2026-09-30T14:00:00Z","updated_at":"2026-09-30T14:00:10Z",
        }

    def test_exact_head_run_is_factual_health_progress_evidence_only(self):
        sha="a"*40
        evidence=build_evidence(sha,[
          self.run_record("b"*40,run_id=99,number=99,branch="feature"),
          self.run_record(sha,run_id=22,number=8),
        ],observed_at="2026-09-30T14:01:00Z")
        self.assertEqual(evidence["automation_health"],"HEALTHY")
        self.assertEqual(evidence["automation_progress"],"EXACT_HEAD_HEALTH_RUN_OBSERVED")
        self.assertEqual(evidence["source_run_id"],22)
        self.assertEqual(evidence["source_run_head_sha"],sha)
        self.assertEqual(evidence["source_sequence"],8)
        self.assertTrue(evidence["source_state_hash"].startswith("sha256:"))
        self.assertEqual(set(evidence["evidence_scope"]),{"AUTOMATION_HEALTH","PROGRESS_EVIDENCE"})
        for field in ("authority_granted","mutation_performed","deploy_authority","external_action_authority",
                      "child_facing_mutation_authority","school_content_publication_authority","child_data_included",
                      "technical_verification_credit","market_verification_credit","revenue_verification_credit"):
            self.assertFalse(evidence[field])

    def test_missing_exact_head_health_run_fails_closed_without_inventing_health(self):
        sha="a"*40
        evidence=build_evidence(sha,[self.run_record("b"*40,run_id=99,number=99)],observed_at="2026-09-30T14:01:00Z")
        self.assertEqual(evidence["automation_health"],"BLOCKED_NO_EXACT_HEAD_HEALTH_RUN")
        self.assertEqual(evidence["automation_progress"],"SOURCE_REVISION_OBSERVED_HEALTH_RUN_MISSING")
        self.assertIsNone(evidence["source_run_id"])
        self.assertIsNone(evidence["source_sequence"])

    def test_failed_exact_head_run_reports_degraded_not_verified(self):
        sha="a"*40
        evidence=build_evidence(sha,[self.run_record(sha,status="completed",conclusion="failure")],observed_at="2026-09-30T14:01:00Z")
        self.assertEqual(evidence["automation_health"],"DEGRADED")
        self.assertFalse(evidence["technical_verification_credit"])

if __name__=="__main__":
    unittest.main()
