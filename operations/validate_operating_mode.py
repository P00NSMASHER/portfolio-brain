#!/usr/bin/env python3
from __future__ import annotations
import json,re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SHA40=re.compile(r"^[0-9a-f]{40}$")
ISO_Z=re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")
EMAIL=re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
RAW_CONNECTOR_ID=re.compile(r"(?<![0-9a-f])[0-9a-f]{16,32}(?![0-9a-f])",re.I)
class OperatingModeValidationError(ValueError):pass
def req(ok,msg):
    if not ok:raise OperatingModeValidationError(msg)
def load(p):return json.loads((ROOT/p).read_text())

def workflow_schedule_crons(path):
    """Return active schedule crons, None when the workflow is not scheduled.

    This deliberately inspects only the top-level ``on.schedule`` block. A raw
    substring search can mistake comments or unrelated scalar values for an
    approved production trigger.
    """
    lines=Path(path).read_text().splitlines()
    in_on=False
    in_schedule=False
    found_schedule=False
    crons=[]
    for raw in lines:
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent=len(raw)-len(raw.lstrip(" "))
        value=raw.strip()
        if indent==0:
            trigger=re.fullmatch(r"(?:on|'on'|\"on\")\s*:\s*(.*)",value)
            in_on=trigger is not None
            in_schedule=False
            if trigger is not None:
                req(not trigger.group(1),f"workflow triggers must use a block mapping in {path}")
            continue
        if not in_on:
            continue
        if indent==2:
            req(not re.match(r"^<<\s*:",value),f"workflow trigger aliases are not allowed in {path}")
            schedule=re.fullmatch(r"(?:schedule|'schedule'|\"schedule\")\s*:\s*(.*)",value)
            in_schedule=schedule is not None
            if schedule is not None:
                req(not schedule.group(1),f"workflow schedules must use a block sequence in {path}")
            found_schedule=found_schedule or in_schedule
            continue
        if in_schedule and indent>=4:
            match=re.match(r"^-\s+(?:cron|'cron'|\"cron\")\s*:\s*(.+?)\s*$",value)
            if match:
                cron=match.group(1).split(" #",1)[0].strip().strip('"\'')
                req(bool(cron),f"empty workflow cron in {path}")
                crons.append(cron)
    return crons if found_schedule else None

def workflow_top_level_triggers(path):
    """Return active keys from the top-level ``on`` mapping.

    The production workflows use block mappings. Parsing only two-space keys
    keeps comments and nested values from masquerading as active triggers.
    """
    triggers=set()
    in_on=False
    for raw in Path(path).read_text().splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent=len(raw)-len(raw.lstrip(" "))
        value=raw.strip()
        if indent==0:
            trigger=re.fullmatch(r"(?:on|'on'|\"on\")\s*:\s*(.*)",value)
            in_on=trigger is not None
            if trigger is not None:
                req(not trigger.group(1),f"workflow triggers must use a block mapping in {path}")
            continue
        if in_on and indent==2:
            match=re.fullmatch(r"([A-Za-z_][A-Za-z0-9_-]*)\s*:\s*(.*)",value)
            if match:
                triggers.add(match.group(1))
    return triggers

def scheduled_workflow_inventory(workflow_dir):
    """Return the canonical scheduled-workflow inventory.

    GitHub loads both ``.yml`` and ``.yaml`` workflow files. Treating only one
    extension as governed lets an alternate-extension workflow bypass the
    approved recurring inventory. Duplicate stems are also rejected so a
    second extension cannot shadow the reviewed workflow identity.
    """
    workflow_dir=Path(workflow_dir)
    paths=sorted((*workflow_dir.glob("*.yml"),*workflow_dir.glob("*.yaml")))
    actual={}
    seen=set()
    for path in paths:
        req(path.stem not in seen,f"duplicate workflow identity: {path.stem}")
        seen.add(path.stem)
        crons=workflow_schedule_crons(path)
        if crons is not None:
            actual[path.stem]=crons
    return actual

