#!/usr/bin/env python3
from __future__ import annotations
import copy,hashlib,json,re
from pathlib import Path
from typing import Any
from governance.authority import require_project_capability
from hunting.autonomous_hunter import candidate_fingerprint,classify_candidate,experiment_proposal,proposal_eligible,structural_inspection
ROOT=Path(__file__).resolve().parents[1];SHA=re.compile(r"^[0-9a-f]{40}$");REPO=re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
class ScoutIntakeError(ValueError):pass
def req(ok:bool,msg:str)->None:
    if not ok:raise ScoutIntakeError(msg)
def load(path:str)->dict[str,Any]:return json.loads((ROOT/path).read_text())
def policy():return load("hunting/REPO_SCOUT_INTAKE_POLICY.json")
def load_seed_state():return load("hunting/HUNTER_REPO_SCOUT_INTAKE_STATE_SEED.json")
def canon(v):return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False)
def digest(v):return "sha256:"+hashlib.sha256(canon(v).encode()).hexdigest()
def validate_state(s):
    p=policy();req(set(s)=={"schema_version","state_id","sequence","updated_at","processed"},"scout state fields changed")
    req(s["schema_version"]=="1.0.0" and s["state_id"]=="repo-001-scout-intake-state","scout state identity mismatch")
    req(type(s["sequence"]) is int and s["sequence"]>=0 and isinstance(s["processed"],list) and len(s["processed"])<=p["max_state_records"],"scout state invalid")
    keys=[]
    for row in s["processed"]:
        req(set(row)=={"dedupe_key","finding_identity","source_revision","disposition"},"scout record fields changed");req(SHA.fullmatch(row["source_revision"] or "") is not None,"source revision invalid");keys.append(row["dedupe_key"])
    req(len(keys)==len(set(keys)),"duplicate scout state key")
def _identity(path,worker,c):return digest({"source_path":path,"worker_id":worker,"repository":c["repository"],"exact_revision":c["exact_revision"]})
def _dedupe(source_revision,identity):
    p=policy();return digest({"source_repository_id":p["source_repository_id"],"source_repository_full_name":p["source_repository_full_name"],"source_revision":source_revision,"finding_identity":identity})
def _eligible(c):
    p=policy();r=[]
    if c.get("status")!=p["required_candidate_status"]:r.append("STATUS_NOT_PRE_VERIFICATION")
    if c.get("archived") is not False:r.append("ARCHIVED_OR_UNKNOWN")
    if type(c.get("triage_score")) is not int or c["triage_score"]<p["min_triage_score"]:r.append("TRIAGE_BELOW_GATE")
    if SHA.fullmatch(str(c.get("exact_revision") or "")) is None:r.append("EXACT_REVISION_MISSING")
    if REPO.fullmatch(str(c.get("repository") or "")) is None:r.append("REPOSITORY_IDENTITY_INVALID")
    if not set(c.get("root_code_signals") or []).intersection(p["required_root_code_signals_any"]):r.append("NO_REQUIRED_ROOT_CODE_SIGNAL")
    return not r,r
