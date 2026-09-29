"""Bridge already-admitted REPAIR work to measured candidate builds.

An empty reviewed task registry means no autonomous candidate execution. A task
cannot approve itself; its source identity and hash must match the separate
registry. Existing scheduler limits, roles, kill switches and factory policy
remain authoritative. A tested candidate is NOT a delivered production repair.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import time

from software_factory.candidate_worker import (
    BuildError, DockerRunner, build_candidate, load_snapshot, object_hash, require, safe_path,
)

ROOT = Path(__file__).resolve().parents[1]


def _deferred(work: dict, reason: str) -> dict:
    return {"status": "DEFERRED", "result_kind": reason,
            "evidence_refs": ["scheduler-work:" + work["scheduler_work_id"]],
            "result": {"source_ref": work["source_ref"], "production_changed": False}}


def _factory_policy() -> dict:
    return json.loads((ROOT / "software_factory/FACTORY_POLICY.json").read_text())


def _kill_state() -> bool:
    from scheduler.autonomous_scheduler import killed
    return killed()[0]


def _configuration() -> dict:
    registry = json.loads((ROOT / "software_factory/BUILD_TASK_REGISTRY.json").read_text())
    require(registry.get("schema_version") == 1 and isinstance(registry.get("tasks"), list),
            "invalid build task registry")
    entries = []
    for entry in registry["tasks"]:
        path = ROOT / safe_path(entry["task_path"])
        require(path.resolve().is_relative_to(ROOT.resolve()) and not path.is_symlink(),
                "task path escaped repository")
        entries.append({**entry, "task": json.loads(path.read_text())})
    return {"tasks": entries, "checkout": ROOT,
            "image_id": os.environ.get("PORTFOLIO_BUILD_IMAGE_ID", ""),
            "output_root": ROOT / "scheduler/out/candidate_builds"}


def repair_handler(work: dict, context: dict) -> dict:
    if _kill_state():
        return _deferred(work, "BUILD_KILL_SWITCH_ACTIVE")
    if (work.get("work_type") != "REPAIR" or work.get("assigned_agent_id") != "AGT-ENGINEER"
            or work.get("required_authority") != "MODIFY"):
        return _deferred(work, "BUILD_ROLE_OR_AUTHORITY_MISMATCH")
    configuration = context.get("candidate_build_configuration")
    if configuration is None:
        configuration = _configuration()
    entries = [e for e in configuration["tasks"] if e.get("source_ref") == work["source_ref"]]
    if len(entries) != 1:
        return _deferred(work, "NO_UNIQUE_APPROVED_BUILD_TASK")
    entry = entries[0]
    task = entry["task"]
    from software_factory.candidate_worker import validate_task
    validate_task(task, entry["task_hash"])
    require(task["source_ref"] == work["source_ref"] and task["project_id"] in work["project_ids"],
            "approved task is not bound to scheduler work")
    policy = _factory_policy()
    repositories = [p for p in policy["repository_policies"] if p["repository_full_name"] == task["repository"]]
    if len(repositories) != 1 or repositories[0].get("candidate_modify_enabled") is not True:
        return _deferred(work, "BUILD_REPOSITORY_NOT_ONBOARDED")
    for path in [e["path"] for e in task["edits"]] + [task["test_path"]]:
        for forbidden in policy["forbidden_candidate_paths"]:
            require(not path.startswith(forbidden), "factory forbids candidate path")
    checkout = Path(configuration["checkout"])
    snapshot = load_snapshot(checkout, task)
    runner = configuration.get("runner")
    if runner is None:
        try:
            runner = DockerRunner(configuration.get("image_id", ""))
        except BuildError:
            return _deferred(work, "BUILD_ISOLATED_RUNTIME_NOT_CONFIGURED")
    # All repair tasks in this scheduler invocation share this execution budget.
    deadline = context.setdefault("candidate_build_deadline", time.monotonic() + 150)
    def bounded_runner(root, argv, timeout):
        remaining = int(deadline - time.monotonic())
        require(remaining > 0, "candidate build cycle deadline exhausted")
        return runner(root, argv, min(timeout, remaining))
    output = Path(configuration["output_root"]) / entry["task_hash"].split(":", 1)[1]
    receipt = build_candidate(task, approved_hash=entry["task_hash"], snapshot=snapshot,
                              runner=bounded_runner, output_dir=output)
    # SUCCESS completes only this candidate-building work item. It is never an
    # independent PASS, PR-open, merged, deployed, or delivered-improvement claim.
    return {"status": "SUCCESS", "result_kind": "CANDIDATE_BUILD_TESTED",
            "evidence_refs": ["scheduler-work:" + work["scheduler_work_id"],
                              "build-receipt:" + receipt["receipt_hash"],
                              "candidate-patch:" + receipt["patch_sha256"]],
            "result": {"task_id": task["task_id"], "base_sha": task["base_sha"],
                       "candidate_status": receipt["status"],
                       "artifact_path": "candidate_builds/" + output.name,
                       "changed_paths": receipt["changed_paths"],
                       "test_count": receipt["tests"][-1]["test_count"],
                       "model_calls": 0, "model_cost_usd": 0,
                       "independent_verification": False, "delivered_improvements": 0,
                       "production_changed": False, "authority_granted": False}}


def handler_table() -> dict:
    from scheduler.work_executor import DEFAULT_HANDLERS
    return {**DEFAULT_HANDLERS, "REPAIR": repair_handler}


def main() -> None:
    from scheduler import work_executor
    # Retain the existing CLI, receipt writer, leases and eight-attempt ceiling.
    work_executor.DEFAULT_HANDLERS.update(handler_table())
    work_executor.main()


if __name__ == "__main__":
    main()
