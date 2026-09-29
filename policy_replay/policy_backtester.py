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
import math
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any, Iterable
from verification.evidence import (canonical, digest, exact_sha, resolve_claim, EvidenceResolver)

ROOT = Path(__file__).resolve().parents[1]

class PolicyReplayError(ValueError):
    pass

def _req(ok: bool, msg: str) -> None:
    if not ok:
        raise PolicyReplayError(msg)

def _canon(value: Any) -> str:
    return canonical(value)

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
    for field in ("cycle_id", "proposal_id", "project_id", "source_id", "agent_id"):
        _req(isinstance(cycle[field], str) and bool(cycle[field]), f"{field} required")
    start = _time(cycle["started_at"], "started_at")
    end = _time(cycle["completed_at"], "completed_at")
    _req(end >= start, "cycle completes before it starts")
    for field in ("cost_usd","estimated_cost_usd"):
        _req(type(cycle[field]) in (int, float) and math.isfinite(cycle[field]) and cycle[field] >= 0, f"{field} invalid")
    for field in ("model_calls","api_calls","github_jobs","planned_model_calls","planned_api_calls","planned_github_jobs","authority_violations"):
        _req(type(cycle[field]) is int and cycle[field] >= 0, f"{field} invalid")
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

    for field in ("include_agents", "exclude_agents", "include_projects", "include_sources", "defer_candidate_ids"):
        if field in candidate:
            v = candidate[field]
            _req(isinstance(v, list) and all(isinstance(x, str) and x for x in v), f"{field} invalid")
            _req(len(v) == len(set(v)), f"{field} must be unique")
    if "suppress_duplicate_candidates" in candidate:
        _req(type(candidate["suppress_duplicate_candidates"]) is bool, "duplicate suppression must be boolean")
    for field in ("max_estimated_cost_usd", "max_planned_model_calls", "max_planned_api_calls", "max_planned_github_jobs"):
        if field in candidate:
            v = candidate[field]
            _req(type(v) in (int, float) and math.isfinite(v) and v >= 0, f"{field} invalid")
            if field != "max_estimated_cost_usd":
                _req(type(v) is int, f"{field} must be integer")
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
        "inconclusive_rate": None if not cycles else round(len(inconclusive)/len(cycles), 6),
        "deferred_work_rate": None if not cycles else round(len(deferred)/len(cycles), 6),
        "authority_violations": sum(c["authority_violations"] for c in cycles),
        "model_calls": sum(c["model_calls"] for c in cycles),
        "api_calls": sum(c["api_calls"] for c in cycles),
        "github_jobs": sum(c["github_jobs"] for c in cycles),
        "cost_usd": total_cost,
    }

