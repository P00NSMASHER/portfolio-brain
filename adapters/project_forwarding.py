#!/usr/bin/env python3
"""Idempotent project-scoped forwarding of sanitized runtime observations.

Forwarding is a logical read-only delivery inside Portfolio Brain. It does not
write downstream repositories, deploy, create external actions, or mint
authority. Project routing comes only from the adapter registry and every
capability is looked up explicitly in governance/boundaries.json.
"""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parents[1]
CAPABILITIES={"READ_OBSERVE","CANDIDATE_PR","DEPLOY","EXTERNAL_ACTION"}

class ProjectForwardingError(ValueError):
    pass

def req(ok: bool, message: str)->None:
    if not ok:
        raise ProjectForwardingError(message)

def load(path: str)->dict:
    return json.loads((ROOT/path).read_text(encoding="utf-8"))

def canon(value: Any)->bytes:
    return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode("utf-8")

def digest(value: Any)->str:
    return "sha256:"+hashlib.sha256(canon(value)).hexdigest()

def _is_sha(value: Any)->bool:
    return isinstance(value,str) and len(value)==40 and all(c in "0123456789abcdef" for c in value)

def capability_row(project_id: str, policy: dict|None=None)->dict:
    policy=policy or load("governance/boundaries.json")
    rows=[row for row in policy["project_capabilities"] if row["project_id"]==project_id]
    req(len(rows)==1,f"project capability row missing/duplicate: {project_id}")
    return rows[0]

def require_capability(project_id: str, capability: str, policy: dict|None=None)->None:
    req(capability in CAPABILITIES,f"unknown capability: {capability}")
    row=capability_row(project_id,policy)
    req(row["capabilities"].get(capability) is True,f"{project_id} lacks explicit {capability} capability")

def _validate_cycle(cycle: dict)->None:
    req(isinstance(cycle,dict),"runtime cycle must be object")
    req(cycle.get("status")=="PASS","only PASS runtime observations may be forwarded")
    req(isinstance(cycle.get("cycle_id"),str) and cycle["cycle_id"],"runtime cycle identity missing")
    given=cycle.get("receipt_hash")
    body={k:v for k,v in cycle.items() if k!="receipt_hash"}
    req(isinstance(given,str) and given==digest(body),"runtime cycle receipt hash mismatch")
    req(isinstance(cycle.get("observations"),list),"runtime observations missing")

def _validate_observation(observation: dict, adapter: dict)->None:
    req(observation.get("adapter_id")==adapter["adapter_id"],"observation adapter identity mismatch")
    req(observation.get("repository_id")==adapter["repository_id"],"observation repository identity mismatch")
    req(observation.get("repository_full_name")==adapter["repository_full_name"],"observation repository name mismatch")
    req(adapter.get("authority_class")=="OBSERVE","source adapter is not OBSERVE-only")
    req(observation.get("status") in {"UNCHANGED","INITIALIZED","CHANGED","BLOCKED"},"observation status invalid")
    given=observation.get("receipt_hash")
    body={k:v for k,v in observation.items() if k!="receipt_hash"}
    req(isinstance(given,str) and given==digest(body),"observation receipt hash mismatch")
    current=observation.get("current_sha")
    if observation["status"]=="BLOCKED":
        req(current is None,"blocked observation cannot claim current revision")
    else:
        req(_is_sha(current),"forwarded observation requires exact current revision")

def forward_cycle(cycle: dict, *, requested_project_id: str|None=None, requested_capability: str="READ_OBSERVE")->dict:
    _validate_cycle(cycle)
    registry=load("adapters/ADAPTER_REGISTRY.json")
    boundaries=load("governance/boundaries.json")
    adapters={row["adapter_id"]:row for row in registry["adapters"]}
    seen_source: dict[tuple[str,str],dict]= {}
    deliveries: dict[str,dict]= {}
    duplicate_observations=0

    for observation in cycle["observations"]:
        adapter=adapters.get(observation.get("adapter_id"))
        req(adapter is not None,"observation references unknown adapter")
        _validate_observation(observation,adapter)
        source_key=(adapter["repository_id"],observation["receipt_hash"])
        prior=seen_source.get(source_key)
        if prior is not None:
            req(prior==observation,"duplicate observation identity has conflicting payload")
            duplicate_observations+=1
            continue
        seen_source[source_key]=observation

        project_ids=list(adapter["project_ids"])
        req(len(project_ids)==len(set(project_ids)) and project_ids,"adapter project routing invalid")
        if requested_project_id is not None:
            req(requested_project_id in project_ids,"wrong-project forwarding rejected")
            project_ids=[requested_project_id]

        for project_id in project_ids:
            require_capability(project_id,requested_capability,boundaries)
            row=capability_row(project_id,boundaries)
            req(row["repository_id"]==adapter["repository_id"],"project/repository routing mismatch")
            core={
              "schema_version":"1.0.0",
              "project_adapter_id":f"PFA-{project_id}",
              "project_id":project_id,
              "repository_id":adapter["repository_id"],
              "repository_full_name":adapter["repository_full_name"],
              "source_adapter_id":adapter["adapter_id"],
              "source_cycle_id":cycle["cycle_id"],
              "source_cycle_receipt_hash":cycle["receipt_hash"],
              "source_observation_receipt_hash":observation["receipt_hash"],
              "source_revision":observation.get("current_sha"),
              "observation_status":observation["status"],
              "capability_used":requested_capability,
              "authority_class":"OBSERVE",
              "downstream_write":False,
              "deployment":False,
              "external_action":False,
            }
            delivery_id="PFD-"+hashlib.sha256(canon(core)).hexdigest()[:24].upper()
            delivery={**core,"delivery_id":delivery_id,"delivery_hash":digest(core)}
            old=deliveries.get(delivery_id)
            req(old is None or old==delivery,"delivery id collision/conflict")
            deliveries[delivery_id]=delivery

    out={
      "schema_version":"1.0.0",
      "forwarding_id":"portfolio-project-forwarding-v1",
      "source_cycle_id":cycle["cycle_id"],
      "source_cycle_receipt_hash":cycle["receipt_hash"],
      "requested_capability":requested_capability,
      "authority_class":"OBSERVE",
      "authority_inherited":False,
      "delivery_semantics":"IDEMPOTENT_EXACT_IDENTITY_ONCE",
      "duplicate_observations_suppressed":duplicate_observations,
      "delivery_count":len(deliveries),
      "deliveries":sorted(deliveries.values(),key=lambda row:(row["repository_id"],row["project_id"],row["delivery_id"])),
    }
    out["receipt_hash"]=digest(out)
    return out

def main()->None:
    parser=argparse.ArgumentParser()
    parser.add_argument("--cycle",default="runtime/out/cycle_receipt.json")
    parser.add_argument("--output",default="runtime/out/project_forwarding_receipt.json")
    parser.add_argument("--project-id",default=None)
    parser.add_argument("--capability",default="READ_OBSERVE")
    args=parser.parse_args()
    cycle=json.loads(Path(args.cycle).read_text(encoding="utf-8"))
    receipt=forward_cycle(cycle,requested_project_id=args.project_id,requested_capability=args.capability)
    output=Path(args.output); output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(receipt,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps({"delivery_count":receipt["delivery_count"],"duplicates_suppressed":receipt["duplicate_observations_suppressed"],
                      "authority_class":receipt["authority_class"]},sort_keys=True))

if __name__=="__main__":
    main()
