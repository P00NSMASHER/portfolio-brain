#!/usr/bin/env python3
from __future__ import annotations
import json,re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SHA40=re.compile(r"^[0-9a-f]{40}$")
class OperatingModeValidationError(ValueError):pass
def req(ok,msg):
    if not ok:raise OperatingModeValidationError(msg)
def load(p):return json.loads((ROOT/p).read_text())

def validate_operating_mode():
    p=load("operations/OPERATING_MODE_POLICY.json")
    s=load("operations/OPERATING_MODE_STATUS.json")
    build=load("PORTFOLIO_BUILD_STATE.json")
    req(p["schema_version"]=="1.0.0" and p["default_branch"]=="main","operating policy identity/default branch mismatch")
    req(p["release_phase"] in {"STEP25_FINAL_RELEASE_CANDIDATE","STEP25_OPERATIONAL"},"invalid release phase")
    req(p["interactive_chatgpt_runtime_dependency"] is False,"interactive ChatGPT became runtime dependency")
    req(p["paid_model_api_default"]=="FINITE_GOVERNED_BUDGET_PROVIDER_GATED","paid/model operating mode mismatch")

    operational=s["status"]=="OPERATIONAL"
    if operational:
        req(p["release_phase"]=="STEP25_OPERATIONAL","operational status without operational policy phase")
        req(SHA40.fullmatch(s["promoted_main_sha"] or "") is not None,"promoted main SHA invalid")
        req(type(s["final_ci_run_id"]) is int and s["final_ci_run_id"]>0,"post-promotion foundation CI run missing")
        req(type(s["post_promotion_runtime_run_id"]) is int and s["post_promotion_runtime_run_id"]>0,"post-promotion runtime run missing")
        req(s["operational_without_interactive_chatgpt"] is True,"runtime independence not verified")
        arts=s["post_promotion_runtime_artifacts"]
        names={a["name"] for a in arts}
        req({"portfolio-runtime-state","portfolio-cost-governor-state"}<=names,"post-promotion continuation artifacts missing")
        req(all(str(a.get("digest","")).startswith("sha256:") for a in arts),"artifact digest missing")
        req(build["current_step"] is None and build["phase"]=="operational","final build cursor not operational")
        req(25 in build["completed_steps"] and build["step_progress"]["25"]["status"]=="COMPLETE","Step 25 not complete")
        req(build["step_progress"]["25"]["verified_contract"]["promoted_main_sha"]==s["promoted_main_sha"],"build/status promotion SHA mismatch")
    else:
        req(s["status"]=="RELEASE_CANDIDATE" and s["promoted_main_sha"] is None,"pre-promotion operating status invalid")
        req(build["current_step"]==25 and build["step_progress"]["24"]["status"]=="COMPLETE","Step 24 is not complete/current Step is not 25")

    step23=build["step_progress"]["23"]["verified_contract"]
    step24=build["step_progress"]["24"]["verified_contract"]
    req(step23["unresolved_findings"]==0,"unresolved hostile finding remains")
    req(step24["paid_cost_usd"]==0 and step24["model_calls"]==0 and step24["learning_promotions"]==0,"Step 24 zero-paid/zero-promotion evidence lost")
    req(step24["authority_violations"]==0 and step24["continuation_selected_work"]==0,"Step 24 authority/dedup evidence lost")
    req(step24["interactive_chatgpt_dependency"] is False,"Step 24 required interactive ChatGPT")

    cost=load("cost_governor/COST_GOVERNOR_POLICY.json")
    for field in ("cost_usd","input_tokens","output_tokens","model_calls","api_calls"):
        value=cost["portfolio_ceiling"][field]
        req(type(value) in {int,float} and value>=0,f"invalid finite portfolio ceiling: {field}")
    req(cost["portfolio_ceiling"]["cost_usd"]>0 and cost["portfolio_ceiling"]["model_calls"]>0,
        "optimized operating mode requires nonzero finite model capacity")
    providers=load("model_router/PROVIDER_REGISTRY.json")
    enabled_nonzero=[(x["provider_id"],m["model_id"]) for x in providers["providers"] for m in x["models"] if x["enabled"] and m["enabled"] and m["tier"]>0]
    req(enabled_nonzero==[
      ("openai","gpt-5.6-luna"),("openai","gpt-5.6-terra"),("openai","gpt-5.6-sol")
    ],"approved non-Tier-0 provider/model set mismatch")

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
        body=(ROOT/".github/workflows"/f"{name}.yml").read_text()
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

    req(p["durable_state_artifacts"]=={
      "runtime":"portfolio-runtime-state","hunter":"portfolio-hunter-state",
      "scheduler":"portfolio-scheduler-state","cost":"portfolio-cost-governor-state",
      "notifications":"portfolio-notification-state"
    },"durable artifact names changed")

    kill_files={
      "runtime":"runtime/KILL_SWITCH.json","hunter":"hunting/KILL_SWITCH.json",
      "scheduler":"scheduler/KILL_SWITCH.json","cost":"cost_governor/COST_KILL_SWITCH.json",
      "notifications":"notifications/KILL_SWITCH.json"
    }
    for name,path in kill_files.items():
        data=load(path);key="spend_disabled" if name=="cost" else "disabled"
        req(data.get(key) is False,f"checked-in {name} kill switch unexpectedly active")

    boundaries=set(p["permanent_authority_boundaries"])
    for b in [
      "PAYMENT_CASH_MOVEMENT_REQUIRES_HUMAN_APPROVAL",
      "LIVE_MARKET_TRADING_AND_BROKERAGE_EXECUTION_PROHIBITED",
      "DEPLOYMENT_AND_MERGE_NOT_GRANTED_TO_AUTONOMOUS_SCHEDULER",
      "CHILD_FACING_CONSEQUENTIAL_CHANGES_REQUIRE_APPROVAL"
    ]:req(b in boundaries,f"authority boundary missing: {b}")

    return {
      "approved_recurring_workflows":len(expected),
      "durable_state_artifacts":len(p["durable_state_artifacts"]),
      "enabled_nonzero_models":len(enabled_nonzero),
      "step23_unresolved":step23["unresolved_findings"],
      "step24_authority_violations":step24["authority_violations"],
      "step24_paid_cost_usd":step24["paid_cost_usd"],
      "interactive_chatgpt_runtime_dependency":False,
      "release_status":s["status"],
      "promoted_main_sha":s["promoted_main_sha"]
    }

if __name__=="__main__":
    print("portfolio-brain Step 25 operating mode: PASS",json.dumps(validate_operating_mode(),sort_keys=True))
