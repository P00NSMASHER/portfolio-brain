#!/usr/bin/env python3
"""Policy/idempotency contract for the ChatGPT Gmail action gateway.

This module never sends email. Private recipient/subject/body data exists only
transiently in the connected Gmail execution context. GitHub persists only
sanitized hashes and action metadata.
"""
from __future__ import annotations
import copy,hashlib,json,re
from datetime import datetime,timezone
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parents[1]
EMAIL_RE=re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")

class ActionEngineError(ValueError):pass

def req(ok,msg):
    if not ok:raise ActionEngineError(msg)

def load(path):
    p=Path(path)
    if not p.is_absolute():p=ROOT/p
    return json.loads(p.read_text())

def policy():return load("action_engine/ACTION_POLICY.json")
def canon(v):return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False)
def hashv(v):return "sha256:"+hashlib.sha256(canon(v).encode()).hexdigest()
def _sha(v):return "sha256:"+hashlib.sha256(str(v).encode()).hexdigest()
def _now():return datetime.now(timezone.utc).isoformat().replace("+00:00","Z")
def _time(v,field):
    req(isinstance(v,str) and v,f"{field} required")
    try:dt=datetime.fromisoformat(v.replace("Z","+00:00"))
    except ValueError as exc:raise ActionEngineError(f"{field} invalid ISO-8601") from exc
    req(dt.tzinfo is not None,f"{field} requires timezone")
    return dt.astimezone(timezone.utc)
def _day(v):return _time(v,"timestamp").date().isoformat()
def target_hash(target):return _sha(target.strip().casefold())
def payload_hash(subject,body,campaign_id):return _sha(subject+"\0"+body+"\0"+campaign_id)
def _safe_ref(x):return isinstance(x,str) and 1<=len(x)<=240 and "\n" not in x and "\r" not in x and "@" not in x

def make_email_request(*,project_id,target,subject,body,campaign_id,evidence_refs,consequence="LOW",target_classification=None,requested_at=None):
    requested_at=requested_at or _now();target=target.strip()
    project_constraint=policy().get("project_constraints",{}).get(project_id,{}).get("CUSTOMER_EMAIL",{})
    if target_classification is None and not project_constraint.get("required_target_classification"):
        target_classification="BUSINESS_CONTACT"
    th=target_hash(target);ph=payload_hash(subject,body,campaign_id)
    idem="action:"+hashlib.sha256((project_id+"\0CUSTOMER_EMAIL\0"+th+"\0"+ph).encode()).hexdigest()
    action_id="PACT-"+hashlib.sha256(idem.encode()).hexdigest()[:20].upper()
    out={
      "schema_version":"1.0.0","action_id":action_id,"idempotency_key":idem,
      "project_id":project_id,"action_type":"CUSTOMER_EMAIL","consequence":consequence,
      "target_classification":target_classification,
      "target":target,"subject":subject,"body":body,"campaign_id":campaign_id,
      "evidence_refs":list(evidence_refs),"requested_at":requested_at
    }
    validate_request(out);return out

def validate_request(r):
    required={"schema_version","action_id","idempotency_key","project_id","action_type","consequence","target_classification","target","subject","body","campaign_id","evidence_refs","requested_at"}
    req(isinstance(r,dict) and set(r)==required,"action request fields changed")
    req(r["schema_version"]=="1.0.0","action request schema mismatch")
    req(r["project_id"] in policy()["allowed_project_ids"],"project not allowed for bounded actions")
    req(r["action_type"] in policy()["allowed_actions"],"action type not allowlisted")
    cfg=policy()["allowed_actions"][r["action_type"]]
    req(r["consequence"] in cfg["allowed_consequences"],"action consequence exceeds bounded policy")
    project_constraint=policy().get("project_constraints",{}).get(r["project_id"],{}).get(r["action_type"],{})
    required_target_classification=project_constraint.get("required_target_classification")
    req(isinstance(r["target_classification"],str) and r["target_classification"],"target classification required")
    if required_target_classification:
        req(r["target_classification"]==required_target_classification,"education validation requires verified adult stakeholder target")
        req(project_constraint.get("direct_minor_contact_allowed") is False,"education project minor-contact boundary missing")
        req(project_constraint.get("child_data_collection_allowed") is False,"education project child-data boundary missing")
        req(project_constraint.get("consequential_child_facing_change_allowed") is False,"education project child-facing boundary missing")
    req(EMAIL_RE.fullmatch(r["target"].strip()) is not None,"invalid email target")
    req(isinstance(r["subject"],str) and 1<=len(r["subject"])<=cfg["max_subject_chars"] and "\n" not in r["subject"] and "\r" not in r["subject"],"invalid subject")
    req(isinstance(r["body"],str) and 1<=len(r["body"])<=cfg["max_body_chars"],"invalid body")
    req(isinstance(r["campaign_id"],str) and 1<=len(r["campaign_id"])<=120,"invalid campaign_id")
    req(isinstance(r["evidence_refs"],list) and r["evidence_refs"] and all(_safe_ref(x) for x in r["evidence_refs"]),"sanitized evidence refs required")
    _time(r["requested_at"],"requested_at")
    th=target_hash(r["target"]);ph=payload_hash(r["subject"],r["body"],r["campaign_id"])
    expected="action:"+hashlib.sha256((r["project_id"]+"\0"+r["action_type"]+"\0"+th+"\0"+ph).encode()).hexdigest()
    req(r["idempotency_key"]==expected,"idempotency key mismatch")
    req(r["action_id"]=="PACT-"+hashlib.sha256(expected.encode()).hexdigest()[:20].upper(),"action_id mismatch")

