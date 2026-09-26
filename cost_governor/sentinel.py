#!/usr/bin/env python3
"""Read-only cost/resource sentinel for Portfolio Brain."""
from __future__ import annotations
import json,re
from collections import Counter,defaultdict
from datetime import datetime,timezone
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parents[1]
USAGE_FIELDS=("cost_usd","input_tokens","output_tokens","model_calls","api_calls","github_job_starts","github_runner_minutes")

def _load(path:str)->dict[str,Any]:
    return json.loads((ROOT/path).read_text())

def _zero()->dict[str,float]:
    return {k:0 for k in USAGE_FIELDS}

def _add(dst:dict[str,float],src:dict[str,Any]|None)->None:
    if not src:return
    for k in USAGE_FIELDS:dst[k]+=float(src.get(k,0) or 0)

def _day(value:str|None)->str|None:
    return value[:10] if isinstance(value,str) and len(value)>=10 else None

def build_sentinel_snapshot(*,cost_policy=None,cost_state=None,provider_registry=None,model_ledger=None,
                            action_policy=None,action_ledger=None,provider_health=None,at:str|None=None)->dict[str,Any]:
    cost_policy=cost_policy or _load("cost_governor/COST_GOVERNOR_POLICY.json")
    cost_state=cost_state or _load("cost_governor/COST_STATE_SEED.json")
    provider_registry=provider_registry or _load("model_router/PROVIDER_REGISTRY.json")
    model_ledger=model_ledger or _load("model_router/MODEL_ROUTING_LEDGER.json")
    action_policy=action_policy or _load("action_engine/ACTION_POLICY.json")
    action_ledger=action_ledger or _load("action_engine/GMAIL_GATEWAY_LEDGER.json")
    provider_health=provider_health or _load("model_router/PROVIDER_HEALTH_SEED.json")
    now=at or datetime.now(timezone.utc).isoformat().replace("+00:00","Z")
    today=_day(now)

    committed=_zero();reserved=_zero();status_counts=Counter()
    model_usage=defaultdict(_zero);provider_failures=Counter()
    for row in cost_state.get("reservations",[]):
        status=row.get("status","UNKNOWN");status_counts[status]+=1
        usage=row.get("actual_usage") if status in {"COMMITTED","OVERAGE"} else (row.get("estimated_usage") if status=="RESERVED" else None)
        if status in {"COMMITTED","OVERAGE"}:_add(committed,usage)
        elif status=="RESERVED":_add(reserved,usage)
        if row.get("resource_kind")=="MODEL_CALL":
            key=f"{row.get('provider_id')}::{row.get('model_id')}"
            if status in {"COMMITTED","OVERAGE"}:_add(model_usage[key],row.get("actual_usage"))
            for ref in row.get("evidence_refs",[]):
                if isinstance(ref,str) and ref.startswith("provider-attempt:"):
                    provider_failures[ref.split(":")[-1]]+=1

    verified_outcomes=sum(1 for x in model_ledger.get("outcomes",[]) if str(x.get("status") or x.get("verification_status")).upper()=="VERIFIED")
    models=[]
    for provider in provider_registry.get("providers",[]):
        if not provider.get("enabled"):continue
        for model in provider.get("models",[]):
            if not model.get("enabled") or model.get("tier",0)<=0:continue
            key=f"{provider['provider_id']}::{model['model_id']}"
            usage=model_usage[key]
            calls=int(usage["model_calls"]);spend=round(float(usage["cost_usd"]),6)
            models.append({
              "provider_id":provider["provider_id"],"model_id":model["model_id"],"tier":model["tier"],
              "configured_input_usd_per_million":model["pricing"]["input_usd_per_million_tokens"],
              "configured_output_usd_per_million":model["pricing"]["output_usd_per_million_tokens"],
              "committed_spend_usd":spend,"successful_calls":calls,
              "spend_per_successful_call_usd":None if calls==0 else round(spend/calls,6),
              "verified_outcomes":0 if calls==0 else verified_outcomes,
              "spend_per_verified_outcome_usd":None if verified_outcomes==0 else round(spend/verified_outcomes,6),
              "value_signal":"NO_SUCCESSFUL_CALL_BASELINE" if calls==0 else ("NO_VERIFIED_OUTCOME_BASELINE" if verified_outcomes==0 else "MEASURABLE"),
            })

    executions=action_ledger.get("executions",[])
    ids=[x.get("idempotency_key") for x in executions if x.get("idempotency_key")]
    duplicates=len(ids)-len(set(ids))
    sent_today=sum(1 for x in executions if x.get("status")=="SENT" and _day(x.get("sent_at"))==today)
    email_limit=action_policy["allowed_actions"]["CUSTOMER_EMAIL"]["max_per_utc_day"]

    watchdog=(ROOT/".github/workflows/portfolio-cost-watchdog.yml").read_text()
    m=re.search(r'cron:\s*"([^"]+)"',watchdog);t=re.search(r'timeout-minutes:\s*(\d+)',watchdog)
    cron=m.group(1) if m else None;timeout=int(t.group(1)) if t else None
    nominal_runs=96 if cron=="*/15 * * * *" else None

    readiness=provider_health.get("readiness","UNPROBED")
    if readiness=="READY":next_paid="ONE_BOUNDED_TERRA_DAILY_ANALYSIS"
    elif readiness=="BUDGET_BLOCKED":next_paid="WAIT_FOR_GOVERNOR_CAPACITY"
    else:next_paid="RESTORE_PROVIDER_READINESS_BEFORE_PAID_WORK"

    return {
      "schema_version":"1.0.0","sentinel_id":"portfolio-cost-governor-sentinel-v1","accounting_day_utc":today,
      "budget":{"portfolio_ceiling":cost_policy["portfolio_ceiling"],"committed_usage":committed,"active_reserved_usage":reserved,"reservation_status_counts":dict(sorted(status_counts.items()))},
      "provider_health":provider_health,
      "provider_failure_evidence_counts":dict(sorted(provider_failures.items())),
      "model_efficiency":{"verified_outcomes_recorded":verified_outcomes,"models":models},
      "github":{"governed_job_usage":{"committed_starts":int(committed["github_job_starts"]),"committed_runner_minutes":int(committed["github_runner_minutes"]),"reserved_starts":int(reserved["github_job_starts"]),"reserved_runner_minutes":int(reserved["github_runner_minutes"])},
                "watchdog_control_plane_overhead":{"accounting_domain":"CONTROL_PLANE_OVERHEAD","included_in_model_spend":False,"governed_by_job_ceiling":False,"cron":cron,"timeout_minutes":timeout,"nominal_runs_per_day":nominal_runs,"nominal_max_runner_minutes_per_day":None if nominal_runs is None or timeout is None else nominal_runs*timeout}},
      "gmail_gateway":{"accounting_domain":"CHATGPT_GMAIL_CONNECTOR_GATEWAY","included_in_model_or_github_spend":False,"sent_today":sent_today,"daily_limit":email_limit,"daily_headroom":max(0,email_limit-sent_today),"duplicate_receipt_count":duplicates,"rate_issue":sent_today>=email_limit,"duplicate_issue":duplicates>0},
      "allocation":{"strategy":"DETERMINISTIC_FIRST_VALUE_WEIGHTED","cash_ceiling_unchanged":True,"next_paid_action":next_paid,
                    "rules":["Use deterministic work when sufficient.","Use Luna for low-cost intelligence.","Use Terra only for Tier-2 reasoning.","Use Sol only for Tier-3 adversarial/high-impact review.","Do not spend through an unready provider.","Prefer work with verified downstream value."]},
    }
