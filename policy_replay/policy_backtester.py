#!/usr/bin/env python3
"""Counterfactual replay over completed Portfolio Brain cycles.

The replay is deliberately conservative: it never invents outcomes for work that did not
actually run. A candidate policy can only include/exclude previously observed cycles using
fields that were available at decision time. Promotion is never granted here; historical
replay can only produce shadow evidence for a later forward canary.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]

class PolicyReplayError(ValueError):
    pass

def _req(ok: bool, msg: str) -> None:
    if not ok:
        raise PolicyReplayError(msg)

def _canon(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

def _hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canon(value).encode("utf-8")).hexdigest()

def _load_policy() -> dict[str, Any]:
    return json.loads((ROOT / "policy_replay" / "POLICY_REPLAY_POLICY.json").read_text())

def _time(value: str, field: str) -> datetime:
    _req(isinstance(value, str) and value, f"{field} required")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PolicyReplayError(f"{field} invalid ISO-8601") from exc
    _req(dt.tzinfo is not None, f"{field} requires timezone")
    return dt

def _validate_cycle(cycle: dict[str, Any]) -> None:
    required = {
        "cycle_id","proposal_id","project_id","source_id","agent_id",
        "started_at","completed_at","result","evidence_state","cost_usd",
        "model_calls","api_calls","github_jobs","duplicate_candidate",
        "deferred","authority_violations","estimated_cost_usd","planned_model_calls",
        "planned_api_calls","planned_github_jobs"
    }
    _req(isinstance(cycle, dict) and set(cycle) == required, "cycle fields changed")
    start = _time(cycle["started_at"], "started_at")
    end = _time(cycle["completed_at"], "completed_at")
    _req(end >= start, "cycle completes before it starts")
    for field in ("cost_usd","estimated_cost_usd"):
        _req(isinstance(cycle[field], (int, float)) and cycle[field] >= 0, f"{field} invalid")
    for field in ("model_calls","api_calls","github_jobs","planned_model_calls","planned_api_calls","planned_github_jobs","authority_violations"):
        _req(isinstance(cycle[field], int) and cycle[field] >= 0, f"{field} invalid")
    _req(isinstance(cycle["duplicate_candidate"], bool), "duplicate_candidate invalid")
    _req(isinstance(cycle["deferred"], bool), "deferred invalid")
    _req(cycle["result"] in {"PASSED","FAILED","INCONCLUSIVE","INVALID"}, "result invalid")
    _req(cycle["evidence_state"] in {"OBSERVED","VERIFIED","INFERRED","UNKNOWN","CONTRADICTED","STALE","INVALID"}, "evidence_state invalid")

def _candidate_admits(cycle: dict[str, Any], candidate: dict[str, Any]) -> tuple[bool, str]:
    """Return a decision using decision-time fields only."""
    allowed = {
        "candidate_id","include_agents","exclude_agents","include_projects","include_sources",
        "max_estimated_cost_usd","max_planned_model_calls","max_planned_api_calls",
        "max_planned_github_jobs","suppress_duplicate_candidates","defer_candidate_ids"
    }
    _req(isinstance(candidate, dict) and set(candidate).issubset(allowed), "candidate policy contains unsupported fields")
    _req(isinstance(candidate.get("candidate_id"), str) and candidate["candidate_id"], "candidate_id required")

    agent = cycle["agent_id"]
    project = cycle["project_id"]
    source = cycle["source_id"]
    if candidate.get("include_agents") is not None and agent not in candidate["include_agents"]:
        return False, "AGENT_NOT_INCLUDED"
    if agent in candidate.get("exclude_agents", []):
        return False, "AGENT_EXCLUDED"
    if candidate.get("include_projects") is not None and project not in candidate["include_projects"]:
        return False, "PROJECT_NOT_INCLUDED"
    if candidate.get("include_sources") is not None and source not in candidate["include_sources"]:
        return False, "SOURCE_NOT_INCLUDED"
    if cycle["estimated_cost_usd"] > candidate.get("max_estimated_cost_usd", float("inf")):
        return False, "ESTIMATED_COST_LIMIT"
    if cycle["planned_model_calls"] > candidate.get("max_planned_model_calls", 2**31-1):
        return False, "MODEL_CALL_LIMIT"
    if cycle["planned_api_calls"] > candidate.get("max_planned_api_calls", 2**31-1):
        return False, "API_CALL_LIMIT"
    if cycle["planned_github_jobs"] > candidate.get("max_planned_github_jobs", 2**31-1):
        return False, "GITHUB_JOB_LIMIT"
    if candidate.get("suppress_duplicate_candidates", False) and cycle["duplicate_candidate"]:
        return False, "DUPLICATE_SUPPRESSED"
    if cycle["cycle_id"] in candidate.get("defer_candidate_ids", []):
        return False, "CANDIDATE_DEFERRED"
    return True, "ADMITTED"

def _metrics(cycles: list[dict[str, Any]]) -> dict[str, Any]:
    verified = [c for c in cycles if c["evidence_state"] == "VERIFIED" and c["result"] in {"PASSED","FAILED"}]
    inconclusive = [c for c in cycles if c["result"] == "INCONCLUSIVE"]
    deferred = [c for c in cycles if c["deferred"]]
    durations = [(_time(c["completed_at"], "completed_at") - _time(c["started_at"], "started_at")).total_seconds()/3600 for c in verified]
    total_cost = round(sum(float(c["cost_usd"]) for c in cycles), 6)
    return {
        "cycle_count": len(cycles),
        "verified_outcomes": len(verified),
        "cost_per_verified_outcome_usd": None if not verified else round(total_cost / len(verified), 6),
        "median_time_to_evidence_hours": None if not durations else round(float(median(durations)), 6),
        "wasted_duplicate_work": sum(1 for c in cycles if c["duplicate_candidate"]),
        "inconclusive_rate": 0.0 if not cycles else round(len(inconclusive)/len(cycles), 6),
        "deferred_work_rate": 0.0 if not cycles else round(len(deferred)/len(cycles), 6),
        "authority_violations": sum(c["authority_violations"] for c in cycles),
        "model_calls": sum(c["model_calls"] for c in cycles),
        "api_calls": sum(c["api_calls"] for c in cycles),
        "github_jobs": sum(c["github_jobs"] for c in cycles),
        "cost_usd": total_cost,
    }

def replay(cycles: Iterable[dict[str, Any]], candidate: dict[str, Any]) -> dict[str, Any]:
    policy = _load_policy()
    observed = [dict(c) for c in cycles]
    for cycle in observed:
        _validate_cycle(cycle)
    _req(len(observed) >= policy["minimum_completed_cycles"], "insufficient completed cycles for replay")
    ordered = sorted(observed, key=lambda c: (c["completed_at"], c["cycle_id"]))

    admitted: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    for cycle in ordered:
        include, reason = _candidate_admits(cycle, candidate)
        decisions.append({"cycle_id": cycle["cycle_id"], "admitted": include, "reason": reason})
        if include:
            admitted.append(cycle)

    baseline_metrics = _metrics(ordered)
    candidate_metrics = _metrics(admitted)
    comparison = {
        key: {
            "baseline": baseline_metrics[key],
            "candidate": candidate_metrics[key]
        }
        for key in policy["comparison_metrics"]
    }
    body = {
        "schema_version": "1.0.0",
        "mode": "SHADOW_ONLY",
        "candidate_id": candidate["candidate_id"],
        "candidate_policy_hash": _hash(candidate),
        "completed_cycle_count": len(ordered),
        "admitted_cycle_count": len(admitted),
        "baseline": baseline_metrics,
        "candidate": candidate_metrics,
        "comparison": comparison,
        "decisions": decisions,
        "promotion_allowed": False,
        "forward_canary_required": bool(policy["promotion_requires_forward_canary"]),
        "limitations": [
            "Replay never fabricates outcomes for work that did not historically execute.",
            "Candidate decisions use decision-time fields only; result/evidence fields cannot influence admission.",
            "Historical replay is shadow evidence and cannot authorize production promotion."
        ]
    }
    return {**body, "replay_hash": _hash(body)}

def validate_replay_receipt(receipt: dict[str, Any]) -> None:
    _req(receipt.get("mode") == "SHADOW_ONLY", "historical replay must remain shadow-only")
    _req(receipt.get("promotion_allowed") is False, "historical replay cannot promote a policy")
    _req(receipt.get("forward_canary_required") is True, "forward canary requirement missing")
    body = dict(receipt)
    given = body.pop("replay_hash", None)
    _req(isinstance(given, str) and given == _hash(body), "replay_hash mismatch")
