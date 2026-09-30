#!/usr/bin/env python3
"""Project-scoped, exact-once routing of sanitized runtime observations.

Repository adapters remain read-only. This module only projects an observation
receipt into project-scoped evidence records after checking the independent
authority matrix. It performs no network write, PR creation, deployment, or
external action.
"""
from __future__ import annotations
import hashlib,json,re
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parents[1]
STATE_ID="portfolio-project-forwarding-state"
MAX_DELIVERED_KEYS=4096
MAX_RECENT_DELIVERIES=256
SHA40=re.compile(r"^[0-9a-f]{40}$")

class ProjectForwardingError(ValueError): pass
def req(ok:bool,msg:str)->None:
    if not ok: raise ProjectForwardingError(msg)
def load(path:Path|str)->dict[str,Any]:
    p=Path(path)
    if not p.is_absolute(): p=ROOT/p
    return json.loads(p.read_text(encoding="utf-8"))
def canon(v:Any)->str:
    return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False)
def hashv(v:Any)->str:
    return "sha256:"+hashlib.sha256(canon(v).encode()).hexdigest()

def seed_state()->dict[str,Any]:
    return load("runtime/PROJECT_FORWARDING_STATE_SEED.json")

def validate_state(state:dict[str,Any])->None:
    required={"schema_version","state_id","sequence","updated_at","delivered_keys","recent_deliveries"}
    req(isinstance(state,dict) and set(state)==required,"forwarding state fields changed")
    req(state["schema_version"]=="1.0.0" and state["state_id"]==STATE_ID,"forwarding state identity mismatch")
    req(type(state["sequence"]) is int and state["sequence"]>=0,"forwarding state sequence invalid")
    req(state["updated_at"] is None or isinstance(state["updated_at"],str),"forwarding state updated_at invalid")
    keys=state["delivered_keys"]
    req(isinstance(keys,list) and len(keys)<=MAX_DELIVERED_KEYS and len(keys)==len(set(keys)),"forwarding dedupe ledger invalid")
    req(all(isinstance(x,str) and x.startswith("sha256:") for x in keys),"forwarding dedupe key invalid")
    deliveries=state["recent_deliveries"]
    req(isinstance(deliveries,list) and len(deliveries)<=MAX_RECENT_DELIVERIES,"forwarding delivery ledger invalid")
    ids=set()
    for row in deliveries:
        expected={"delivery_id","delivery_key","project_id","repository_id","source_ref","source_revision",
                  "observation_receipt_hash","observation_status","capability","evidence_state","evidence_scope",
                  "payload_scope","authority_granted","mutation_performed","deploy_authority",
                  "external_action_authority","child_facing_mutation_authority",
                  "school_content_publication_authority","forwarded_at"}
        req(isinstance(row,dict) and set(row)==expected,"forwarding delivery fields changed")
        req(row["delivery_id"].startswith("PFD-") and row["delivery_id"] not in ids,"forwarding delivery id invalid")
        ids.add(row["delivery_id"])
        req(row["delivery_key"] in keys,"delivery missing dedupe key")
        req(row["capability"]=="READ_OBSERVE" and row["evidence_state"]=="OBSERVED","forwarding evidence authority widened")
        req(row["payload_scope"]=="SANITIZED_METADATA_ONLY","forwarding persisted payload widened")
        for field in ("authority_granted","mutation_performed","deploy_authority","external_action_authority","child_facing_mutation_authority","school_content_publication_authority"):
            req(row[field] is False,"forwarding delivery gained authority: "+field)

def load_state(path:Path|str|None=None)->dict[str,Any]:
    if path is not None and Path(path).exists():
        state=json.loads(Path(path).read_text(encoding="utf-8"))
    else:
        state=seed_state()
    validate_state(state)
    return state

def _configs(adapter_registry=None,boundaries=None):
    adapters=(adapter_registry if adapter_registry is not None else load("adapters/ADAPTER_REGISTRY.json"))["adapters"]
    policy=boundaries if boundaries is not None else load("governance/boundaries.json")
    by_repo={row["repository_id"]:row for row in adapters}
    caps={row["project_id"]:row for row in policy["project_capabilities"]}
    return by_repo,caps,policy

def _validated_adapter(observation:dict[str,Any],by_repo:dict[str,Any])->dict[str,Any]:
    rid=observation.get("repository_id")
    req(rid in by_repo,"observation references unknown repository")
    adapter=by_repo[rid]
    req(observation.get("adapter_id")==adapter["adapter_id"],"observation adapter identity mismatch")
    req(observation.get("repository_full_name")==adapter["repository_full_name"],"observation repository identity mismatch")
    req(observation.get("source_ref")==adapter["source_ref_policy"]["ref"],"observation source ref mismatch")
    req(adapter["authority_class"]=="OBSERVE","repository adapter widened beyond OBSERVE")
    return adapter

