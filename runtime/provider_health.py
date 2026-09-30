#!/usr/bin/env python3
"""Sanitized, durable model-provider readiness and usability state."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


STATUSES = {
    "READY",
    "MISSING_CREDENTIAL",
    "BILLING_NOT_ACTIVE",
    "QUOTA_EXHAUSTED",
    "RATE_LIMITED",
    "BUDGET_BLOCKED",
    "PROVIDER_ERROR",
    "UNKNOWN",
}
LEGACY_SCHEMA = "1.0.0"
CURRENT_SCHEMA = "1.1.0"
BASE_FIELDS = {
    "schema_version",
    "state_id",
    "sequence",
    "updated_at",
    "mode",
    "status",
    "source_analysis_status",
    "provider_id",
    "model_id",
    "cost_gate_status",
    "retryable",
    "provider_attempt",
    "authority_granted",
    "evidence_upgraded",
}
USABILITY_FIELDS = {
    "configured",
    "enabled",
    "credential_ready",
    "call_verified",
    "last_successful_at",
}


class ProviderHealthError(ValueError):
    pass


def _timestamp(value: Any, field: str, *, optional: bool = False) -> None:
    if value is None and optional:
        return
    if not isinstance(value, str) or not value:
        raise ProviderHealthError(f"provider health {field} invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProviderHealthError(f"provider health {field} invalid") from exc
    if parsed.tzinfo is None:
        raise ProviderHealthError(f"provider health {field} requires timezone")


def validate_provider_health(state: dict[str, Any]) -> None:
    if not isinstance(state, dict):
        raise ProviderHealthError("provider health must be an object")
    schema = state.get("schema_version")
    expected = BASE_FIELDS if schema == LEGACY_SCHEMA else BASE_FIELDS | USABILITY_FIELDS
    if schema not in {LEGACY_SCHEMA, CURRENT_SCHEMA} or set(state) != expected:
        raise ProviderHealthError("provider health fields changed")
    if state["state_id"] != "portfolio-provider-readiness-state":
        raise ProviderHealthError("provider health identity mismatch")
    if type(state["sequence"]) is not int or state["sequence"] < 0:
        raise ProviderHealthError("provider health sequence invalid")
    _timestamp(state["updated_at"], "updated_at")
    if state["mode"] not in {"daily", "weekly", None}:
        raise ProviderHealthError("provider health mode invalid")
    if state["status"] not in STATUSES:
        raise ProviderHealthError("provider health status invalid")
    if not isinstance(state["source_analysis_status"], str) or not state["source_analysis_status"]:
        raise ProviderHealthError("provider health source status missing")
    for field in ("provider_id", "model_id", "cost_gate_status"):
        if state[field] is not None and (not isinstance(state[field], str) or not state[field]):
            raise ProviderHealthError(f"provider health {field} invalid")
    if type(state["retryable"]) is not bool:
        raise ProviderHealthError("provider health retryable flag invalid")
    if state["provider_attempt"] is not None and (
        type(state["provider_attempt"]) is not int or state["provider_attempt"] < 1
    ):
        raise ProviderHealthError("provider health attempt invalid")
    if state["authority_granted"] is not False or state["evidence_upgraded"] is not False:
        raise ProviderHealthError("provider health cannot grant authority or upgrade evidence")

    if schema == LEGACY_SCHEMA:
        return

    if type(state["configured"]) is not bool or type(state["enabled"]) is not bool:
        raise ProviderHealthError("provider health configuration flags invalid")
    if state["enabled"] and not state["configured"]:
        raise ProviderHealthError("enabled provider cannot be unconfigured")
    for field in ("credential_ready", "call_verified"):
        if state[field] is not None and type(state[field]) is not bool:
            raise ProviderHealthError(f"provider health {field} invalid")
    _timestamp(state["last_successful_at"], "last_successful_at", optional=True)
    if state["call_verified"] is True:
        if state["credential_ready"] is not True or state["last_successful_at"] is None:
            raise ProviderHealthError("verified call requires ready credential and success timestamp")
        if not state["configured"] or not state["enabled"]:
            raise ProviderHealthError("verified call requires configured enabled provider")
        if state["status"] != "READY":
            raise ProviderHealthError("verified call cannot coexist with a non-READY status")
    if state["status"] == "READY":
        if not (
            state["configured"] is True
            and state["enabled"] is True
            and state["credential_ready"] is True
            and state["call_verified"] is True
            and state["last_successful_at"] is not None
        ):
            raise ProviderHealthError("READY requires verified provider usability")
    if state["status"] == "MISSING_CREDENTIAL" and state["credential_ready"] is not False:
        raise ProviderHealthError("missing credential must be explicit")


def write_provider_health(path: Path, state: dict[str, Any]) -> dict[str, Any]:
    validate_provider_health(state)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return state
