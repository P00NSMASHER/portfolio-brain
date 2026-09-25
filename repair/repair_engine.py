#!/usr/bin/env python3
"""Fail-closed continuous repair and self-improvement control plane."""
from __future__ import annotations
import copy,hashlib,json
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parents[1]
class RepairError(ValueError):pass
def req(ok,msg):
    if not ok:raise RepairError(msg)
def load(path):
    p=Path(path)
    if not p.is_absolute():p=ROOT/p
    return json.loads(p.read_text())
def canon(v):return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False)
def hashv(v):return "sha256:"+hashlib.sha256(canon(v).encode()).hexdigest()
def policy():return load("repair/REPAIR_POLICY.json")
def _time(v,field):
    req(isinstance(v,str) and v,f"{field} required")
    try:dt=datetime.fromisoformat(v.replace("Z","+00:00"))
    except ValueError as exc:raise RepairError(f"{field} invalid timestamp") from exc
    req(dt.tzinfo is not None,f"{field} requires timezone");return dt
def _protected(path):
    return any(path==x or path.startswith(x) for x in policy()["protected_target_prefixes"])

def validate_failure(f):
    required={"schema_version","failure_id","source_type","project_ids","target_repository_id","target_paths","failure_class","observation","reproduction_steps","evidence_refs","regression_test_requirement","evidence_state","sensitive_material_involved","benchmark_contaminated","reported_at"}
    req(isinstance(f,dict) and set(f)==required,"failure fields changed")
    req(f["schema_version"]=="1.0.0" and f["failure_id"].startswith("RFAIL-"),"failure identity invalid")
    req(f["source_type"] in {"LEARNING_ALERT","FAILURE_PACKET"},"invalid source type")
    req(f["project_ids"] and len(f["project_ids"])==len(set(f["project_ids"])),"project_ids required")
    req(f["target_repository_id"].startswith("REPO-"),"target repository invalid")
    req(f["target_paths"] and len(f["target_paths"])==len(set(f["target_paths"])),"target paths required")
    req(f["observation"] and f["evidence_refs"],"failure observation/evidence required")
    req(f["evidence_state"] in {"OBSERVED","VERIFIED","INFERRED","UNKNOWN","CONTRADICTED","STALE","INVALID"},"invalid evidence state")
    _time(f["reported_at"],"reported_at")
    if f["source_type"]=="FAILURE_PACKET" and f["evidence_state"]=="VERIFIED":
        req(f["reproduction_steps"],"verified failure needs reproduction steps")
        req(isinstance(f["regression_test_requirement"],str) and f["regression_test_requirement"],"verified failure needs regression test")

def _append(task,event_type,detail):
    t=copy.deepcopy(task);prev=t["history_head_hash"]
    event={"event_type":event_type,"detail":detail,"prev_hash":prev}
    event_hash=hashv(event);event["event_hash"]=event_hash
    t["history"].append(event);t["history_head_hash"]=event_hash
    body=dict(t);body.pop("task_hash",None);t["task_hash"]=hashv(body);return t

def failure_to_task(f):
    validate_failure(f)
    tid="RTASK-"+hashlib.sha256(f["failure_id"].encode()).hexdigest()[:20].upper()
    blocked_reason=None
    if f["sensitive_material_involved"]:blocked_reason="SENSITIVE_MATERIAL_BLOCKED"
    elif f["benchmark_contaminated"]:blocked_reason="BENCHMARK_CONTAMINATION_BLOCKED"
    elif f["target_repository_id"]!=policy()["repair_repository_id"]:blocked_reason="REPOSITORY_NOT_REPAIR_ENABLED"
    elif any(_protected(p) for p in f["target_paths"]):blocked_reason="PROTECTED_TARGET_BLOCKED"
    if blocked_reason:state="BLOCKED"
    elif f["source_type"]=="LEARNING_ALERT" or f["evidence_state"]!="VERIFIED":state="NEEDS_REPRODUCTION"
    else:state="READY_FOR_REPAIR"
    genesis="sha256:"+"0"*64
    task={
      "schema_version":"1.0.0","repair_task_id":tid,"failure_id":f["failure_id"],"project_ids":f["project_ids"],
      "target_repository_id":f["target_repository_id"],"target_paths":f["target_paths"],"state":state,
      "regression_test_requirement":f["regression_test_requirement"],"factory_work_id":None,"candidate":None,"heldout":None,"audit":None,"canary":None,"promotion":None,
      "evidence_refs":f["evidence_refs"],"history":[],"history_head_hash":genesis,"task_hash":""
    }
    return _append(task,"FAILURE_ASSESSED",{"state":state,"blocked_reason":blocked_reason,"source_type":f["source_type"],"evidence_state":f["evidence_state"]})