def ingest_queue(*,queue,source_revision,source_path,hunter_state,provider,intake_state=None,at):
    p=policy();s=copy.deepcopy(intake_state if intake_state is not None else load_seed_state());validate_state(s)
    req(SHA.fullmatch(source_revision or "") is not None,"REPO-001 source revision must be exact")
    req(re.fullmatch(r"intelligence/scout_queue/HUNTER-[0-9]{2}\.json",source_path or "") is not None,"scout source path not allowlisted")
    req(queue.get("schema_version")==2 and queue.get("authority")==p["required_source_authority"],"scout source contract invalid")
    worker=queue.get("worker_id");req(worker in p["worker_targets"],"scout worker has no explicit target");target=p["worker_targets"][worker];require_project_capability(target,"READ_OBSERVE")
    req(queue.get("candidate_count")==len(queue.get("candidates") or []),"candidate count mismatch")
    obj={"objective_id":"HOBJ-"+hashlib.sha256((source_revision+"|"+worker).encode()).hexdigest()[:20].upper(),"gap_id":"HGAP-"+hashlib.sha256((target+"|repo-scout").encode()).hexdigest()[:20].upper(),"project_ids":[target],"strategy_id":"STRAT:capability-conjunction-search-claim-tracing","capability_key":p["target_capability_keys"][target],"search_concepts":["roblox","luau","framework"]}
    seen={x["dedupe_key"] for x in s["processed"]};admitted=[];rejected=[];duplicates=[];inspections=0
    for c in sorted(queue["candidates"],key=lambda x:(-int(x.get("triage_score") or 0),str(x.get("repository") or ""))):
        identity=_identity(source_path,worker,c);key=_dedupe(source_revision,identity)
        if key in seen:duplicates.append({"finding_identity":identity,"dedupe_key":key});continue
        ok,reasons=_eligible(c)
        if not ok:
            rejected.append({"finding_identity":identity,"dedupe_key":key,"reason_codes":reasons});s["processed"].append({"dedupe_key":key,"finding_identity":identity,"source_revision":source_revision,"disposition":"INELIGIBLE"});seen.add(key);continue
        if inspections>=p["max_candidates_per_cycle"]:break
        meta=provider.repository_metadata(c["repository"]);req(meta.get("private") is False and meta.get("full_name")==c["repository"],"candidate metadata mismatch")
        ins=provider.inspect_revision(meta,c["exact_revision"]);inspections+=1;struct=structural_inspection(meta,ins,obj);fp=candidate_fingerprint(meta,c["exact_revision"],obj);disp,negative,trace=classify_candidate(hunter_state,fp,struct);rank=trace["ranking"];fid="HFD-"+hashlib.sha256((key+"|"+fp).encode()).hexdigest()[:20].upper()
        finding={"schema_version":"1.0.0","finding_id":fid,"objective_id":obj["objective_id"],"gap_id":obj["gap_id"],"project_ids":[target],"strategy_id":obj["strategy_id"],"candidate_fingerprint":fp,"source":{"source_kind":"PUBLIC_GITHUB","repository_full_name":c["repository"],"repository_id":meta["id"],"revision":c["exact_revision"],"public":True},"inspection":struct,"rights":{"rights_classification":"SCOUT_METADATA_ONLY_NO_REUSE_AUTHORITY","automatic_reuse_authority_granted":False},"capability_hypothesis":f"{c['repository']}@{c['exact_revision']} is a REPO-001 pre-verification scout candidate for {obj['capability_key']}.","evidence_state":"OBSERVED" if disp=="RETAIN" else "UNKNOWN","disposition":disp,"provenance_refs":[f"repo-001:{source_path}@{source_revision}",f"scout-finding:{identity}",f"github:{c['repository']}@{c['exact_revision']}"],"negative_reason":negative,"ranking":rank,"proposal_eligibility":"ELIGIBLE" if disp=="RETAIN" and proposal_eligible(rank) else ("DEFER_LOW_RANK" if disp=="RETAIN" else "NOT_APPLICABLE"),"decision_trace":trace,"experiment_proposal_id":None}
        proposal=None
        if disp=="RETAIN" and proposal_eligible(rank):proposal=experiment_proposal(finding);finding["experiment_proposal_id"]=proposal["proposal_id"];finding["proposal_eligibility"]="SELECTED"
        admitted.append({"finding_identity":identity,"dedupe_key":key,"finding":finding,"proposal":proposal});s["processed"].append({"dedupe_key":key,"finding_identity":identity,"source_revision":source_revision,"disposition":disp});seen.add(key)
    s["processed"]=s["processed"][-p["max_state_records"]:];s["sequence"]+=1;s["updated_at"]=at;validate_state(s)
    out={"schema_version":"1.0.0","intake_id":p["intake_id"],"status":"PASS","authority_class":"OBSERVE","source_repository_id":p["source_repository_id"],"source_repository_full_name":p["source_repository_full_name"],"source_revision":source_revision,"source_path":source_path,"worker_id":worker,"target_project_id":target,"bounded_candidate_limit":p["max_candidates_per_cycle"],"inspected_candidates":inspections,"admitted":admitted,"rejected":rejected,"duplicates":duplicates,"reuse_rights_granted":False,"downstream_write_authority":False,"deployment_authority":False,"technical_verification_granted":False,"market_verification_granted":False,"revenue_verification_granted":False,"finished_at":at};out["receipt_hash"]=digest(out);return s,out
