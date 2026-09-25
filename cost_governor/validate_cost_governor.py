#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from cost_governor.cost_governor import (
    load_state,
    make_github_job_request,
    preflight,
    reserve_model_execution,
    validate_policy,
)

ROOT = Path(__file__).resolve().parents[1]

class CostValidationError(ValueError):
    pass

def req(ok, msg):
    if not ok:
        raise CostValidationError(msg)

def load(path):
    return json.loads((ROOT / path).read_text())

def validate_cost_governor():
    p = load("cost_governor/COST_GOVERNOR_POLICY.json")
    validate_policy(p)
    seed = load_state()
    req(p["portfolio_ceiling"]["cost_usd"] == 0.0, "paid cost budget unexpectedly open")
    req(p["portfolio_ceiling"]["model_calls"] == 0 and p["portfolio_ceiling"]["api_calls"] == 0, "model/API call budget unexpectedly open")
    req(p["retry_limits"] == {"MODEL_CALL": 2, "API_CALL": 2, "GITHUB_JOB": 2}, "retry ceiling changed")
    req(p["state_persistence"]["sanitized_only"] is True, "cost persistence must remain sanitized")
    req(p["global_concurrency_group"] == "portfolio-cost-governed-autonomy", "cost serialization group changed")

    at = "2026-09-25T21:20:00Z"
    job = make_github_job_request(
        workflow_id="portfolio-autonomous-scheduler",
        job_id="schedule",
        run_id="36190000000",
        attempt=1,
        project_ids=["PRJ-000"],
        estimated_minutes=5,
        authority_class="OBSERVE",
        at=at,
    )
    state, first = preflight(seed, job, at=at)
    req(first["status"] == "RESERVED" and first["can_execute"] is True, "configured scheduler job was not reserved")
    req(len(state["reservations"]) == 1, "reservation did not persist")
    state, duplicate = preflight(state, job, at=at)
    req(duplicate["status"] == "DUPLICATE_SUPPRESSED" and len(state["reservations"]) == 1, "duplicate spend was not suppressed")

    paid_route = {
        "route_id": "MRT-SYNTH-STEP20",
        "route_hash": "sha256:" + "a" * 64,
        "status": "ROUTED",
        "tier": 2,
        "provider_id": "approved-api-slot",
        "model_id": "UNCONFIGURED_STRONG",
        "max_estimated_cost_usd": 0.01,
    }
    model_request = {
        "request_id": "MRQ-SYNTH-STEP20",
        "project_ids": ["PRJ-000"],
        "authority_class": "OBSERVE",
        "data_classification": "SANITIZED",
        "max_input_tokens": 100,
        "max_output_tokens": 100,
    }
    _, paid = reserve_model_execution(load_state(), paid_route, model_request, at=at)
    req(paid["status"] == "BLOCKED_BUDGET", "checked-in zero paid/model budget did not fail closed")

    tier0_route = {"status": "ROUTED", "tier": 0}
    unchanged, tier0 = reserve_model_execution(load_state(), tier0_route, model_request, at=at)
    req(tier0["status"] == "TIER0_NO_SPEND" and tier0["can_execute"] is True and unchanged["sequence"] == 0, "Tier 0 should require no model/API reservation")

    managed = [
        ".github/workflows/runtime-worker.yml",
        ".github/workflows/hunter-autonomous-cycle.yml",
        ".github/workflows/software-factory-candidate.yml",
        ".github/workflows/portfolio-autonomous-scheduler.yml",
    ]
    for path in managed:
        body = (ROOT / path).read_text()
        low = body.lower()
        req("portfolio-cost-governed-autonomy" in body, f"{path} missing global cost concurrency")
        req("cost_governor.workflow_gate preflight" in body, f"{path} missing cost preflight")
        req("cost_governor.workflow_gate finalize" in body, f"{path} missing conservative cost commit")
        req("portfolio-cost-governor-state" in body, f"{path} missing durable cost state artifact")
        req("openai" not in low and "anthropic" not in low, f"{path} added direct model dependency")

    watchdog = (ROOT / ".github/workflows/portfolio-cost-watchdog.yml").read_text().lower()
    req("actions: write" in watchdog and "cancel_managed_jobs" in watchdog, "cost watchdog cannot cancel managed jobs")
    req("contents: write" not in watchdog and "pull-requests: write" not in watchdog, "watchdog has excess repository write authority")

    contract = (ROOT / "cost_governor/COST_GOVERNOR_CONTRACT.md").read_text()
    for phrase in ["fail-closed", "Idempotency", "PORTFOLIO_SPEND_DISABLED", "ACT requests are rejected"]:
        req(phrase in contract, f"cost contract missing {phrase}")

    return {
        "portfolio_paid_usd_daily": p["portfolio_ceiling"]["cost_usd"],
        "portfolio_model_calls_daily": p["portfolio_ceiling"]["model_calls"],
        "retry_max": max(p["retry_limits"].values()),
        "managed_budgeted_workflows": len(managed),
        "durable_state_artifact": p["state_persistence"]["artifact_name"],
        "global_concurrency_group": p["global_concurrency_group"],
        "paid_route_checked_in_status": paid["status"],
        "tier0_status": tier0["status"],
    }

if __name__ == "__main__":
    print("portfolio-brain Step 20 cost governor: PASS", json.dumps(validate_cost_governor(), sort_keys=True))
