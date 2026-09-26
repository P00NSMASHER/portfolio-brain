#!/usr/bin/env python3
"""Bounded, idempotent external action execution.

The current production transport is SMTP email. Durable state persists only
hashes and sanitized references, never raw recipients, subjects, or bodies.
"""
from __future__ import annotations
import copy,hashlib,json,os,re,smtplib
from datetime import datetime,timezone
from email.message import EmailMessage
from email.utils import format_datetime,make_msgid,parseaddr
from pathlib import Path
from typing import Any,Callable

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

def _now():return datetime.now(timezone.utc).isoformat().replace("+00:00","Z")

def _time(v,field):
    req(isinstance(v,str) and v,f"{field} required")
    try:dt=datetime.fromisoformat(v.replace("Z","+00:00"))
    except ValueError as exc:raise ActionEngineError(f"{field} invalid ISO-8601") from exc
    req(dt.tzinfo is not None,f"{field} requires timezone")
    return dt.astimezone(timezone.utc)

def _day(v):return _time(v,"timestamp").date().isoformat()

def _target_hash(target):
    return "sha256:"+hashlib.sha256(target.strip().casefold().encode()).hexdigest()

def _payload_hash(subject,body,campaign_id):
    return "sha256:"+hashlib.sha256((subject+"\0"+body+"\0"+campaign_id).encode()).hexdigest()

def _safe_ref(x):
    return isinstance(x,str) and 1<=len(x)<=240 and "\n" not in x and "\r" not in x and "@" not in x

def make_email_request(*,project_id,target,subject,body,campaign_id,evidence_refs,consequence="LOW",requested_at=None):
    requested_at=requested_at or _now()
    target=target.strip()
    th=_target_hash(target);ph=_payload_hash(subject,body,campaign_id)
    idem="action:"+hashlib.sha256((project_id+"\0CUSTOMER_EMAIL\0"+th+"\0"+ph).encode()).hexdigest()
    action_id="PACT-"+hashlib.sha256(idem.encode()).hexdigest()[:20].upper()
    req_obj={
      "schema_version":"1.0.0","action_id":action_id,"idempotency_key":idem,
      "project_id":project_id,"action_type":"CUSTOMER_EMAIL","consequence":consequence,
      "target":target,"subject":subject,"body":body,"campaign_id":campaign_id,
      "evidence_refs":list(evidence_refs),"requested_at":requested_at
    }
    validate_request(req_obj)
    return req_obj

def validate_request(r):
    required={"schema_version","action_id","idempotency_key","project_id","action_type","consequence","target","subject","body","campaign_id","evidence_refs","requested_at"}
    req(isinstance(r,dict) and set(r)==required,"action request fields changed")
    req(r["schema_version"]=="1.0.0","action request schema mismatch")
    req(isinstance(r["action_id"],str) and r["action_id"].startswith("PACT-"),"invalid action_id")
    req(isinstance(r["idempotency_key"],str) and r["idempotency_key"].startswith("action:"),"invalid idempotency key")
    req(r["project_id"] in policy()["allowed_project_ids"],"project not allowed for bounded actions")
    req(r["action_type"] in policy()["allowed_actions"],"action type not allowlisted")
    cfg=policy()["allowed_actions"][r["action_type"]]
    req(r["consequence"] in cfg["allowed_consequences"],"action consequence exceeds bounded channel policy")
    req(isinstance(r["target"],str) and EMAIL_RE.fullmatch(r["target"].strip()) is not None,"invalid email target")
    req(isinstance(r["subject"],str) and 1<=len(r["subject"])<=cfg["max_subject_chars"] and "\n" not in r["subject"] and "\r" not in r["subject"],"invalid email subject")
    req(isinstance(r["body"],str) and 1<=len(r["body"])<=cfg["max_body_chars"],"invalid email body")
    req(isinstance(r["campaign_id"],str) and 1<=len(r["campaign_id"])<=120 and _safe_ref("campaign:"+r["campaign_id"]),"invalid campaign_id")
    req(isinstance(r["evidence_refs"],list) and r["evidence_refs"] and all(_safe_ref(x) for x in r["evidence_refs"]),"sanitized evidence refs required")
    _time(r["requested_at"],"requested_at")
    th=_target_hash(r["target"]);ph=_payload_hash(r["subject"],r["body"],r["campaign_id"])
    expected="action:"+hashlib.sha256((r["project_id"]+"\0"+r["action_type"]+"\0"+th+"\0"+ph).encode()).hexdigest()
    req(r["idempotency_key"]==expected,"idempotency key does not bind target/payload")
    req(r["action_id"]=="PACT-"+hashlib.sha256(expected.encode()).hexdigest()[:20].upper(),"action_id mismatch")