def replay(cycles: Iterable[dict[str, Any]], candidate: dict[str, Any], *, provenance: dict[str, Any] | None = None) -> dict[str, Any]:
    policy = _load_policy()
    observed = deepcopy(list(cycles))
    candidate = deepcopy(candidate)
    _req(len(observed) <= 10000, "replay input bound exceeded")
    for cycle in observed:
        _validate_cycle(cycle)
    _req(len(observed) >= policy["minimum_completed_cycles"], "insufficient completed cycles for replay")
    _req(len({c["cycle_id"] for c in observed}) == len(observed), "duplicate cycle_id")
    ordered = sorted(observed, key=lambda c: (_time(c["completed_at"], "completed_at"), c["cycle_id"]))
    provenance = deepcopy(provenance) if provenance is not None else {
        "input_ref": None, "source_revision_sha": None, "evaluator_revision_sha": None,
    }
    _req(isinstance(provenance, dict) and set(provenance) == {"input_ref", "source_revision_sha", "evaluator_revision_sha"}, "provenance fields changed")
    if any(v is not None for v in provenance.values()):
        _req(isinstance(provenance["input_ref"], str) and bool(provenance["input_ref"]), "input evidence reference required")
        _req(exact_sha(provenance["source_revision_sha"]) and exact_sha(provenance["evaluator_revision_sha"]), "exact source/evaluator revisions required")

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
        "schema_version": "2.0.0",
        "mode": "SHADOW_ONLY",
        "input_evidence_state": "UNVERIFIED_UNTIL_RESOLVED",
        "input_cycles": ordered,
        "candidate_policy": candidate,
        "provenance": provenance,
        "input_manifest_hash": _hash(ordered),
        "evaluation_contract_hash": _hash(policy),
        "opportunity_count": len(ordered),
        "excluded_cycle_count": len(ordered) - len(admitted),
        "admission_coverage": round(len(admitted) / len(ordered), 6),
        "exclusion_rate": round((len(ordered) - len(admitted)) / len(ordered), 6),
        "historical_authority_violations": baseline_metrics["authority_violations"],
        "unexecuted_alternative_outcomes": "UNKNOWN",
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
    """Recompute every derived field; this is not proof of input authenticity."""
    _req(isinstance(receipt, dict), "replay receipt must be object")
    _req(receipt.get("schema_version") == "2.0.0", "legacy/incomplete replay cannot enter trusted consumption")
    _req(receipt.get("mode") == "SHADOW_ONLY", "historical replay must remain shadow-only")
    _req(receipt.get("promotion_allowed") is False, "historical replay cannot promote a policy")
    _req(receipt.get("forward_canary_required") is True, "forward canary requirement missing")
    _req(all(k in receipt for k in ("input_cycles", "candidate_policy", "provenance")), "replay source material missing")
    expected = replay(receipt["input_cycles"], receipt["candidate_policy"], provenance=receipt["provenance"])
    _req(_canon(receipt) == _canon(expected), "replay source/summary/hash contradiction")


def verify_replay_inputs(receipt: dict[str, Any], resolver: EvidenceResolver | None, subject: dict[str, Any]) -> str:
    validate_replay_receipt(receipt)
    _req(receipt["candidate_id"] == subject["candidate_id"], "replay candidate mismatch")
    _req(receipt["candidate_policy_hash"] == subject["candidate_policy_hash"], "replay policy mismatch")
    _req(receipt["provenance"]["source_revision_sha"] == subject["source_revision_sha"], "replay source revision mismatch")
    _req(receipt["provenance"]["evaluator_revision_sha"] == subject["evaluator_revision_sha"], "replay evaluator revision mismatch")
    evidence = resolve_claim(resolver, receipt["provenance"]["input_ref"], kind="REPLAY_INPUTS", subject=subject)
    measurements = evidence.record["measurements"]
    _req(set(measurements) == {"cycles", "candidate_policy", "decision_inputs"}, "replay measurements missing")
    _req(_canon(measurements["cycles"]) == _canon(receipt["input_cycles"]), "source cycles mismatch")
    _req(_canon(measurements["candidate_policy"]) == _canon(receipt["candidate_policy"]), "source policy mismatch")
    decisions = measurements["decision_inputs"]
    _req(isinstance(decisions, dict) and set(decisions) == {c["cycle_id"] for c in receipt["input_cycles"]}, "decision-time coverage incomplete")
    fields = ("cycle_id", "proposal_id", "project_id", "source_id", "agent_id", "estimated_cost_usd", "planned_model_calls", "planned_api_calls", "planned_github_jobs", "duplicate_candidate")
    for cycle in receipt["input_cycles"]:
        decision = decisions[cycle["cycle_id"]]
        _req(set(decision) == {"recorded_at", "input_hash"}, "decision snapshot schema invalid")
        _req(_time(decision["recorded_at"], "recorded_at") <= _time(cycle["started_at"], "started_at"), "decision inputs recorded after execution")
        _req(decision["input_hash"] == _hash({k: cycle[k] for k in fields}), "decision-time input hash mismatch")
    return evidence.scope
