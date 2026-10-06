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
      "runtime-daily-learning":"43 9 * * *",
      "runtime-weekly-synthesis":"43 10 * * 1",
      "hunter-autonomous-cycle":"47 */6 * * *",
      "portfolio-autonomous-scheduler":"23 * * * *",
      "portfolio-cost-watchdog":"53 * * * *",
      "portfolio-notification-cycle":"7 */6 * * *",
      "command-center-pages":"37 * * * *",
      "agent-heartbeat-sweep":"29 */2 * * *",
      "portfolio-state-reducer":"11 4 * * *",
      "portfolio-state-checkpoint-candidate":"19 * * * *",
      "verified-feedback-bootstrap":"17 * * * *",
    }
    req(expected["runtime-daily-learning"].split()[0] != expected["command-center-pages"].split()[0],
        "daily learning must not collide with hourly command-center publication")
    req(expected["runtime-weekly-synthesis"].split()[0] != expected["runtime-hourly-sync"].split()[0],
        "weekly synthesis must not collide with hourly runtime sync")
    req(expected["portfolio-state-reducer"].split()[0] != expected["portfolio-state-checkpoint-candidate"].split()[0],
        "checkpoint candidate must not collide with daily reducer refresh")
    req(set(p["approved_recurring_workflows"])==set(expected),"approved recurring workflow set changed")
    # Step 23 is owner-armed for the 2x8 two-hour exact-main window at 07:30-09:30 UTC.
    # The strict collector still requires two genuine scheduled successes per
    # required workflow; manual/dispatch work never substitutes for schedule evidence.
    delivery=load("operations/SCHEDULE_DELIVERY_POLICY.json")
    req(delivery == {
        "schema_version":"1.0.0", "workflow":"portfolio-schedule-delivery",
        "cron":"7,17,27,37,47,57 * * * *", "purpose":"DELIVERY_PREFLIGHT_AND_DIAGNOSTICS",
        "max_api_requests":80, "timeout_seconds":15, "new_soak_start":None,
    }, "schedule delivery monitor policy changed")
    window=load("operations/STEP23_DELIVERY_WINDOW.json")
    required_temp={
      "portfolio-state-reducer","runtime-hourly-sync","portfolio-autonomous-scheduler",
      "hunter-autonomous-cycle","agent-heartbeat-sweep","portfolio-cost-watchdog",
      "portfolio-notification-cycle","command-center-pages",
    }
    req(window["schema_version"]=="1.0.0" and window["status"]=="CANARY_REQUIRED",
        "Step 23 canary identity changed")
    req(set(window["temporary_crons"])==required_temp,"Step 23 canary workflow set changed")
    req(window["qualification_horizon_start"]=="2026-10-06T12:15:00Z"
        and window["qualification_horizon_end"]=="2026-10-06T12:45:00Z",
        "Step 23 canary horizon changed")
    req(window["required_successes_per_workflow"]==1 and window["max_soak_duration_seconds"]==0,
        "Step 23 canary must prove delivery only")
    req(all(len(crons)==1 for crons in window["temporary_crons"].values())
        and window["observer_crons"]==[], "Step 23 canary cadence changed")
    workflow_dir=ROOT/".github/workflows"
    actual=scheduled_workflow_inventory(workflow_dir)
    req(set(actual)==set(expected)|{delivery["workflow"]},
        "scheduled workflow inventory differs from approved canary policy")
    for name,cron in expected.items():
        req(actual[name]==[cron,*window["temporary_crons"].get(name,[])],f"{name} cron mismatch")
    req(actual[delivery["workflow"]]==[delivery["cron"]],"delivery probe cron mismatch")
    control=load("operations/STEP23_CONTROL.json")
    req(control.get("status")=="CANARY_REQUIRED" and control.get("next_soak_start") is None
        and control.get("acceptance_complete") is False,
        "Step 23 must remain disarmed until scheduler canary passes")

