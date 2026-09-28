#!/usr/bin/env python3
from __future__ import annotations

from attribution.attribution_engine import allocator_dimensions, build_attribution_snapshot, validate_snapshot

def row(record_id, parent_id, stage, hour, *, result="NOT_APPLICABLE", evidence="OBSERVED", cost=0.0, calls=0, failure=None, source="SRC-A"):
    return {
        "record_id": record_id,
        "parent_id": parent_id,
        "stage": stage,
        "project_id": "PRJ-001",
        "agent_id": "Hunter" if stage in {"HUNTER_DISCOVERY","PROPOSAL"} else "Engineer",
        "source_id": source,
        "event_time": f"2026-09-20T{hour:02d}:00:00+00:00",
        "evidence_state": evidence,
        "result": result,
        "cost_usd": cost,
        "model_calls": calls,
        "failure_cause": failure,
        "provenance_refs": [f"evidence:{record_id}"],
    }

def main() -> None:
    rows = [
        row("D1", None, "HUNTER_DISCOVERY", 8),
        row("P1", "D1", "PROPOSAL", 9),
        row("E1", "P1", "EXPERIMENT", 10, result="PASSED", cost=1.0, calls=2),
        row("I1", "E1", "IMPLEMENTATION", 11, cost=0.5, calls=1),
        row("O1", "I1", "VERIFIED_OUTCOME", 12, result="PASSED", evidence="VERIFIED"),
        row("C1", "O1", "COMMERCIAL_EVIDENCE", 13, evidence="VERIFIED"),
    ]
    snap = build_attribution_snapshot(rows, generated_at="2026-09-20T14:00:00+00:00")
    validate_snapshot(snap)
    dims = allocator_dimensions(snap)
    profile = dims["PRJ-001"]
    assert profile["verified_outcomes"] == 1
    assert profile["proposal_to_experiment_conversion"] == 1.0
    assert profile["implementation_success_rate"] == 1.0
    assert profile["source_discovery_yield"] == 1.0
    assert snap["opaque_score_used"] is False
    print("attribution validation: PASS")

if __name__ == "__main__":
    main()
