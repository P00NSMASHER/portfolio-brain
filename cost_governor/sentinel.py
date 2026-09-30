#!/usr/bin/env python3
"""Read-only resource/cost sentinel for Portfolio Brain."""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
USAGE_FIELDS = (
    "cost_usd", "input_tokens", "output_tokens", "model_calls",
    "api_calls", "github_job_starts", "github_runner_minutes",
)

def _load(path: str) -> dict[str, Any]:
    return json.loads((ROOT / path).read_text())

def _zero() -> dict[str, float]:
    return {field: 0 for field in USAGE_FIELDS}

def _add(dst: dict[str, float], src: dict[str, Any] | None) -> None:
    if not src:
        return
    for field in USAGE_FIELDS:
        dst[field] += float(src.get(field, 0) or 0)

def _day(value: str | None) -> str | None:
    return value[:10] if isinstance(value, str) and len(value) >= 10 else None

def _at_or_before(value: str | None, now: str) -> bool:
    """Return whether an ISO timestamp has elapsed; malformed state stays fail closed."""
    if not isinstance(value, str) or not value:
        return False
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        current = datetime.fromisoformat(now.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return True
    if timestamp.tzinfo is None or current.tzinfo is None:
        return True
    return timestamp.astimezone(timezone.utc) <= current.astimezone(timezone.utc)

def _nominal_daily_runs(cron: str | None) -> int | None:
    """Return the exact daily run count for supported all-day cron forms."""
    if not isinstance(cron, str):
        return None
    fields = cron.split()
    if len(fields) != 5 or fields[2:] != ["*", "*", "*"]:
        return None
    minute, hour = fields[:2]
    if hour != "*":
        return None
    if minute.isdigit() and 0 <= int(minute) <= 59:
        return 24
    if minute.startswith("*/") and minute[2:].isdigit():
        interval = int(minute[2:])
        if interval > 0 and 60 % interval == 0:
            return 24 * (60 // interval)
    return None

def _provider_attempt_failure(row: dict[str, Any]) -> bool:
    return any(
        isinstance(ref, str) and ref.startswith("provider-attempt:")
        for ref in row.get("evidence_refs", [])
    )

def _verified_model_feedback(state: dict[str, Any]) -> dict[str, Any]:
    """Project durable verified model feedback without inventing value."""
    if state.get("state_id") == "portfolio-model-feedback-state":
        calls = {
            row.get("invocation_id"): row
            for row in state.get("calls", [])
            if isinstance(row, dict) and isinstance(row.get("invocation_id"), str)
        }
        per_model: dict[str, dict[str, Any]] = {}
        verified_records = 0
        value_events: set[str] = set()
        for outcome in state.get("outcomes", []):
            if not isinstance(outcome, dict) or outcome.get("evidence_state") != "VERIFIED":
                continue
            call = calls.get(outcome.get("invocation_id"))
            if call is None:
                continue
            provider_id = call.get("provider_id")
            model_id = call.get("model_id")
            if not isinstance(provider_id, str) or not isinstance(model_id, str):
                continue
            key = f"{provider_id}::{model_id}"
            bucket = per_model.setdefault(key, {
                "verified_feedback_records": 0,
                "verified_value_events": set(),
                "outcome_value_sum": 0.0,
                "invocation_ids": set(),
            })
            bucket["verified_feedback_records"] += 1
            event_id = outcome.get("outcome_event_id")
            if isinstance(event_id, str) and event_id:
                bucket["verified_value_events"].add(event_id)
                value_events.add(event_id)
            value = outcome.get("outcome_value")
            if type(value) in {int, float}:
                bucket["outcome_value_sum"] += float(value)
            bucket["invocation_ids"].add(call["invocation_id"])
            verified_records += 1

        projected: dict[str, dict[str, Any]] = {}
        for key, bucket in per_model.items():
            costs = [
                float(calls[invocation_id].get("cost_usd", 0) or 0)
                for invocation_id in bucket["invocation_ids"]
                if invocation_id in calls
            ]
            count = bucket["verified_feedback_records"]
            lifetime_cost = round(sum(costs), 6)
            projected[key] = {
                "verified_feedback_records": count,
                "verified_value_events": len(bucket["verified_value_events"]),
                "mean_verified_outcome_value": None if count == 0 else round(bucket["outcome_value_sum"] / count, 6),
                "feedback_call_cost_usd": lifetime_cost,
                "mean_feedback_cost_per_verified_outcome_usd": None if count == 0 else round(lifetime_cost / count, 6),
            }
        return {
            "source": "DURABLE_VERIFIED_FEEDBACK",
            "state_sequence": state.get("sequence"),
            "state_updated_at": state.get("updated_at"),
            "verified_feedback_records": verified_records,
            "verified_value_events": len(value_events),
            "per_model": projected,
            "task_summaries": state.get("routing_task_summaries", {}),
        }

    verified = [
        outcome
        for outcome in state.get("outcomes", [])
        if str(outcome.get("verification_status") or outcome.get("status") or "").upper() == "VERIFIED"
    ]
    return {
        "source": "LEGACY_ROUTING_LEDGER",
        "state_sequence": None,
        "state_updated_at": None,
        "verified_feedback_records": len(verified),
        "verified_value_events": len(verified),
        "per_model": {},
        "task_summaries": {},
    }

def build_sentinel_snapshot(
    *,
    cost_policy: dict[str, Any] | None = None,
    cost_state: dict[str, Any] | None = None,
    provider_registry: dict[str, Any] | None = None,
    model_ledger: dict[str, Any] | None = None,
    model_feedback_state: dict[str, Any] | None = None,
    action_policy: dict[str, Any] | None = None,
    action_ledger: dict[str, Any] | None = None,
    provider_health: dict[str, Any] | None = None,
    at: str | None = None,
) -> dict[str, Any]:
    cost_policy = cost_policy or _load("cost_governor/COST_GOVERNOR_POLICY.json")
    cost_state = cost_state or _load("cost_governor/COST_STATE_SEED.json")
    provider_registry = provider_registry or _load("model_router/PROVIDER_REGISTRY.json")
    if model_feedback_state is None:
        model_feedback_state = model_ledger if model_ledger is not None else _load("model_router/MODEL_FEEDBACK_STATE_SEED.json")
    action_policy = action_policy or _load("action_engine/ACTION_POLICY.json")
    action_ledger = action_ledger or _load("action_engine/GMAIL_GATEWAY_LEDGER.json")
    provider_health = provider_health or _load("runtime/PROVIDER_HEALTH_SEED.json")

    now = at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    today = _day(now)

    committed = _zero()
    reserved = _zero()
    fail_closed_expired = _zero()
    reservation_status_counts: Counter[str] = Counter()
    model_usage: dict[str, dict[str, float]] = defaultdict(_zero)
    failed_attempts: Counter[str] = Counter()

    for row in cost_state.get("reservations", []):
        status = row.get("status", "UNKNOWN")
        reservation_status_counts[status] += 1
        # Durable state intentionally retains several days of history, while all
        # budget ceilings are scoped to the current UTC calendar day.
        if _day(row.get("created_at")) != today:
            continue
        if status in {"COMMITTED", "OVERAGE"}:
            _add(committed, row.get("actual_usage"))
        elif status == "EXPIRED" or (
            status == "RESERVED" and _at_or_before(row.get("expires_at"), now)
        ):
            # Keep dashboard accounting in exact parity with the governor. A
            # crashed/unknown execution is charged at its reserved maximum for
            # the rest of its UTC accounting day, even after its lease expires.
            _add(fail_closed_expired, row.get("estimated_usage"))
        elif status == "RESERVED":
            _add(reserved, row.get("estimated_usage"))

        if row.get("resource_kind") == "MODEL_CALL":
            key = f"{row.get('provider_id')}::{row.get('model_id')}"
            if status in {"COMMITTED", "OVERAGE"}:
                _add(model_usage[key], row.get("actual_usage"))
            if _provider_attempt_failure(row):
                failed_attempts[key] += 1

    effective = _zero()
    _add(effective, committed)
    _add(effective, reserved)
    _add(effective, fail_closed_expired)
    ceiling = cost_policy["portfolio_ceiling"]
    remaining_headroom = {
        field: max(0.0, float(ceiling.get(field, 0) or 0) - effective[field])
        for field in USAGE_FIELDS
    }

    feedback = _verified_model_feedback(model_feedback_state)

    models = []
    for provider in provider_registry.get("providers", []):
        if not provider.get("enabled"):
            continue
        for model in provider.get("models", []):
            if not model.get("enabled") or model.get("tier", 0) <= 0:
                continue
            key = f"{provider['provider_id']}::{model['model_id']}"
            usage = model_usage[key]
            successful_calls = int(usage["model_calls"])
            spend = round(float(usage["cost_usd"]), 6)
            feedback_row = feedback["per_model"].get(key, {})
            verified_feedback = int(feedback_row.get("verified_feedback_records", 0) or 0)
            verified_events = int(feedback_row.get("verified_value_events", 0) or 0)
            if verified_feedback > 0:
                value_signal = "VERIFIED_VALUE_EVIDENCE"
            elif successful_calls == 0:
                value_signal = "NO_SUCCESSFUL_CALL_BASELINE"
            else:
                value_signal = "NO_VERIFIED_OUTCOME_BASELINE"
            models.append({
                "provider_id": provider["provider_id"],
                "model_id": model["model_id"],
                "tier": model["tier"],
                "configured_input_usd_per_million": model["pricing"]["input_usd_per_million_tokens"],
                "configured_output_usd_per_million": model["pricing"]["output_usd_per_million_tokens"],
                "committed_spend_usd": spend,
                "successful_calls": successful_calls,
                "failed_provider_attempts": failed_attempts[key],
                "spend_per_successful_call_usd": None if successful_calls == 0 else round(spend / successful_calls, 6),
                "verified_outcomes_recorded": verified_feedback,
                "verified_value_events": verified_events,
                "mean_verified_outcome_value": feedback_row.get("mean_verified_outcome_value"),
                "feedback_call_cost_usd": feedback_row.get("feedback_call_cost_usd", 0.0),
                "spend_per_verified_outcome_usd": feedback_row.get("mean_feedback_cost_per_verified_outcome_usd"),
                "value_signal": value_signal,
            })

    executions = action_ledger.get("executions", [])
    idempotency_keys = [x.get("idempotency_key") for x in executions if x.get("idempotency_key")]
    duplicate_receipts = len(idempotency_keys) - len(set(idempotency_keys))
    sent_today = sum(
        1 for item in executions
        if item.get("status") == "SENT" and _day(item.get("sent_at")) == today
    )
    email_limit = action_policy["allowed_actions"]["CUSTOMER_EMAIL"]["max_per_utc_day"]

    watchdog_text = (ROOT / ".github/workflows/portfolio-cost-watchdog.yml").read_text()
    cron_match = re.search(r'cron:\s*"([^"]+)"', watchdog_text)
    timeout_match = re.search(r'timeout-minutes:\s*(\d+)', watchdog_text)
    cron = cron_match.group(1) if cron_match else None
    timeout_minutes = int(timeout_match.group(1)) if timeout_match else None
    nominal_runs = _nominal_daily_runs(cron)

    raw_readiness = provider_health.get("status", "UNKNOWN")
    usability_verified = bool(
        provider_health.get("configured") is True
        and provider_health.get("enabled") is True
        and provider_health.get("credential_ready") is True
        and provider_health.get("call_verified") is True
        and provider_health.get("last_successful_at")
    )
    # Legacy/config-only READY is not usable readiness under the v1.1 contract.
    readiness = raw_readiness if raw_readiness != "READY" or usability_verified else "UNKNOWN"
    if readiness == "READY":
        next_paid_action = "ONE_BOUNDED_TERRA_DAILY_ANALYSIS"
    elif readiness == "BUDGET_BLOCKED":
        next_paid_action = "WAIT_FOR_GOVERNOR_CAPACITY"
    else:
        next_paid_action = "RESTORE_PROVIDER_READINESS_BEFORE_PAID_WORK"

    return {
        "schema_version": "1.0.0",
        "sentinel_id": "portfolio-cost-governor-sentinel-v1",
        "accounting_day_utc": today,
        "budget": {
            "portfolio_ceiling": ceiling,
            "committed_usage": committed,
            "active_reserved_usage": reserved,
            "fail_closed_expired_usage": fail_closed_expired,
            "effective_budget_usage": effective,
            "remaining_headroom": remaining_headroom,
            "reservation_status_counts": dict(sorted(reservation_status_counts.items())),
        },
        "provider_readiness": {
            "status": readiness,
            "configured": provider_health.get("configured"),
            "enabled": provider_health.get("enabled"),
            "credential_ready": provider_health.get("credential_ready"),
            "call_verified": provider_health.get("call_verified"),
            "last_successful_at": provider_health.get("last_successful_at"),
            "cost_gate_status": provider_health.get("cost_gate_status"),
            "provider_id": provider_health.get("provider_id"),
            "model_id": provider_health.get("model_id"),
            "retryable": bool(provider_health.get("retryable", False)),
            "provider_domain_blocked": readiness in {
                "MISSING_CREDENTIAL", "BILLING_NOT_ACTIVE", "QUOTA_EXHAUSTED",
                "RATE_LIMITED", "PROVIDER_ERROR",
            },
            "budget_domain_blocked": readiness == "BUDGET_BLOCKED",
        },
        "model_efficiency": {
            "feedback_source": feedback["source"],
            "feedback_state_sequence": feedback["state_sequence"],
            "feedback_state_updated_at": feedback["state_updated_at"],
            "verified_outcomes_recorded": feedback["verified_feedback_records"],
            "verified_feedback_records": feedback["verified_feedback_records"],
            "verified_value_events": feedback["verified_value_events"],
            "task_summaries": feedback["task_summaries"],
            "models": models,
        },
        "github": {
            "governed_job_usage": {
                "committed_starts": int(committed["github_job_starts"]),
                "committed_runner_minutes": int(committed["github_runner_minutes"]),
                "reserved_starts": int(reserved["github_job_starts"]),
                "reserved_runner_minutes": int(reserved["github_runner_minutes"]),
            },
            "watchdog_control_plane_overhead": {
                "accounting_domain": "CONTROL_PLANE_OVERHEAD",
                "included_in_model_spend": False,
                "governed_by_job_ceiling": False,
                "cron": cron,
                "timeout_minutes": timeout_minutes,
                "nominal_runs_per_day": nominal_runs,
                "nominal_max_runner_minutes_per_day": (
                    None if nominal_runs is None or timeout_minutes is None
                    else nominal_runs * timeout_minutes
                ),
            },
        },
        "gmail_gateway": {
            "accounting_domain": "CHATGPT_GMAIL_CONNECTOR_GATEWAY",
            "included_in_model_or_github_spend": False,
            "sent_today": sent_today,
            "daily_limit": email_limit,
            "daily_headroom": max(0, email_limit - sent_today),
            "duplicate_receipt_count": duplicate_receipts,
            "rate_issue": sent_today >= email_limit,
            "duplicate_issue": duplicate_receipts > 0,
        },
        "allocation": {
            "strategy": "DETERMINISTIC_FIRST_VALUE_WEIGHTED",
            "cash_ceiling_unchanged": True,
            "next_paid_action": next_paid_action,
            "rules": [
                "Use deterministic work whenever it is sufficient.",
                "Use Luna for low-cost intelligence.",
                "Use Terra only for Tier-2 reasoning.",
                "Use Sol only for Tier-3 adversarial or high-impact review.",
                "Do not spend through an unready provider.",
                "Prefer work with verified downstream value.",
            ],
        },
    }
