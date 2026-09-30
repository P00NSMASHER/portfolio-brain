#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json
from typing import Any
from governance.authority import project_capability,require_project_capability
class ABVMObservationError(ValueError):pass
def req(ok:bool,msg:str)->None:
    if not ok:raise ABVMObservationError(msg)
def _hash(v:Any)->str:return "sha256:"+hashlib.sha256(json.dumps(v,sort_keys=True,separators=(",",":")).encode()).hexdigest()
def build_abvm_evidence(r:dict[str,Any],*,automation_health:str,progress:dict[str,Any])->dict[str,Any]:
    require_project_capability("PRJ-006","READ_OBSERVE")
    req(not project_capability("PRJ-006","CANDIDATE_PR") and not project_capability("PRJ-006","DEPLOY") and not project_capability("PRJ-006","EXTERNAL_ACTION"),"ABVM authority widened")
    req(r.get("adapter_id")=="ADP-003" and r.get("repository_id")=="REPO-003" and r.get("repository_full_name")=="P00NSMASHER/abvmschoolstarworld","ABVM route mismatch")
    req(r.get("status") in {"INITIALIZED","CHANGED","UNCHANGED"},"ABVM observation not successful")
    req(automation_health in {"HEALTHY","RUNNING","DEGRADED","UNKNOWN"},"automation health invalid")
    allowed={"latest_run_id","latest_run_status","latest_run_conclusion","source_sequence","source_revision"}
    req(isinstance(progress,dict) and set(progress)<=allowed,"ABVM progress contains non-health/content data")
    raw=json.dumps(progress,sort_keys=True).lower()
    for forbidden in ("student","child","grade","homework","answer","school_content","lesson"):req(forbidden not in raw,"ABVM child/school content leaked")
    return {"schema_version":"1.0.0","evidence_id":"ABVM-OBS-"+_hash({"receipt":r["receipt_hash"],"health":automation_health,"progress":progress}).split(":")[1][:24].upper(),"project_id":"PRJ-006","repository_id":"REPO-003","authority_class":"OBSERVE","evidence_scope":"AUTOMATION_HEALTH_AND_PROGRESS_ONLY","automation_health":automation_health,"progress":progress,"source_revision":r["current_sha"],"source_observation_hash":r["receipt_hash"],"child_facing_mutation_authority":False,"deployment_authority":False,"school_content_publication_authority":False,"verification_credit":[]}
