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
        value=p["portfolio_ceiling"][field]
        req(type(value) in {int,float} and value>=0, f"invalid finite paid/model budget: {field}")
    req(p["portfolio_ceiling"]["cost_usd"]>0 and p["portfolio_ceiling"]["model_calls"]>0,
        "optimized cost governor requires finite nonzero model capacity")
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
        "command-center-pages": ROOT / ".github/workflows/command-center-pages.yml",
        "agent-heartbeat-sweep": ROOT / ".github/workflows/agent-heartbeat-sweep.yml",
        "model-value-proof": ROOT / ".github/workflows/model-value-proof.yml",
        "verified-feedback-bootstrap": ROOT / ".github/workflows/verified-feedback-bootstrap.yml",
        "continuous-learning-bootstrap": ROOT / ".github/workflows/continuous-learning-bootstrap.yml",
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

    command_center = (ROOT / ".github/workflows/command-center-pages.yml").read_text().lower()
    req('cron: "37 * * * *"' in command_center,"hourly command-center refresh schedule missing")
    req("actions: read" in command_center and "pages: write" in command_center,"command-center read/deploy permissions incomplete")
    req("contents: write" not in command_center and "actions: write" not in command_center,"command-center publication write authority widened")
    req("dashboard.live_state_bridge" in command_center,"command-center live-state restore missing")
    req("command-center-pages::publish" in p["workflow_job_ceilings"],"command-center publication lacks cost ceiling")
    req("command-center-pages" in p["managed_workflow_names"],"command-center publication is not cost managed")
    value_proof = governed_workflows["model-value-proof"].read_text().lower()
    req("model-value-proof::proof" in p["workflow_job_ceilings"],"model value proof lacks cost ceiling")
    req("model-value-proof" in p["managed_workflow_names"],"model value proof is not cost managed")
    req("portfolio_model_api_key" in value_proof,"model value proof provider credential binding missing")
    req("value_proof.end_to_end" in value_proof,"model value proof finalization missing")
    req("authority observe" in value_proof,"model value proof job reservation authority drifted")
    req("contents: write" not in value_proof and "actions: write" not in value_proof,"model value proof workflow write authority widened")

    feedback_bootstrap=governed_workflows["verified-feedback-bootstrap"].read_text().lower()
    req("verified-feedback-bootstrap::feedback" in p["workflow_job_ceilings"],"verified feedback bootstrap lacks cost ceiling")
    req("verified-feedback-bootstrap" in p["managed_workflow_names"],"verified feedback bootstrap is not cost managed")
    req("value_proof.proof_artifact_state" in feedback_bootstrap,"verified feedback bootstrap does not restore prior proof")
    req("value_proof.feedback_loop" in feedback_bootstrap,"verified feedback bootstrap does not apply feedback")
    req("portfolio_model_api_key" not in feedback_bootstrap,"feedback bootstrap may not bind model credentials")
    req("python -m value_proof.model_task" not in feedback_bootstrap and "python -m value_proof.verifier" not in feedback_bootstrap,"feedback bootstrap may not execute model calls")
    req("contents: write" not in feedback_bootstrap and "actions: write" not in feedback_bootstrap,"feedback bootstrap workflow write authority widened")

    learning_bootstrap=governed_workflows["continuous-learning-bootstrap"].read_text().lower()
    req("continuous-learning-bootstrap::bootstrap" in p["workflow_job_ceilings"],"continuous learning bootstrap lacks cost ceiling")
    req("continuous-learning-bootstrap" in p["managed_workflow_names"],"continuous learning bootstrap is not cost managed")
    req("value_proof.proof_artifact_state" in learning_bootstrap,"continuous learning bootstrap does not restore prior proof")
    req("learning.live_observations" in learning_bootstrap,"continuous learning bootstrap does not ingest verified observations")
    req("learning.integrity" in learning_bootstrap,"continuous learning bootstrap lacks cross-subsystem proof")
    req("portfolio_model_api_key" not in learning_bootstrap,"continuous learning bootstrap may not bind model credentials")
    req("python -m value_proof.model_task" not in learning_bootstrap and "python -m value_proof.verifier" not in learning_bootstrap,"continuous learning bootstrap may not execute model calls")
    req("contents: write" not in learning_bootstrap and "actions: write" not in learning_bootstrap,"continuous learning bootstrap workflow write authority widened")

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