def validate_reasoning_fallback(data=None):
    d=load("operations/CHATGPT_REASONING_FALLBACK.json") if data is None else data
    expected={
      "schema_version","generated_at","provider","source_main_sha","trigger_reason",
      "authority_granted","evidence_upgraded","top_bottleneck","next_actions",
      "experiment_improvement","reuse_opportunity","risks","evidence_refs"
    }
    req(type(d) is dict and set(d)==expected,"reasoning fallback fields changed")
    req(d["schema_version"]=="1.0.0","reasoning fallback schema mismatch")
    req(d["provider"]=="CHATGPT_SCHEDULED_FALLBACK","reasoning fallback provider mismatch")
    req(d["authority_granted"] is False,"reasoning fallback granted authority")
    req(d["evidence_upgraded"] is False,"reasoning fallback upgraded evidence")
    req(SHA40.fullmatch(d["source_main_sha"] or "") is not None,"reasoning fallback source SHA invalid")
    req(ISO_Z.fullmatch(d["generated_at"] or "") is not None,"reasoning fallback timestamp invalid")
    req(d["trigger_reason"] in {
      "OPENAI_API_BILLING_NOT_ACTIVE","OPENAI_API_QUOTA_EXHAUSTED",
      "OPENAI_API_THROTTLED","OPENAI_API_CREDENTIAL_MISSING",
      "GOVERNED_MODEL_ANALYSIS_DEFERRED"
    },"reasoning fallback trigger is not an approved continuity condition")
    for field in ("top_bottleneck","experiment_improvement","reuse_opportunity"):
        req(type(d[field]) is str and 1<=len(d[field])<=1200,f"reasoning fallback {field} invalid")
    req(type(d["next_actions"]) is list and len(d["next_actions"])==3,"reasoning fallback must contain exactly three actions")
    req(type(d["risks"]) is list and 1<=len(d["risks"])<=12,"reasoning fallback risks invalid")
    req(type(d["evidence_refs"]) is list and 1<=len(d["evidence_refs"])<=24,"reasoning fallback evidence refs invalid")
    for field in ("next_actions","risks","evidence_refs"):
        req(all(type(x) is str and 1<=len(x)<=500 for x in d[field]),f"reasoning fallback {field} entry invalid")
        req(len(d[field])==len(set(d[field])),f"reasoning fallback {field} contains duplicates")
    raw=json.dumps(d,sort_keys=True,ensure_ascii=False)
    req(EMAIL.search(raw) is None,"reasoning fallback contains an email address")
    req(RAW_CONNECTOR_ID.search(raw) is None,"reasoning fallback contains a raw connector identifier")
    forbidden=("gmail_message_id","gmail_thread_id","message_id","thread_id","draft_id","recipient","sender","subject","body","connector_id")
    req(not any(re.search(rf'"{re.escape(token)}"\s*:',raw,re.I) for token in forbidden),"reasoning fallback contains a private connector field")
    return {"provider":d["provider"],"authority_granted":False,"evidence_upgraded":False}