def validate_state(s):
    required={"schema_version","state_id","sequence","updated_at","executions","recent_decisions"}
    req(isinstance(s,dict) and set(s)==required,"action state fields changed")
    req(s["schema_version"]=="1.0.0" and s["state_id"]=="portfolio-action-engine-state","action state identity mismatch")
    req(type(s["sequence"]) is int and s["sequence"]>=0,"invalid action state sequence")
    if s["updated_at"] is not None:_time(s["updated_at"],"updated_at")
    req(isinstance(s["executions"],list),"executions must be list")
    req(isinstance(s["recent_decisions"],list) and len(s["recent_decisions"])<=100,"recent decisions invalid")
    seen=set()
    for row in s["executions"]:
        fields={"action_id","idempotency_key","attempt","project_id","action_type","target_hash","payload_hash","status","created_at","completed_at","remote_ref","evidence_refs"}
        req(isinstance(row,dict) and set(row)==fields,"execution fields changed")
        key=(row["idempotency_key"],row["attempt"])
        req(key not in seen,"duplicate action attempt")
        seen.add(key)
        req(type(row["attempt"]) is int and row["attempt"]>=1,"invalid action attempt")
        req(row["status"] in {"SENT","FAILED"},"invalid execution status")
        req(str(row["target_hash"]).startswith("sha256:") and str(row["payload_hash"]).startswith("sha256:"),"execution hashes missing")
        req(all(_safe_ref(x) for x in row["evidence_refs"]),"execution evidence refs not sanitized")
        _time(row["created_at"],"created_at");_time(row["completed_at"],"completed_at")

def load_state(path=None):
    if path is not None and Path(path).exists():
        s=json.loads(Path(path).read_text())
    else:s=load("action_engine/ACTION_STATE_SEED.json")
    validate_state(s);return s

def killed():
    k=load("action_engine/KILL_SWITCH.json")
    if k.get("disabled") is True:return True,k.get("reason") or "file kill switch"
    if os.environ.get("PORTFOLIO_ACTIONS_DISABLED","").strip().lower()=="true":return True,"repository/environment kill switch"
    return False,None

def _decision(request,status,reasons,at,can_execute):
    core={
      "schema_version":"1.0.0",
      "decision_id":"PAD-"+hashlib.sha256((request["action_id"]+"\0"+at+"\0"+status).encode()).hexdigest()[:20].upper(),
      "action_id":request["action_id"],"idempotency_key":request["idempotency_key"],
      "project_id":request["project_id"],"action_type":request["action_type"],
      "status":status,"reason_codes":list(dict.fromkeys(reasons)),
      "can_execute":bool(can_execute),"decided_at":at
    }
    return {**core,"decision_hash":hashv(core)}

def _append_decision(state,d):
    state["recent_decisions"]=([*state["recent_decisions"],d])[-100:]

def preflight(state,request,*,at=None):
    validate_state(state);validate_request(request);at=at or request["requested_at"];_time(at,"at")
    out=copy.deepcopy(state)
    disabled,reason=killed()
    if disabled:
        d=_decision(request,"BLOCKED_KILL_SWITCH",["ACTION_KILL_SWITCH",reason or "disabled"],at,False);_append_decision(out,d);return out,d
    prior=[x for x in out["executions"] if x["idempotency_key"]==request["idempotency_key"]]
    if any(x["status"]=="SENT" for x in prior):
        d=_decision(request,"DUPLICATE_SUPPRESSED",["EXISTING_SUCCESSFUL_EXECUTION"],at,False);_append_decision(out,d);return out,d
    if len(prior)>=policy()["retry_limit"]:
        d=_decision(request,"BLOCKED_RETRY_LIMIT",["ACTION_RETRY_LIMIT"],at,False);_append_decision(out,d);return out,d
    p=policy();cfg=p["allowed_actions"][request["action_type"]];today=_day(at);th=_target_hash(request["target"])
    sent_today=[x for x in out["executions"] if x["status"]=="SENT" and _day(x["created_at"])==today and x["action_type"]==request["action_type"]]
    if len(sent_today)>=cfg["max_per_utc_day"]:
        d=_decision(request,"BLOCKED_RATE_LIMIT",["DAILY_ACTION_LIMIT"],at,False);_append_decision(out,d);return out,d
    same=[x for x in sent_today if x["target_hash"]==th]
    if len(same)>=cfg["max_per_recipient_per_utc_day"]:
        d=_decision(request,"BLOCKED_RATE_LIMIT",["RECIPIENT_DAILY_LIMIT"],at,False);_append_decision(out,d);return out,d
    if same:
        latest=max(_time(x["created_at"],"created_at") for x in same)
        if (_time(at,"at")-latest).total_seconds()<cfg["min_seconds_between_same_recipient"]:
            d=_decision(request,"BLOCKED_RATE_LIMIT",["RECIPIENT_COOLDOWN"],at,False);_append_decision(out,d);return out,d
    d=_decision(request,"APPROVED_BOUNDED_ACTION",["PROJECT_ACTION_ALLOWLIST","RATE_LIMITS_PASS","IDEMPOTENCY_CLEAR"],at,True)
    _append_decision(out,d);return out,d

