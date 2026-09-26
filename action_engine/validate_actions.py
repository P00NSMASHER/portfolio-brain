#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path
from action_engine.action_executor import load_ledger,make_email_request,policy,preflight,record_gmail_send

ROOT=Path(__file__).resolve().parents[1]
class ActionValidationError(ValueError):pass
def req(ok,msg):
    if not ok:raise ActionValidationError(msg)

def validate_actions():
    p=policy()
    req(p["mode"]=="CHATGPT_GMAIL_CONNECTOR_GATEWAY" and p["execution_provider"]=="CHATGPT_GMAIL_CONNECTOR","Gmail gateway mode mismatch")
    req(p["gmail_account_ref"]=="PRIMARY_GMAIL_CONNECTOR","wrong Gmail connector alias")
    req(set(p["allowed_project_ids"])=={"PRJ-001","PRJ-002","PRJ-003","PRJ-004","PRJ-005","PRJ-006"},"bounded action project set changed")
    req(set(p["allowed_actions"])=={"CUSTOMER_EMAIL"},"unexpected action channel")
    req("credential_env" not in p["allowed_actions"]["CUSTOMER_EMAIL"],"SMTP credentials remain in Gmail gateway policy")
    request=make_email_request(project_id="PRJ-001",target="validator@example.com",subject="Validation",body="Synthetic Gmail gateway validation.",campaign_id="validator",evidence_refs=["validator:gmail"],requested_at="2026-09-26T12:00:00Z")
    ledger=load_ledger()
    d=preflight(ledger,request,at="2026-09-26T12:00:00Z",gmail_sent_today_count=0,gmail_target_sent_today_count=0)
    req(d["status"]=="APPROVED_GMAIL_CONNECTOR_ACTION" and d["can_execute"],"Gmail connector preflight failed")
    out,row=record_gmail_send(ledger,request,gmail_message_id="synthetic-message",gmail_thread_id="synthetic-thread",sent_at="2026-09-26T12:00:01Z")
    raw=json.dumps(out)
    for forbidden in ["validator@example.com","Synthetic Gmail gateway","synthetic-message","synthetic-thread"]:
        req(forbidden not in raw,"private Gmail data leaked into ledger")
    d2=preflight(out,request,at="2026-09-26T13:00:00Z")
    req(d2["status"]=="DUPLICATE_SUPPRESSED","sanitized-ledger duplicate suppression failed")
    education=make_email_request(project_id="PRJ-005",target="adult@example.com",subject="Adult validation",body="Would you review this product as an adult stakeholder?",campaign_id="education-validator",evidence_refs=["validator:education"],target_classification="VERIFIED_ADULT_STAKEHOLDER",requested_at="2026-09-26T12:00:00Z")
    de=preflight(ledger,education,at="2026-09-26T12:00:00Z")
    req(de["status"]=="APPROVED_GMAIL_CONNECTOR_ACTION" and "VERIFIED_ADULT_STAKEHOLDER_ONLY" in de["reason_codes"],"adult-only education preflight failed")
    try:
        make_email_request(project_id="PRJ-005",target="adult@example.com",subject="Missing audience",body="x",campaign_id="education-validator-missing",evidence_refs=["validator:education"],requested_at="2026-09-26T12:00:00Z")
        raise ActionValidationError("education request accepted without verified adult target")
    except Exception as exc:
        if isinstance(exc,ActionValidationError):raise
    return {"provider":"CHATGPT_GMAIL_CONNECTOR","gmail_account_ref":"PRIMARY_GMAIL_CONNECTOR","allowed_projects":6,"allowed_channels":1,"daily_email_limit":p["allowed_actions"]["CUSTOMER_EMAIL"]["max_per_utc_day"],"education_adult_only":True,"private_payload_persisted":False,"duplicate_suppression":True}

if __name__=="__main__":
    print("portfolio-brain Gmail action gateway: PASS",json.dumps(validate_actions(),sort_keys=True))
