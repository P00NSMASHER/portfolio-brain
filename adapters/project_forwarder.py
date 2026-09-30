#!/usr/bin/env python3
from __future__ import annotations
import copy,hashlib,json
from pathlib import Path
from typing import Any,Callable
from governance.authority import require_project_capability
ROOT=Path(__file__).resolve().parents[1];MAX_FORWARD_IDS=2048
class ProjectForwardingError(ValueError):pass
def req(ok:bool,msg:str)->None:
    if not ok:raise ProjectForwardingError(msg)
def _load(path:str)->dict[str,Any]:return json.loads((ROOT/path).read_text())
def load_seed_state()->dict[str,Any]:return {"schema_version":"1.0.0","state_id":"project-observation-forwarding-v1","sequence":0,"applied_forward_ids":[]}
def validate_state(s):
    req(set(s)=={"schema_version","state_id","sequence","applied_forward_ids"},"forwarding state fields changed")
    req(s["schema_version"]=="1.0.0" and s["state_id"]=="project-observation-forwarding-v1","forwarding state identity mismatch")
    req(type(s["sequence"]) is int and s["sequence"]>=0,"forwarding sequence invalid")
    req(isinstance(s["applied_forward_ids"],list) and len(s["applied_forward_ids"])==len(set(s["applied_forward_ids"])) and len(s["applied_forward_ids"])<=MAX_FORWARD_IDS,"forwarding id ledger invalid")
def _adapter(r):
    m=[x for x in _load("adapters/ADAPTER_REGISTRY.json")["adapters"] if x["adapter_id"]==r.get("adapter_id")];req(len(m)==1,"observation adapter not registered");return m[0]
def _id(pid,r):
    raw=json.dumps({"project_id":pid,"adapter_id":r["adapter_id"],"repository_id":r["repository_id"],"source_ref":r["source_ref"],"current_sha":r["current_sha"],"receipt_hash":r["receipt_hash"]},sort_keys=True,separators=(",",":")).encode()
    return "PFWD-"+hashlib.sha256(raw).hexdigest()[:32].upper()
def forward_observation(project_id:str,receipt:dict[str,Any],state:dict[str,Any],sink:Callable[[dict[str,Any]],None]):
    validate_state(state);require_project_capability(project_id,"READ_OBSERVE");a=_adapter(receipt)
    req(project_id in a["project_ids"],"wrong-project routing rejected")
    req(receipt.get("repository_id")==a["repository_id"] and receipt.get("repository_full_name")==a["repository_full_name"],"repository route mismatch")
    req(receipt.get("status") in {"INITIALIZED","CHANGED","UNCHANGED"},"only successful observations may forward")
    req(isinstance(receipt.get("current_sha"),str) and len(receipt["current_sha"])==40,"exact SHA required")
    req(isinstance(receipt.get("receipt_hash"),str) and receipt["receipt_hash"].startswith("sha256:"),"receipt hash required")
    fid=_id(project_id,receipt)
    if fid in state["applied_forward_ids"]:return copy.deepcopy(state),{"status":"DUPLICATE_SUPPRESSED","forward_id":fid,"delivered":False}
    event={"schema_version":"1.0.0","event_kind":"PROJECT_REPOSITORY_OBSERVATION","project_id":project_id,"adapter_id":a["adapter_id"],"repository_id":a["repository_id"],"repository_full_name":a["repository_full_name"],"source_ref":receipt["source_ref"],"source_revision":receipt["current_sha"],"observation_receipt_hash":receipt["receipt_hash"],"authority_class":"OBSERVE","downstream_write_authority":False,"deployment_authority":False,"external_action_authority":False}
    sink(event);out=copy.deepcopy(state);out["applied_forward_ids"]=([*out["applied_forward_ids"],fid])[-MAX_FORWARD_IDS:];out["sequence"]+=1;validate_state(out)
    return out,{"status":"FORWARDED","forward_id":fid,"delivered":True,"event":event}