def _smtp_credentials(cfg):
    names=cfg["credential_env"];vals={k:os.environ.get(v,"").strip() for k,v in names.items()}
    if not vals["port"]:vals["port"]="465"
    missing=[k for k in ("host","username","password","sender") if not vals[k]]
    if missing:raise ActionEngineError("missing SMTP credential environment: "+",".join(missing))
    try:vals["port"]=str(int(vals["port"]))
    except ValueError as exc:raise ActionEngineError("invalid SMTP port") from exc
    req(EMAIL_RE.fullmatch(vals["sender"]) is not None,"invalid SMTP sender")
    return vals

def _smtp_transport(request,creds):
    msg=EmailMessage()
    msg["From"]=creds["sender"];msg["To"]=request["target"];msg["Subject"]=request["subject"]
    msg["Date"]=format_datetime(datetime.now(timezone.utc))
    domain=creds["sender"].split("@",1)[1];msg["Message-ID"]=make_msgid(domain=domain)
    msg.set_content(request["body"])
    with smtplib.SMTP_SSL(creds["host"],int(creds["port"]),timeout=30) as smtp:
        smtp.login(creds["username"],creds["password"]);smtp.send_message(msg)
    return msg["Message-ID"]

def execute_email(state,request,*,at=None,transport:Callable[[dict[str,Any],dict[str,str]],str]|None=None):
    next_state,decision=preflight(state,request,at=at)
    if not decision["can_execute"]:return next_state,decision,None
    cfg=policy()["allowed_actions"]["CUSTOMER_EMAIL"]
    creds=_smtp_credentials(cfg)
    fn=transport or _smtp_transport
    started=at or request["requested_at"]
    try:
        remote_ref=fn(request,creds)
        status="SENT"
    except Exception as exc:
        remote_ref=None;status="FAILED";failure=type(exc).__name__
    completed=_now()
    attempt=1+sum(1 for x in next_state["executions"] if x["idempotency_key"]==request["idempotency_key"])
    row={
      "action_id":request["action_id"],"idempotency_key":request["idempotency_key"],"attempt":attempt,"project_id":request["project_id"],
      "action_type":request["action_type"],"target_hash":_target_hash(request["target"]),
      "payload_hash":_payload_hash(request["subject"],request["body"],request["campaign_id"]),
      "status":status,"created_at":started,"completed_at":completed,
      "remote_ref":None if remote_ref is None else "sha256:"+hashlib.sha256(str(remote_ref).encode()).hexdigest(),
      "evidence_refs":[*request["evidence_refs"],"campaign-hash:sha256:"+hashlib.sha256(request["campaign_id"].encode()).hexdigest()]
    }
    next_state=copy.deepcopy(next_state);next_state["executions"].append(row);next_state["sequence"]+=1;next_state["updated_at"]=completed
    if status=="FAILED":
        d=_decision(request,"TRANSPORT_FAILED",[failure],completed,False);_append_decision(next_state,d);validate_state(next_state);return next_state,d,row
    d=_decision(request,"EXECUTED",["SMTP_ACCEPTED"],completed,False);_append_decision(next_state,d);validate_state(next_state);return next_state,d,row

def sanitized_receipt(row):
    validate_state({"schema_version":"1.0.0","state_id":"portfolio-action-engine-state","sequence":0,"updated_at":row["completed_at"],"executions":[row],"recent_decisions":[]})
    return {
      "schema_version":"1.0.0","action_id":row["action_id"],"project_id":row["project_id"],"action_type":row["action_type"],
      "target_hash":row["target_hash"],"payload_hash":row["payload_hash"],"status":row["status"],
      "created_at":row["created_at"],"completed_at":row["completed_at"],"remote_ref":row["remote_ref"],
      "evidence_refs":row["evidence_refs"]
    }

def main():
    import argparse
    ap=argparse.ArgumentParser()
    ap.add_argument("--state",required=True);ap.add_argument("--request",required=True);ap.add_argument("--output-dir",required=True)
    a=ap.parse_args()
    state=load_state(a.state)
    request=json.loads(Path(a.request).read_text())
    next_state,decision,row=execute_email(state,request)
    out=Path(a.output_dir);out.mkdir(parents=True,exist_ok=True)
    (out/"action_state.json").write_text(json.dumps(next_state,indent=2)+"\n")
    (out/"action_decision.json").write_text(json.dumps(decision,indent=2)+"\n")
    if row is not None:
        (out/"action_receipt.json").write_text(json.dumps(sanitized_receipt(row),indent=2)+"\n")
    print(json.dumps({"action_id":request["action_id"],"status":decision["status"],"executed":row is not None and row["status"]=="SENT"}))
    if decision["status"] in {"BLOCKED_KILL_SWITCH","BLOCKED_RATE_LIMIT","BLOCKED_RETRY_LIMIT","TRANSPORT_FAILED"}:
        raise SystemExit(3)

if __name__=="__main__":main()
