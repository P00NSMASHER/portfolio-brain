import copy
import unittest
from unittest.mock import patch
from hunting.license_admission import admission, load_policy, license_review_required, LicenseAdmissionError, POLICY_PATH
from hunting.rights_gate import build_rights_record
from hunting.validate_license_admission import validate
from hunting.autonomous_hunter import experiment_proposal, run_cycle, load_seed_state
from transfer.cross_project_transfer import detect_transfer_hypotheses, validate_proposal
import test_champion_challenger as fixtures
from challenger.champion_challenger import assess_candidate, validate_assessment, ChallengerError

class OwnerLicensePolicyTests(unittest.TestCase):
    def test_all_license_classes_are_advisory_without_false_verification(self):
        self.assertEqual(len(validate()["controls"]),9)
        self.assertFalse(license_review_required())

    def test_challenger_no_license_reaches_review_but_not_promotion(self):
        d,adapter,replay,canary=fixtures.ChampionChallengerTests().happy_inputs()
        rights=fixtures.no_license_rights(d)
        before=copy.deepcopy(rights)
        assessment=assess_candidate(discovery=d,rights_record=rights,adapter_receipt=adapter,replay_receipt=replay,forward_canary_receipt=canary)
        validate_assessment(assessment)
        stage=assessment["stages"][1]
        self.assertEqual(stage["stage"],"RIGHTS_POLICY_ADMISSION")
        self.assertEqual(stage["license_admission"]["status"],"OPERATOR_ASSUMED")
        self.assertTrue(assessment["eligible_for_human_promotion_review"])
        self.assertFalse(assessment["automatic_promotion_allowed"])
        self.assertFalse(assessment["authority_granted"])
        self.assertFalse(assessment["active_policy_changed"])
        self.assertEqual(before,rights)
        self.assertFalse(rights["commercial_use_allowed"])

    def test_advisory_still_rejects_adapter_revision_mismatch(self):
        d,adapter,replay,canary=fixtures.ChampionChallengerTests().happy_inputs()
        adapter["source_revision_sha"]="f"*40
        with self.assertRaises(ChallengerError):
            assess_candidate(discovery=d,rights_record=fixtures.no_license_rights(d),adapter_receipt=adapter,replay_receipt=replay,forward_canary_receipt=canary)

    def test_transfer_license_review_is_disabled_but_implementation_is_not_authorized(self):
        proposals=detect_transfer_hypotheses()
        self.assertEqual(len(proposals),44)
        for p in proposals:
            validate_proposal(p)
            self.assertFalse(p["rights_review_required"])
            self.assertFalse(p["implementation_allowed"])
        self.assertEqual(sum(p["state"]=="BLOCKED" for p in proposals),4)

    def test_hunter_does_not_require_license_verification(self):
        proposal=experiment_proposal({"finding_id":"test","candidate_fingerprint":"sha256:"+"a"*64,"gap_id":"test","project_ids":["PRJ-001"]})
        self.assertNotIn("License/rights verification",proposal["evidence_requirements"])
        self.assertNotIn("incompatible rights",proposal["failure_condition"])
        self.assertIn("OPERATOR_ASSUMED",str(proposal))

    def test_hunter_skips_license_fetches_only(self):
        class Provider:
            requests=0
            def search(self,query):
                self.requests+=1
                return [{"id":1,"full_name":"synthetic/recovery","private":False,"license":None}]
            def inspect(self,candidate):
                return {"revision":"a"*40,"tree_sha":"b"*40,"paths":["src/recovery.py","tests/test_recovery.py"],"truncated":False}
            def rights_evidence(self,*args):
                raise AssertionError("advisory mode must not fetch license text")
        _,receipt=run_cycle(load_seed_state(),Provider(),at="2026-09-28T15:30:00Z")
        self.assertTrue(receipt["findings"])
        for finding in receipt["findings"]:
            self.assertEqual(finding["decision_trace"]["license_admission"]["status"],"OPERATOR_ASSUMED")
            self.assertFalse(finding["rights"]["automatic_reuse_authority_granted"])

    def test_unknown_or_forged_policy_mode_rejected(self):
        import json
        bad=load_policy()
        bad["mode"]="VERIFIED"
        with patch.object(type(POLICY_PATH),"read_text",return_value=json.dumps(bad)):
            with self.assertRaises(LicenseAdmissionError):
                load_policy()

if __name__=="__main__":
    unittest.main()