def learning_alert_failures(learning_state,reported_at="1970-01-01T00:00:00Z"):
    rows=[]
    for alert in learning_state.get("learning_alerts") or []:
        key=str(alert.get("memory_key") or "unknown")
        aid=hashlib.sha256((str(alert.get("type"))+"\0"+key).encode()).hexdigest()[:20].upper()
        rows.append({
          "schema_version":"1.0.0","failure_id":"RFAIL-ALERT-"+aid,"source_type":"LEARNING_ALERT","project_ids":["PRJ-000"],
          "target_repository_id":"REPO-008","target_paths":["learning/"],"failure_class":"OVERFIT" if alert.get("type")=="overfit_signal" else "REGRESSION",
          "observation":f"Learning alert {alert.get('type')} for {key} requires reproduction before any repair.",
          "reproduction_steps":[],"evidence_refs":[f"learning-alert:{key}"],"regression_test_requirement":None,
          "evidence_state":"OBSERVED","sensitive_material_involved":False,"benchmark_contaminated":False,"reported_at":reported_at
        })
    return rows

def compile_factory_work(task,base_sha):
    req(task["state"]=="READY_FOR_REPAIR","only READY_FOR_REPAIR may compile factory work")
    req(task["regression_test_requirement"],"repair task missing regression requirement")
    req(len(base_sha)==40 and all(c in "0123456789abcdef" for c in base_sha),"base_sha invalid")
    wid="SFW-REPAIR-"+hashlib.sha256((task["repair_task_id"]+"\0"+base_sha).encode()).hexdigest()[:16].upper()
    updated=copy.deepcopy(task);updated["state"]="FACTORY_PENDING";updated["factory_work_id"]=wid
    updated=_append(updated,"FACTORY_WORK_COMPILED",{"factory_work_id":wid,"base_sha":base_sha,"builder_agent_id":policy()["builder_agent_id"],"verifier_agent_id":"AGT-TESTER","required_regression_test":task["regression_test_requirement"]})
    packet={"factory_work_id":wid,"project_id":task["project_ids"][0],"repository_id":task["target_repository_id"],"base_sha":base_sha,
            "title":f"Repair {task['failure_id']}","issue_ref":f"repair:{task['repair_task_id']}","verifier_agent_id":"AGT-TESTER",
            "target_paths":task["target_paths"],"required_regression_test":task["regression_test_requirement"],"provenance_refs":[*task["evidence_refs"],f"repair-task:{task['repair_task_id']}"]}
    return updated,packet

def record_factory_candidate(task,factory_record):
    req(task["state"]=="FACTORY_PENDING","task not waiting for factory candidate")
    req(factory_record["work_id"]==task["factory_work_id"],"factory work mismatch")
    req(factory_record["state"]=="PR_OPEN","factory candidate must be independently verified and PR_OPEN")
    req(factory_record["builder_agent_id"]==policy()["builder_agent_id"],"unexpected factory builder")
    req(factory_record["verification_id"],"factory verification missing")
    req(factory_record["commit_sha"] and factory_record["diff_hash"],"candidate identity incomplete")
    req(factory_record["test_receipt_hashes"],"candidate regression receipts missing")
    candidate={"factory_work_id":factory_record["work_id"],"commit_sha":factory_record["commit_sha"],"diff_hash":factory_record["diff_hash"],
               "verification_id":factory_record["verification_id"],"test_receipt_hashes":factory_record["test_receipt_hashes"],"builder_agent_id":factory_record["builder_agent_id"],"pr_number":factory_record["pr_number"],"pr_url":factory_record["pr_url"]}
    t=copy.deepcopy(task);t["candidate"]=candidate;t["state"]="HELD_OUT_PENDING"
    return _append(t,"FACTORY_CANDIDATE_ACCEPTED",candidate)

def validate_evaluation(e):
    required={"schema_version","evaluation_id","repair_task_id","stage","actor_agent_id","candidate_commit_sha","candidate_diff_hash","result","tests_total","tests_passed","regressions","authority_violations","evidence_refs","report_hash"}
    req(isinstance(e,dict) and set(e)==required,"evaluation fields changed")
    req(e["schema_version"]=="1.0.0" and e["evaluation_id"].startswith("REVAL-"),"evaluation identity invalid")
    req(e["stage"] in {"HELD_OUT","INDEPENDENT_AUDIT","CANARY"},"evaluation stage invalid")
    req(e["result"] in {"PASS","FAIL","UNKNOWN"},"evaluation result invalid")
    req(type(e["tests_total"]) is int and type(e["tests_passed"]) is int and 0<=e["tests_passed"]<=e["tests_total"],"evaluation test counts invalid")
    req(type(e["regressions"]) is int and e["regressions"]>=0 and type(e["authority_violations"]) is int and e["authority_violations"]>=0,"evaluation counters invalid")
    req(e["evidence_refs"] and e["report_hash"].startswith("sha256:") and len(e["report_hash"])==71,"evaluation evidence/report required")

