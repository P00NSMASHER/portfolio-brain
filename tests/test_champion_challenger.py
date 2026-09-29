import hashlib
import unittest
from unittest.mock import patch
from hunting.license_admission import load_policy as load_license_policy

from challenger.champion_challenger import (
    ChallengerError,
    assess_candidate,
    build_adapter_receipt,
    build_forward_canary_receipt,
    derive_replay_metrics,
    validate_assessment,
)
from hunting.rights_gate import build_rights_record
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
      "candidate_id":candidate_id(discovery()),
      "max_estimated_cost_usd":2.0,
      "max_planned_model_calls":2,
      "max_planned_api_calls":2,
      "max_planned_github_jobs":2,
      "suppress_duplicate_candidates":True,
    }, provenance={"input_ref":"fixture:replay", "source_revision_sha":discovery()["revision"], "evaluator_revision_sha":"e"*40})

def candidate_id(d):
    return "CHL-"+hashlib.sha256((d["candidate_fingerprint"]+"\0"+d["revision"]).encode()).hexdigest()[:20].upper()

class ChampionChallengerTests(unittest.TestCase):
    def happy_inputs(self):
        d=discovery()
        replay_receipt=good_replay()
        adapter=build_adapter_receipt(adapter_id="A",discovery=d,evidence_refs=["test-receipt:A"], candidate_policy_hash=replay_receipt["candidate_policy_hash"], evaluator_revision_sha="e"*40)
        canary=build_forward_canary_receipt(
          candidate_id=candidate_id(d),
          evidence_refs=["canary:C1", "canary:C2", "canary:C3"],
          observed_cycles=3,
          candidate_policy_hash=replay_receipt["candidate_policy_hash"],
          source_revision_sha=d["revision"],
          evaluator_revision_sha="e"*40,
        )
        return d,adapter,replay_receipt,canary

    def test_unresolved_demo_does_not_reach_human_review(self):
        d,adapter,replay_receipt,canary=self.happy_inputs()
        assessment=assess_candidate(
          discovery=d,rights_record=permissive_rights(d),
          adapter_receipt=adapter,replay_receipt=replay_receipt,
          forward_canary_receipt=canary,
        )
        validate_assessment(assessment)
        self.assertFalse(assessment["eligible_for_human_promotion_review"])
        self.assertFalse(assessment["automatic_promotion_allowed"])
        self.assertFalse(assessment["active_policy_changed"])
        self.assertFalse(assessment["authority_granted"])

    def test_no_license_blocks_in_explicit_enforcement_mode(self):
        strict=load_license_policy()
        strict["mode"]="ENFORCE"
        strict["license_based_blocking"]=True
        override=patch("hunting.license_admission.load_policy",return_value=strict)
        override.start()
        self.addCleanup(override.stop)
        d,adapter,replay_receipt,canary=self.happy_inputs()
        assessment=assess_candidate(
          discovery=d,rights_record=no_license_rights(d),
          adapter_receipt=adapter,replay_receipt=replay_receipt,
          forward_canary_receipt=canary,
        )
        validate_assessment(assessment)
        self.assertFalse(assessment["eligible_for_human_promotion_review"])
        self.assertEqual(assessment["stages"][1]["status"],"BLOCKED")
        self.assertEqual(assessment["decision"],"REMAIN_SHADOW_BLOCKED")

    def test_revision_mismatch_fails_closed(self):
        d,adapter,replay_receipt,canary=self.happy_inputs()
        rr=permissive_rights(d)
        rr=dict(rr)
        rr["source_revision_sha"]="d"*40
        with self.assertRaises(Exception):
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

    def test_canary_authority_violation_fails_closed(self):
        d,adapter,replay_receipt,_=self.happy_inputs()
        bad=build_forward_canary_receipt(
          candidate_id=candidate_id(d),
          evidence_refs=["canary:bad"],
          observed_cycles=1,
          authority_violations=1,
        )
        with self.assertRaises(ChallengerError):
            assess_candidate(
              discovery=d,rights_record=permissive_rights(d),
              adapter_receipt=adapter,replay_receipt=replay_receipt,
              forward_canary_receipt=bad,
            )

    def test_historical_replay_never_promotes_by_itself(self):
        r=good_replay()
        self.assertFalse(r["promotion_allowed"])
        self.assertTrue(r["forward_canary_required"])

if __name__=="__main__":
    unittest.main()
