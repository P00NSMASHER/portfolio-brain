#!/usr/bin/env python3
"""Restore a sanitized provider-readiness signal from runtime artifacts."""
from __future__ import annotations
import json, os, zipfile
from io import BytesIO
from pathlib import Path
from typing import Any

from runtime.artifact_state import BudgetedHTTP
from runtime.artifact_restore import _atomic_write
from runtime.artifact_state import policy as runtime_policy

ROOT=Path(__file__).resolve().parents[1]
SEED=ROOT/"model_router"/"PROVIDER_HEALTH_SEED.json"

READINESS={
    "SUCCESS":"READY",
    "BLOCKED_MISSING_CREDENTIAL":"MISSING_CREDENTIAL",
    "BLOCKED_PROVIDER_BILLING":"BILLING_NOT_ACTIVE",
    "BLOCKED_PROVIDER_QUOTA":"QUOTA_EXHAUSTED",
    "DEFERRED_PROVIDER_RETRY":"RATE_LIMITED",
    "BLOCKED_COST_BUDGET":"BUDGET_BLOCKED",
    "BLOCKED_COST_RETRY_LIMIT":"BUDGET_BLOCKED",
    "SKIPPED_DUPLICATE_PACKET":"DUPLICATE_SUPPRESSED",
    "BLOCKED_PROVIDER_ERROR":"PROVIDER_ERROR",
}

def _normalize(payload:dict[str,Any], *, artifact_id:int, created_at:str|None)->dict[str,Any]:
    status=payload.get("status")
    if status=="SUCCESS" and "receipt" in payload:
        receipt=payload.get("receipt") or {};route=payload.get("route") or {}
        provider_id=route.get("provider_id") or receipt.get("provider_id")
        model_id=route.get("model_id") or receipt.get("model_id")
        updated=receipt.get("completed_at") or created_at
        credential="PRESENT_AT_SUCCESS"
        provider_code=provider_type=None;retryable=False;reason_codes=[]
    else:
        provider_id="openai";model_id=payload.get("model_id")
        updated=created_at
        credential="MISSING" if status=="BLOCKED_MISSING_CREDENTIAL" else (
            "PRESENT_AT_ATTEMPT" if payload.get("provider_attempt") is not None else "UNKNOWN"
        )
        provider_code=payload.get("provider_code");provider_type=payload.get("provider_type")
        retryable=bool(payload.get("retryable",False));reason_codes=list(payload.get("reason_codes") or [])
    readiness=READINESS.get(status,"UNKNOWN_PROVIDER_STATE")
    return {
      "schema_version":"1.0.0","state_id":"portfolio-provider-health-state",
      "sequence":int(artifact_id),"updated_at":updated,"readiness":readiness,
      "source_status":status or "UNKNOWN","credential_state":credential,
      "provider_id":provider_id,"model_id":model_id,
      "provider_code":provider_code,"provider_type":provider_type,"retryable":retryable,
      "budget_domain_blocked":readiness=="BUDGET_BLOCKED",
      "provider_domain_blocked":readiness in {"MISSING_CREDENTIAL","BILLING_NOT_ACTIVE","QUOTA_EXHAUSTED","RATE_LIMITED","PROVIDER_ERROR"},
      "reason_codes":reason_codes,
    }

def _payload_from_archive(raw:bytes)->dict[str,Any]|None:
    if len(raw)>runtime_policy()["budgets"]["max_output_bytes"]: return None
    with zipfile.ZipFile(BytesIO(raw)) as z:
        names=set(z.namelist())
        for name in ("daily_model_analysis.json","daily_model_analysis_status.json"):
            if name in names:
                try:return json.loads(z.read(name).decode("utf-8"))
                except Exception:return None
    return None

def restore(*, output:Path, metadata_output:Path|None=None)->str:
    token=os.environ.get("GITHUB_TOKEN") or os.environ.get("PORTFOLIO_GITHUB_TOKEN")
    repository=os.environ.get("GITHUB_REPOSITORY")
    current_run=os.environ.get("GITHUB_RUN_ID")
    branch=os.environ.get("GITHUB_REF_NAME")
    if not token or not repository:return "NO_ACTIONS_CONTEXT"
    p=runtime_policy();b=p["budgets"]
    http=BudgetedHTTP(token,max_requests=min(8,b["max_api_requests_per_cycle"]),retries=b["retry_limit"],backoff=b["retry_backoff_seconds"])
    data=http.json(f"https://api.github.com/repos/{repository}/actions/artifacts?name={p['state_persistence']['artifact_name']}&per_page=100")
    candidates=[x for x in data.get("artifacts",[]) if not x.get("expired") and str((x.get("workflow_run") or {}).get("id"))!=str(current_run) and (branch is None or (x.get("workflow_run") or {}).get("head_branch")==branch)]
    candidates.sort(key=lambda x:(x.get("created_at",""),x.get("id",0)),reverse=True)
    for item in candidates:
        try:payload=_payload_from_archive(http.bytes(item["archive_download_url"]))
        except Exception:continue
        if not isinstance(payload,dict):continue
        normalized=_normalize(payload,artifact_id=int(item.get("id") or 0),created_at=item.get("created_at"))
        _atomic_write(output,(json.dumps(normalized,indent=2,sort_keys=True)+"\n").encode())
        if metadata_output is not None:
            wr=item.get("workflow_run") or {}
            meta={"schema_version":"1.0.0","restore_status":"RESTORED","artifact_id":item.get("id"),"artifact_name":item.get("name"),"artifact_created_at":item.get("created_at"),"artifact_expires_at":item.get("expires_at"),"source_run_id":wr.get("id"),"source_head_sha":wr.get("head_sha")}
            _atomic_write(metadata_output,(json.dumps(meta,sort_keys=True)+"\n").encode())
        return "RESTORED"
    return "NO_PRIOR_ARTIFACT"
