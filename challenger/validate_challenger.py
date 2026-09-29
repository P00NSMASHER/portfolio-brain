#!/usr/bin/env python3
from __future__ import annotations

from challenger.champion_challenger import (
    assess_candidate,
    build_adapter_receipt,
    build_forward_canary_receipt,
    derive_replay_metrics,
    validate_assessment,
)
from hunting.rights_gate import build_rights_record
from policy_replay.policy_backtester import replay

def cycle(i, *, cost=2.0, calls=2, api=3, jobs=2, duplicate=False, inconclusive=False):
    return {
      "cycle_id":f"C{i}",
      "proposal_id":f"P{i}",
      "project_id":"PRJ-001",
      "source_id":"SRC-A",
      "agent_id":"Hunter",
      "started_at":f"2026-09-2{i}T10:00:00+00:00",
      "completed_at":f"2026-09-2{i}T11:00:00+00:00",
      "result":"INCONCLUSIVE" if inconclusive else "PASSED",
      "evidence_state":"OBSERVED" if inconclusive else "VERIFIED",
      "cost_usd":cost,
      "model_calls":calls,
      "api_calls":api,
      "github_jobs":jobs,
      "duplicate_candidate":duplicate,
      "deferred":False,
      "authority_violations":0,
      "estimated_cost_usd":cost,
      "planned_model_calls":calls,
      "planned_api_calls":api,
      "planned_github_jobs":jobs,
    }

def discovery():
    return {
      "finding_id":"HFD-CHALLENGER-DEMO",
      "candidate_fingerprint":"sha256:"+"a"*64,
      "repository_full_name":"example/project",
      "revision":"b"*40,
      "project_ids":["PRJ-001"],
      "provenance_refs":["hunter-finding:HFD-CHALLENGER-DEMO"],
    }

def rights(d):
    return build_rights_record(
      {"full_name":d["repository_full_name"],"license":{"spdx_id":"MIT"}},
      {"revision":d["revision"],"paths":["LICENSE","src/core.py"],"tree_sha":"c"*40,"truncated":False},
      {"license_path":"LICENSE","license_text":"MIT License\nCopyright (c) 2026 Example\nPermission is hereby granted, free of charge"},
    )

def main():
    d=discovery()
    rr=rights(d)
    candidate_id="CHL-"+__import__("hashlib").sha256((d["candidate_fingerprint"]+"\0"+d["revision"]).encode()).hexdigest()[:20].upper()
    cycles=[
      cycle(1,cost=2.0,calls=2,api=3,jobs=2),
      cycle(2,cost=3.0,calls=3,api=4,jobs=3,duplicate=True,inconclusive=True),
      cycle(3,cost=2.0,calls=2,api=3,jobs=2),
    ]
    replay_receipt=replay(cycles,{
      "candidate_id":candidate_id,
      "max_estimated_cost_usd":2.0,
      "max_planned_model_calls":2,
      "max_planned_api_calls":3,
      "max_planned_github_jobs":2,
      "suppress_duplicate_candidates":True,
    }, provenance={"input_ref":"fixture:replay", "source_revision_sha":d["revision"], "evaluator_revision_sha":"e"*40})
    adapter=build_adapter_receipt(adapter_id="isolated-adapter-demo", discovery=d, evidence_refs=["test-receipt:adapter-pass"], candidate_policy_hash=replay_receipt["candidate_policy_hash"], evaluator_revision_sha="e"*40)
    metrics=derive_replay_metrics(replay_receipt)
    assert metrics["beats_champion"] is True
    canary=build_forward_canary_receipt(
      candidate_id=candidate_id,
      evidence_refs=["fixture:canary-1", "fixture:canary-2", "fixture:canary-3"],
      observed_cycles=3,
      candidate_policy_hash=replay_receipt["candidate_policy_hash"],
      source_revision_sha=d["revision"],
      evaluator_revision_sha="e"*40,
    )
    assessment=assess_candidate(
      discovery=d,
      rights_record=rr,
      adapter_receipt=adapter,
      replay_receipt=replay_receipt,
      forward_canary_receipt=canary,
    )
    validate_assessment(assessment)
    assert assessment["decision"]=="REMAIN_SHADOW_BLOCKED"
    assert assessment["evidence_scope"]=="UNRESOLVED"
    assert assessment["automatic_promotion_allowed"] is False
    assert assessment["active_policy_changed"] is False
    assert assessment["authority_granted"] is False
    print("champion/challenger structural validation: PASS; production evidence remains UNRESOLVED")

if __name__=="__main__":
    main()
