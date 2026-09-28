import copy
import hashlib
import json
import unittest

from challenger.champion_challenger import (
    ChallengerError,
    assess_candidate,
    build_adapter_receipt,
    build_forward_canary_receipt,
    derive_replay_metrics,
    validate_assessment,
)
from hunting.rights_gate import build_rights_record, validate_rights_record
from hunting.rights_usage import RightsUsageError, evaluate_rights_usage
from policy_replay.policy_backtester import replay


def cycle(cid, *, cost=2.0, calls=2, api=2, jobs=2, duplicate=False, authority=0):
    return {
      "cycle_id":cid,
      "proposal_id":"P-"+cid,
      "project_id":"PRJ-001",
      "source_id":"SRC",
      "agent_id":"Hunter",
      "started_at":"2026-09-20T10:00:00+00:00",
      "completed_at":"2026-09-20T11:00:00+00:00",
      "result":"PASSED",
      "evidence_state":"VERIFIED",
      "cost_usd":cost,
      "model_calls":calls,
      "api_calls":api,
      "github_jobs":jobs,
      "duplicate_candidate":duplicate,
      "deferred":False,
      "authority_violations":authority,
      "estimated_cost_usd":cost,
      "planned_model_calls":calls,
      "planned_api_calls":api,
      "planned_github_jobs":jobs,
    }


def discovery():
    return {
      "finding_id":"HFD-1",
      "candidate_fingerprint":"sha256:"+"a"*64,
      "repository_full_name":"example/project",
      "revision":"b"*40,
      "project_ids":["PRJ-001"],
      "provenance_refs":["hunter:HFD-1"],
    }


def permissive_rights(d):
    return build_rights_record(
      {"full_name":d["repository_full_name"],"license":{"spdx_id":"MIT"}},
      {"revision":d["revision"],"paths":["LICENSE","src/x.py"],"tree_sha":"c"*40,"truncated":False},
      {"license_path":"LICENSE","license_text":"MIT License\nCopyright (c) 2026 Example\nPermission is hereby granted, free of charge"},
    )


def no_license_rights(d):
    return build_rights_record(
      {"full_name":d["repository_full_name"],"license":None},
      {"revision":d["revision"],"paths":["src/x.py"],"tree_sha":"c"*40,"truncated":False},
    )


def good_replay():
    duplicate=cycle("2",cost=3,calls=3,api=3,jobs=3,duplicate=True)
    duplicate["result"]="INCONCLUSIVE"
    duplicate["evidence_state"]="OBSERVED"
    cycles=[
      cycle("1",cost=2,calls=2,api=2,jobs=2),
      duplicate,
      cycle("3",cost=2,calls=2,api=2,jobs=2),
    ]
    return replay(cycles,{
      "candidate_id":"c-good",
      "max_estimated_cost_usd":2.0,
      "max_planned_model_calls":2,
      "max_planned_api_calls":2,
      "max_planned_github_jobs":2,
      "suppress_duplicate_candidates":True,
    })


def candidate_id(d):
    return "CHL-"+hashlib.sha256((d["candidate_fingerprint"]+"\0"+d["revision"]).encode()).hexdigest()[:20].upper()


