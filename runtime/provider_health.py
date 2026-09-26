#!/usr/bin/env python3
"""Sanitized, durable model-provider readiness state."""
from __future__ import annotations

import json
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


class ProviderHealthError(ValueError):
    pass


def validate_provider_health(state: dict[str, Any]) -> None:
    required = {
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
    if not isinstance(state, dict) or set(state) != required:
        raise ProviderHealthError("provider health fields changed")
    if state["schema_version"] != "1.0.0" or state["state_id"] != "portfolio-provider-readiness-state":
        raise ProviderHealthError("provider health identity mismatch")
    if type(state["sequence"]) is not int or state["sequence"] < 0:
        raise ProviderHealthError("provider health sequence invalid")
    if not isinstance(state["updated_at"], str) or not state["updated_at"]:
        raise ProviderHealthError("provider health timestamp missing")
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


def write_provider_health(path: Path, state: dict[str, Any]) -> dict[str, Any]:
    validate_provider_health(state)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return state
