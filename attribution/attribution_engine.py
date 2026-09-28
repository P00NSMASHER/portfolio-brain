#!/usr/bin/env python3
"""Deterministic attribution across Portfolio Brain's value chain.

This module reports transparent evidence dimensions only. It does not produce a
weighted/composite score, rank, allocation, promotion, or execution authority.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
STAGES = (
    "HUNTER_DISCOVERY","PROPOSAL","EXPERIMENT","IMPLEMENTATION",
    "VERIFIED_OUTCOME","COMMERCIAL_EVIDENCE",
)
STAGE_INDEX = {name: i for i, name in enumerate(STAGES)}
EVIDENCE_STATES = {"OBSERVED","VERIFIED","INFERRED","UNKNOWN","CONTRADICTED","STALE","INVALID"}
RESULTS = {"PASSED","FAILED","INCONCLUSIVE","INVALID","NOT_APPLICABLE"}

class AttributionError(ValueError):
    pass

def _req(ok: bool, msg: str) -> None:
    if not ok:
        raise AttributionError(msg)

def _canon(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

def _hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canon(value).encode("utf-8")).hexdigest()

def _time(value: str, field: str) -> datetime:
    _req(isinstance(value, str) and value, f"{field} required")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AttributionError(f"{field} invalid ISO-8601") from exc
    _req(dt.tzinfo is not None, f"{field} requires timezone")
    return dt

def _validate_record(record: dict[str, Any]) -> None:
    required = {
        "record_id","parent_id","stage","project_id","agent_id","source_id",
        "event_time","evidence_state","result","cost_usd","model_calls",
        "failure_cause","provenance_refs",
    }
    _req(isinstance(record, dict) and set(record) == required, "attribution record fields changed")
    _req(isinstance(record["record_id"], str) and record["record_id"], "record_id required")
    _req(record["parent_id"] is None or (isinstance(record["parent_id"], str) and record["parent_id"]), "parent_id invalid")
    _req(record["stage"] in STAGE_INDEX, "stage invalid")
    _req(isinstance(record["project_id"], str) and record["project_id"].startswith("PRJ-"), "project_id invalid")
    _req(isinstance(record["agent_id"], str) and record["agent_id"], "agent_id required")
    _req(isinstance(record["source_id"], str) and record["source_id"], "source_id required")
    _time(record["event_time"], "event_time")
    _req(record["evidence_state"] in EVIDENCE_STATES, "evidence_state invalid")
    _req(record["result"] in RESULTS, "result invalid")
    _req(isinstance(record["cost_usd"], (int, float)) and record["cost_usd"] >= 0, "cost_usd invalid")
    _req(type(record["model_calls"]) is int and record["model_calls"] >= 0, "model_calls invalid")
    _req(record["failure_cause"] is None or (isinstance(record["failure_cause"], str) and record["failure_cause"]), "failure_cause invalid")
    refs = record["provenance_refs"]
    _req(isinstance(refs, list) and refs and len(refs) == len(set(refs)), "provenance_refs required and unique")
    _req(all(isinstance(ref, str) and ref for ref in refs), "invalid provenance_ref")
    if record["stage"] in {"VERIFIED_OUTCOME","COMMERCIAL_EVIDENCE"}:
        _req(record["evidence_state"] == "VERIFIED", f"{record['stage']} must be VERIFIED")
    if record["stage"] == "VERIFIED_OUTCOME":
        _req(record["result"] in {"PASSED","FAILED"}, "verified outcome must be definitive")

def _validated(records: Iterable[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, list[str]]]:
    rows = [dict(r) for r in records]
    _req(rows, "attribution requires records")
    by_id: dict[str, dict[str, Any]] = {}
    children: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        _validate_record(row)
        _req(row["record_id"] not in by_id, "duplicate record_id")
        by_id[row["record_id"]] = row
    for row in rows:
        parent = row["parent_id"]
        if parent is None:
            _req(row["stage"] == "HUNTER_DISCOVERY", "root attribution record must be HUNTER_DISCOVERY")
            continue
        _req(parent in by_id, "parent attribution record missing")
        p = by_id[parent]
        _req(STAGE_INDEX[p["stage"]] < STAGE_INDEX[row["stage"]], "attribution stage cannot move backward or sideways")
        _req(p["project_id"] == row["project_id"], "project identity changed across attribution chain")
        _req(_time(p["event_time"], "parent event_time") <= _time(row["event_time"], "event_time"), "child predates parent")
        children[parent].append(row["record_id"])
    return sorted(rows, key=lambda r: (r["event_time"], r["record_id"])), by_id, children

def _descendants(record_id: str, children: dict[str, list[str]]) -> set[str]:
    seen: set[str] = set()
    stack = list(children.get(record_id, []))
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        stack.extend(children.get(current, []))
    return seen

def _root_time(record: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> datetime:
    current = record
    seen: set[str] = set()
    while current["parent_id"] is not None:
        _req(current["record_id"] not in seen, "attribution parent cycle")
        seen.add(current["record_id"])
        current = by_id[current["parent_id"]]
    return _time(current["event_time"], "root event_time")

def _ratio(num: int, den: int) -> float | None:
    return None if den == 0 else round(num / den, 6)

def _profile(rows: list[dict[str, Any]], all_by_id: dict[str, dict[str, Any]], children: dict[str, list[str]]) -> dict[str, Any]:
    ids = {r["record_id"] for r in rows}
    verified_outcomes = [r for r in rows if r["stage"] == "VERIFIED_OUTCOME" and r["evidence_state"] == "VERIFIED"]
    total_cost = round(sum(float(r["cost_usd"]) for r in rows), 6)
    total_model_calls = sum(r["model_calls"] for r in rows)

    proposals = [r for r in rows if r["stage"] == "PROPOSAL"]
    experiments = [r for r in rows if r["stage"] == "EXPERIMENT"]
    implementations = [r for r in rows if r["stage"] == "IMPLEMENTATION"]
    discoveries = [r for r in rows if r["stage"] == "HUNTER_DISCOVERY"]

    proposal_with_experiment = 0
    for proposal in proposals:
        if any(all_by_id[d]["stage"] == "EXPERIMENT" for d in _descendants(proposal["record_id"], children)):
            proposal_with_experiment += 1

    implementation_successes = 0
    for implementation in implementations:
        if any(
            all_by_id[d]["stage"] == "VERIFIED_OUTCOME" and all_by_id[d]["result"] == "PASSED"
            for d in _descendants(implementation["record_id"], children)
        ):
            implementation_successes += 1

    discovery_with_proposal = 0
    for discovery in discoveries:
        if any(all_by_id[d]["stage"] == "PROPOSAL" for d in _descendants(discovery["record_id"], children)):
            discovery_with_proposal += 1

    durations = [
        (_time(outcome["event_time"], "event_time") - _root_time(outcome, all_by_id)).total_seconds() / 3600
        for outcome in verified_outcomes
    ]
    result_counts = Counter(r["result"] for r in experiments)
    failure_counts = Counter(r["failure_cause"] for r in rows if r["failure_cause"])

    return {
        "record_count": len(rows),
        "verified_outcomes": len(verified_outcomes),
        "total_cost_usd": total_cost,
        "total_model_calls": total_model_calls,
        "verified_outcomes_per_dollar": None if total_cost == 0 else round(len(verified_outcomes) / total_cost, 6),
        "verified_outcomes_per_model_call": None if total_model_calls == 0 else round(len(verified_outcomes) / total_model_calls, 6),
        "median_time_to_evidence_hours": None if not durations else round(float(median(durations)), 6),
        "proposal_count": len(proposals),
        "experiment_count": len(experiments),
        "implementation_count": len(implementations),
        "proposal_to_experiment_conversion": _ratio(proposal_with_experiment, len(proposals)),
        "implementation_success_rate": _ratio(implementation_successes, len(implementations)),
        "source_discovery_yield": _ratio(discovery_with_proposal, len(discoveries)),
        "experiment_result_ratios": {
            result: _ratio(result_counts[result], len(experiments))
            for result in ("PASSED","FAILED","INCONCLUSIVE","INVALID")
        },
        "recurring_failure_causes": [
            {"failure_cause": cause, "count": count}
            for cause, count in sorted(failure_counts.items(), key=lambda item: (-item[1], item[0]))
        ],
        "evidence_record_ids": sorted(ids),
    }

def build_attribution_snapshot(records: Iterable[dict[str, Any]], generated_at: str | None = None) -> dict[str, Any]:
    rows, by_id, children = _validated(records)
    group_fields = ("agent_id","project_id","source_id")
    groups: dict[str, dict[str, Any]] = {}
    for field in group_fields:
        bucket: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            bucket[row[field]].append(row)
        groups[field] = {key: _profile(bucket[key], by_id, children) for key in sorted(bucket)}

    body = {
        "schema_version": "1.0.0",
        "generated_at": generated_at,
        "mode": "ADVISORY_EVIDENCE_ONLY",
        "opaque_score_used": False,
        "record_count": len(rows),
        "groups": groups,
        "global_profile": _profile(rows, by_id, children),
        "limitations": [
            "Attribution describes observed evidence chains; it does not establish causality by itself.",
            "No weighted/composite score or automatic ranking is produced.",
            "Missing links remain missing rather than being inferred.",
        ],
    }
    return {**body, "attribution_hash": _hash(body)}

def allocator_dimensions(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    _req(snapshot.get("mode") == "ADVISORY_EVIDENCE_ONLY", "invalid attribution snapshot")
    _req(snapshot.get("opaque_score_used") is False, "opaque attribution score forbidden")
    projects = snapshot["groups"]["project_id"]
    allowed = (
        "verified_outcomes","verified_outcomes_per_dollar","verified_outcomes_per_model_call",
        "median_time_to_evidence_hours","proposal_to_experiment_conversion",
        "implementation_success_rate","source_discovery_yield","experiment_result_ratios",
        "recurring_failure_causes","evidence_record_ids",
    )
    return {project_id: {key: profile[key] for key in allowed} for project_id, profile in projects.items()}

def validate_snapshot(snapshot: dict[str, Any]) -> None:
    _req(snapshot.get("mode") == "ADVISORY_EVIDENCE_ONLY", "attribution mode changed")
    _req(snapshot.get("opaque_score_used") is False, "opaque score introduced")
    _req(set(snapshot.get("groups", {})) == {"agent_id","project_id","source_id"}, "attribution group dimensions changed")
    body = dict(snapshot)
    given = body.pop("attribution_hash", None)
    _req(given == _hash(body), "attribution_hash mismatch")
