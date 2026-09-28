#!/usr/bin/env python3
from __future__ import annotations

from policy_replay.policy_backtester import replay, validate_replay_receipt

def _cycle(i, *, result="PASSED", verified=True, duplicate=False, deferred=False, cost=1.0, model_calls=1):
    return {
        "cycle_id": f"C{i}",
        "proposal_id": f"P{i}",
        "project_id": "PRJ-001",
        "source_id": "SRC-A",
        "agent_id": "Hunter",
        "started_at": f"2026-09-2{i}T10:00:00+00:00",
        "completed_at": f"2026-09-2{i}T11:00:00+00:00",
        "result": result,
        "evidence_state": "VERIFIED" if verified else "OBSERVED",
        "cost_usd": cost,
        "model_calls": model_calls,
        "api_calls": 2,
        "github_jobs": 1,
        "duplicate_candidate": duplicate,
        "deferred": deferred,
        "authority_violations": 0,
        "estimated_cost_usd": cost,
        "planned_model_calls": model_calls,
        "planned_api_calls": 2,
        "planned_github_jobs": 1,
    }

def main() -> None:
    cycles = [
        _cycle(1),
        _cycle(2, duplicate=True, cost=2.0),
        _cycle(3, result="INCONCLUSIVE", verified=False, deferred=True, cost=1.5),
    ]
    receipt = replay(cycles, {
        "candidate_id": "suppress-duplicates",
        "suppress_duplicate_candidates": True,
    })
    validate_replay_receipt(receipt)
    assert receipt["mode"] == "SHADOW_ONLY"
    assert receipt["promotion_allowed"] is False
    assert receipt["baseline"]["cycle_count"] == 3
    assert receipt["candidate"]["cycle_count"] == 2
    assert receipt["baseline"]["wasted_duplicate_work"] == 1
    assert receipt["candidate"]["wasted_duplicate_work"] == 0
    assert receipt["baseline"]["verified_outcomes"] == 2
    assert receipt["candidate"]["verified_outcomes"] == 1
    assert any(d["reason"] == "DUPLICATE_SUPPRESSED" for d in receipt["decisions"])
    print("policy replay validation: PASS")

if __name__ == "__main__":
    main()
