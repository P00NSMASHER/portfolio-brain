#!/usr/bin/env python3
"""Fail-closed Step 19 provider-usability acceptance receipt builder.

This verifier never performs a provider call. The controlled canary is executed by
runtime-worker under the existing cost governor; this module validates the
sanitized provider-health artifact and exact-main identity after that run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from runtime.provider_health import CURRENT_SCHEMA, ProviderHealthError, validate_provider_health

SHA40 = re.compile(r"^[0-9a-f]{40}$")


class ProviderUsabilityAcceptanceError(ValueError):
    pass


def _hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _load_health(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def build_receipt(
    provider_health: dict[str, Any] | None,
    *,
    source_run_id: int,
    source_head_sha: str,
    observed_main_sha: str,
) -> dict[str, Any]:
    if type(source_run_id) is not int or source_run_id < 1:
        raise ProviderUsabilityAcceptanceError("source run id invalid")
    for label, value in (("source head", source_head_sha), ("observed main", observed_main_sha)):
        if not isinstance(value, str) or SHA40.fullmatch(value) is None:
            raise ProviderUsabilityAcceptanceError(f"{label} SHA invalid")

    reasons: list[str] = []
    health_hash = None
    state: dict[str, Any] = {}
    if provider_health is None:
        reasons.append("PROVIDER_HEALTH_ARTIFACT_MISSING")
    else:
        state = provider_health
        health_hash = _hash(provider_health)
        try:
            validate_provider_health(provider_health)
        except ProviderHealthError:
            reasons.append("PROVIDER_HEALTH_INVALID")

    if source_head_sha != observed_main_sha:
        reasons.append("MAIN_ADVANCED_DURING_CANARY")

    if state:
        if state.get("schema_version") != CURRENT_SCHEMA:
            reasons.append("USABILITY_SCHEMA_NOT_CURRENT")
        if state.get("configured") is not True:
            reasons.append("PROVIDER_NOT_CONFIGURED")
        if state.get("enabled") is not True:
            reasons.append("PROVIDER_NOT_ENABLED")
        if state.get("credential_ready") is not True:
            reasons.append("CREDENTIAL_NOT_READY")
        if state.get("call_verified") is not True:
            reasons.append("CALL_NOT_VERIFIED")
        if not isinstance(state.get("last_successful_at"), str) or not state.get("last_successful_at"):
            reasons.append("LAST_SUCCESSFUL_CALL_MISSING")
        if state.get("status") != "READY":
            reasons.append("PROVIDER_STATUS_NOT_READY")
        if state.get("source_analysis_status") != "SUCCESS":
            reasons.append("MODEL_ANALYSIS_NOT_SUCCESSFUL")
        if state.get("cost_gate_status") != "COMMITTED":
            reasons.append("COST_GATE_NOT_COMMITTED")
        if not isinstance(state.get("provider_id"), str) or not state.get("provider_id"):
            reasons.append("PROVIDER_ID_MISSING")
        if not isinstance(state.get("model_id"), str) or not state.get("model_id"):
            reasons.append("MODEL_ID_MISSING")
        if state.get("authority_granted") is not False or state.get("evidence_upgraded") is not False:
            reasons.append("AUTHORITY_OR_EVIDENCE_WIDENED")

    body = {
        "schema_version": "1.0.0",
        "step": 19,
        "status": "PASS" if not reasons else "BLOCKED",
        "source_run_id": source_run_id,
        "source_head_sha": source_head_sha,
        "observed_main_sha": observed_main_sha,
        "exact_main_identity": source_head_sha == observed_main_sha,
        "provider_health_hash": health_hash,
        "provider_id": state.get("provider_id"),
        "model_id": state.get("model_id"),
        "provider_status": state.get("status", "UNKNOWN"),
        "configured": state.get("configured"),
        "enabled": state.get("enabled"),
        "credential_ready": state.get("credential_ready"),
        "call_verified": state.get("call_verified"),
        "last_successful_at": state.get("last_successful_at"),
        "source_analysis_status": state.get("source_analysis_status"),
        "cost_gate_status": state.get("cost_gate_status"),
        "reason_codes": sorted(set(reasons)),
        "authority_granted": False,
        "evidence_upgraded": False,
    }
    return body | {"receipt_hash": _hash(body)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider-health", type=Path, required=True)
    parser.add_argument("--source-run-id", type=int, required=True)
    parser.add_argument("--source-head-sha", required=True)
    parser.add_argument("--observed-main-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-pass", action="store_true")
    args = parser.parse_args()

    receipt = build_receipt(
        _load_health(args.provider_health),
        source_run_id=args.source_run_id,
        source_head_sha=args.source_head_sha,
        observed_main_sha=args.observed_main_sha,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "step": 19,
        "status": receipt["status"],
        "receipt_hash": receipt["receipt_hash"],
        "reason_codes": receipt["reason_codes"],
    }, sort_keys=True))
    return 2 if args.require_pass and receipt["status"] != "PASS" else 0


if __name__ == "__main__":
    raise SystemExit(main())
