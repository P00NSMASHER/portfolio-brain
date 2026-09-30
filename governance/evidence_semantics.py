#!/usr/bin/env python3
from __future__ import annotations
from typing import Any
SEMANTICS={
 "HEARTBEAT":{"semantic_class":"LIVENESS_CONNECTIVITY_ONLY","technical_verification":False,"market_verification":False,"revenue_verification":False,"verification_credit":[]},
 "NOTIFICATION":{"semantic_class":"ALERT_ONLY","technical_verification":False,"market_verification":False,"revenue_verification":False,"verification_credit":[]},
 "PAGES_PUBLICATION":{"semantic_class":"SANITIZED_PUBLICATION_ONLY","technical_verification":False,"market_verification":False,"revenue_verification":False,"verification_credit":[]},
}
def semantics(kind:str)->dict[str,Any]:
    if kind not in SEMANTICS:raise ValueError(f"unknown evidence semantic kind: {kind}")
    return dict(SEMANTICS[kind])
def source_projection(name:str,row:dict[str,Any])->dict[str,Any]:
    return {"source":name,"status":row.get("status","UNKNOWN"),"freshness_age_minutes":row.get("age_minutes"),"stale_after_minutes":row.get("stale_after_minutes"),"state_sequence":row.get("state_sequence"),"state_hash":row.get("state_hash"),"source_head_sha":row.get("source_head_sha"),"source_run_id":row.get("source_run_id"),"source_ref":row.get("source_ref"),"blocked_reason":row.get("blocked_reason") or row.get("error_class")}
