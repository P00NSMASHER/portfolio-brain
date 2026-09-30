#!/usr/bin/env python3
from __future__ import annotations
import json
from action_engine.action_executor import load_ledger,make_email_request,policy,preflight,record_gmail_send
class ActionValidationError(ValueError):pass
def req(ok,msg):
    if not ok:raise ActionValidationError(msg)
def validate_actions():
    p=policy();req(p["mode"]=="HUMAN_APPROVAL_GATED_GMAIL_CONNECTOR" and p["execution_provider"]=="CHATGPT_GMAIL_CONNECTOR","Gmail mode mismatch");req(p["human_approval_required"] is True and p["autonomous_execution_allowed"] is False,"Gmail is not human gated")
    ledger=load_ledger()
    blocked=make_email_request(project_id="PRJ-001",target="validator@example.com",subject="Validation",body="Synthetic Gmail gateway validation.",campaign_id="validator",evidence_refs=["validator:gmail"],requested_at="2026-09-26T12:00:00Z")
    d0=preflight(ledger,blocked,at="2026-09-26T12:00:00Z");req(d0["status"]=="HUMAN_APPROVAL_REQUIRED" and not d0["can_execute"],"unapproved Gmail request did not fail closed")
    request=make_email_request(project_id="PRJ-001",target="validator@example.com",subject="Validation",body="Synthetic Gmail gateway validation.",campaign_id="validator",evidence_refs=["validator:gmail"],requested_at="2026-09-26T12:00:00Z",human_approval_ref="human-approval:validator")
    d=preflight(ledger,request,at="2026-09-26T12:00:00Z");req(d["can_execute"] and "EXPLICIT_HUMAN_APPROVAL" in d["reason_codes"],"approved Gmail preflight failed")
    out,_=record_gmail_send(ledger,request,gmail_message_id="synthetic-message",gmail_thread_id="synthetic-thread",sent_at="2026-09-26T12:00:01Z")
    raw=json.dumps(out)
    for forbidden in ["validator@example.com","Synthetic Gmail gateway","synthetic-message","synthetic-thread","human-approval:validator"]:req(forbidden not in raw,"transient/private Gmail data leaked")
    req(preflight(out,request,at="2026-09-26T13:00:00Z")["status"]=="DUPLICATE_SUPPRESSED","duplicate suppression failed")
    edu=make_email_request(project_id="PRJ-005",target="adult@example.com",subject="Adult validation",body="Review as an adult stakeholder.",campaign_id="education-validator",evidence_refs=["validator:education"],target_classification="VERIFIED_ADULT_STAKEHOLDER",requested_at="2026-09-26T12:00:00Z",human_approval_ref="human-approval:education")
    de=preflight(ledger,edu,at="2026-09-26T12:00:00Z");req(de["can_execute"] and "VERIFIED_ADULT_STAKEHOLDER_ONLY" in de["reason_codes"],"adult-only education preflight failed")
    return {"provider":"CHATGPT_GMAIL_CONNECTOR","human_approval_required":True,"autonomous_execution_allowed":False,"allowed_projects":len(p["allowed_project_ids"]),"private_payload_persisted":False,"duplicate_suppression":True}
if __name__=="__main__":print("portfolio-brain Gmail action gateway: PASS",json.dumps(validate_actions(),sort_keys=True))