def validate_ledger(s):
    required={"schema_version","ledger_id","sequence","updated_at","executions"}
    req(isinstance(s,dict) and set(s)==required,"Gmail gateway ledger fields changed")
    req(s["schema_version"]=="1.0.0" and s["ledger_id"]=="portfolio-gmail-gateway-ledger","Gmail gateway ledger identity mismatch")
    req(type(s["sequence"]) is int and s["sequence"]>=0,"invalid ledger sequence")
    if s["updated_at"] is not None:_time(s["updated_at"],"updated_at")
    req(isinstance(s["executions"],list),"executions must be list")
    ids=set()
    for row in s["executions"]:
        fields={"action_id","idempotency_key","project_id","action_type","target_hash","payload_hash","campaign_hash","gmail_message_hash","gmail_thread_hash","status","sent_at","evidence_refs"}
        req(isinstance(row,dict) and set(row)==fields,"execution fields changed")
        req(row["action_id"] not in ids,"duplicate action_id");ids.add(row["action_id"])
        req(row["status"]=="SENT","only successful Gmail sends belong in durable ledger")
        for key in ("target_hash","payload_hash","campaign_hash","gmail_message_hash","gmail_thread_hash"):
            req(isinstance(row[key],str) and row[key].startswith("sha256:"),"execution hash missing")
        req(all(_safe_ref(x) for x in row["evidence_refs"]),"unsanitized evidence ref")
        _time(row["sent_at"],"sent_at")

def load_ledger(path=None):
    p=Path(path) if path else ROOT/"action_engine/GMAIL_GATEWAY_LEDGER.json"
    s=json.loads(p.read_text());validate_ledger(s);return s

def killed():
    k=load("action_engine/KILL_SWITCH.json")
    return (k.get("disabled") is True,k.get("reason") or "file kill switch")

def preflight(ledger,request,*,at=None,gmail_sent_today_count=0,gmail_target_sent_today_count=0):
    validate_ledger(ledger);validate_request(request);at=at or request["requested_at"];_time(at,"at")
    disabled,reason=killed()
    if disabled:return {"status":"BLOCKED_KILL_SWITCH","can_execute":False,"reason_codes":["ACTION_KILL_SWITCH",reason]}
    if any(x["idempotency_key"]==request["idempotency_key"] for x in ledger["executions"]):
        return {"status":"DUPLICATE_SUPPRESSED","can_execute":False,"reason_codes":["EXISTING_SANITIZED_LEDGER_EXECUTION"]}
    cfg=policy()["allowed_actions"][request["action_type"]]
    project_constraint=policy().get("project_constraints",{}).get(request["project_id"],{}).get(request["action_type"],{})
    today=_day(at);th=target_hash(request["target"])
    ledger_today=[x for x in ledger["executions"] if _day(x["sent_at"])==today]
    total=max(len(ledger_today),int(gmail_sent_today_count))
    if total>=cfg["max_per_utc_day"]:
        return {"status":"BLOCKED_RATE_LIMIT","can_execute":False,"reason_codes":["DAILY_ACTION_LIMIT"]}
    project_limit=project_constraint.get("max_per_project_per_utc_day")
    if project_limit is not None:
        project_total=sum(1 for x in ledger_today if x["project_id"]==request["project_id"])
        if project_total>=int(project_limit):
            return {"status":"BLOCKED_RATE_LIMIT","can_execute":False,"reason_codes":["PROJECT_DAILY_ACTION_LIMIT"]}
    target_total=max(sum(1 for x in ledger_today if x["target_hash"]==th),int(gmail_target_sent_today_count))
    if target_total>=cfg["max_per_recipient_per_utc_day"]:
        return {"status":"BLOCKED_RATE_LIMIT","can_execute":False,"reason_codes":["RECIPIENT_DAILY_LIMIT"]}
    reasons=["PROJECT_ALLOWLIST","GMAIL_DUPLICATE_CHECK_REQUIRED","RATE_LIMITS_PASS"]
    if project_constraint.get("required_target_classification"):
        reasons.append("VERIFIED_ADULT_STAKEHOLDER_ONLY")
    return {"status":"APPROVED_GMAIL_CONNECTOR_ACTION","can_execute":True,"reason_codes":reasons}

def record_gmail_send(ledger,request,*,gmail_message_id,gmail_thread_id,sent_at=None,evidence_refs=None):
    validate_ledger(ledger);validate_request(request)
    req(isinstance(gmail_message_id,str) and gmail_message_id,"gmail_message_id required")
    req(isinstance(gmail_thread_id,str) and gmail_thread_id,"gmail_thread_id required")
    sent_at=sent_at or _now();_time(sent_at,"sent_at")
    row={
      "action_id":request["action_id"],"idempotency_key":request["idempotency_key"],
      "project_id":request["project_id"],"action_type":request["action_type"],
      "target_hash":target_hash(request["target"]),"payload_hash":payload_hash(request["subject"],request["body"],request["campaign_id"]),
      "campaign_hash":_sha(request["campaign_id"]),"gmail_message_hash":_sha(gmail_message_id),"gmail_thread_hash":_sha(gmail_thread_id),
      "status":"SENT","sent_at":sent_at,
      "evidence_refs":list(dict.fromkeys([*request["evidence_refs"],*(evidence_refs or []),"gmail-connector:primary"]))
    }
    req(all(_safe_ref(x) for x in row["evidence_refs"]),"receipt evidence ref unsafe")
    out=copy.deepcopy(ledger);out["executions"].append(row);out["sequence"]+=1;out["updated_at"]=sent_at
    validate_ledger(out);return out,row

def sanitized_receipt(row):
    return {k:row[k] for k in row}

if __name__=="__main__":
    raise SystemExit("This module is a policy/receipt contract; Gmail execution occurs through the connected ChatGPT Gmail plugin.")
