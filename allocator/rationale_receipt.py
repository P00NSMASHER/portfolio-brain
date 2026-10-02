#!/usr/bin/env python3
"""Hash-bound rationale receipts for existing Portfolio Brain allocator plans.

This module never scores, ranks, or allocates. It records why an already-built
plan was recommended, binding the explanation to the existing immutable plan
hash and evidence references.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable


class AllocationRationaleReceiptError(ValueError):
    pass


def _req(ok: bool, message: str) -> None:
    if not ok:
        raise AllocationRationaleReceiptError(message)


def _canon(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canon(value).encode("utf-8")).hexdigest()


def _contains_score(value: Any) -> bool:
    if isinstance(value, dict):
        return any(
            key in {"score", "weighted_score", "composite_score"} or _contains_score(child)
            for key, child in value.items()
        )
    if isinstance(value, list):
        return any(_contains_score(child) for child in value)
    return False


def build_rationale_receipt(
    plan: dict[str, Any],
    *,
    generated_at: str,
    dependency_refs: Iterable[str] = (),
) -> dict[str, Any]:
    """Create a deterministic explanation receipt without changing allocator rank."""
    _req(isinstance(plan, dict), "allocation plan must be an object")
    _req(plan.get("schema_version") == "1.0.0", "unsupported allocation plan schema")
    _req(isinstance(plan.get("resource_type"), str) and plan["resource_type"], "resource_type required")
    _req(isinstance(plan.get("status"), str) and plan["status"], "plan status required")
    _req(
        isinstance(plan.get("plan_hash"), str)
        and plan["plan_hash"].startswith("sha256:")
        and len(plan["plan_hash"]) == 71,
        "valid plan_hash required",
    )
    _req(
        type(plan.get("allocated_share_basis_points")) is int
        and type(plan.get("unallocated_share_basis_points")) is int
        and plan["allocated_share_basis_points"] + plan["unallocated_share_basis_points"] == 10000,
        "allocation shares must conserve 10000 basis points",
    )
    _req(isinstance(generated_at, str) and generated_at, "generated_at required")
    _req(not _contains_score(plan), "opaque score fields are not allowed in rationale receipts")

    deps = sorted(set(dependency_refs))
    _req(all(isinstance(ref, str) and ref for ref in deps), "dependency refs must be non-empty strings")

    entries = []
    for recommendation in plan.get("recommendations", []):
        required = {
            "project_id",
            "source_uncertainty_id",
            "source_experiment_id",
            "pareto_layer",
            "rank_order",
            "share_basis_points",
            "authority_requirement",
            "actionability",
            "resource_fit_reason",
            "evidence_refs",
        }
        _req(
            isinstance(recommendation, dict) and required <= set(recommendation),
            "recommendation rationale fields missing",
        )
        _req(
            isinstance(recommendation["evidence_refs"], list) and recommendation["evidence_refs"],
            "recommendation evidence refs required",
        )
        entries.append(
            {
                "project_id": recommendation["project_id"],
                "source_uncertainty_id": recommendation["source_uncertainty_id"],
                "source_experiment_id": recommendation["source_experiment_id"],
                "pareto_layer": recommendation["pareto_layer"],
                "rank_order": recommendation["rank_order"],
                "share_basis_points": recommendation["share_basis_points"],
                "authority_requirement": recommendation["authority_requirement"],
                "actionability": recommendation["actionability"],
                "resource_fit_reason": recommendation["resource_fit_reason"],
                "evidence_refs": list(dict.fromkeys(recommendation["evidence_refs"])),
            }
        )

    body = {
        "schema_version": "1.0.0",
        "receipt_type": "PORTFOLIO_ALLOCATION_RATIONALE",
        "generated_at": generated_at,
        "resource_type": plan["resource_type"],
        "plan_status": plan["status"],
        "source_plan_hash": plan["plan_hash"],
        "allocated_share_basis_points": plan["allocated_share_basis_points"],
        "unallocated_share_basis_points": plan["unallocated_share_basis_points"],
        "dependency_refs": deps,
        "rationale_entries": entries,
        "execution_authority_granted": False,
    }
    return {**body, "receipt_hash": _hash(body)}