def _eval_matches(task,e,stage):
    validate_evaluation(e);req(e["repair_task_id"]==task["repair_task_id"],"evaluation task mismatch");req(e["stage"]==stage,"wrong evaluation stage")
    req(task["candidate"] is not None,"candidate missing");req(e["candidate_commit_sha"]==task["candidate"]["commit_sha"] and e["candidate_diff_hash"]==task["candidate"]["diff_hash"],"evaluation candidate identity mismatch")
    req(e["actor_agent_id"]!=task["candidate"]["builder_agent_id"],"builder cannot evaluate own repair")

def apply_heldout(task,e):
    req(task["state"]=="HELD_OUT_PENDING","task not held-out pending");_eval_matches(task,e,"HELD_OUT")
    req(e["actor_agent_id"] in policy()["heldout_evaluator_agent_ids"],"held-out evaluator not allowed")
    passed=e["result"]=="PASS" and e["tests_total"]>0 and e["tests_passed"]==e["tests_total"] and e["regressions"]==0 and e["authority_violations"]==0
    t=copy.deepcopy(task);t["heldout"]=e;t["state"]="INDEPENDENT_AUDIT_PENDING" if passed else "BLOCKED"
    return _append(t,"HELD_OUT_EVALUATED",{"evaluation_id":e["evaluation_id"],"passed":passed,"result":e["result"]})

def apply_independent_audit(task,e):
    req(task["state"]=="INDEPENDENT_AUDIT_PENDING","task not audit pending");_eval_matches(task,e,"INDEPENDENT_AUDIT")
    req(e["actor_agent_id"] in policy()["independent_auditor_agent_ids"],"independent auditor not allowed")
    req(task["heldout"] and e["actor_agent_id"]!=task["heldout"]["actor_agent_id"],"auditor must differ from held-out evaluator")
    passed=e["result"]=="PASS" and e["regressions"]==0 and e["authority_violations"]==0
    t=copy.deepcopy(task);t["audit"]=e;t["state"]="CANARY_PENDING" if passed else "BLOCKED"
    return _append(t,"INDEPENDENT_AUDIT",{"evaluation_id":e["evaluation_id"],"passed":passed,"result":e["result"]})

def apply_canary(task,e):
    req(task["state"]=="CANARY_PENDING","task not canary pending");_eval_matches(task,e,"CANARY")
    req(e["actor_agent_id"] in policy()["canary_verifier_agent_ids"],"canary verifier not allowed")
    req(e["tests_total"]>0,"canary must execute at least one check")
    passed=e["result"]=="PASS" and e["tests_passed"]==e["tests_total"] and e["regressions"]==0 and e["authority_violations"]==0
    t=copy.deepcopy(task);t["canary"]=e
    if passed:
        t["state"]="PROMOTION_ELIGIBLE";t["promotion"]={"automatic_promotion":False,"required_approval":"INTEGRATOR_APPROVAL","approved":False,"promotion_action":None}
    else:t["state"]="BLOCKED"
    return _append(t,"CANARY_EVALUATED",{"evaluation_id":e["evaluation_id"],"passed":passed,"result":e["result"],"promotion_eligible":passed})

def validate_history(task):
    prev="sha256:"+"0"*64
    for e in task["history"]:
        body={k:v for k,v in e.items() if k!="event_hash"}
        req(e["prev_hash"]==prev and e["event_hash"]==hashv(body),"repair history hash mismatch");prev=e["event_hash"]
    req(task["history_head_hash"]==prev,"repair history head mismatch")
    body=dict(task);given=body.pop("task_hash");req(given==hashv(body),"repair task hash mismatch")
    return True

def build_repair_state(learning_state=None):
    ledger=load("repair/REPAIR_LEDGER.json");failures=list(ledger["failures"]);tasks=[failure_to_task(f) for f in failures]
    if learning_state is not None:
        tasks += [failure_to_task(f) for f in learning_alert_failures(learning_state)]
    return {"schema_version":"1.0.0","mode":policy()["mode"],"failure_count":len(failures),"task_count":len(tasks),
            "ready_for_repair":sum(1 for t in tasks if t["state"]=="READY_FOR_REPAIR"),"needs_reproduction":sum(1 for t in tasks if t["state"]=="NEEDS_REPRODUCTION"),
            "blocked":sum(1 for t in tasks if t["state"]=="BLOCKED"),"promotion_eligible":sum(1 for t in tasks if t["state"]=="PROMOTION_ELIGIBLE"),"tasks":tasks}
