#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
class OperatingModeValidationError(ValueError):pass
def req(ok,msg):
    if not ok:raise OperatingModeValidationError(msg)
def load(p):return json.loads((ROOT/p).read_text())

def validate_operating_mode():
    p=load("operations/OPERATING_MODE_POLICY.json")
    s=load("operations/OPERATING_MODE_STATUS.json")
    build=load("PORTFOLIO_BUILD_STATE.json")
    req(p["schema_version"]=="1.0.0" and p["default_branch"]=="main","operating policy identity/default branch mismatch")
    req(p["interactive_chatgpt_runtime_dependency"] is False,"interactive ChatGPT became runtime dependency")
    req(p["paid_model_api_default"]=="DENY_ZERO_BUDGET","paid/model default widened")
    req(s["status"]=="RELEASE_CANDIDATE" and s["promoted_main_sha"] is None,"pre-promotion operating status invalid")

    step23=build["step_progress"]["23"]["verified_contract"]
    step24=build["step_progress"]["24"]["verified_contract"]
    req(build["current_step"]==25 and build["step_progress"]["24"]["status"]=="COMPLETE","Step 24 is not complete/current Step is not 25")
    req(step23["unresolved_findings"]==0,"unresolved hostile finding remains")
    req(step24["paid_cost_usd"]==0 and step24["model_calls"]==0 and step24["learning_promotions"]==0,"Step 24 zero-paid/zero-promotion evidence lost")
    req(step24["authority_violations"]==0 and step24["continuation_selected_work"]==0,"Step 24 authority/dedup evidence lost")
    req(step24["interactive_chatgpt_dependency"] is False,"Step 24 required interactive ChatGPT")

    cost=load("cost_governor/COST_GOVERNOR_POLICY.json")
    for field in ("cost_usd","input_tokens","output_tokens","model_calls","api_calls"):
        req(cost["portfolio_ceiling"][field]==0,f"checked-in paid/model/API ceiling opened: {field}")
    providers=load("model_router/PROVIDER_REGISTRY.json")
    enabled_nonzero=[(x["provider_id"],m["model_id"]) for x in providers["providers"] for m in x["models"] if x["enabled"] and m["enabled"] and m["tier"]>0]
    req(enabled_nonzero==[],"non-Tier-0 provider/model enabled before final release")

    expected={
      "runtime-hourly-sync":"17 * * * *",
      "runtime-daily-learning":"37 9 * * *",
      "runtime-weekly-synthesis":"17 10 * * 1",
      "hunter-autonomous-cycle":"47 */6 * * *",
      "portfolio-autonomous-scheduler":"23 * * * *",
      "portfolio-cost-watchdog":"*/15 * * * *",
      "portfolio-notification-cycle":"7 */6 * * *",
    }
    req(set(p["approved_recurring_workflows"])==set(expected),"approved recurring workflow set changed")
    for name,cron in expected.items():
        path=ROOT/".github/workflows"/f"{name}.yml"
        body=path.read_text()
        req(cron in body,f"{name} cron mismatch")
    for name in ["hunter-autonomous-cycle","portfolio-autonomous-scheduler","portfolio-notification-cycle"]:
        body=(ROOT/".github/workflows"/f"{name}.yml").read_text().lower()
        req("portfolio-cost-governed-autonomy" in body and "cost_governor.workflow_gate preflight" in body,f"{name} is not cost governed")
    worker=(ROOT/".github/workflows/runtime-worker.yml").read_text().lower()
    req("portfolio-cost-governed-autonomy" in worker and "cost_governor.workflow_gate preflight" in worker,"runtime worker is not cost governed")
    factory=(ROOT/".github/workflows/software-factory-candidate.yml").read_text().lower()
    req("workflow_call" in factory and "schedule:" not in factory,"software factory unexpectedly recurring")
    req("cost_governor.workflow_gate preflight" in factory,"software factory is not cost governed")
    event=(ROOT/".github/workflows/runtime-event-observe.yml").read_text().lower()
    req("push:" in event and 'branches: ["main"]' in event,"main push observer missing")
    watchdog=(ROOT/".github/workflows/portfolio-cost-watchdog.yml").read_text().lower()
    req("actions: write" in watchdog and "contents: read" in watchdog and "contents: write" not in watchdog,"watchdog permissions invalid")
    foundation=(ROOT/".github/workflows/foundation-ci.yml").read_text().lower()
    req('branches: ["main", "step*-*"]' in foundation,"foundation CI main trigger missing")

    artifacts=p["durable_state_artifacts"]
    req(artifacts=={
      "runtime":"portfolio-runtime-state","hunter":"portfolio-hunter-state",
      "scheduler":"portfolio-scheduler-state","cost":"portfolio-cost-governor-state",
      "notifications":"portfolio-notification-state"
    },"durable artifact names changed")

    kill_files={
      "runtime":"runtime/KILL_SWITCH.json",
      "hunter":"hunting/KILL_SWITCH.json",
      "scheduler":"scheduler/KILL_SWITCH.json",
      "cost":"cost_governor/COST_KILL_SWITCH.json",
      "notifications":"notifications/KILL_SWITCH.json"
    }
    for name,path in kill_files.items():
        data=load(path)
        key="spend_disabled" if name=="cost" else "disabled"
        req(data.get(key) is False,f"checked-in {name} kill switch unexpectedly active")

    req("CUSTOMER_COMMUNICATION_REQUIRES_HUMAN_APPROVAL" in p["permanent_authority_boundaries"],"customer communication boundary missing")
    req("LIVE_MARKET_TRADING_AND_BROKERAGE_EXECUTION_PROHIBITED" in p["permanent_authority_boundaries"],"trading prohibition missing")
    req("DEPLOYMENT_AND_MERGE_NOT_GRANTED_TO_AUTONOMOUS_SCHEDULER" in p["permanent_authority_boundaries"],"deploy/merge boundary missing")

    return {
      "approved_recurring_workflows":len(expected),
      "durable_state_artifacts":len(artifacts),
      "enabled_nonzero_models":len(enabled_nonzero),
      "step23_unresolved":step23["unresolved_findings"],
      "step24_authority_violations":step24["authority_violations"],
      "step24_paid_cost_usd":step24["paid_cost_usd"],
      "interactive_chatgpt_runtime_dependency":False,
      "release_status":s["status"]
    }

if __name__=="__main__":
    print("portfolio-brain Step 25 operating-mode release candidate: PASS",json.dumps(validate_operating_mode(),sort_keys=True))
