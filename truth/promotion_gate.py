#!/usr/bin/env python3
"""Fail-closed promotion gate layered on the pinned canonical Truth Engine adapter.

This module does not evaluate claims or create a second verifier. It consumes the
existing pinned Truth Engine receipt through truth_adapter.project_receipt and
only emits a deterministic promotion receipt for downstream portfolio facts.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from truth.truth_adapter import project_receipt

ROOT=Path(__file__).resolve().parents[1]
CONTRACT_PATH=ROOT/"truth"/"TRUSTED_FACT_PROMOTION_CONTRACT.json"

class PromotionGateError(ValueError):
    pass

def _require(ok: bool, message: str) -> None:
    if not ok:
        raise PromotionGateError(message)

def _canonical_hash(value: Any) -> str:
    raw=json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode("utf-8")
    return "sha256:"+hashlib.sha256(raw).hexdigest()

def load_contract() -> dict[str,Any]:
    contract=json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    expected={
        "schema_version":"1.0.0",
        "input":"PINNED_AI_BUSINESS_OS_TRUTH_RECEIPT",
        "adapter":"truth.truth_adapter.project_receipt",
        "promotable_truth_states":["VERIFIED"],
        "held_truth_states":["UNKNOWN","STALE","CONTRADICTED"],
        "decision_values":["PROMOTE","HOLD"],
        "requires_exact_pinned_source_identity":True,
        "promotion_requires_upstream_proven":True,
        "promotion_requires_required_findings_satisfied":True,
        "stale_is_not_proof":True,
        "contradicted_is_not_proof":True,
        "unknown_is_not_proof":True,
        "authority_change":"NONE",
    }
    _require(contract==expected,"trusted-fact promotion contract changed")
    return contract

def promotion_decision(
    receipt: dict[str,Any],
    *,
    project_id: str,
    source_revision: str,
    source_blob_sha: str,
    source_receipt_ref: str,
) -> dict[str,Any]:
    """Return a deterministic promotion receipt without persisting or granting authority."""
    contract=load_contract()
    projection=project_receipt(
        receipt,
        project_id=project_id,
        source_revision=source_revision,
        source_blob_sha=source_blob_sha,
        source_receipt_ref=source_receipt_ref,
    )
    state=projection["truth_state"]
    allowed_states=set(contract["promotable_truth_states"]) | set(contract["held_truth_states"])
    _require(state in allowed_states,"unsupported projected truth state")

    eligible=state in contract["promotable_truth_states"]
    if eligible:
        _require(
            projection["upstream_verdict"]=="PROVEN",
            "promotion requires upstream PROVEN",
        )
        _require(
            projection["required_findings"]
            and all(finding["status"]=="SATISFIED" for finding in projection["required_findings"]),
            "promotion requires every required finding SATISFIED",
        )

    reason={
        "VERIFIED":"PINNED_TRUTH_ENGINE_VERIFIED",
        "UNKNOWN":"TRUTH_UNKNOWN_NOT_PROOF",
        "STALE":"TRUTH_STALE_NOT_PROOF",
        "CONTRADICTED":"TRUTH_CONTRADICTED_NOT_PROOF",
    }[state]
    decision={
        "schema_version":"1.0.0",
        "project_id":projection["project_id"],
        "claim_id":projection["claim_id"],
        "promotion_decision":"PROMOTE" if eligible else "HOLD",
        "trusted_fact_eligible":eligible,
        "reason_code":reason,
        "projection_hash":projection["projection_hash"],
        "upstream_receipt_hash":projection["upstream_receipt_hash"],
        "upstream_evidence_set_hash":projection["upstream_evidence_set_hash"],
        "source_revision":projection["upstream_source"]["revision"],
        "evaluated_at":projection["evaluated_at"],
        "authority_change":"NONE",
    }
    return decision | {"promotion_hash":_canonical_hash(decision)}