def validate_gmail_gateway_status(gmail,gateway_status,ledger):
    req(gateway_status.get("provider")==gmail["provider"] and gateway_status.get("account")==gmail["account_ref"],"operating status Gmail gateway binding mismatch")
    req(gateway_status.get("status")=="LIVE_GATEWAY_PROVEN","live Gmail gateway proof not recorded")
    req(gateway_status.get("proof_ledger")=="action_engine/GMAIL_GATEWAY_LEDGER.json","Gmail gateway proof ledger mismatch")
    req(ledger.get("ledger_id")=="portfolio-gmail-gateway-ledger" and type(ledger.get("sequence")) is int and ledger["sequence"]>0,"live Gmail gateway ledger proof missing")
    req(len(ledger.get("executions",[]))==ledger["sequence"] and all(row.get("status")=="SENT" for row in ledger["executions"]),"Gmail gateway proof executions invalid")
    req(gateway_status.get("proof_sequence")==ledger["sequence"],"Gmail gateway proof sequence stale")
    req(gateway_status.get("proof_at")==ledger.get("updated_at") and ISO_Z.fullmatch(gateway_status.get("proof_at") or "") is not None,"Gmail gateway proof timestamp stale or invalid")
    req(gateway_status.get("raw_connector_identifiers_persisted") is False,"Gmail gateway status permits raw connector identifiers")
    return {"status":gateway_status["status"],"proof_sequence":gateway_status["proof_sequence"]}

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
      "portfolio-cost-watchdog":"53 * * * *",
      "portfolio-notification-cycle":"7 */6 * * *",
      "command-center-pages":"37 * * * *",
      "agent-heartbeat-sweep":"29 */2 * * *",
    }
    req(set(p["approved_recurring_workflows"])==set(expected),"approved recurring workflow set changed")
    workflow_dir=ROOT/".github/workflows"
    actual=scheduled_workflow_inventory(workflow_dir)
    req(set(actual)==set(expected),"scheduled workflow inventory differs from approved operating policy")
    for name,cron in expected.items():
        req(actual[name]==[cron],f"{name} cron mismatch")
    workload=load("workload_control/WORKLOAD_POLICY.json")
    req(workload["mode"]=="GITHUB_NATIVE_WORKLOAD_CONTROL","workload control mode changed")
    workload_workflows={
      "hunter-autonomous-cycle":("hunt","portfolio-hunter-cycle"),
      "portfolio-autonomous-scheduler":("schedule","portfolio-scheduler"),
      "portfolio-notification-cycle":("notify","portfolio-notification"),
      "command-center-pages":("publish","portfolio-reporting-pages"),
      "agent-heartbeat-sweep":("heartbeat","portfolio-heartbeat"),
    }
    for name,(job_id,group) in workload_workflows.items():
        body=(ROOT/".github/workflows"/f"{name}.yml").read_text().lower()
        req("workload_control.workload_gate preflight" in body,f"{name} is not workload controlled")
        req("cost_governor.workflow_gate" not in body,f"{name} is still coupled to paid cost governance")
        req(f"group: {group}" in body,f"{name} independent concurrency lane missing")
        req("steps.workload.outputs.allowed != 'true'" in body,f"{name} lacks blocked-work reporting")
        req("exit 1" in body,f"{name} can still report green after workload admission blocks")
        scope=f"{name}::{job_id}"
        req(scope in workload["services"],f"{name} workload policy entry missing")
        req(workload["services"][scope]["concurrency_group"]==group,f"{name} workload policy lane drifted")
    for name in ["portfolio-autonomous-scheduler","agent-heartbeat-sweep"]:
        triggers=workflow_top_level_triggers(ROOT/".github/workflows"/f"{name}.yml")
        req("push" not in triggers,f"{name} must not fan out on push")

    worker=(ROOT/".github/workflows/runtime-worker.yml").read_text().lower()
    req("portfolio-cost-governed-autonomy" in worker and "cost_governor.workflow_gate preflight" in worker,
        "runtime worker lost serialized paid-wrapper governance")
    req("workload_control.workload_gate preflight" in worker,
        "runtime worker lost non-paid workload admission")
    req("format('portfolio-runtime-{0}', inputs.mode)" in worker,
        "runtime worker lost mode-specific non-paid concurrency")
    for mode in ("observe","sync"):
        scope=f"runtime-worker::runtime-{mode}"
        req(scope in workload["services"],f"runtime {mode} workload policy entry missing")
        req(workload["services"][scope]["concurrency_group"]==f"portfolio-runtime-{mode}",
            f"runtime {mode} workload lane drifted")
    req("steps.admission.outputs.allowed != 'true'" in worker and "exit 1" in worker,
        "runtime worker can still report green after mode-specific admission blocks")

    proof=(ROOT/".github/workflows/model-value-proof.yml").read_text().lower()
    req("portfolio-cost-governed-autonomy" in proof and "cost_governor.workflow_gate preflight" in proof,
        "model value proof lost paid cost governance")
    req("steps.cost.outputs.allowed != 'true'" in proof and "exit 1" in proof,
        "model value proof can still report green after paid admission blocks")

    factory=(ROOT/".github/workflows/software-factory-candidate.yml").read_text().lower()
    req("workflow_call" in factory and "schedule:" not in factory,"software factory unexpectedly recurring")
    req("workload_control.workload_gate preflight" in factory,"software factory is not workload controlled")
    req("cost_governor.workflow_gate" not in factory,"software factory is still coupled to paid cost governance")
    req("run: exit 3" in factory,"software factory must fail closed when workload admission is denied")
    repair_path=ROOT/".github/workflows/repair-candidate-cycle.yml"
    repair_cycle=repair_path.read_text().lower()
    repair_triggers=workflow_top_level_triggers(repair_path)
    req("workflow_run" in repair_triggers and "schedule" not in repair_triggers and "workflow_call" not in repair_triggers,
        "repair candidate cycle must be event-driven from scheduler completion")
    req('workflows: ["portfolio-autonomous-scheduler"]' in repair_cycle
        and "types: [completed]" in repair_cycle and 'branches: ["main"]' in repair_cycle,
        "repair candidate cycle scheduler trigger binding missing")
    req("github.event.workflow_run.conclusion == 'success'" in repair_cycle
        and "github.event.workflow_run.head_branch == 'main'" in repair_cycle
        and "github.event.workflow_run.head_repository.full_name == github.repository" in repair_cycle,
        "repair candidate cycle trigger provenance gate missing")
    req("run-id: ${{ github.event.workflow_run.id }}" in repair_cycle
        and "github-token: ${{ github.token }}" in repair_cycle,
        "repair candidate cycle does not consume the exact triggering scheduler artifact")
    req("steps.select.outputs.has_work == 'true'" in repair_cycle
        and "needs.plan-build.outputs.has_work == 'true'" in repair_cycle,
        "repair candidate cycle can spend or continue without selected repair work")
    req("group: portfolio-cost-governed-autonomy" in repair_cycle,"repair planning lost paid-state serialization")
    req("cost_governor.workflow_gate preflight" in repair_cycle and "cost_governor.workflow_gate finalize" in repair_cycle,
        "repair planning lost paid wrapper governance")
    for job in ("replay","submit","finalize"):
        req(f"--job-id {job}" in repair_cycle,f"repair {job} workload gate missing")
        req(f"repair-candidate-cycle::{job}" in workload["services"],f"repair {job} workload policy missing")
    req("software_factory.candidate_submitter" in repair_cycle,"repair cycle remote candidate submission missing")
    req("software_factory.complete_repair_work" in repair_cycle,"repair cycle scheduler completion missing")
    req(repair_cycle.count("contents: write")==1 and "pull-requests: write" not in repair_cycle
        and "create_pr" not in repair_cycle and "merge_pr" not in repair_cycle
        and "deployment_authorized: true" not in repair_cycle,
        "repair candidate cycle widened write authority beyond isolated candidate submission")
    repair_policy=p.get("event_driven_workflows",{}).get("repair-candidate-cycle",{})
    req(repair_policy.get("trigger")=="workflow_run:portfolio-autonomous-scheduler:completed:main",
        "repair candidate workflow event trigger is not recorded in operating policy")
    scheduler_body=(ROOT/".github/workflows/portfolio-autonomous-scheduler.yml").read_text().lower()
    req("contents: write" not in scheduler_body and "repair-candidate-cycle.yml" not in scheduler_body,
        "scheduler directly owns candidate write authority")
    event=(ROOT/".github/workflows/runtime-event-observe.yml").read_text().lower()
    req("push:" in event and 'branches: ["main"]' in event,"main push observer missing")
    req('"operations/command_center_refresh_request.json"' in event,"trigger-only command-center refresh still creates redundant runtime work")
    watchdog=(ROOT/".github/workflows/portfolio-cost-watchdog.yml").read_text().lower()
    req("actions: write" in watchdog and "contents: read" in watchdog and "contents: write" not in watchdog,"watchdog permissions invalid")
    watchdog_triggers=workflow_top_level_triggers(ROOT/".github/workflows/portfolio-cost-watchdog.yml")
    req({"schedule","workflow_run","push","workflow_dispatch"}<=watchdog_triggers,"watchdog independent recovery triggers incomplete")
    for producer in ("portfolio-autonomous-scheduler","runtime-hourly-sync","agent-heartbeat-sweep","hunter-autonomous-cycle","portfolio-notification-cycle"):
        req(f'- "{producer}"' in watchdog,f"watchdog liveness recovery anchor missing: {producer}")
    for producer in ("portfolio-autonomous-scheduler","runtime-hourly-sync","agent-heartbeat-sweep","hunter-autonomous-cycle","portfolio-notification-cycle"):
        req(f'- "{producer}"' in watchdog,f"watchdog missing liveness recovery anchor: {producer}")
    req("types: [completed]" in watchdog and 'branches: ["main"]' in watchdog,"watchdog liveness recovery anchors drifted")
    runtime_sync=(ROOT/".github/workflows/runtime-hourly-sync.yml").read_text().lower()
    req("push:" in runtime_sync and 'branches: ["main"]' in runtime_sync and '"adapters/**"' in runtime_sync and '"runtime/**"' in runtime_sync,"runtime repair wakeup trigger missing")
    req('"operations/trigger_workflow_liveness"' in watchdog,"watchdog explicit liveness trigger path missing")
    req("paths:" in watchdog,"watchdog push trigger must remain path-scoped")
    req("operations.workflow_liveness" in watchdog and "portfolio-workflow-liveness" in watchdog,"watchdog core-workflow recovery missing")
    liveness=load("operations/WORKFLOW_LIVENESS_POLICY.json")
    req(liveness["schema_version"]=="1.0.0" and liveness["liveness_id"]=="portfolio-core-workflow-liveness-v1","workflow liveness policy identity mismatch")
    req(liveness["authority_class"]=="NONE" and liveness["dispatch_authority_effect"]=="NONE","workflow liveness recovery widened authority")
    req(liveness["hard_stop_behavior"]=="NONPAID_RECOVERY_CONTINUES","workflow liveness paid/non-paid separation drifted")
    req(any(row["admission_domain"]=="WORKLOAD" for row in liveness["targets"]),"workflow liveness lacks non-paid workload recovery")
    req(all(row["admission_domain"]=="WORKLOAD" for row in liveness["targets"]),"core workflow liveness must remain non-paid workload recovery")
    req(1<=liveness["max_dispatches_per_cycle"]<=2 and 1<=liveness["max_history_pages"]<=5,"workflow liveness recovery bounds invalid")
    recovery_names={row["workflow_name"] for row in liveness["targets"]}
    req(recovery_names<=set(expected),"workflow liveness recovery target is not an approved recurring workflow")
    for target in liveness["targets"]:
        path=ROOT/".github/workflows"/target["workflow_file"]
        req(path.exists(),f"workflow liveness target file missing: {target['workflow_file']}")
        req("workflow_dispatch" in workflow_top_level_triggers(path),f"workflow liveness target not dispatchable: {target['workflow_name']}")
    foundation=(ROOT/".github/workflows/foundation-ci.yml").read_text().lower()
    req('branches: ["main", "step*-*"]' in foundation,"foundation CI main trigger missing")

    req(p["durable_state_artifacts"]=={
      "runtime":"portfolio-runtime-state","hunter":"portfolio-hunter-state",
      "scheduler":"portfolio-scheduler-state","cost":"portfolio-cost-governor-state",
      "notifications":"portfolio-notification-state","agents":"portfolio-agent-heartbeat-state"
    },"durable artifact names changed")

    kill_files={
      "runtime":"runtime/KILL_SWITCH.json","hunter":"hunting/KILL_SWITCH.json",
      "scheduler":"scheduler/KILL_SWITCH.json","cost":"cost_governor/COST_KILL_SWITCH.json",
      "notifications":"notifications/KILL_SWITCH.json"
    }
    for name,path in kill_files.items():
        data=load(path);key="spend_disabled" if name=="cost" else "disabled"
        req(data.get(key) is False,f"checked-in {name} kill switch unexpectedly active")

    gmail=p.get("external_connector_gateways",{}).get("gmail",{})
    req(gmail.get("provider")=="CHATGPT_GMAIL_CONNECTOR" and gmail.get("account_ref")=="PRIMARY_GMAIL_CONNECTOR","Gmail connector gateway binding missing")
    req(gmail.get("execution_task_id")=="6ab377c25df08191a6e2aa1537d9d2ef","Gmail gateway executor task mismatch")
    req(gmail.get("planner_task_id")=="6ab377be3184819186a3075f37a530b8","Gmail gateway planner task mismatch")
    req(load("action_engine/KILL_SWITCH.json").get("disabled") is False,"checked-in Gmail action kill switch unexpectedly active")
    req(not (ROOT/".github/workflows/portfolio-action-worker.yml").exists(),"obsolete SMTP action worker still present")
    gateway_status=s.get("connector_gateways",{}).get("gmail",{})
    ledger=load("action_engine/GMAIL_GATEWAY_LEDGER.json")
    validate_gmail_gateway_status(gmail,gateway_status,ledger)
    boundaries=set(p["permanent_authority_boundaries"])
    for b in [
      "PAYMENT_CASH_MOVEMENT_REQUIRES_HUMAN_APPROVAL",
      "LIVE_MARKET_TRADING_AND_BROKERAGE_EXECUTION_PROHIBITED",
      "DEPLOYMENT_AND_MERGE_NOT_GRANTED_TO_AUTONOMOUS_SCHEDULER",
      "CHILD_FACING_CONSEQUENTIAL_CHANGES_REQUIRE_APPROVAL"
    ]:req(b in boundaries,f"authority boundary missing: {b}")

    fallback=validate_reasoning_fallback()
    return {
      "approved_recurring_workflows":len(expected),
      "workflow_liveness_recovery_targets":len(liveness["targets"]),
      "workflow_liveness_max_dispatches":liveness["max_dispatches_per_cycle"],
      "truthful_blocked_workflows":len(workload_workflows)+2,
      "workload_controlled_services":len(workload["services"]),
      "durable_state_artifacts":len(p["durable_state_artifacts"]),
      "gmail_gateway_account_ref":gmail["account_ref"],
      "gmail_gateway_status":gateway_status["status"],
      "enabled_nonzero_models":len(enabled_nonzero),
      "step23_unresolved":step23["unresolved_findings"],
      "step24_authority_violations":step24["authority_violations"],
      "step24_paid_cost_usd":step24["paid_cost_usd"],
      "interactive_chatgpt_runtime_dependency":False,
      "reasoning_fallback_provider":fallback["provider"],
      "reasoning_fallback_authority_granted":fallback["authority_granted"],
      "reasoning_fallback_evidence_upgraded":fallback["evidence_upgraded"],
      "release_status":s["status"],
      "promoted_main_sha":s["promoted_main_sha"]
    }

if __name__=="__main__":
    print("portfolio-brain Step 25 operating mode: PASS",json.dumps(validate_operating_mode(),sort_keys=True))
