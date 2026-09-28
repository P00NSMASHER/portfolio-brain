"""Brain-only operational rights policy, separate from license observations.

The owner's standing assumption makes license categories non-blocking. It is
not independent verification and cannot change source evidence, costs, sandbox
requirements, canary requirements, or execution authority.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "hunting" / "RIGHTS_USAGE_POLICY.json"


class RightsUsageError(ValueError):
    pass


def _require(ok: bool, message: str) -> None:
    if not ok:
        raise RightsUsageError(message)


def _hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def current_usage_decision() -> dict[str, Any]:
    """Apply checked-in owner configuration, never repository-supplied instructions."""
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    _require(policy.get("schema_version") == "1.0.0", "rights usage policy schema invalid")
    _require(policy.get("policy_id") == "brain-operator-assumed-rights-v1", "rights usage policy identity invalid")
    _require(policy.get("scope") == "P00NSMASHER/portfolio-brain", "rights assumption scope changed")
    _require(policy.get("mode") == "NON_BLOCKING_OPERATOR_ASSUMED", "rights usage mode invalid")
    _require(policy.get("license_blocks_enabled") is False, "license blocking unexpectedly enabled")
    _require(policy.get("assumption_status") == "OPERATOR_ASSUMED", "assumption mislabeled as verification")
    _require(policy.get("independently_verified") is False, "owner assumption is not independent verification")
    _require(policy.get("preserve_license_observations") is True, "rights observations must be preserved")
    _require(policy.get("execution_authority_granted") is False, "rights policy cannot grant execution authority")
    _require(policy.get("instruction_source") == "USER_REQUEST_2026_09_28", "standing instruction provenance missing")
    body = {
        "schema_version": "1.0.0",
        "policy_id": policy["policy_id"],
        "scope": policy["scope"],
        "mode": policy["mode"],
        "allowed_by_brain_license_policy": True,
        "license_blocks_enabled": False,
        "assumption_status": "OPERATOR_ASSUMED",
        "independently_verified": False,
        "execution_authority_granted": False,
        "policy_sha256": _hash(policy),
        "instruction_source": policy["instruction_source"],
    }
    return {**body, "usage_hash": _hash(body)}


def validate_usage_decision(decision: dict[str, Any]) -> None:
    """Validate embedded historical policy metadata without rewriting observations."""
    expected = {
        "schema_version", "policy_id", "scope", "mode",
        "allowed_by_brain_license_policy", "license_blocks_enabled", "assumption_status",
        "independently_verified", "execution_authority_granted", "policy_sha256",
        "instruction_source", "usage_hash",
    }
    _require(isinstance(decision, dict) and set(decision) == expected, "rights usage decision fields invalid")
    _require(decision["schema_version"] == "1.0.0", "rights usage decision schema invalid")
    _require(decision["policy_id"] == "brain-operator-assumed-rights-v1", "rights usage decision identity invalid")
    _require(decision["scope"] == "P00NSMASHER/portfolio-brain", "rights usage decision scope invalid")
    _require(decision["mode"] == "NON_BLOCKING_OPERATOR_ASSUMED", "rights usage decision mode invalid")
    _require(decision["allowed_by_brain_license_policy"] is True, "rights usage admission invalid")
    _require(decision["license_blocks_enabled"] is False, "rights usage blocking flag invalid")
    _require(decision["assumption_status"] == "OPERATOR_ASSUMED", "rights assumption mislabeled")
    _require(decision["independently_verified"] is False, "rights assumption cannot claim independent verification")
    _require(decision["execution_authority_granted"] is False, "rights assumption cannot authorize execution")
    _require(decision["instruction_source"] == "USER_REQUEST_2026_09_28", "rights usage instruction provenance invalid")
    digest = decision["policy_sha256"]
    _require(isinstance(digest, str) and digest.startswith("sha256:") and len(digest) == 71 and all(c in "0123456789abcdef" for c in digest[7:]), "rights usage policy digest invalid")
    body = dict(decision)
    supplied = body.pop("usage_hash")
    _require(supplied == _hash(body), "rights usage decision hash mismatch")


def evaluate_rights_usage(record: dict[str, Any]) -> dict[str, Any]:
    """Current internal admission is non-blocking; malformed evidence still fails."""
    from hunting.rights_gate import validate_rights_record

    validate_rights_record(record)
    return current_usage_decision()
