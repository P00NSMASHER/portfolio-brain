#!/usr/bin/env python3
"""Governed OpenAI Responses API execution for Portfolio Brain."""
from __future__ import annotations
import hashlib,json,os,random,time,urllib.request
from urllib.error import HTTPError,URLError
from datetime import datetime,timezone
from typing import Any,Callable

from cost_governor.cost_governor import commit_reservation,zero_usage
from model_router.model_router import (
    ModelRouterError,hashv,prepare_governed_execution,provider_registry,validate_call_receipt
)

class OpenAIExecutorError(ValueError):
    def __init__(self,message,*,status_code=None,provider_code=None,provider_type=None,retryable=False,retry_after=None):
        super().__init__(message)
        self.status_code=status_code
        self.provider_code=provider_code
        self.provider_type=provider_type
        self.retryable=bool(retryable)
        self.retry_after=retry_after

def _now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00","Z")

def _provider_and_model(provider_id:str,model_id:str):
    for p in provider_registry()["providers"]:
        if p["provider_id"]!=provider_id:continue
        for m in p["models"]:
            if m["model_id"]==model_id:return p,m
    raise OpenAIExecutorError("provider/model not registered")

def _endpoint(provider:dict[str,Any])->str:
    env=provider.get("base_url_env_var")
    raw=(os.environ.get(env,"").strip() if env else "")
    if not raw:return "https://api.openai.com/v1/responses"
    if raw.rstrip("/").endswith("/responses"):return raw.rstrip("/")
    return raw.rstrip("/")+"/v1/responses"

def _extract_output_text(data:dict[str,Any])->str:
    if isinstance(data.get("output_text"),str):return data["output_text"]
    parts=[]
    for item in data.get("output",[]) or []:
        if not isinstance(item,dict):continue
        for part in item.get("content",[]) or []:
            if isinstance(part,dict) and part.get("type")=="output_text" and isinstance(part.get("text"),str):
                parts.append(part["text"])
    if not parts:raise OpenAIExecutorError("Responses API returned no output text")
    return "\n".join(parts)

NON_RETRYABLE_429_CODES={
    "credit_balance_exhausted","organization_spend_limit_exceeded",
    "project_spend_limit_exceeded","organization_usage_limit_exceeded","insufficient_quota"
}

def _parse_http_error(exc:HTTPError):
    raw=b""
    try: raw=exc.read()
    except Exception: pass
    data={}
    if raw:
        try: data=json.loads(raw.decode("utf-8","replace"))
        except Exception: data={}
    err=data.get("error") if isinstance(data,dict) else {}
    if not isinstance(err,dict):err={}
    code=err.get("code");typ=err.get("type")
    retry_after=None
    value=exc.headers.get("Retry-After") if exc.headers else None
    if value is not None:
        try:
            parsed=float(value)
            if parsed>=0:retry_after=parsed
        except (TypeError,ValueError):pass
    retryable=exc.code in {429,500,502,503,504} and code not in NON_RETRYABLE_429_CODES
    return code,typ,retry_after,retryable

