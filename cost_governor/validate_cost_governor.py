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
    reserve_model_execution,
    validate_policy,
    zero_usage,
)

ROOT = Path(__file__).resolve().parents[1]


class CostGovernorValidationError(ValueError):
    pass


def req(ok, msg):
    if not ok:
        raise CostGovernorValidationError(msg)


def _model_route(route_id: str) -> dict:
    return {
        "status": "ROUTED",
        "tier": 2,
        "route_id": route_id,
        "provider_id": "approved-api-slot",
        "model_id": "UNCONFIGURED_STRONG",
        "max_estimated_cost_usd": 0.01,
        "route_hash": "sha256:" + route_id.lower().ljust(64, "0")[:64],
    }


def _model_request(request_id: str) -> dict:
    return {
        "request_id": request_id,
        "project_ids": ["PRJ-000"],
        "max_input_tokens": 100,
        "max_output_tokens": 100,
        "authority_class": "OBSERVE",
        "data_classification": "SANITIZED",
    }


def validate_cost_governor():
    p = policy()
    validate_policy(p)
    seed = load_state()
    req(p["mode"] == "FAIL_CLOSED_PRE_EXECUTION_RESERVATION", "cost governor mode changed")
    req(p["authority_class"] == "NONE", "cost governor authority widened")
    req(p["portfolio_ceiling"]["cost_usd"] == 10, "paid USD ceiling changed")
    req(p["portfolio_ceiling"]["github_job_starts"] == 0, "GitHub starts still coupled to paid ceiling")
    req(p["portfolio_ceiling"]["github_runner_minutes"] == 0, "runner minutes still coupled to paid ceiling")
    req(p["workflow_job_ceilings"] == {}, "legacy daily GitHub job quotas remain enabled")
    req(p["workflow_job_controls"], "workflow workload controls missing")
    req(p["global_concurrency_group"] == "portfolio-paid-cost-ledger", "paid ledger serialization changed")
    req(set(p["paid_workflow_names"]) == {"model-value-proof", "runtime-daily-learning", "runtime-weekly-synthesis"},
        "paid cancellation allowlist drifted")

    at = "2026-09-27T12:00:00Z"

    # Compatibility workload preflight remains bounded and idempotent, but daily
    # GitHub counts no longer consume or hard-stop the paid budget.
    job = make_github_job_request(
        workflow_id="portfolio-autonomous-scheduler",
        job_id="schedule",
        run_id="workload-validator",
        attempt=1,
        project_ids=["PRJ-000"],
        estimated_minutes=1,
        authority_class="OBSERVE",
        at=at,
    )
    state, first = preflight(seed, job, at=at)
    req(first["status"] == "RESERVED" and first["can_execute"] is True, "workload control did not admit bounded scheduler job")
    state, duplicate = preflight(state, job, at=at)
    req(duplicate["status"] == "DUPLICATE_SUPPRESSED", "workload duplicate suppression failed")
    actual = zero_usage()
    actual.update({"github_job_starts": 1, "github_runner_minutes": 2})
    state, overrun = commit_reservation(state, first["reservation_id"], actual, at=at)
    req(overrun["status"] == "WORKLOAD_OVERRUN", "workload overrun was misclassified as paid hard stop")
    req(hard_stop_reason(state, at=at) is None, "workload overrun incorrectly activated paid hard stop")
    next_job = make_github_job_request(
        workflow_id="portfolio-autonomous-scheduler",
        job_id="schedule",
        run_id="workload-validator-2",
        attempt=1,
        project_ids=["PRJ-000"],
        estimated_minutes=5,
        authority_class="OBSERVE",
        at=at,
    )
    _, next_decision = preflight(state, next_job, at=at)
    req(next_decision["status"] == "RESERVED", "prior GitHub counts still block later workload")

    # A paid reservation overage must stop subsequent paid execution immediately.
    paid, reserved = reserve_model_execution(
        load_state(), _model_route("MRT-OVERAGE-ONE"), _model_request("MRQ-OVERAGE-ONE"), at=at
    )
    req(reserved["status"] == "RESERVED", "paid model reservation failed")
    paid_actual = zero_usage()
    paid_actual.update({
        "cost_usd": 0.02,
        "input_tokens": 100,
        "output_tokens": 100,
        "model_calls": 1,
        "api_calls": 1,
    })
    paid, committed = commit_reservation(paid, reserved["reservation_id"], paid_actual, at=at)
    req(committed["status"] == "HARD_STOP_OVERAGE", "paid overage did not trip hard stop")
    req(hard_stop_reason(paid, at=at) == "CURRENT_DAY_PAID_RESERVATION_OVERAGE", "paid hard-stop reason missing")
    _, blocked = reserve_model_execution(
        paid, _model_route("MRT-OVERAGE-TWO"), _model_request("MRQ-OVERAGE-TWO"), at=at
    )
    req(blocked["status"] == "BLOCKED_HARD_STOP" and blocked["can_execute"] is False,
        "paid hard stop is not enforced inside preflight")

    workflow_paths = {
        "portfolio-autonomous-scheduler": ROOT / ".github/workflows/portfolio-autonomous-scheduler.yml",
        "hunter-autonomous-cycle": ROOT / ".github/workflows/hunter-autonomous-cycle.yml",
        "software-factory-candidate": ROOT / ".github/workflows/software-factory-candidate.yml",
        "portfolio-notification-cycle": ROOT / ".github/workflows/portfolio-notification-cycle.yml",
        "command-center-pages": ROOT / ".github/workflows/command-center-pages.yml",
        "agent-heartbeat-sweep": ROOT / ".github/workflows/agent-heartbeat-sweep.yml",
        "model-value-proof": ROOT / ".github/workflows/model-value-proof.yml",
        "verified-feedback-bootstrap": ROOT / ".github/workflows/verified-feedback-bootstrap.yml",
        "continuous-learning-bootstrap": ROOT / ".github/workflows/continuous-learning-bootstrap.yml",
        "runtime-worker": ROOT / ".github/workflows/runtime-worker.yml",
    }
    expected_groups = {
        "portfolio-autonomous-scheduler": "portfolio-workload-scheduler",
        "hunter-autonomous-cycle": "portfolio-workload-hunter",
        "software-factory-candidate": "portfolio-workload-software-factory",
        "portfolio-notification-cycle": "portfolio-telemetry-notifications",
        "command-center-pages": "portfolio-reporting-command-center",
        "agent-heartbeat-sweep": "portfolio-telemetry-heartbeats",
        "model-value-proof": "portfolio-paid-cost-ledger",
        "verified-feedback-bootstrap": "portfolio-learning-feedback",
        "continuous-learning-bootstrap": "portfolio-learning-continuous",
    }
    for name, group in expected_groups.items():
        body = workflow_paths[name].read_text()
        req(group in body, f"{name} service-specific concurrency group missing")
        req("portfolio-cost-governed-autonomy" not in body, f"{name} still uses shared pending-job replacement group")

    for name in (
        "portfolio-autonomous-scheduler",
        "hunter-autonomous-cycle",
        "software-factory-candidate",
        "portfolio-notification-cycle",
        "agent-heartbeat-sweep",
        "verified-feedback-bootstrap",
        "continuous-learning-bootstrap",
        "command-center-pages",
    ):
        body = workflow_paths[name].read_text()
        req("cost_governor.workflow_gate" not in body, f"{name} still couples ordinary workload to paid budget")

    command_center = workflow_paths["command-center-pages"].read_text()
    req('cron: "37 * * * *"' in command_center, "hourly command-center refresh schedule missing")
    req("cost_governor.artifact_state" in command_center, "command center no longer reads paid status")
    req("portfolio-cost-governor-state" not in command_center, "command center unexpectedly mutates cost state")

    value_proof = workflow_paths["model-value-proof"].read_text()
    req("portfolio-paid-cost-ledger" in value_proof, "model value proof not serialized on paid ledger")
    req("cost_governor.workflow_gate" not in value_proof, "model value proof still reserves free GitHub job budget")
    req("cost_governor.artifact_state" in value_proof and "portfolio-cost-governor-state" in value_proof,
        "model value proof lost durable paid accounting")
    req("python -m value_proof.model_task" in value_proof and "python -m value_proof.verifier" in value_proof,
        "model value proof paid execution path missing")

    runtime_worker = workflow_paths["runtime-worker"].read_text()
    req("portfolio-paid-cost-ledger" in runtime_worker and "portfolio-runtime-{0}" in runtime_worker,
        "runtime paid/free concurrency split missing")
    req("cost_governor.workflow_gate" not in runtime_worker, "runtime still reserves free GitHub job budget")
    req("python -m runtime.model_analysis" in runtime_worker, "runtime paid model analysis path missing")

    watchdog = (ROOT / ".github/workflows/portfolio-cost-watchdog.yml").read_text().lower()
    req("cost_governor.cancel_managed_jobs" in watchdog, "watchdog cancellation helper missing")
    cancel_helper = (ROOT / "cost_governor/cancel_managed_jobs.py").read_text()
    req('p["paid_workflow_names"]' in cancel_helper, "watchdog can still cancel non-paid workflows")

    liveness = json.loads((ROOT / "operations/WORKFLOW_LIVENESS_POLICY.json").read_text())
    req(liveness["hard_stop_behavior"] == "ALLOW_NONPAID_RECOVERY", "non-paid liveness recovery still coupled to spend stop")
    req({row["workflow_name"] for row in liveness["targets"]} <= set(p["managed_workflow_names"]),
        "liveness recovery targets unmanaged workflows")

    router_policy = json.loads((ROOT / "model_router/MODEL_ROUTER_POLICY.json").read_text())
    req(any("cost governor" in x.lower().replace("-", " ") for x in router_policy["invariants"]),
        "model router missing cost-governor execution invariant")

    return {
        "paid_usd_ceiling": p["portfolio_ceiling"]["cost_usd"],
        "paid_model_calls_ceiling": p["portfolio_ceiling"]["model_calls"],
        "github_job_budget_coupled": False,
        "workload_control_count": len(p["workflow_job_controls"]),
        "paid_hard_stop_preflight_enforced": True,
        "reporting_independent": True,
        "paid_cancellation_allowlist_size": len(p["paid_workflow_names"]),
        "authority_change": "NONE",
    }


if __name__ == "__main__":
    print("portfolio-brain Step 20 cost governor: PASS", json.dumps(validate_cost_governor(), sort_keys=True))
