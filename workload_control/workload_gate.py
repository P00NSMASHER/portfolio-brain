#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "workload_control" / "WORKLOAD_POLICY.json"


class WorkloadControlError(ValueError):
    pass


def load_policy() -> dict:
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    if policy.get("schema_version") != "1.0.0":
        raise WorkloadControlError("workload policy schema mismatch")
    if policy.get("mode") != "GITHUB_NATIVE_WORKLOAD_CONTROL":
        raise WorkloadControlError("workload control mode changed")
    services = policy.get("services")
    if not isinstance(services, dict) or not services:
        raise WorkloadControlError("workload services missing")
    for key, cfg in services.items():
        if "::" not in key:
            raise WorkloadControlError(f"invalid service key: {key}")
        if type(cfg.get("max_minutes_per_job")) is not int or cfg["max_minutes_per_job"] < 1:
            raise WorkloadControlError(f"invalid max minutes: {key}")
        if not isinstance(cfg.get("concurrency_group"), str) or not cfg["concurrency_group"]:
            raise WorkloadControlError(f"missing concurrency group: {key}")
        if cfg.get("coalesce_pending") is not True:
            raise WorkloadControlError(f"pending coalescing must stay enabled: {key}")
    return policy


def evaluate(*, workflow_id: str, job_id: str, estimated_minutes: int) -> dict:
    policy = load_policy()
    key = f"{workflow_id}::{job_id}"
    cfg = policy["services"].get(key)
    if cfg is None:
        return {
            "status": "BLOCKED_WORKLOAD",
            "allowed": False,
            "reason": f"UNCONFIGURED_WORKLOAD:{key}",
            "service_key": key,
            "concurrency_group": None,
        }
    if estimated_minutes < 1 or estimated_minutes > cfg["max_minutes_per_job"]:
        return {
            "status": "BLOCKED_WORKLOAD",
            "allowed": False,
            "reason": f"WORKLOAD_TIMEOUT_EXCEEDED:{key}",
            "service_key": key,
            "concurrency_group": cfg["concurrency_group"],
        }
    return {
        "status": "WORKLOAD_ALLOWED",
        "allowed": True,
        "reason": "WORKLOAD_CONTROLS_PASS",
        "service_key": key,
        "concurrency_group": cfg["concurrency_group"],
    }


def _github_output(**values) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


def preflight_command(args) -> int:
    decision = evaluate(
        workflow_id=args.workflow_id,
        job_id=args.job_id,
        estimated_minutes=args.estimated_minutes,
    )
    _github_output(
        allowed=str(decision["allowed"]).lower(),
        decision_status=decision["status"],
        reason=decision["reason"],
        concurrency_group=decision.get("concurrency_group") or "",
    )
    print(json.dumps(decision, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    pre = sub.add_parser("preflight")
    pre.add_argument("--workflow-id", required=True)
    pre.add_argument("--job-id", required=True)
    pre.add_argument("--estimated-minutes", type=int, required=True)
    pre.set_defaults(func=preflight_command)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