def _default_transport(url:str,headers:dict[str,str],payload:bytes,timeout:int)->dict[str,Any]:
    req=urllib.request.Request(url,data=payload,headers=headers,method="POST")
    max_attempts=3
    for attempt in range(max_attempts):
        try:
            with urllib.request.urlopen(req,timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except HTTPError as exc:
            code,typ,retry_after,retryable=_parse_http_error(exc)
            if not retryable:
                raise OpenAIExecutorError(
                    f"provider_http_{exc.code}:{code or typ or 'unknown'}",
                    status_code=exc.code,provider_code=code,provider_type=typ,retryable=False,retry_after=retry_after
                ) from exc
            if attempt>=max_attempts-1:
                raise OpenAIExecutorError(
                    f"provider_retry_exhausted_http_{exc.code}:{code or typ or 'unknown'}",
                    status_code=exc.code,provider_code=code,provider_type=typ,retryable=True,retry_after=retry_after
                ) from exc
            if retry_after is not None:
                if retry_after>30:
                    raise OpenAIExecutorError(
                        f"provider_retry_deferred_http_{exc.code}:{code or typ or 'unknown'}",
                        status_code=exc.code,provider_code=code,provider_type=typ,retryable=True,retry_after=retry_after
                    ) from exc
                delay=retry_after+random.uniform(0.0,0.5)
            else:
                delay=(2**attempt)+random.uniform(0.0,0.5)
            time.sleep(delay)
        except URLError as exc:
            if attempt>=max_attempts-1:
                raise OpenAIExecutorError("provider_network_retry_exhausted",retryable=True) from exc
            time.sleep((2**attempt)+random.uniform(0.0,0.5))
    raise OpenAIExecutorError("provider_transport_unreachable",retryable=True)

def _actual_cost(model:dict[str,Any],input_tokens:int,output_tokens:int)->float:
    p=model["pricing"]
    if p["basis"]!="CONFIGURED_RATE":raise OpenAIExecutorError("model pricing is not configured")
    return float(p["fixed_call_usd"])+(input_tokens*float(p["input_usd_per_million_tokens"])+output_tokens*float(p["output_usd_per_million_tokens"]))/1_000_000

def execute_openai(
    model_request:dict[str,Any],
    input_text:str,
    cost_state:dict[str,Any],
    *,
    attempt:int=1,
    reasoning_effort:str="medium",
    timeout:int=90,
    at:str|None=None,
    transport:Callable[[str,dict[str,str],bytes,int],dict[str,Any]]|None=None,
):
    if not isinstance(input_text,str) or not input_text:raise OpenAIExecutorError("input_text required")
    next_state,guard=prepare_governed_execution(model_request,cost_state,attempt=attempt,at=at)
    route=guard["route"]
    if route["status"]!="ROUTED" or route["tier"]==0:raise OpenAIExecutorError("non-Tier-0 routed model required")
    if route["provider_id"]!="openai":raise OpenAIExecutorError("route is not OpenAI")
    provider,model=_provider_and_model(route["provider_id"],route["model_id"])
    credential_env=provider.get("credential_env_var")
    key=(os.environ.get(credential_env,"").strip() if credential_env else "")
    if not key:raise OpenAIExecutorError(f"missing credential environment variable: {credential_env}")
    if not guard["cost_gate_passed"]:raise OpenAIExecutorError("cost governor blocked model execution")

    started=at or _now()
    payload=json.dumps({
        "model":route["model_id"],
        "input":input_text,
        "max_output_tokens":model_request["max_output_tokens"],
        "reasoning":{"effort":reasoning_effort},
    },separators=(",",":")).encode()
    headers={"Authorization":"Bearer "+key,"Content-Type":"application/json"}
    call=transport or _default_transport
    t0=time.monotonic()
    data=call(_endpoint(provider),headers,payload,timeout)
    latency_ms=max(0,int((time.monotonic()-t0)*1000))
    completed=_now()
    text=_extract_output_text(data)
    usage=data.get("usage") or {}
    input_tokens=int(usage.get("input_tokens",0))
    output_tokens=int(usage.get("output_tokens",0))
    if input_tokens<0 or output_tokens<0:raise OpenAIExecutorError("invalid API usage")
    cost=_actual_cost(model,input_tokens,output_tokens)

    actual=zero_usage()
    actual.update({"cost_usd":cost,"input_tokens":input_tokens,"output_tokens":output_tokens,"model_calls":1,"api_calls":1})
    reservation_id=guard["cost_decision"]["reservation_id"]
    next_state,commit=commit_reservation(next_state,reservation_id,actual,at=completed,evidence_ref=f"openai-response:{data.get('id','unknown')}")
    if commit["status"]!="COMMITTED":raise OpenAIExecutorError("model usage exceeded reserved maximum")

    input_hash="sha256:"+hashlib.sha256(input_text.encode()).hexdigest()
    output_hash="sha256:"+hashlib.sha256(text.encode()).hexdigest()
    core={
      "schema_version":"1.0.0",
      "invocation_id":"MINV-"+hashlib.sha256((route["route_id"]+"\0"+input_hash+"\0"+output_hash).encode()).hexdigest()[:20].upper(),
      "request_id":model_request["request_id"],"route_id":route["route_id"],"tier":route["tier"],
      "provider_id":route["provider_id"],"model_id":route["model_id"],"independence_group":route["independence_group"],
      "status":"SUCCESS","started_at":started,"completed_at":completed,
      "input_tokens":input_tokens,"output_tokens":output_tokens,"cost_usd":cost,
      "cost_basis":"CONFIGURED_RATE_CONSERVATIVE_INPUT","latency_ms":latency_ms,
      "input_hash":input_hash,"output_hash":output_hash,
      "authority_granted":False,"evidence_upgraded":False,"downstream_outcome_ids":[]
    }
    receipt={**core,"receipt_hash":hashv(core)}
    validate_call_receipt(receipt,route,model_request)
    return next_state,{"route":route,"receipt":receipt,"output_text":text,"response_id":data.get("id")}

if __name__=="__main__":
    raise SystemExit("Import execute_openai from a governed runtime; prompts are not accepted on the CLI.")