def rehash(value, field):
    body={k:v for k,v in value.items() if k!=field}
    value[field]="sha256:"+hashlib.sha256(json.dumps(body,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()


class ChampionChallengerTests(unittest.TestCase):
    def happy_inputs(self):
        d=discovery()
        adapter=build_adapter_receipt(adapter_id="A",discovery=d,evidence_refs=["test-receipt:A"])
        replay_receipt=good_replay()
        canary=build_forward_canary_receipt(
          candidate_id=candidate_id(d),
          evidence_refs=["canary:C"],
          observed_cycles=2,
        )
        return d,adapter,replay_receipt,canary

    def test_happy_path_only_reaches_human_review(self):
        d,adapter,replay_receipt,canary=self.happy_inputs()
        assessment=assess_candidate(
          discovery=d,rights_record=permissive_rights(d),
          adapter_receipt=adapter,replay_receipt=replay_receipt,
          forward_canary_receipt=canary,
        )
        validate_assessment(assessment)
        self.assertTrue(assessment["eligible_for_human_promotion_review"])
        self.assertFalse(assessment["automatic_promotion_allowed"])
        self.assertFalse(assessment["active_policy_changed"])
        self.assertFalse(assessment["authority_granted"])

    def test_all_license_categories_are_non_blocking_under_owner_assumption(self):
        d,adapter,replay_receipt,canary=self.happy_inputs()
        for spdx in ["MIT","Apache-2.0","AGPL-3.0-only","MPL-2.0","BUSL-1.1","PolyForm-Noncommercial-1.0.0","LicenseRef-Custom",None]:
            with self.subTest(spdx=spdx):
                rr=build_rights_record(
                    {"full_name":d["repository_full_name"],"license":None if spdx is None else {"spdx_id":spdx}},
                    {"revision":d["revision"],"paths":[]},
                )
                before=copy.deepcopy(rr)
                assessment=assess_candidate(
                  discovery=d,rights_record=rr,adapter_receipt=adapter,
                  replay_receipt=replay_receipt,forward_canary_receipt=canary,
                )
                validate_assessment(assessment)
                self.assertTrue(assessment["eligible_for_human_promotion_review"])
                self.assertEqual(assessment["stages"][1]["stage"],"RIGHTS_POLICY_SATISFIED")
                self.assertEqual(assessment["stages"][1]["assumption_status"],"OPERATOR_ASSUMED")
                self.assertFalse(assessment["stages"][1]["independently_verified"])
                self.assertEqual(rr,before)
                self.assertFalse(assessment["automatic_promotion_allowed"])

    def test_missing_license_observation_does_not_block_or_invent_verification(self):
        d,adapter,replay_receipt,canary=self.happy_inputs()
        assessment=assess_candidate(
          discovery=d,rights_record=None,adapter_receipt=adapter,
          replay_receipt=replay_receipt,forward_canary_receipt=canary,
        )
        validate_assessment(assessment)
        self.assertTrue(assessment["eligible_for_human_promotion_review"])
        self.assertEqual(assessment["stages"][1]["rights_classification"],"NO_LICENSE_NO_REUSE")
        self.assertFalse(assessment["rights_usage_policy"]["independently_verified"])

    def test_revision_mismatch_fails_closed(self):
        d,adapter,replay_receipt,canary=self.happy_inputs()
        rr=permissive_rights(d)
        rr["source_revision_sha"]="d"*40
        rehash(rr,"rights_hash")
        with self.assertRaises(ChallengerError):
            assess_candidate(
              discovery=d,rights_record=rr,adapter_receipt=adapter,
              replay_receipt=replay_receipt,forward_canary_receipt=canary,
            )

    def test_replay_without_improvement_stays_blocked(self):
        cycles=[cycle("1"),cycle("2"),cycle("3")]
        r=replay(cycles,{"candidate_id":"same"})
        metrics=derive_replay_metrics(r)
        self.assertFalse(metrics["beats_champion"])
        self.assertEqual(metrics["strict_improvement_count"],0)

    def test_canary_authority_violation_fails_closed_even_without_license(self):
        d,adapter,replay_receipt,_=self.happy_inputs()
        bad=build_forward_canary_receipt(
          candidate_id=candidate_id(d),evidence_refs=["canary:bad"],
          observed_cycles=1,authority_violations=1,
        )
        with self.assertRaises(ChallengerError):
            assess_candidate(
              discovery=d,rights_record=no_license_rights(d),
              adapter_receipt=adapter,replay_receipt=replay_receipt,
              forward_canary_receipt=bad,
            )

    def test_historical_replay_never_promotes_by_itself(self):
        r=good_replay()
        self.assertFalse(r["promotion_allowed"])
        self.assertTrue(r["forward_canary_required"])

    def test_legacy_observations_use_current_policy_without_being_rewritten(self):
        rr=no_license_rights(discovery())
        rr.pop("usage_policy")
        rehash(rr,"rights_hash")
        before=copy.deepcopy(rr)
        validate_rights_record(rr)
        usage=evaluate_rights_usage(rr)
        self.assertTrue(usage["allowed_by_brain_license_policy"])
        self.assertFalse(usage["independently_verified"])
        self.assertEqual(rr,before)
        self.assertIsNone(rr["license_text_hash"])
        self.assertIsNone(rr["license_spdx"])

    def test_self_rehashed_claim_of_independent_verification_is_rejected(self):
        rr=no_license_rights(discovery())
        rr["usage_policy"]["independently_verified"]=True
        rehash(rr["usage_policy"],"usage_hash")
        rehash(rr,"rights_hash")
        with self.assertRaises(RightsUsageError):
            evaluate_rights_usage(rr)

    def test_self_rehashed_execution_authority_is_rejected(self):
        rr=no_license_rights(discovery())
        rr["usage_policy"]["execution_authority_granted"]=True
        rehash(rr["usage_policy"],"usage_hash")
        rehash(rr,"rights_hash")
        with self.assertRaises(RightsUsageError):
            evaluate_rights_usage(rr)

    def test_license_observation_tampering_still_fails(self):
        rr=no_license_rights(discovery())
        rr["license_spdx"]="MIT"
        with self.assertRaises(ValueError):
            evaluate_rights_usage(rr)


if __name__=="__main__":
    unittest.main()
