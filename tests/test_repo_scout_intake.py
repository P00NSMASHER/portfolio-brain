import unittest
from hunting.repo_scout_intake import ScoutIntakeError, build_intake, seed_state

def queue():
    return {"schema_version":2,"authority":"PRE_VERIFICATION_DISCOVERY_ONLY","worker_id":"HUNTER-01","candidates":[
      {"repository":"bigfootpp/sync","exact_revision":"a"*40,"status":"PRE_VERIFICATION_CANDIDATE","archived":False,"triage_score":42,"published_license_spdx":"MIT","root_code_signals":["src","tests"]},
      {"repository":"MingauRM/fobos-framework","exact_revision":"b"*40,"status":"PRE_VERIFICATION_CANDIDATE","archived":False,"triage_score":41,"published_license_spdx":"Zlib","root_code_signals":["src"]},
      {"repository":"bad/unknown","exact_revision":"c"*40,"status":"PRE_VERIFICATION_CANDIDATE","archived":False,"triage_score":99,"published_license_spdx":"UNKNOWN","root_code_signals":["src"]},
      {"repository":"third/eligible","exact_revision":"d"*40,"status":"PRE_VERIFICATION_CANDIDATE","archived":False,"triage_score":40,"published_license_spdx":"MIT","root_code_signals":["src"]},
    ]}

class RepoScoutIntakeTests(unittest.TestCase):
    def test_intake_is_bounded_eligible_and_preverification_only(self):
        state,receipt=build_intake(queue(),source_revision="1"*40,prior_state=seed_state(),at="2026-09-30T14:00:00Z")
        self.assertEqual(receipt["selected_candidates"],2)
        self.assertLessEqual(receipt["selected_candidates"],receipt["max_intake"])
        self.assertTrue(all(x["project_ids"]==["PRJ-005"] for x in receipt["hints"]))
        self.assertTrue(all(x["status"]=="ELIGIBLE_FOR_EXISTING_HUNTER_INSPECTION" for x in receipt["hints"]))
        self.assertTrue(all(x["rights_granted"] is False and x["value_verified"] is False and x["reuse_authority_granted"] is False for x in receipt["hints"]))
        self.assertFalse(receipt["license_based_blocking"])
        self.assertTrue(any(x["published_license_spdx"]=="UNKNOWN" for x in receipt["hints"]))
        self.assertEqual(state["sequence"],1)

    def test_source_repo_revision_and_candidate_identity_are_deduplicated(self):
        state,first=build_intake(queue(),source_revision="1"*40,prior_state=seed_state(),at="2026-09-30T14:00:00Z")
        state2,second=build_intake(queue(),source_revision="1"*40,prior_state=state,at="2026-09-30T14:01:00Z")
        self.assertEqual(second["selected_candidates"],2) # remaining bounded candidates continue next cycle
        state3,third=build_intake(queue(),source_revision="2"*40,prior_state=state2,at="2026-09-30T14:02:00Z")
        self.assertEqual(third["selected_candidates"],0) # same exact candidates stay deduped across source refreshes
        self.assertGreaterEqual(len(state3["source_keys"]),4)

    def test_unallowlisted_worker_fails_closed(self):
        q=queue();q["worker_id"]="HUNTER-99"
        with self.assertRaises(ScoutIntakeError):
            build_intake(q,source_revision="1"*40,prior_state=seed_state())

if __name__=="__main__":unittest.main()