def build_project_delivery(observation:dict[str,Any],project_id:str,*,at:str,adapter_registry=None,boundaries=None)->dict[str,Any]:
    by_repo,caps,policy=_configs(adapter_registry,boundaries)
    adapter=_validated_adapter(observation,by_repo)
    req(adapter["enabled"] is True and adapter["blocked_by"] is None,"blocked adapter cannot forward")
    req(project_id in adapter["project_ids"],"wrong-project forwarding rejected")
    req(project_id in caps,"project capability missing")
    read=caps[project_id]["READ_OBSERVE"]
    req(read["allowed"] is True and adapter["repository_id"] in read["repository_ids"],"project observation capability denied")
    req(observation.get("status") in {"INITIALIZED","CHANGED"},"only new repository revisions may be forwarded")
    revision=observation.get("current_sha")
    req(isinstance(revision,str) and SHA40.fullmatch(revision) is not None,"forwarded observation requires exact source revision")
    obs_hash=observation.get("receipt_hash")
    req(isinstance(obs_hash,str) and obs_hash.startswith("sha256:"),"forwarded observation requires receipt hash")
    core={"repository_id":adapter["repository_id"],"project_id":project_id,"source_ref":observation["source_ref"],"source_revision":revision}
    key=hashv(core)
    evidence_scope=list(read["scope"])
    if project_id=="PRJ-006":
        abvm=policy["constrained_integrations"]["PRJ-006"]
        req(abvm["child_facing_mutation"] is False and abvm["deployment_authority"] is False and abvm["school_content_publication_authority"] is False,
            "ABVM constrained integration widened")
        req(evidence_scope==["REPOSITORY_OBSERVATION"],"ABVM repository forwarding must remain repository observation only")
        req(set(abvm["allowed_evidence"])=={"AUTOMATION_HEALTH","PROGRESS_EVIDENCE"},"ABVM constrained evidence policy widened")
    return {
      "delivery_id":"PFD-"+hashlib.sha256(key.encode()).hexdigest()[:20].upper(),
      "delivery_key":key,
      "project_id":project_id,
      "repository_id":adapter["repository_id"],
      "source_ref":observation["source_ref"],
      "source_revision":revision,
      "observation_receipt_hash":obs_hash,
      "observation_status":observation["status"],
      "capability":"READ_OBSERVE",
      "evidence_state":"OBSERVED",
      "evidence_scope":evidence_scope,
      "payload_scope":"SANITIZED_METADATA_ONLY",
      "authority_granted":False,
      "mutation_performed":False,
      "deploy_authority":False,
      "external_action_authority":False,
      "child_facing_mutation_authority":False,
      "school_content_publication_authority":False,
      "forwarded_at":at,
    }

def forward_observations(state:dict[str,Any],observations:list[dict[str,Any]],*,at:str,cycle_id:str,cycle_receipt_hash:str,
                         adapter_registry=None,boundaries=None)->tuple[dict[str,Any],dict[str,Any]]:
    validate_state(state)
    req(isinstance(cycle_id,str) and cycle_id,"forwarding cycle id required")
    req(isinstance(cycle_receipt_hash,str) and cycle_receipt_hash.startswith("sha256:"),"forwarding cycle receipt hash required")
    by_repo,_,_=_configs(adapter_registry,boundaries)
    out=json.loads(json.dumps(state))
    seen=set(out["delivered_keys"])
    deliveries=[]; duplicates=[]; skipped=[]
    observation_keys=set()
    for observation in observations:
        adapter=_validated_adapter(observation,by_repo)
        status=observation.get("status")
        if status in {"BLOCKED","UNCHANGED"}:
            skipped.append({"repository_id":adapter["repository_id"],"status":status})
            continue
        req(status in {"INITIALIZED","CHANGED"},"unsupported repository observation status")
        obs_identity=(adapter["repository_id"],observation.get("source_ref"),observation.get("current_sha"),observation.get("receipt_hash"))
        if obs_identity in observation_keys:
            # The same observation may appear twice after an upstream fan-in retry.
            pass
        observation_keys.add(obs_identity)
        for project_id in sorted(adapter["project_ids"]):
            delivery=build_project_delivery(observation,project_id,at=at,adapter_registry=adapter_registry,boundaries=boundaries)
            key=delivery["delivery_key"]
            if key in seen:
                duplicates.append(key)
                continue
            seen.add(key)
            deliveries.append(delivery)
    if deliveries:
        out["sequence"]+=1
        out["updated_at"]=at
        out["delivered_keys"]=list(dict.fromkeys([*out["delivered_keys"],*(d["delivery_key"] for d in deliveries)]))[-MAX_DELIVERED_KEYS:]
        out["recent_deliveries"]=([*out["recent_deliveries"],*deliveries])[-MAX_RECENT_DELIVERIES:]
    validate_state(out)
    body={"schema_version":"1.0.0","cycle_id":cycle_id,"source_cycle_receipt_hash":cycle_receipt_hash,
          "status":"PASS","deliveries":deliveries,"duplicate_delivery_keys":sorted(set(duplicates)),
          "skipped_observations":skipped,"authority_granted":False,"mutation_performed":False}
    body["receipt_hash"]=hashv(body)
    return out,body
