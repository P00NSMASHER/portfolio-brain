"""Select one real queued REPAIR item for the paid candidate cycle."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
from typing import Any

from repair.repair_engine import build_repair_state, validate_history
from scheduler.autonomous_scheduler import validate_state as validate_scheduler_state
from software_factory.model_repair_planner import repair_lineage
from software_factory.software_factory import policy as factory_policy


class RepairCycleInputError(ValueError):
    pass


def req(ok: bool, message: str) -> None:
    if not ok:
        raise RepairCycleInputError(message)


def _repo_for(repository_id: str) -> dict:
    rows = [row for row in factory_policy()["repository_policies"]
            if row["repository_id"] == repository_id]
    req(len(rows) == 1, "repair repository policy missing or duplicate")
    req(rows[0]["candidate_modify_enabled"] is True, "repair target is not candidate-write enabled")
    return rows[0]


def select_repair(scheduler_state: dict, *, base_sha: str,
                  repair_state: dict | None = None) -> dict | None:
    validate_scheduler_state(scheduler_state)
    req(re.fullmatch(r"[0-9a-f]{40}", base_sha or "") is not None, "base SHA invalid")
    queued = [
        row for row in scheduler_state["work_items"]
        if row["state"] == "QUEUED" and row["work_type"] == "REPAIR"
    ]
    queued.sort(key=lambda row: (row.get("created_at") or "", row["source_ref"], row["scheduler_work_id"]))
    if not queued:
        return None
    work = queued[0]
    req(work["assigned_agent_id"] == "AGT-ENGINEER", "queued repair has wrong builder")
    req(work["required_authority"] == "MODIFY", "queued repair has wrong authority")
    repair_state = repair_state or build_repair_state()
    tasks = [row for row in repair_state["tasks"] if row["repair_task_id"] == work["source_ref"]]
    req(len(tasks) == 1, "queued repair source task missing or duplicate")
    task = tasks[0]
    validate_history(task)
    req(task["state"] == "READY_FOR_REPAIR", "queued repair source is no longer READY_FOR_REPAIR")
    req(set(task["project_ids"]) == set(work["project_ids"]), "queued repair project mismatch")
    repo = _repo_for(task["target_repository_id"])
    lineage = repair_lineage(work, task, repo["repository_full_name"], base_sha)
    return {
        "schema_version": 1,
        "selection_status": "REPAIR_SELECTED",
        "scheduler_work_id": work["scheduler_work_id"],
        "fingerprint": work["fingerprint"],
        "source_ref": work["source_ref"],
        "repository": repo["repository_full_name"],
        "repository_id": repo["repository_id"],
        "base_sha": base_sha,
        "lineage_id": lineage,
        "work": work,
        "repair_task": task,
        "authority_granted": False,
    }


def _github_output(**values: Any) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scheduler-state", type=Path, required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    state = json.loads(args.scheduler_state.read_text())
    selected = select_repair(state, base_sha=args.base_sha)
    if selected is None:
        _github_output(has_work="false", lineage_id="", source_ref="", scheduler_work_id="")
        print(json.dumps({"status": "NO_REPAIR_WORK"}, sort_keys=True))
        return 0
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "selection.json").write_text(json.dumps(selected, indent=2) + "\n")
    (args.output_dir / "work.json").write_text(json.dumps(selected["work"], indent=2) + "\n")
    (args.output_dir / "repair_task.json").write_text(json.dumps(selected["repair_task"], indent=2) + "\n")
    _github_output(has_work="true", lineage_id=selected["lineage_id"],
                   source_ref=selected["source_ref"], scheduler_work_id=selected["scheduler_work_id"])
    print(json.dumps({"status": selected["selection_status"],
                      "source_ref": selected["source_ref"],
                      "lineage_id": selected["lineage_id"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
