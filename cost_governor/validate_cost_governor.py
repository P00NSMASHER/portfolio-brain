#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from cost_governor.cost_governor import (
    commit_reservation,
    hard_stop_reason,
    load_state,
    make_github_job_request,
    policy,
    preflight,
    validate_policy,
    zero_usage,
)

ROOT = Path(__file__).resolve().parents[1]

class CostGovernorValidationError(ValueError):
    pass

def req(ok, msg):
    if not ok:
        raise CostGovernorValidationError(msg)

def validate_cost_governor():
    p = policy()
    validate_policy(p)
    seed = load_state()
    req(p["mode"] == "FAIL_CLOSED_PRE_EXECUTION_RESERVATION", "cost governor mode changed")
    req(p["authority_class"] == "NONE", "cost governor authority widened")
    for field in ("cost_usd", "input_tokens", "output_tokens", "model_calls", "api_calls"):
        req(p["portfolio_ceiling"][field] == 0, f"checked-in paid/model budget opened: {field}")
    req(p["global_concurrency_group"] == "portfolio-cost-governed-autonomy", "global cost serialization changed")

    at = "2026-09-25T12:00:00Z"
    request = make_github_job_request(
        workflow_id="portfolio-autonomous-scheduler",
        job_id="schedule",
        run_id="step20-validator",
        attempt=1,
        project_ids=["PRJ-000"],
        estimated_minutes=5,
        authority_class="OBSERVE",
        at=at,
    )
    state, first = preflight(seed, request, at=at)
    req(first["status"] == "RESERVED" and first["can_execute"] is True, "managed scheduler job did not reserve")
    state, duplicate = preflight(state, request, at=at)
    req(duplicate["status"] == "DUPLICATE_SUPPRESSED" and duplicate["can_execute"] is False, "duplicate spend was not suppressed")

    actual = zero_usage()
    actual.update({"github_job_starts": 1, "github_runner_minutes": 5})
    state, committed = commit_reservation(state, first["reservation_id"], actual, at=at)
    req(committed["status"] == "COMMITTED" and hard_stop_reason(state, at=at) is None, "valid reservation commit failed")

    fresh = load_state()
    short = make_github_job_request(
        workflow_id="portfolio-autonomous-scheduler",
        job_id="schedule",
        run_id="step20-overage",
        attempt=1,
        project_ids=["PRJ-000"],
        estimated_minutes=1,
        authority_class="OBSERVE",
        at=at,
    )
    fresh, reserved = preflight(fresh, short, at=at)
    over = zero_usage()
    over.update({"github_job_starts": 1, "github_runner_minutes": 2})
    fresh, overage = commit_reservation(fresh, reserved["reservation_id"], over, at=at)
    req(overage["status"] == "HARD_STOP_OVERAGE", "overage did not trip hard stop")
    req(hard_stop_reason(fresh, at=at) == "CURRENT_DAY_RESERVATION_OVERAGE", "hard stop reason missing")

    governed_workflows = {
        "portfolio-autonomous-scheduler": ROOT / ".github/workflows/portfolio-autonomous-scheduler.yml",
        "runtime-worker": ROOT / ".github/workflows/runtime-worker.yml",
        "hunter-autonomous-cycle": ROOT / ".github/workflows/hunter-autonomous-cycle.yml",
        "software-factory-candidate": ROOT / ".github/workflows/software-factory-candidate.yml",
        "portfolio-notification-cycle": ROOT / ".github/workflows/portfolio-notification-cycle.yml",
    }
    for name, path in governed_workflows.items():
        body = path.read_text().lower()
        for text in [
            "portfolio-cost-governed-autonomy",
            "cost_governor.artifact_state",
            "cost_governor.workflow_gate preflight",
            "cost_governor.workflow_gate finalize",
            "portfolio_spend_disabled",
            "portfolio-cost-governor-state",
        ]:
            req(text in body, f"{name} cost integration missing: {text}")
    scheduler = governed_workflows["portfolio-autonomous-scheduler"].read_text().lower()
    req("contents: write" not in scheduler and "actions: write" not in scheduler, "scheduler write authority widened")

    watchdog = (ROOT / ".github/workflows/portfolio-cost-watchdog.yml").read_text().lower()
    req("actions: write" in watchdog, "watchdog cannot cancel managed jobs")
    req("cost_governor.cancel_managed_jobs" in watchdog, "watchdog cancellation helper missing")
    req("foundation-ci" not in p["managed_workflow_names"], "foundation CI may not be cost-cancel managed")

    router_policy = json.loads((ROOT / "model_router/MODEL_ROUTER_POLICY.json").read_text())
    req(any("cost governor" in x.lower().replace("-", " ") for x in router_policy["invariants"]), "model router missing cost-governor execution invariant")

    return {
        "paid_usd_ceiling": p["portfolio_ceiling"]["cost_usd"],
        "paid_model_calls_ceiling": p["portfolio_ceiling"]["model_calls"],
        "github_job_starts_ceiling": p["portfolio_ceiling"]["github_job_starts"],
        "github_runner_minutes_ceiling": p["portfolio_ceiling"]["github_runner_minutes"],
        "retry_limits": p["retry_limits"],
        "managed_workflows": len(p["managed_workflow_names"]),
        "governed_execution_workflows": len(governed_workflows),
        "duplicate_suppression": True,
        "overage_hard_stop": True,
        "authority_change": "NONE",
    }

if __name__ == "__main__":
    print("portfolio-brain Step 20 cost governor: PASS", json.dumps(validate_cost_governor(), sort_keys=True))
