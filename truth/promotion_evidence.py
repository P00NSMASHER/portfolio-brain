#!/usr/bin/env python3
"""Project a successful Truth Engine promotion into the existing evidence schema.

This is an adapter, not a verifier and not a persistence layer. It consumes the
fail-closed promotion gate, requires an explicit mapping from upstream support
identities to already-existing Portfolio Brain evidence receipts, and emits one
deterministic EVIDENCE_SCHEMA record for downstream consumers.
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any

from events.validate_event import compute_evidence_hash, validate_evidence
from truth.promotion_gate import PromotionGateError, promotion_decision

EVIDENCE_ID = re.compile(r"^EVD-[A-Z0-9-]{8,}$")

class PromotionEvidenceError(ValueError):
    pass

def _require(ok: bool, message: str) -> None:
    if not ok:
        raise PromotionEvidenceError(message)

def _evaluated_at_iso(value: Any) -> str:
    _require(type(value) in (int, float), "evaluated_at must be numeric")
    _require(math.isfinite(value) and value >= 0, "evaluated_at must be finite and non-negative")
    try:
        stamp = datetime.fromtimestamp(value, tz=timezone.utc)
    except (OverflowError, OSError, ValueError) as exc:
        raise PromotionEvidenceError("evaluated_at is outside supported timestamp range") from exc
    return stamp.isoformat().replace("+00:00", "Z")

def _support_bindings(
    receipt: dict[str, Any],
    basis_bindings: list[dict[str, str]],
) -> tuple[list[str], list[str]]:
    _require(isinstance(basis_bindings, list), "basis_bindings must be a list")
    upstream_required = sorted({
        evidence_id
        for finding in receipt["findings"]
        if finding["required"]
        for evidence_id in finding["supporting_evidence_ids"]
    })
    _require(bool(upstream_required), "verified promotion requires explicit upstream support identities")

    upstream_seen: list[str] = []
    portfolio_seen: list[str] = []
    for binding in basis_bindings:
        _require(
            isinstance(binding, dict)
            and set(binding) == {"upstream_evidence_id", "portfolio_evidence_id"},
            "basis binding fields changed",
        )
        upstream_id = binding["upstream_evidence_id"]
        portfolio_id = binding["portfolio_evidence_id"]
        _require(isinstance(upstream_id, str) and upstream_id, "upstream_evidence_id required")
        _require(
            isinstance(portfolio_id, str) and EVIDENCE_ID.fullmatch(portfolio_id) is not None,
            "portfolio_evidence_id must satisfy EVIDENCE_SCHEMA",
        )
        upstream_seen.append(upstream_id)
        portfolio_seen.append(portfolio_id)

    _require(len(upstream_seen) == len(set(upstream_seen)), "duplicate upstream evidence binding")
    _require(len(portfolio_seen) == len(set(portfolio_seen)), "duplicate portfolio evidence binding")
    _require(sorted(upstream_seen) == upstream_required, "basis bindings must exactly cover required upstream support")
    return upstream_required, sorted(portfolio_seen)

def promoted_fact_evidence(
    receipt: dict[str, Any],
    *,
    project_id: str,
    source_revision: str,
    source_blob_sha: str,
    source_receipt_ref: str,
    basis_bindings: list[dict[str, str]],
) -> dict[str, Any]:
    """Emit one deterministic VERIFIED evidence receipt for a promotable claim.

    HOLD decisions fail closed. No memory, graph, event, or authority mutation is
    performed here.
    """
    decision = promotion_decision(
        receipt,
        project_id=project_id,
        source_revision=source_revision,
        source_blob_sha=source_blob_sha,
        source_receipt_ref=source_receipt_ref,
    )
    _require(
        decision["promotion_decision"] == "PROMOTE"
        and decision["trusted_fact_eligible"] is True,
        "only PROMOTE decisions can become trusted Portfolio Brain evidence",
    )
    _require(decision["authority_change"] == "NONE", "promotion cannot grant authority")

    upstream_support_ids, basis_evidence_ids = _support_bindings(receipt, basis_bindings)
    stamp = _evaluated_at_iso(decision["evaluated_at"])
    promotion_hex = decision["promotion_hash"].split(":", 1)[1]
    evidence_id = "EVD-TRUTH-" + promotion_hex[:24].upper()

    record = {
        "schema_version": "1.0.0",
        "evidence_id": evidence_id,
        "project_id": decision["project_id"],
        "evidence_type": "DETERMINISTIC_DERIVATION",
        "evidence_state": "VERIFIED",
        "subject_refs": ["truth-claim:" + decision["claim_id"]],
        "source": {
            "source_kind": "SYSTEM",
            "source_ref": source_receipt_ref,
            "source_revision": decision["source_revision"],
            "retrieved_at": stamp,
            "content_hash": decision["promotion_hash"],
        },
        "actor": {
            "actor_type": "SYSTEM",
            "actor_id": "portfolio-truth-promotion-adapter",
        },
        "observed_at": stamp,
        "verification": {
            "method": "INDEPENDENT_VERIFIER",
            "verifier_actor_id": "ai-business-os-truth-engine:pinned",
            "verified_at": stamp,
            "basis_evidence_ids": basis_evidence_ids,
            "reason": (
                "Pinned Truth Engine PROVEN receipt passed the fail-closed trusted-fact "
                "promotion gate; basis bindings exactly cover required upstream support."
            ),
        },
        "supports_refs": [
            "truth-projection:" + decision["projection_hash"],
            "truth-promotion:" + decision["promotion_hash"],
            "truth-upstream-receipt:sha256:" + decision["upstream_receipt_hash"],
            "truth-upstream-evidence-set:sha256:" + decision["upstream_evidence_set_hash"],
            *["truth-upstream-evidence:" + value for value in upstream_support_ids],
        ],
        "contradicts_refs": [],
        "evidence_hash": "",
    }
    record["evidence_hash"] = compute_evidence_hash(record)
    validate_evidence(record)
    return record
