#!/usr/bin/env python3
"""Build a bounded Step 22 controlled-fault repair request.

This module detects only the dedicated non-production fixture. It does not edit
main, dispatch workflows, grant authority, or claim Step 22 complete.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from acceptance.step22_controlled_fault_target import acceptance_value
from repair.autonomous_repair import request_from_scheduler_work, validate_request
from repair.repair_engine import failure_to_task
from scheduler.autonomous_scheduler import _candidate, _work_packet

TARGET_PATH = "acceptance/step22_controlled_fault_target.py"
FAULT_ID = "RFAIL-STEP22-CONTROLLED-FIXTURE"
FIXTURE_EVIDENCE = "acceptance:step22-controlled-repair-fixture"


class Step22FixtureError(RuntimeError):
    pass


def _canon(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canon(value)).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def build_plan(base_sha: str, *, at: str | None = None) -> dict[str, Any]:
    if not isinstance(base_sha, str) or len(base_sha) != 40 or any(ch not in "0123456789abcdef" for ch in base_sha):
        raise Step22FixtureError("exact protected-main SHA required")
    at = at or _now()
    observed = acceptance_value()
    if observed != "BASELINE":
        raise Step22FixtureError(f"controlled Step 22 fixture is not armed: {observed!r}")

    regression = (
        "Change acceptance_value() in acceptance/step22_controlled_fault_target.py "
        "to return CANDIDATE only in the isolated repair candidate and add a NEW "
        "regression-test file under tests/ asserting exactly CANDIDATE. Do not "
        "modify any existing test file or any production runtime path."
    )
    failure = {
        "schema_version": "1.0.0",
        "failure_id": FAULT_ID,
        "source_type": "FAILURE_PACKET",
        "project_ids": ["PRJ-000"],
        "target_repository_id": "REPO-008",
        "target_paths": [TARGET_PATH],
        "failure_class": "CONTROLLED_ACCEPTANCE",
        "observation": (
            "Dedicated non-production Step 22 fixture remains BASELINE. The bounded "
            "autonomous repair proof must transition only this fixture to CANDIDATE."
        ),
        "reproduction_steps": [
            "Import acceptance_value from acceptance.step22_controlled_fault_target.",
            "Call acceptance_value() and observe BASELINE.",
            "Require the isolated repair candidate to return CANDIDATE.",
        ],
        "evidence_refs": [FIXTURE_EVIDENCE, f"github:protected-main@{base_sha}"],
        "regression_test_requirement": regression,
        "evidence_state": "VERIFIED",
        "sensitive_material_involved": False,
        "benchmark_contaminated": False,
        "reported_at": at,
    }
    task = failure_to_task(failure)
    candidate = _candidate(
        "REPAIR",
        task["repair_task_id"],
        ["PRJ-000"],
        "AGT-ENGINEER",
        "CONTROLLED_SELF_REPAIR_ACCEPTANCE",
        "MODIFY",
        "HIGH",
        reason="Bounded Step 22 autonomous self-repair acceptance fixture.",
        evidence_refs=[FIXTURE_EVIDENCE, f"repair-task:{task['repair_task_id']}"],
        external_milestone="PUBLISH_PRODUCT",
        value_lane="INTERNAL_BLOCKER",
        signal_basis="CONTROLLED_LIVE_ACCEPTANCE",
    )
    work = _work_packet(candidate, at)
    request = request_from_scheduler_work(work, {"tasks": [task]}, base_sha=base_sha)
    validate_request(request)
    request_b64 = base64.b64encode(_canon(request)).decode("ascii")

    body = {
        "schema_version": "1.0.0",
        "status": "CONTROLLED_FAULT_DETECTED",
        "fault_mechanism": "CONTROLLED_REPRODUCIBLE_FIXTURE",
        "production_main_damaged": False,
        "fault_reversible": True,
        "authority_granted": False,
        "canonical_state_mutated": False,
        "base_sha": base_sha,
        "detected_at": at,
        "target_path": TARGET_PATH,
        "observed_value": observed,
        "required_repaired_value": "CANDIDATE",
        "failure": failure,
        "repair_task_id": task["repair_task_id"],
        "scheduler_work_id": work["scheduler_work_id"],
        "request": request,
        "request_b64": request_b64,
    }
    return body | {"fault_receipt_hash": _hash(body)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-sha", required=True)
    ap.add_argument("--at")
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    result = build_plan(args.base_sha, at=args.at)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
