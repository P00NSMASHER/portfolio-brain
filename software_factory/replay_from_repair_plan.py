"""Replay a generated repair candidate and emit the existing factory review handoff."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from software_factory.candidate_replay import replay_candidate
from software_factory.candidate_worker import DockerRunner, object_hash, require, validate_task


def replay_from_plan(*, plan_path: Path, checkout: Path, build_dir: Path,
                     image_id: str, output_dir: Path) -> dict:
    plan = json.loads(plan_path.read_text())
    require(isinstance(plan, dict) and isinstance(plan.get("task"), dict)
            and isinstance(plan.get("task_hash"), str), "repair plan artifact invalid")
    task = plan["task"]
    require(plan["task_hash"] == object_hash(task), "repair plan task hash mismatch")
    validate_task(task, plan["task_hash"])
    receipt = replay_candidate(task, approved_hash=plan["task_hash"], checkout=checkout,
                               artifact_dir=build_dir, runner=DockerRunner(image_id),
                               output_dir=output_dir)
    require(receipt["task_hash"] == plan["task_hash"], "replay/task hash mismatch")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--checkout", type=Path, default=Path("."))
    parser.add_argument("--build-dir", type=Path, required=True)
    parser.add_argument("--image-id", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    receipt = replay_from_plan(plan_path=args.plan, checkout=args.checkout,
                               build_dir=args.build_dir, image_id=args.image_id,
                               output_dir=args.output_dir)
    print(json.dumps({"status": receipt["status"],
                      "candidate_commit_sha": receipt["candidate_commit_sha"],
                      "receipt_hash": receipt["receipt_hash"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
