#!/usr/bin/env python3
from __future__ import annotations
import json,os
from unittest.mock import patch
from pathlib import Path
from action_engine.action_executor import execute_email,load_state,make_email_request,policy,preflight

ROOT=Path(__file__).resolve().parents[1]
class ActionValidationError(ValueError):pass
def req(ok,msg):
    if not ok:raise ActionValidationError(msg)

def validate_actions():
    p=policy()
    req(p["mode"]=="BOUNDED_CHANNEL_EXECUTION" and p["enabled"] is True,"action engine disabled/mode mismatch")
    req(set(p["allowed_project_ids"])=={"PRJ-001","PRJ-002","PRJ-003","PRJ-004"},"commercial action project set changed")
    req(set(p["allowed_actions"])=={"CUSTOMER_EMAIL"},"unexpected action channel enabled")
    prohibited=set(p["prohibited_action_types"])
    for x in ["MOVE_MONEY","PAYMENT_OR_PURCHASE","LIVE_MARKET_TRADING","BROKERAGE_ORDER","PRIVATE_INFORMATION_DISCLOSURE","CONSEQUENTIAL_CHILD_FACING_CHANGE"]:
        req(x in prohibited,f"high-risk action protection missing: {x}")
    request=make_email_request(project_id="PRJ-001",target="validator@example.com",subject="Validation","body="Synthetic bounded action validation.",campaign_id="validator",evidence_refs=["validator:actions"],requested_at="2026-09-26T04:00:00Z")
    state,d=preflight(load_state(),request,at="2026-09-26T04:00:00Z")
    req(d["status"]=="APPROVED_BOUNDED_ACTION" and d["can_execute"],"bounded action preflight failed")
    env={
      "PORTFOLIO_EMAIL_SMTP_HOST":"smtp.example.com","PORTFOLIO_EMAIL_SMTP_PORT":"465",
      "PORTFOLIO_EMAIL_SMTP_USER":"operator@example.com","PORTFOLIO_EMAIL_SMTP_PASSWORD":"synthetic",
      "PORTFOLIO_EMAIL_FROM":"operator@example.com"
    }
    with patch.dict(os.environ,env,clear=True):
        state,d,row=execute_email(load_state(),request,at="2026-09-26T04:00:00Z",transport=lambda request,creds:"synthetic-remote-ref")
    req(d["status"]=="EXECUTED" and row["status"]=="SENT","synthetic action execution failed")
    raw=json.dumps(state)
    req("validator@example.com" not in raw and "Synthetic bounded action" not in raw,"private action payload leaked into durable state")
    state,d2,row2=execute_email(state,request,at="2026-09-26T05:00:00Z",transport=lambda *args:(_ for _ in ()).throw(RuntimeError("duplicate transport reached")))
    req(d2["status"]=="DUPLICATE_SUPPRESSED" and row2 is None,"exactly-once suppression failed")
    return {"allowed_projects":4,"allowed_channels":1,"daily_email_limit":p["allowed_actions"]["CUSTOMER_EMAIL"]["max_per_utc_day"],"durable_payload_leak":False,"duplicate_suppression":True}

if __name__=="__main__":
    print("portfolio-brain bounded action engine: PASS",json.dumps(validate_actions(),sort_keys=True))
