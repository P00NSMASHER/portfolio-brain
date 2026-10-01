#!/usr/bin/env python3
"""Build and validate the final Step 23 sustained-production-soak receipt."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from acceptance.final_acceptance import bind_receipt, validate_step23


class Step23FinalizeError(ValueError):
    pass


def req(ok: bool, message: str) -> None:
    if not ok:
        raise Step23FinalizeError(message)


def _handler_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"REPAIR": 0, "TEST": 0, "VERIFICATION": 0}
    for row in rows:
        kind = row.get("kind")
        req(kind in counts, f"unexpected Step 23 handler kind: {kind}")
        counts[kind] += 1
    return counts


def build_receipt(meta: dict[str, Any]) -> dict[str, Any]:
    req(isinstance(meta, dict), "Step 23 metadata must be an object")
    req(meta.get("schema_version") == "1.0.0", "Step 23 metadata schema mismatch")
    exact_main_sha = meta.get("exact_main_sha")
    req(isinstance(exact_main_sha, str) and len(exact_main_sha) == 40,
        "Step 23 exact main SHA missing")

    runs = meta.get("runs")
    samples = meta.get("canonical_samples")
    handler_evidence = meta.get("handler_execution_evidence")
    hunter_evidence = meta.get("hunter_substantive_work_evidence")
    dashboard = meta.get("dashboard")

    req(isinstance(runs, list) and runs, "Step 23 run evidence missing")
    req(isinstance(samples, list) and samples, "Step 23 canonical samples missing")
    req(isinstance(handler_evidence, list) and handler_evidence,
        "Step 23 handler execution evidence missing")
    req(isinstance(hunter_evidence, list) and hunter_evidence,
        "Step 23 Hunter substantive-work evidence missing")
    req(isinstance(dashboard, dict), "Step 23 dashboard evidence missing")

    pending_start = meta.get("pending_events_start")
    pending_final = meta.get("pending_events_final")
    req(type(pending_start) is int and pending_start >= 0,
        "Step 23 pending_events_start invalid")
    req(pending_final == 0, "Step 23 pending events did not drain")

    req(meta.get("hash_traceability_pass") is True,
        "Step 23 hash traceability is not proven")
    req(dashboard.get("fresh") is True, "Step 23 dashboard is not fresh")
    dashboard_hash = dashboard.get("hash")
    req(isinstance(dashboard_hash, str) and dashboard_hash.startswith("sha256:"),
        "Step 23 dashboard hash missing")

    receipt = bind_receipt({
        "schema_version": "1.0.0",
        "step": 23,
        "status": "PASS",
        "exact_main_sha": exact_main_sha,
        "run_classification_policy": "EXPLICIT",
        "hash_traceability_pass": True,
        "dashboard_fresh": True,
        "dashboard_hash": dashboard_hash,
        "runs": runs,
        "canonical_samples": samples,
        "pending_events_start": pending_start,
        "pending_events_final": pending_final,
        "handler_execution_counts": _handler_counts(handler_evidence),
        "handler_execution_evidence": handler_evidence,
        "hunter_substantive_work_count": len(hunter_evidence),
        "hunter_substantive_work_evidence": hunter_evidence,
    })
    validate_step23(receipt)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--meta", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    meta = json.loads(args.meta.read_text(encoding="utf-8"))
    receipt = build_receipt(meta)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "status": receipt["status"],
        "exact_main_sha": receipt["exact_main_sha"],
        "receipt_hash": receipt["receipt_hash"],
        "scheduled_run_rows": len(receipt["runs"]),
        "canonical_samples": len(receipt["canonical_samples"]),
        "hunter_substantive_work_count": receipt["hunter_substantive_work_count"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
