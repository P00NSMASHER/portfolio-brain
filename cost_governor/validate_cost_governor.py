#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from cost_governor.cost_governor import (
    commit_reservation,
    hard_stop_reason,
    load_state,
    make_github_job_request,
    make_model_request,
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
    req(p["portfolio_ceiling"]["cost_usd"] == 10, "paid USD ceiling changed")
    req(p["portfolio_ceiling"]["model_calls"] > 0, "paid model capacity disabled")
    workload=p["github_workload_control"]
    req(workload["daily_job_count_quotas_enforced"] is False, "GitHub daily job quotas re-enabled")
    req(workload["durable_cost_reservations"] is False, "GitHub workload consumes paid ledger")
    req(p["global_concurrency_group"] == "portfolio-cost-governed-autonomy", "paid ledger serialization changed")
    paid_names=set(p["paid_execution_workflow_names"])
    req({"model-value-proof","runtime-daily-learning","runtime-weekly-synthesis"} <= paid_names,
        "paid execution workflow coverage incomplete")
    req(paid_names <= set(p["managed_workflow_names"]), "paid execution workflow is unmanaged")

    at = "2026-09-25T12:00:00Z"

    # Ordinary GitHub workload is bounded but state-neutral and independent of spend.
    workload_request = make_github_job_request(
        workflow_id="portfolio-autonomous-scheduler",
        job_id="schedule",
        run_id="step20-validator",
        attempt=1,
        project_ids=["PRJ-000"],
        estimated_minutes=5,
        authority_class="OBSERVE",
        at=at,
    )
    state, admitted = preflight(seed, workload_request, at=at)
    req(admitted["status"] == "WORKLOAD_ADMITTED" and admitted["can_execute"] is True,
        "managed scheduler workload was not admitted")
    req(state["sequence"] == seed["sequence"] and not state["reservations"],
        "GitHub workload mutated the paid ledger")
    state, admitted_again = preflight(state, workload_request, at=at)
    req(admitted_again["status"] == "WORKLOAD_ADMITTED" and not state["reservations"],
        "repeated workload admission consumed paid state")

    def paid_request(route_id: str, request_id: str):
        route={
            "status":"ROUTED","tier":2,"route_id":route_id,
            "provider_id":"approved-api-slot","model_id":"UNCONFIGURED_STRONG",
            "max_estimated_cost_usd":0.01,"route_hash":f"sha256:{route_id.lower()}",
        }
        model={
            "request_id":request_id,"project_ids":["PRJ-000"],
            "max_input_tokens":100,"max_output_tokens":100,
            "authority_class":"OBSERVE","data_classification":"SANITIZED",
        }
        return make_model_request(route,model,at=at)

    # Paid execution still reserves, suppresses duplicates, reconciles, and hard-stops.
    paid=paid_request("MRT-VALIDATOR","MRQ-VALIDATOR")
    paid_state, first = preflight(load_state(), paid, at=at)
    req(first["status"] == "RESERVED" and first["can_execute"] is True,
        "paid model request did not reserve")
    paid_state, duplicate = preflight(paid_state, paid, at=at)
    req(duplicate["status"] == "DUPLICATE_SUPPRESSED" and duplicate["can_execute"] is False,
        "duplicate paid execution was not suppressed")
    actual=zero_usage()
    actual.update({"cost_usd":0.01,"input_tokens":100,"output_tokens":100,"model_calls":1,"api_calls":1})
    paid_state, committed=commit_reservation(paid_state,first["reservation_id"],actual,at=at)
    req(committed["status"]=="COMMITTED" and hard_stop_reason(paid_state,at=at) is None,
        "valid paid reservation commit failed")

    over_state, reserved=preflight(load_state(),paid_request("MRT-OVERAGE","MRQ-OVERAGE"),at=at)
    over=zero_usage()
    over.update({"cost_usd":0.02,"input_tokens":50,"output_tokens":50,"model_calls":1,"api_calls":1})
    over_state, overage=commit_reservation(over_state,reserved["reservation_id"],over,at=at)
    req(overage["status"]=="HARD_STOP_OVERAGE","paid overage did not trip hard stop")
    req(hard_stop_reason(over_state,at=at)=="CURRENT_DAY_PAID_RESERVATION_OVERAGE",
        "paid hard stop reason missing")
    _, blocked=preflight(over_state,paid_request("MRT-AFTER-OVERAGE","MRQ-AFTER-OVERAGE"),at=at)
    req(blocked["status"]=="BLOCKED_HARD_STOP" and not blocked["can_execute"],
        "paid hard stop did not block the next preflight")

    workflows = {
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
    paid_ledger_workflows={"runtime-worker","model-value-proof"}
    workload_only=set(workflows)-paid_ledger_workflows
    for name,path in workflows.items():
        body=path.read_text().lower()
        req("cost_governor.workflow_gate preflight" in body,f"{name} workload preflight missing")
        if name in paid_ledger_workflows:
            for text in (
                "portfolio-cost-governed-autonomy",
                "cost_governor.artifact_state",
                "cost_governor.workflow_gate finalize",
                "portfolio_spend_disabled",
                "portfolio-cost-governor-state",
            ):
                req(text in body,f"{name} paid-ledger integration missing: {text}")
        else:
            req("--state cost_governor/cost_state_seed.json" in body,
                f"{name} does not use state-neutral workload seed")
            req("cost_governor.artifact_state" not in body,
                f"{name} still depends on paid-ledger restore")
            req("cost_governor.workflow_gate finalize" not in body,
                f"{name} still finalizes paid-ledger state")
            req("portfolio-cost-governor-state" not in body,
                f"{name} still publishes paid-ledger state")

    # Unrelated services get independent concurrency lanes; shared-state work keeps
    # only the minimum serialization necessary for consistency.
    pages=workflows["command-center-pages"].read_text()
    hunter=workflows["hunter-autonomous-cycle"].read_text()
    scheduler=workflows["portfolio-autonomous-scheduler"].read_text()
    heartbeat=workflows["agent-heartbeat-sweep"].read_text()
    notifications=workflows["portfolio-notification-cycle"].read_text()
    factory=workflows["software-factory-candidate"].read_text()
    req("group: portfolio-command-center-publish" in pages,"Pages lacks independent concurrency lane")
    req("group: portfolio-discovery-scheduling" in hunter and "group: portfolio-discovery-scheduling" in scheduler,
        "Hunter/Scheduler shared-state lane drifted")
    req("group: portfolio-agent-heartbeat" in heartbeat,"heartbeat concurrency lane drifted")
    req("group: portfolio-notification-cycle" in notifications,"notification concurrency lane drifted")
    req("group: portfolio-software-factory" in factory,"software-factory concurrency lane drifted")

    runtime_worker=workflows["runtime-worker"].read_text()
    runtime_keys=[
      "runtime-worker::runtime-observe",
      "runtime-worker::runtime-sync",
      "runtime-worker::runtime-daily",
      "runtime-worker::runtime-weekly",
    ]
    req(all(key in p["workflow_job_ceilings"] for key in runtime_keys),"runtime workload controls incomplete")
    req('--job-id "runtime-${RUNTIME_MODE}"' in runtime_worker,"runtime worker workload identity drifted")
    req(all(p["workflow_job_ceilings"][key]["max_minutes_per_job"]<=5 for key in runtime_keys),
        "runtime workload timeout widened")

    command_center=pages.lower()
    req('cron: "37 * * * *"' in command_center,"hourly command-center refresh schedule missing")
    req("actions: read" in command_center and "pages: write" in command_center,
        "command-center read/deploy permissions incomplete")
    req("contents: write" not in command_center and "actions: write" not in command_center,
        "command-center publication write authority widened")
    req("dashboard.live_state_bridge" in command_center,"command-center live-state restore missing")
    req("summarize command-center execution status" in command_center,
        "command-center lacks attempted/blocked/executed/verified receipt")

    value_proof=workflows["model-value-proof"].read_text().lower()
    req("portfolio_model_api_key" in value_proof,"model value proof provider credential binding missing")
    req("value_proof.end_to_end" in value_proof,"model value proof finalization missing")
    req("authority observe" in value_proof,"model value proof authority drifted")

    feedback=workflows["verified-feedback-bootstrap"].read_text().lower()
    learning=workflows["continuous-learning-bootstrap"].read_text().lower()
    for name,body in (("verified feedback",feedback),("continuous learning",learning)):
        req("portfolio_model_api_key" not in body,f"{name} workload may not bind model credentials")
        req("python -m value_proof.model_task" not in body and "python -m value_proof.verifier" not in body,
            f"{name} workload may not execute model calls")

    watchdog=(ROOT/".github/workflows/portfolio-cost-watchdog.yml").read_text().lower()
    req("cancel only paid-execution runs on spend hard stop" in watchdog,
        "watchdog cancellation scope is not explicit")
    cancel_helper=(ROOT/"cost_governor/cancel_managed_jobs.py").read_text()
    req('p["paid_execution_workflow_names"]' in cancel_helper,
        "watchdog still targets all managed workload")

    liveness=json.loads((ROOT/"operations/WORKFLOW_LIVENESS_POLICY.json").read_text())
    req(liveness["hard_stop_behavior"]=="WORKLOAD_RECOVERY_CONTINUES_PAID_TARGETS_EXCLUDED",
        "workload liveness is still coupled to paid hard stops")
    liveness_names={row["workflow_name"] for row in liveness["targets"]}
    req(liveness_names.isdisjoint(paid_names),"liveness recovery targets paid-execution workflows")
    req(liveness_names<=set(p["managed_workflow_names"]),"workflow liveness targets unmanaged workflows")
    req("foundation-ci" not in liveness_names,"foundation CI may not be auto-recovered")

    router_policy = json.loads((ROOT / "model_router/MODEL_ROUTER_POLICY.json").read_text())
    req(any("cost governor" in x.lower().replace("-", " ") for x in router_policy["invariants"]),
        "model router missing cost-governor execution invariant")

    return {
        "paid_usd_ceiling":p["portfolio_ceiling"]["cost_usd"],
        "paid_model_calls_ceiling":p["portfolio_ceiling"]["model_calls"],
        "github_daily_job_quotas_enforced":workload["daily_job_count_quotas_enforced"],
        "github_workload_uses_paid_reservations":workload["durable_cost_reservations"],
        "paid_execution_workflows":len(paid_names),
        "workload_only_workflows":len(workload_only),
        "paid_hard_stop_preflight_enforced":True,
        "service_scoped_concurrency":True,
        "authority_change":"NONE",
    }

if __name__ == "__main__":
    print("portfolio-brain Step 20 cost governor: PASS", json.dumps(validate_cost_governor(), sort_keys=True))
