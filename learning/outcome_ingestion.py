#!/usr/bin/env python3
"""Validated exact-once adapter for VERIFIED outcome ingestion.

This module does not create a new learning, memory, graph, or feedback engine.
It atomically composes the existing Hunter feedback, model-feedback, and durable
live-learning projections behind one validated outcome identity.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

from hunting.autonomous_hunter import validate_state as validate_hunter_state
from learning.live_observations import (
    apply_verified_value_outcome,
    validate_state as validate_learning_state,
)
from model_router.feedback_state import (
    rebuild_summaries,
    validate_state as validate_model_feedback_state,
)
from value_proof.feedback_loop import (
    apply_verified_value_feedback,
    validate_value_outcome,
)
from value_proof.model_task import digest, load_contract
from value_proof.verifier import load_verifier_contract

ROOT = Path(__file__).resolve().parents[1]
CONTROLLED_CASES = ROOT / "hunting" / "CONTROLLED_PROOF_CASES.json"
INGESTION_ID = "portfolio-verified-outcome-ingestion-v1"


class OutcomeIngestionError(ValueError):
    pass


def req(ok: bool, message: str) -> None:
    if not ok:
        raise OutcomeIngestionError(message)


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _assert_outcome_identity(
    learning_state: dict[str, Any], outcome: dict[str, Any]
) -> str:
    """Reject one logical outcome id being rebound to different content."""
    validate_learning_state(learning_state)
    outcome_id = outcome["outcome_id"]
    expected = f"value-outcome:{outcome_id}:{outcome['outcome_hash']}"
    prefix = f"value-outcome:{outcome_id}:"
    prior = [key for key in learning_state["applied_source_keys"] if key.startswith(prefix)]
    req(
        all(key == expected for key in prior),
        f"conflicting verified outcome identity for {outcome_id}",
    )
    return expected


def ingest_verified_outcome(
    *,
    task_contract: dict[str, Any],
    verifier_contract: dict[str, Any],
    outcome: dict[str, Any],
    builder_provider_receipt: dict[str, Any],
    verifier_provider_receipt: dict[str, Any],
    hunter_state: dict[str, Any],
    model_feedback_state: dict[str, Any],
    learning_state: dict[str, Any],
    controlled_cases: dict[str, Any],
    at: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Validate and project one VERIFIED outcome into existing engines atomically."""
    validate_value_outcome(outcome)
    validate_hunter_state(hunter_state)
    rebuild_summaries(model_feedback_state)
    validate_model_feedback_state(model_feedback_state)
    validate_learning_state(learning_state)
    source_key = _assert_outcome_identity(learning_state, outcome)

    hunter = copy.deepcopy(hunter_state)
    model = copy.deepcopy(model_feedback_state)
    learning = copy.deepcopy(learning_state)
    before = {
        "hunter": digest(hunter),
        "model_feedback": digest(model),
        "learning": digest(learning),
    }

    feedback_receipt = apply_verified_value_feedback(
        task_contract=task_contract,
        verifier_contract=verifier_contract,
        outcome=outcome,
        builder_provider_receipt=builder_provider_receipt,
        verifier_provider_receipt=verifier_provider_receipt,
        hunter_state=hunter,
        model_feedback_state=model,
        controlled_cases=controlled_cases,
        at=at,
    )
    learning_result = apply_verified_value_outcome(
        learning,
        task_contract=task_contract,
        verifier_contract=verifier_contract,
        outcome=outcome,
        feedback_receipt=feedback_receipt,
        builder_provider_receipt=builder_provider_receipt,
        verifier_provider_receipt=verifier_provider_receipt,
        at=at,
    )

    validate_hunter_state(hunter)
    rebuild_summaries(model)
    validate_model_feedback_state(model)
    validate_learning_state(learning)
    req(source_key in learning["applied_source_keys"], "learning projection lost outcome identity")

    changed = feedback_receipt["status"] == "FEEDBACK_APPLIED" or learning_result["status"] == "APPLIED"
    core = {
        "schema_version": "1.0.0",
        "ingestion_id": INGESTION_ID,
        "status": "INGESTED" if changed else "ALREADY_INGESTED",
        "source_outcome_id": outcome["outcome_id"],
        "source_outcome_hash": outcome["outcome_hash"],
        "source_key": source_key,
        "value_class": outcome["value_class"],
        "evidence_state": outcome["evidence_state"],
        "provenance_refs": list(outcome["provenance_refs"]),
        "projection_state_hashes_before": before,
        "projection_state_hashes_after": {
            "hunter": digest(hunter),
            "model_feedback": digest(model),
            "learning": digest(learning),
        },
        "projections": {
            "hunter": {
                "changed": bool(feedback_receipt["hunter_feedback_applied"]),
                "sequence": hunter["sequence"],
            },
            "model_feedback": {
                "changed": bool(
                    feedback_receipt["builder_feedback_applied"]
                    or feedback_receipt["verifier_feedback_applied"]
                ),
                "sequence": model["sequence"],
            },
            "learning": {
                "changed": learning_result["status"] == "APPLIED",
                "sequence": learning["sequence"],
                "added_observations": learning_result["added_observations"],
            },
        },
        "logical_ingestion_applied": changed,
        "feedback_receipt_hash": feedback_receipt["receipt_hash"],
        "authority_granted": False,
        "market_verified": False,
        "revenue_verified": False,
        "static_checked_in_knowledge_mutated": False,
    }
    receipt = {**core, "receipt_hash": digest(core)}
    return hunter, model, learning, feedback_receipt, receipt


def main() -> None:
    ap = argparse.ArgumentParser(description="Ingest one VERIFIED outcome exactly once")
    ap.add_argument("--task-contract", type=Path, default=Path("value_proof/MODEL_TASK_CONTRACT.json"))
    ap.add_argument("--verifier-contract", type=Path, default=Path("value_proof/VERIFIER_CONTRACT.json"))
    ap.add_argument("--value-outcome", type=Path, required=True)
    ap.add_argument("--builder-provider-receipt", type=Path, required=True)
    ap.add_argument("--verifier-provider-receipt", type=Path, required=True)
    ap.add_argument("--hunter-state", type=Path, required=True)
    ap.add_argument("--model-feedback-state", type=Path, required=True)
    ap.add_argument("--learning-state", type=Path, required=True)
    ap.add_argument("--controlled-cases", type=Path, default=CONTROLLED_CASES)
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--at", default=None)
    args = ap.parse_args()

    hunter, model, learning, feedback, receipt = ingest_verified_outcome(
        task_contract=load_contract(args.task_contract),
        verifier_contract=load_verifier_contract(args.verifier_contract),
        outcome=_load(args.value_outcome),
        builder_provider_receipt=_load(args.builder_provider_receipt),
        verifier_provider_receipt=_load(args.verifier_provider_receipt),
        hunter_state=_load(args.hunter_state),
        model_feedback_state=_load(args.model_feedback_state),
        learning_state=_load(args.learning_state),
        controlled_cases=_load(args.controlled_cases),
        at=args.at,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "hunter_state.json": hunter,
        "model_feedback_state.json": model,
        "learning_observation_state.json": learning,
        "feedback_loop_receipt.json": feedback,
        "outcome_ingestion_receipt.json": receipt,
    }
    for name, value in outputs.items():
        (args.output_dir / name).write_text(
            json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
