#!/usr/bin/env python3
"""Fail-closed durable cost governor for model/API/GitHub execution."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
USAGE_FIELDS = (
    "cost_usd",
    "input_tokens",
    "output_tokens",
    "model_calls",
    "api_calls",
    "github_job_starts",
    "github_runner_minutes",
)
RESOURCE_KINDS = {"MODEL_CALL", "API_CALL", "GITHUB_JOB"}
AUTHORITY_CLASSES = {"NONE", "OBSERVE", "EXPERIMENT", "MODIFY", "ACT"}
DATA_CLASSES = {"PUBLIC", "SANITIZED", "PRIVATE_REFERENCE_ONLY"}

class CostGovernorError(ValueError):
    pass

def req(ok: bool, msg: str) -> None:
    if not ok:
        raise CostGovernorError(msg)

def load(path: str | Path) -> Any:
    p = Path(path)
    if not p.is_absolute():
        p = ROOT / p
    return json.loads(p.read_text())

def policy() -> dict[str, Any]:
    return load("cost_governor/COST_GOVERNOR_POLICY.json")

def canon(v: Any) -> str:
    return json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

def hashv(v: Any) -> str:
    return "sha256:" + hashlib.sha256(canon(v).encode()).hexdigest()

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def _time(v: str, field: str) -> datetime:
    req(isinstance(v, str) and v, f"{field} required")
    try:
        dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CostGovernorError(f"{field} invalid ISO-8601") from exc
    req(dt.tzinfo is not None, f"{field} requires timezone")
    return dt.astimezone(timezone.utc)

def zero_usage() -> dict[str, int | float]:
    return {
        "cost_usd": 0.0,
        "input_tokens": 0,
        "output_tokens": 0,
        "model_calls": 0,
        "api_calls": 0,
        "github_job_starts": 0,
        "github_runner_minutes": 0,
    }

def validate_usage(usage: dict[str, Any]) -> None:
    req(isinstance(usage, dict) and set(usage) == set(USAGE_FIELDS), "usage fields changed")
    cost = usage["cost_usd"]
    req(type(cost) in {int, float} and math.isfinite(float(cost)) and float(cost) >= 0, "invalid cost_usd")
    for field in USAGE_FIELDS[1:]:
        req(type(usage[field]) is int and usage[field] >= 0, f"invalid {field}")

def _add_usage(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    return {field: a[field] + b[field] for field in USAGE_FIELDS}

def _budget_dict(v: Any, label: str) -> dict[str, Any]:
    req(isinstance(v, dict) and set(v) == set(USAGE_FIELDS), f"{label} budget fields changed")
    validate_usage(v)
    return v

def validate_policy(p: dict[str, Any] | None = None) -> None:
    p = p or policy()
    req(p["schema_version"] == "1.0.0", "cost policy schema mismatch")
    req(p["mode"] == "FAIL_CLOSED_PRE_EXECUTION_RESERVATION", "cost governor mode weakened")
    req(p["authority_class"] == "NONE", "cost governor may not hold authority")
    req(p["accounting_window"] == "UTC_CALENDAR_DAY", "unexpected accounting window")
    _budget_dict(p["portfolio_ceiling"], "portfolio")
    _budget_dict(p["project_default_ceiling"], "project default")
    _budget_dict(p["provider_model_default_ceiling"], "provider/model default")
    for key, value in p["project_overrides"].items():
        req(isinstance(key, str) and key, "invalid project override key")
        _budget_dict(value, f"project {key}")
    for key, value in p["provider_model_overrides"].items():
        req("::" in key, "provider/model override key invalid")
        _budget_dict(value, f"provider/model {key}")
    for key, value in p["workflow_job_ceilings"].items():
        req("::" in key, "workflow/job ceiling key invalid")
        _budget_dict(value["daily_ceiling"], f"workflow/job {key}")
        req(type(value["max_minutes_per_job"]) is int and value["max_minutes_per_job"] > 0, "invalid max minutes per job")
    req(set(p["retry_limits"]) == RESOURCE_KINDS, "retry limit kinds changed")
    req(all(type(v) is int and v >= 1 for v in p["retry_limits"].values()), "retry limits invalid")
    req(type(p["max_state_records"]) is int and p["max_state_records"] >= 100, "state record ceiling too small")
    req(type(p["recent_decision_limit"]) is int and p["recent_decision_limit"] >= 20, "decision retention too small")
    req(p["global_concurrency_group"] == "portfolio-cost-governed-autonomy", "global cost concurrency group changed")
    # Paid/model/API execution may be enabled, but only under finite checked-in
    # ceilings. Provider/model routing and pre-execution reservations remain
    # independent gates, so budget capacity alone never creates an executable route.
    for field in ("cost_usd", "input_tokens", "output_tokens", "model_calls", "api_calls"):
        value=p["portfolio_ceiling"][field]
        req(type(value) in {int,float} and math.isfinite(float(value)) and float(value)>=0,
            f"checked-in portfolio {field} budget must be finite and nonnegative")

def validate_request(r: dict[str, Any]) -> None:
    required = {
        "schema_version", "request_id", "idempotency_key", "retry_group", "attempt",
        "resource_kind", "project_ids", "provider_id", "model_id", "workflow_id", "job_id",
        "authority_class", "data_classification", "estimated_usage", "evidence_refs", "requested_at",
    }
    req(isinstance(r, dict) and set(r) == required, "cost request fields changed")
    req(r["schema_version"] == "1.0.0", "cost request schema mismatch")
    req(isinstance(r["request_id"], str) and r["request_id"].startswith("CGR-"), "invalid cost request id")
    for key in ("idempotency_key", "retry_group"):
        req(isinstance(r[key], str) and r[key], f"{key} required")
    req(type(r["attempt"]) is int and r["attempt"] >= 1, "attempt invalid")
    req(r["resource_kind"] in RESOURCE_KINDS, "resource kind invalid")
    req(isinstance(r["project_ids"], list) and r["project_ids"] and len(r["project_ids"]) == len(set(r["project_ids"])), "project_ids invalid")
    req(all(isinstance(x, str) and x for x in r["project_ids"]), "project_id invalid")
    req(r["authority_class"] in AUTHORITY_CLASSES, "authority class invalid")
    req(r["data_classification"] in DATA_CLASSES, "data classification invalid")
    validate_usage(r["estimated_usage"])
    req(isinstance(r["evidence_refs"], list) and r["evidence_refs"] and all(isinstance(x, str) and x for x in r["evidence_refs"]), "sanitized evidence refs required")
    req(r["idempotency_key"]==f'{r["retry_group"]}:attempt:{r["attempt"]}',"idempotency key must bind retry group and attempt")
    _time(r["requested_at"], "requested_at")
    usage = r["estimated_usage"]
    if r["resource_kind"] == "MODEL_CALL":
        req(isinstance(r["provider_id"], str) and r["provider_id"], "model call provider required")
        req(isinstance(r["model_id"], str) and r["model_id"], "model call model required")
        route_refs=[x[6:] for x in r["evidence_refs"] if x.startswith("route:")]
        req(len(route_refs)==1 and route_refs[0],"model call requires exactly one route evidence ref")
        req(r["retry_group"]==f"model:{route_refs[0]}","model retry group must bind routed identity")
        req(r["workflow_id"] is None and r["job_id"] is None, "model call may not claim workflow/job scope")
        req(usage["model_calls"] == 1 and usage["api_calls"] == 1, "model call must reserve one model/API call")
        req(usage["github_job_starts"] == 0 and usage["github_runner_minutes"] == 0, "model call may not reserve GitHub usage")
    elif r["resource_kind"] == "API_CALL":
        req(isinstance(r["provider_id"], str) and r["provider_id"], "API provider required")
        req(r["model_id"] is None, "generic API call model_id must be null")
        op_refs=[x[len("api-operation:"):] for x in r["evidence_refs"] if x.startswith("api-operation:")]
        req(len(op_refs)==1 and op_refs[0],"API call requires exactly one stable api-operation evidence ref")
        req(r["retry_group"]==f"api:{op_refs[0]}","API retry group must bind stable operation identity")
        req(r["workflow_id"] is None and r["job_id"] is None, "API call may not claim workflow/job scope")
        req(usage["api_calls"] == 1 and usage["model_calls"] == 0, "API call usage invalid")
        req(usage["github_job_starts"] == 0 and usage["github_runner_minutes"] == 0, "API call may not reserve GitHub usage")
    else:
        req(r["provider_id"] is None and r["model_id"] is None, "GitHub job provider/model must be null")
        req(isinstance(r["workflow_id"], str) and r["workflow_id"], "workflow_id required")
        req(isinstance(r["job_id"], str) and r["job_id"], "job_id required")
        run_refs=[x[len("github-run:"):] for x in r["evidence_refs"] if x.startswith("github-run:")]
        req(len(run_refs)==1 and run_refs[0],"GitHub job requires exactly one github-run evidence ref")
        req(r["retry_group"]==f'github-job:{run_refs[0]}:{r["job_id"]}',"GitHub retry group must bind run and job identity")
        req(usage["github_job_starts"] == 1 and usage["github_runner_minutes"] > 0, "GitHub job usage invalid")
        req(all(usage[x] == 0 for x in ("cost_usd", "input_tokens", "output_tokens", "model_calls", "api_calls")), "GitHub job cannot reserve model/API usage")

def validate_state(state: dict[str, Any], p: dict[str, Any] | None = None) -> None:
    p = p or policy()
    required = {"schema_version", "state_id", "sequence", "updated_at", "reservations", "recent_decisions"}
    req(isinstance(state, dict) and set(state) == required, "cost state fields changed")
    req(state["schema_version"] == "1.0.0" and state["state_id"] == "portfolio-cost-governor-state", "cost state identity mismatch")
    req(type(state["sequence"]) is int and state["sequence"] >= 0, "cost state sequence invalid")
    if state["updated_at"] is not None:
        _time(state["updated_at"], "state updated_at")
    req(isinstance(state["reservations"], list) and len(state["reservations"]) <= p["max_state_records"], "cost reservation ledger invalid")
    req(isinstance(state["recent_decisions"], list) and len(state["recent_decisions"]) <= p["recent_decision_limit"], "cost decision ledger invalid")
    seen_res: set[str] = set()
    seen_idem: set[str] = set()
    for row in state["reservations"]:
        fields = {
            "reservation_id", "request_id", "request_hash", "idempotency_key", "retry_group", "attempt",
            "resource_kind", "project_ids", "provider_id", "model_id", "workflow_id", "job_id",
            "estimated_usage", "actual_usage", "status", "created_at", "expires_at", "committed_at", "evidence_refs",
        }
        req(isinstance(row, dict) and set(row) == fields, "reservation fields changed")
        req(row["reservation_id"].startswith("CRES-") and row["reservation_id"] not in seen_res, "reservation id invalid/duplicate")
        seen_res.add(row["reservation_id"])
        req(row["idempotency_key"] not in seen_idem, "idempotency key duplicated in ledger")
        seen_idem.add(row["idempotency_key"])
        req(row["status"] in {"RESERVED", "COMMITTED", "CANCELLED", "EXPIRED", "OVERAGE"}, "reservation status invalid")
        validate_usage(row["estimated_usage"])
        if row["actual_usage"] is not None:
            validate_usage(row["actual_usage"])
        _time(row["created_at"], "reservation created_at")
        _time(row["expires_at"], "reservation expires_at")
        if row["committed_at"] is not None:
            _time(row["committed_at"], "reservation committed_at")
        req(isinstance(row["evidence_refs"], list) and all(isinstance(x, str) for x in row["evidence_refs"]), "reservation evidence refs invalid")

def load_state(path: str | Path | None = None) -> dict[str, Any]:
    if path is not None and Path(path).exists():
        state = json.loads(Path(path).read_text())
    else:
        state = load("cost_governor/COST_STATE_SEED.json")
    validate_state(state)
    return state

def killed(p: dict[str, Any] | None = None) -> tuple[bool, str | None]:
    p = p or policy()
    kill = load(p["kill_switches"]["file"])
    if kill.get("spend_disabled") is True:
        return True, kill.get("reason") or "file spend kill switch"
    env_name = p["kill_switches"]["repository_variable"]
    if os.environ.get(env_name, "").strip().lower() == "true":
        return True, "repository/environment spend kill switch"
    return False, None

def _day(v: str) -> str:
    return _time(v, "timestamp").date().isoformat()

def _expire_and_compact(state: dict[str, Any], at: str, p: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(state)
    now = _time(at, "at")
    for row in out["reservations"]:
        if row["status"] == "RESERVED" and _time(row["expires_at"], "expires_at") <= now:
            row["status"] = "EXPIRED"
    cutoff = now - timedelta(days=p["state_retention_days"])
    out["reservations"] = [
        row for row in out["reservations"]
        if row["status"] == "RESERVED" or _time(row["created_at"], "created_at") >= cutoff
    ]
    return out

def _usage_for(state: dict[str, Any], at: str, predicate) -> dict[str, Any]:
    total = zero_usage()
    today = _day(at)
    now = _time(at, "at")
    for row in state["reservations"]:
        if _day(row["created_at"]) != today or not predicate(row):
            continue
        usage = None
        if row["status"] == "RESERVED" and _time(row["expires_at"], "expires_at") > now:
            usage = row["estimated_usage"]
        elif row["status"] == "EXPIRED":
            # Fail closed after a crash: unknown execution is charged at the reserved
            # maximum for the remainder of the accounting day.
            usage = row["estimated_usage"]
        elif row["status"] in {"COMMITTED", "OVERAGE"}:
            usage = row["actual_usage"] or row["estimated_usage"]
        if usage is not None:
            total = _add_usage(total, usage)
    return total

def _breaches(used: dict[str, Any], estimate: dict[str, Any], ceiling: dict[str, Any], label: str) -> list[str]:
    out = []
    for field in USAGE_FIELDS:
        if used[field] + estimate[field] > ceiling[field] + (1e-12 if field == "cost_usd" else 0):
            out.append(f"BUDGET_EXCEEDED:{label}:{field}")
    return out

def _decision(request: dict[str, Any], at: str, status: str, reasons: list[str], reservation_id: str | None, can_execute: bool) -> dict[str, Any]:
    core = {
        "schema_version": "1.0.0",
        "decision_id": "CGD-" + hashlib.sha256((request["request_id"] + "\0" + at + "\0" + status).encode()).hexdigest()[:20].upper(),
        "request_id": request["request_id"],
        "request_hash": hashv(request),
        "status": status,
        "reason_codes": list(dict.fromkeys(reasons)),
        "reservation_id": reservation_id,
        "can_execute": bool(can_execute),
        "authority_granted": False,
        "decided_at": at,
    }
    return {**core, "decision_hash": hashv(core)}

def _append_decision(state: dict[str, Any], decision: dict[str, Any], p: dict[str, Any]) -> None:
    state["recent_decisions"] = ([*state["recent_decisions"], decision])[-p["recent_decision_limit"]:]

def _finish_state(state: dict[str, Any], at: str, p: dict[str, Any]) -> dict[str, Any]:
    state["sequence"] += 1
    state["updated_at"] = at
    validate_state(state, p)
    return state

def preflight(state: dict[str, Any], request: dict[str, Any], *, at: str | None = None, policy_data: dict[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    p = copy.deepcopy(policy_data or policy())
    validate_policy(p)
    validate_state(state, p)
    validate_request(request)
    at = at or request["requested_at"] or now_iso()
    _time(at, "at")
    out = _expire_and_compact(state, at, p)
    request_hash = hashv(request)

    existing = next((row for row in out["reservations"] if row["idempotency_key"] == request["idempotency_key"]), None)
    if existing is not None:
        if existing["request_hash"] != request_hash:
            d = _decision(request, at, "BLOCKED_IDEMPOTENCY_COLLISION", ["IDEMPOTENCY_KEY_REUSED_FOR_DIFFERENT_REQUEST"], None, False)
        else:
            d = _decision(request, at, "DUPLICATE_SUPPRESSED", ["EXISTING_RESERVATION_OR_CONSUMPTION"], existing["reservation_id"], False)
        _append_decision(out, d, p)
        return _finish_state(out, at, p), d

    is_killed, kill_reason = killed(p)
    if is_killed:
        d = _decision(request, at, "BLOCKED_KILL_SWITCH", ["SPEND_KILL_SWITCH", kill_reason or "kill switch"], None, False)
        _append_decision(out, d, p)
        return _finish_state(out, at, p), d
    if request["authority_class"] == "ACT":
        d = _decision(request, at, "BLOCKED_AUTHORITY", ["COST_BUDGET_CANNOT_AUTHORIZE_ACT"], None, False)
        _append_decision(out, d, p)
        return _finish_state(out, at, p), d

    max_attempts = p["retry_limits"][request["resource_kind"]]
    group_rows = [row for row in out["reservations"] if row["retry_group"] == request["retry_group"]]
    prior_attempts = sorted({row["attempt"] for row in group_rows})
    retry_reasons: list[str] = []
    if request["attempt"] > max_attempts:
        retry_reasons.append("RETRY_LIMIT_EXCEEDED")
    if not prior_attempts and request["attempt"] != 1:
        retry_reasons.append("RETRY_SEQUENCE_MUST_START_AT_ONE")
    if prior_attempts and request["attempt"] != max(prior_attempts) + 1:
        retry_reasons.append("RETRY_SEQUENCE_GAP_OR_RESET")
    if retry_reasons:
        d = _decision(request, at, "BLOCKED_RETRY_LIMIT", retry_reasons, None, False)
        _append_decision(out, d, p)
        return _finish_state(out, at, p), d

    estimate = request["estimated_usage"]
    reasons: list[str] = []
    portfolio_used = _usage_for(out, at, lambda row: True)
    reasons += _breaches(portfolio_used, estimate, p["portfolio_ceiling"], "portfolio")

    for project_id in request["project_ids"]:
        ceiling = p["project_overrides"].get(project_id, p["project_default_ceiling"])
        used = _usage_for(out, at, lambda row, project_id=project_id: project_id in row["project_ids"])
        reasons += _breaches(used, estimate, ceiling, f"project:{project_id}")

    if request["resource_kind"] in {"MODEL_CALL", "API_CALL"}:
        key = f'{request["provider_id"]}::{request["model_id"] or "NONE"}'
        ceiling = p["provider_model_overrides"].get(key, p["provider_model_default_ceiling"])
        used = _usage_for(out, at, lambda row, key=key: f'{row["provider_id"]}::{row["model_id"] or "NONE"}' == key)
        reasons += _breaches(used, estimate, ceiling, f"provider_model:{key}")

    if request["resource_kind"] == "GITHUB_JOB":
        key = f'{request["workflow_id"]}::{request["job_id"]}'
        cfg = p["workflow_job_ceilings"].get(key)
        if cfg is None:
            reasons.append(f"UNCONFIGURED_WORKFLOW_JOB:{key}")
        else:
            if estimate["github_runner_minutes"] > cfg["max_minutes_per_job"]:
                reasons.append(f"JOB_MINUTE_CEILING_EXCEEDED:{key}")
            used = _usage_for(out, at, lambda row, key=key: f'{row["workflow_id"]}::{row["job_id"]}' == key)
            reasons += _breaches(used, estimate, cfg["daily_ceiling"], f"workflow_job:{key}")

    if reasons:
        d = _decision(request, at, "BLOCKED_BUDGET", reasons, None, False)
        _append_decision(out, d, p)
        return _finish_state(out, at, p), d

    ttl = p["reservation_ttl_seconds"][request["resource_kind"]]
    expires = (_time(at, "at") + timedelta(seconds=ttl)).isoformat().replace("+00:00", "Z")
    reservation_core = {
        "request_id": request["request_id"],
        "request_hash": request_hash,
        "idempotency_key": request["idempotency_key"],
        "retry_group": request["retry_group"],
        "attempt": request["attempt"],
        "resource_kind": request["resource_kind"],
        "project_ids": list(request["project_ids"]),
        "provider_id": request["provider_id"],
        "model_id": request["model_id"],
        "workflow_id": request["workflow_id"],
        "job_id": request["job_id"],
    }
    reservation_id = "CRES-" + hashlib.sha256(canon(reservation_core).encode()).hexdigest()[:20].upper()
    row = {
        "reservation_id": reservation_id,
        **reservation_core,
        "estimated_usage": copy.deepcopy(estimate),
        "actual_usage": None,
        "status": "RESERVED",
        "created_at": at,
        "expires_at": expires,
        "committed_at": None,
        "evidence_refs": list(request["evidence_refs"]),
    }
    out["reservations"].append(row)
    req(len(out["reservations"]) <= p["max_state_records"], "cost state capacity exceeded")
    d = _decision(request, at, "RESERVED", ["ALL_COST_GATES_PASS"], reservation_id, True)
    _append_decision(out, d, p)
    return _finish_state(out, at, p), d

def commit_reservation(state: dict[str, Any], reservation_id: str, actual_usage: dict[str, Any], *, at: str | None = None, evidence_ref: str = "cost:commit", policy_data: dict[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    p = copy.deepcopy(policy_data or policy())
    validate_policy(p)
    validate_state(state, p)
    validate_usage(actual_usage)
    at = at or now_iso()
    out = copy.deepcopy(state)
    matches = [row for row in out["reservations"] if row["reservation_id"] == reservation_id]
    req(len(matches) == 1, "reservation missing/duplicate")
    row = matches[0]
    if row["status"] in {"COMMITTED", "OVERAGE"}:
        return out, {"status": row["status"], "reservation_id": reservation_id}
    req(row["status"] == "RESERVED", "only active reservation may be committed")
    over = [field for field in USAGE_FIELDS if actual_usage[field] > row["estimated_usage"][field] + (1e-12 if field == "cost_usd" else 0)]
    row["actual_usage"] = copy.deepcopy(actual_usage)
    row["status"] = "OVERAGE" if over else "COMMITTED"
    row["committed_at"] = at
    if evidence_ref not in row["evidence_refs"]:
        row["evidence_refs"].append(evidence_ref)
    fake_request = {
        "schema_version": "1.0.0",
        "request_id": row["request_id"],
        "idempotency_key": row["idempotency_key"],
        "retry_group": row["retry_group"],
        "attempt": row["attempt"],
        "resource_kind": row["resource_kind"],
        "project_ids": row["project_ids"],
        "provider_id": row["provider_id"],
        "model_id": row["model_id"],
        "workflow_id": row["workflow_id"],
        "job_id": row["job_id"],
        "authority_class": "NONE",
        "data_classification": "SANITIZED",
        "estimated_usage": row["estimated_usage"],
        "evidence_refs": row["evidence_refs"],
        "requested_at": row["created_at"],
    }
    status = "HARD_STOP_OVERAGE" if over else "COMMITTED"
    reasons = [f"ACTUAL_EXCEEDED_RESERVATION:{x}" for x in over] or ["ACTUAL_USAGE_COMMITTED"]
    d = _decision(fake_request, at, status, reasons, reservation_id, False)
    _append_decision(out, d, p)
    return _finish_state(out, at, p), d

def cancel_reservation(state: dict[str, Any], reservation_id: str, *, at: str | None = None, evidence_ref: str = "cost:cancel", policy_data: dict[str, Any] | None = None) -> dict[str, Any]:
    p = copy.deepcopy(policy_data or policy())
    validate_policy(p)
    validate_state(state, p)
    at = at or now_iso()
    out = copy.deepcopy(state)
    matches = [row for row in out["reservations"] if row["reservation_id"] == reservation_id]
    req(len(matches) == 1, "reservation missing/duplicate")
    row = matches[0]
    if row["status"] != "RESERVED":
        return out
    row["status"] = "CANCELLED"
    row["committed_at"] = at
    if evidence_ref not in row["evidence_refs"]:
        row["evidence_refs"].append(evidence_ref)
    return _finish_state(out, at, p)

def hard_stop_reason(state: dict[str, Any], *, at: str | None = None, policy_data: dict[str, Any] | None = None) -> str | None:
    p = copy.deepcopy(policy_data or policy())
    validate_policy(p)
    validate_state(state, p)
    at = at or now_iso()
    is_killed, reason = killed(p)
    if is_killed:
        return "KILL_SWITCH:" + (reason or "spend disabled")
    today = _day(at)
    if any(row["status"] == "OVERAGE" and _day(row["created_at"]) == today for row in state["reservations"]):
        return "CURRENT_DAY_RESERVATION_OVERAGE"
    used = _usage_for(_expire_and_compact(state, at, p), at, lambda row: True)
    for field in USAGE_FIELDS:
        if used[field] > p["portfolio_ceiling"][field] + (1e-12 if field == "cost_usd" else 0):
            return f"PORTFOLIO_BUDGET_BREACH:{field}"
    return None

def make_model_request(route: dict[str, Any], model_request: dict[str, Any], *, attempt: int = 1, at: str | None = None) -> dict[str, Any]:
    req(route.get("status") == "ROUTED" and int(route.get("tier", 0)) > 0, "non-Tier-0 routed model request required")
    at = at or now_iso()
    request_id = "CGR-MODEL-" + hashlib.sha256((route["route_id"] + "\0" + str(attempt)).encode()).hexdigest()[:16].upper()
    usage = zero_usage()
    usage.update({
        "cost_usd": float(route["max_estimated_cost_usd"]),
        "input_tokens": int(model_request["max_input_tokens"]),
        "output_tokens": int(model_request["max_output_tokens"]),
        "model_calls": 1,
        "api_calls": 1,
    })
    return {
        "schema_version": "1.0.0",
        "request_id": request_id,
        "idempotency_key": f'model:{route["route_id"]}:attempt:{attempt}',
        "retry_group": f'model:{route["route_id"]}',
        "attempt": attempt,
        "resource_kind": "MODEL_CALL",
        "project_ids": list(model_request["project_ids"]),
        "provider_id": route["provider_id"],
        "model_id": route["model_id"],
        "workflow_id": None,
        "job_id": None,
        "authority_class": model_request["authority_class"],
        "data_classification": model_request["data_classification"],
        "estimated_usage": usage,
        "evidence_refs": [f'model-request:{model_request["request_id"]}', f'route:{route["route_id"]}', route["route_hash"]],
        "requested_at": at,
    }

def reserve_model_execution(state: dict[str, Any], route: dict[str, Any], model_request: dict[str, Any], *, attempt: int = 1, at: str | None = None, policy_data: dict[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    if model_request.get("authority_class") == "ACT":
        return state, {
            "schema_version": "1.0.0",
            "status": "BLOCKED_AUTHORITY",
            "can_execute": False,
            "reservation_id": None,
            "authority_granted": False,
            "reason_codes": ["COST_BUDGET_CANNOT_AUTHORIZE_ACT"],
        }
    if route.get("status") == "ROUTED" and route.get("tier") == 0:
        return state, {
            "schema_version": "1.0.0",
            "status": "TIER0_NO_SPEND",
            "can_execute": True,
            "reservation_id": None,
            "authority_granted": False,
            "reason_codes": ["DETERMINISTIC_TIER0_REQUIRES_NO_MODEL_API_RESERVATION"],
        }
    request = make_model_request(route, model_request, attempt=attempt, at=at)
    return preflight(state, request, at=at, policy_data=policy_data)

def make_github_job_request(*, workflow_id: str, job_id: str, run_id: str, attempt: int, project_ids: list[str], estimated_minutes: int, authority_class: str, at: str | None = None) -> dict[str, Any]:
    at = at or now_iso()
    usage = zero_usage()
    usage.update({"github_job_starts": 1, "github_runner_minutes": int(estimated_minutes)})
    return {
        "schema_version": "1.0.0",
        "request_id": "CGR-GH-" + hashlib.sha256((run_id + "\0" + job_id + "\0" + str(attempt)).encode()).hexdigest()[:16].upper(),
        "idempotency_key": f"github-job:{run_id}:{job_id}:attempt:{attempt}",
        "retry_group": f"github-job:{run_id}:{job_id}",
        "attempt": int(attempt),
        "resource_kind": "GITHUB_JOB",
        "project_ids": list(project_ids),
        "provider_id": None,
        "model_id": None,
        "workflow_id": workflow_id,
        "job_id": job_id,
        "authority_class": authority_class,
        "data_classification": "SANITIZED",
        "estimated_usage": usage,
        "evidence_refs": [f"github-run:{run_id}", f"workflow:{workflow_id}", f"job:{job_id}"],
        "requested_at": at,
    }
