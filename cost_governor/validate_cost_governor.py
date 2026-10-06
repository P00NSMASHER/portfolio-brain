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
from workload_control.workload_gate import evaluate as evaluate_workload, load_policy as workload_policy

ROOT = Path(__file__).resolve().parents[1]


class CostGovernorValidationError(ValueError):
    pass


def req(ok, msg):
    if not ok:
        raise CostGovernorValidationError(msg)


def validate_cost_governor():
    p = policy()
    validate_policy(p)
    wp = workload_policy()

    req(p["mode"] == "FAIL_CLOSED_PRE_EXECUTION_RESERVATION", "cost governor mode changed")
    req(p["authority_class"] == "NONE", "cost governor authority widened")
    req(p["portfolio_ceiling"]["cost_usd"] == 10, "USD 10/day paid ceiling changed")
    req(p["portfolio_ceiling"]["model_calls"] > 0 and p["portfolio_ceiling"]["api_calls"] > 0,
        "paid model/API capacity missing")
    for field in ("cost_usd", "input_tokens", "output_tokens", "model_calls", "api_calls"):
        value = p["portfolio_ceiling"][field]
        req(type(value) in {int, float} and value >= 0, f"invalid paid budget: {field}")

    req(p["portfolio_ceiling"]["github_job_starts"] == 0, "GitHub job starts are still a financial ceiling")
    req(p["portfolio_ceiling"]["github_runner_minutes"] == 0, "GitHub runner minutes are still a financial ceiling")
    req(p["workload_separation"]["github_daily_job_quotas_enforced"] is False,
        "daily GitHub job quotas unexpectedly re-enabled")
    req(p["workload_separation"]["reporting_remains_available_during_paid_hard_stop"] is True,
        "reporting no longer survives paid hard stops")
    req(p["global_concurrency_group"] == "portfolio-cost-governed-autonomy",
        "paid cost serialization changed")

    at = "2026-09-25T12:00:00Z"

    # Paid-workflow wrappers remain bounded by a per-job timeout but not daily
    # GitHub job-count quotas.
    wrapper = make_github_job_request(
        workflow_id="runtime-worker",
        job_id="runtime-daily",
        run_id="step20-validator",
        attempt=1,
        project_ids=["PRJ-000"],
        estimated_minutes=5,
        authority_class="OBSERVE",
        at=at,
    )
    state, first = preflight(load_state(), wrapper, at=at)
    req(first["status"] == "RESERVED" and first["can_execute"] is True,
        "paid workflow wrapper did not reserve")
    state, duplicate = preflight(state, wrapper, at=at)
    req(duplicate["status"] == "DUPLICATE_SUPPRESSED",
        "duplicate wrapper admission was not suppressed")

    actual = zero_usage()
    actual.update({"github_job_starts": 1, "github_runner_minutes": 6})
    state, committed = commit_reservation(state, first["reservation_id"], actual, at=at)
    req(committed["status"] == "COMMITTED",
        "GitHub runner-minute variance incorrectly tripped a paid hard stop")
    req(hard_stop_reason(state, at=at) is None,
        "GitHub workload usage incorrectly entered paid hard-stop state")

    # A paid model overage must block the next paid preflight.
    route = {
        "status": "ROUTED",
        "tier": 2,
        "route_id": "MRT-STEP20-OVERAGE-1",
        "provider_id": "openai",
        "model_id": "gpt-5.6-luna",
        "max_estimated_cost_usd": 0.01,
        "route_hash": "sha256:step20-overage-1",
    }
    request = {
        "request_id": "MRQ-STEP20-OVERAGE-1",
        "project_ids": ["PRJ-000"],
        "max_input_tokens": 100,
        "max_output_tokens": 100,
        "authority_class": "OBSERVE",
        "data_classification": "SANITIZED",
    }
    paid_state, paid = reserve_model_execution(load_state(), route, request, at=at)
    req(paid["status"] == "RESERVED", "bounded paid model request did not reserve")

    paid_actual = zero_usage()
    paid_actual.update({
        "cost_usd": 0.02,
        "input_tokens": 100,
        "output_tokens": 100,
        "model_calls": 1,
        "api_calls": 1,
    })
    paid_state, overage = commit_reservation(
        paid_state, paid["reservation_id"], paid_actual, at=at
    )
    req(overage["status"] == "HARD_STOP_OVERAGE", "paid overage did not trip hard stop")
    req(hard_stop_reason(paid_state, at=at) == "CURRENT_DAY_PAID_RESERVATION_OVERAGE",
        "paid hard-stop reason missing")

    route2 = dict(route, route_id="MRT-STEP20-OVERAGE-2", route_hash="sha256:step20-overage-2")
    request2 = dict(request, request_id="MRQ-STEP20-OVERAGE-2")
    paid_state, blocked = reserve_model_execution(paid_state, route2, request2, at=at)
    req(blocked["status"] == "BLOCKED_BUDGET" and blocked["can_execute"] is False,
        "subsequent paid preflight ignored active hard stop")
    req(any(code.startswith("HARD_STOP_ACTIVE:") for code in blocked["reason_codes"]),
        "paid hard-stop block reason missing")

    # The same paid hard stop must not block a GitHub wrapper admission.
    _, wrapper_after_stop = preflight(
        paid_state,
        make_github_job_request(
            workflow_id="runtime-worker",
            job_id="runtime-daily",
            run_id="step20-after-paid-stop",
            attempt=1,
            project_ids=["PRJ-000"],
            estimated_minutes=5,
            authority_class="OBSERVE",
            at=at,
        ),
        at=at,
    )
    req(wrapper_after_stop["status"] == "RESERVED",
        "paid hard stop incorrectly blocked non-paid wrapper work")

    paid_workflows = {
        "runtime-worker": ROOT / ".github/workflows/runtime-worker.yml",
        "model-value-proof": ROOT / ".github/workflows/model-value-proof.yml",
    }
    for name, workflow_path in paid_workflows.items():
        body = workflow_path.read_text(encoding="utf-8").lower()
        for fragment in (
            "portfolio-cost-governed-autonomy",
            "state_journal.production_reader --domain cost",
            "cost_governor.workflow_gate preflight",
            "cost_governor.workflow_gate finalize",
            "portfolio-cost-governor-state",
        ):
            req(fragment in body, f"{name} paid cost integration missing: {fragment}")

    nonpaid_workflows = {
        "portfolio-autonomous-scheduler": ("schedule", "portfolio-scheduler", 12),
        "hunter-autonomous-cycle": ("hunt", "portfolio-hunter-cycle", 10),
        "command-center-pages": ("publish", "portfolio-reporting-pages", 10),
        "agent-heartbeat-sweep": ("heartbeat", "portfolio-heartbeat", 8),
        "portfolio-notification-cycle": ("notify", "portfolio-notification", 8),
        "software-factory-candidate": ("execute-candidate-action", "portfolio-software-factory", 5),
        "verified-feedback-bootstrap": ("feedback", "portfolio-feedback-bootstrap", 2),
        "continuous-learning-bootstrap": ("bootstrap", "portfolio-learning-bootstrap", 2),
    }
    for workflow_id, (job_id, group, minutes) in nonpaid_workflows.items():
        body = (ROOT / ".github/workflows" / f"{workflow_id}.yml").read_text(encoding="utf-8")
        req("workload_control.workload_gate preflight" in body,
            f"{workflow_id} missing workload admission")
        req("cost_governor.workflow_gate" not in body,
            f"{workflow_id} still coupled to paid cost gate")
        req(f"group: {group}" in body,
            f"{workflow_id} missing independent concurrency lane")
        decision = evaluate_workload(
            workflow_id=workflow_id,
            job_id=job_id,
            estimated_minutes=minutes,
        )
        req(decision["status"] == "WORKLOAD_ALLOWED",
            f"{workflow_id} workload admission failed")
        req(wp["services"][f"{workflow_id}::{job_id}"]["concurrency_group"] == group,
            f"{workflow_id} workload policy lane drifted")

    runtime_worker = paid_workflows["runtime-worker"].read_text(encoding="utf-8")
    req("workload_control.workload_gate preflight" in runtime_worker,
        "runtime worker missing non-paid workload admission")
    req("format('portfolio-runtime-{0}', inputs.mode)" in runtime_worker,
        "runtime worker missing mode-specific non-paid concurrency")
    for job_id, group in (
        ("runtime-observe", "portfolio-runtime-observe"),
        ("runtime-sync", "portfolio-runtime-sync"),
    ):
        decision = evaluate_workload(
            workflow_id="runtime-worker",
            job_id=job_id,
            estimated_minutes=15,
        )
        req(decision["status"] == "WORKLOAD_ALLOWED",
            f"{job_id} workload admission failed")
        req(wp["services"][f"runtime-worker::{job_id}"]["concurrency_group"] == group,
            f"{job_id} workload concurrency drifted")
    req("runtime-hourly-sync" not in p["managed_workflow_names"],
        "paid hard stop still targets non-paid runtime sync")
    req("runtime-event-observe" not in p["managed_workflow_names"],
        "paid hard stop still targets non-paid runtime observe")
    for name in ("runtime-daily-learning", "runtime-weekly-synthesis", "model-value-proof"):
        req(name in p["managed_workflow_names"], f"paid hard-stop target missing: {name}")

    runtime_keys = [
        "runtime-worker::runtime-observe",
        "runtime-worker::runtime-sync",
        "runtime-worker::runtime-daily",
        "runtime-worker::runtime-weekly",
        "model-value-proof::proof",
    ]
    req(all(key in p["workflow_job_ceilings"] for key in runtime_keys),
        "paid wrapper timeout controls incomplete")
    for key in runtime_keys:
        cfg = p["workflow_job_ceilings"][key]
        req(cfg["daily_ceiling"]["github_job_starts"] == 0,
            f"{key} still has a daily job-start quota")
        req(cfg["daily_ceiling"]["github_runner_minutes"] == 0,
            f"{key} still has a daily runner-minute quota")
        req(cfg["max_minutes_per_job"] > 0, f"{key} per-job timeout missing")

    command_center = nonpaid_workflows["command-center-pages"]
    command_body = (ROOT / ".github/workflows/command-center-pages.yml").read_text(encoding="utf-8").lower()
    req('cron: "37 * * * *"' in command_body, "hourly command-center refresh schedule missing")
    req("portfolio_spend_disabled" not in command_body,
        "command-center publication is still coupled to spend kill switch")
    req("actions: read" in command_body and "pages: write" in command_body,
        "command-center permissions incomplete")
    req("contents: write" not in command_body and "actions: write" not in command_body,
        "command-center publication write authority widened")
    req("dashboard.live_state_bridge" in command_body,
        "command-center live-state restore missing")

    value_proof = paid_workflows["model-value-proof"].read_text(encoding="utf-8").lower()
    req("portfolio_model_api_key" in value_proof, "model value proof credential binding missing")
    req("value_proof.end_to_end" in value_proof, "model value proof finalization missing")

    feedback = (ROOT / ".github/workflows/verified-feedback-bootstrap.yml").read_text(encoding="utf-8").lower()
    learning = (ROOT / ".github/workflows/continuous-learning-bootstrap.yml").read_text(encoding="utf-8").lower()
    for name, body in (("verified feedback", feedback), ("continuous learning", learning)):
        req("portfolio_model_api_key" not in body, f"{name} unexpectedly binds model credentials")
        req("python -m value_proof.model_task" not in body and "python -m value_proof.verifier" not in body,
            f"{name} unexpectedly executes paid model calls")

    watchdog = (ROOT / ".github/workflows/portfolio-cost-watchdog.yml").read_text(encoding="utf-8").lower()
    req("actions: write" in watchdog and "contents: read" in watchdog and "contents: write" not in watchdog,
        "watchdog permissions invalid")
    req("cost_governor.cancel_managed_jobs" in watchdog, "watchdog cancellation helper missing")
    req("operations.workflow_liveness" in watchdog, "watchdog liveness recovery helper missing")

    liveness = json.loads((ROOT / "operations/WORKFLOW_LIVENESS_POLICY.json").read_text())
    req(liveness["hard_stop_behavior"] == "NONPAID_RECOVERY_CONTINUES",
        "workflow liveness still globally stops on paid hard stop")
    req(any(t["admission_domain"] == "WORKLOAD" for t in liveness["targets"]),
        "workflow liveness lacks workload-domain targets")
    req(all(t["admission_domain"] == "WORKLOAD" for t in liveness["targets"]),
        "core workflow liveness must recover only non-paid workload targets")
    req("foundation-ci" not in {t["workflow_name"] for t in liveness["targets"]},
        "foundation CI may not be auto-recovered by watchdog")

    router_policy = json.loads((ROOT / "model_router/MODEL_ROUTER_POLICY.json").read_text())
    req(any("cost governor" in x.lower().replace("-", " ") for x in router_policy["invariants"]),
        "model router missing cost-governor execution invariant")

    return {
        "paid_usd_ceiling": p["portfolio_ceiling"]["cost_usd"],
        "paid_model_calls_ceiling": p["portfolio_ceiling"]["model_calls"],
        "github_daily_job_quota_enforced": p["workload_separation"]["github_daily_job_quotas_enforced"],
        "workload_services": len(wp["services"]),
        "paid_cost_workflows": len(paid_workflows),
        "nonpaid_workload_workflows": len(nonpaid_workflows),
        "duplicate_suppression": True,
        "paid_overage_hard_stop": True,
        "paid_hard_stop_blocks_next_paid_preflight": True,
        "paid_hard_stop_blocks_reporting": False,
        "authority_change": "NONE",
    }


if __name__ == "__main__":
    print(
        "portfolio-brain Step 20 cost governor: PASS",
        json.dumps(validate_cost_governor(), sort_keys=True),
    )
