"""Build a candidate from a previously validated repair-plan artifact."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from software_factory.candidate_worker import DockerRunner, build_candidate, load_snapshot, object_hash, require, validate_task


def build_from_plan(*, plan_path: Path, checkout: Path, image_id: str, output_dir: Path) -> dict:
    plan = json.loads(plan_path.read_text())
    require(isinstance(plan, dict) and isinstance(plan.get("task"), dict)
            and isinstance(plan.get("task_hash"), str), "repair plan artifact invalid")
    task = plan["task"]
    require(plan["task_hash"] == object_hash(task), "repair plan task hash mismatch")
    validate_task(task, plan["task_hash"])
    snapshot = load_snapshot(checkout, task)
    runner = DockerRunner(image_id)
    receipt = build_candidate(task, approved_hash=plan["task_hash"], snapshot=snapshot,
                              runner=runner, output_dir=output_dir)
    require(receipt["task_hash"] == plan["task_hash"]
            and receipt["status"] == "CANDIDATE_TESTED_AWAITING_INDEPENDENT_REVIEW",
            "candidate build receipt did not bind repair plan")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--checkout", type=Path, default=Path("."))
    parser.add_argument("--image-id", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    receipt = build_from_plan(plan_path=args.plan, checkout=args.checkout,
                              image_id=args.image_id, output_dir=args.output_dir)
    print(json.dumps({"status": receipt["status"], "task_id": receipt["task_id"],
                      "receipt_hash": receipt["receipt_hash"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
