#!/usr/bin/env python3
"""Evidence-gated Hunter -> implementation -> value lifecycle.

The lifecycle is a projection over existing Hunter review and SoftwareFactory
evidence. It does not grant discovery, reuse, merge, deployment, market, or revenue
authority. Every stage transition requires a separate evidence object and stages
cannot be skipped.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from hunting.proposal_review_state import digest
from software_factory.software_factory import SoftwareFactory

STAGES=(
  "DISCOVERED","REVIEWED","ACCEPTED_FOR_WORK","IMPLEMENTED",
  "TECHNICALLY_VERIFIED","MARKET_VERIFIED","REVENUE_VERIFIED",
)
STAGE_INDEX={stage:i for i,stage in enumerate(STAGES)}

class HunterLifecycleError(ValueError):
    pass

def req(ok:bool,msg:str)->None:
    if not ok:
        raise HunterLifecycleError(msg)

def _hash(v:Any)->str:
    return "sha256:"+hashlib.sha256(
      json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()
    ).hexdigest()

def _evidence(stage:str,kind:str,refs:list[str],at:str,payload:dict[str,Any])->dict[str,Any]:
    req(stage in STAGE_INDEX,"unknown Hunter lifecycle stage")
    req(isinstance(kind,str) and kind,"lifecycle evidence kind missing")
    req(isinstance(refs,list) and refs and len(refs)==len(set(refs)),"lifecycle evidence refs invalid")
    req(isinstance(at,str) and at.endswith("Z"),"lifecycle evidence time must be UTC")
    core={"stage":stage,"evidence_kind":kind,"evidence_refs":refs,"observed_at":at,"payload":payload}
    return {**core,"evidence_hash":_hash(core)}

def _advance(lifecycle:dict[str,Any], evidence:dict[str,Any])->dict[str,Any]:
    current=lifecycle["current_stage"]
    target=evidence["stage"]
    req(STAGE_INDEX[target]==STAGE_INDEX[current]+1,"Hunter lifecycle stages cannot be skipped")
    out=json.loads(json.dumps(lifecycle))
    out["current_stage"]=target
    out["stage_history"].append(evidence)
    out["market_verified"]=target in {"MARKET_VERIFIED","REVENUE_VERIFIED"}
    out["revenue_verified"]=target=="REVENUE_VERIFIED"
    out["lifecycle_hash"]=_hash({k:v for k,v in out.items() if k!="lifecycle_hash"})
    return out

def validate_lifecycle(lifecycle:dict[str,Any])->None:
    expected={
      "schema_version","lifecycle_id","proposal_id","finding_id","review_id","review_hash",
      "project_ids","source_repository_full_name","source_revision","current_stage","stage_history",
      "factory_work_id","market_verified","revenue_verified","merge_authority_granted",
      "deployment_authority_granted","lifecycle_hash",
    }
    req(isinstance(lifecycle,dict) and set(lifecycle)==expected,"Hunter lifecycle fields changed")
    req(lifecycle["schema_version"]=="1.0.0","Hunter lifecycle schema mismatch")
    req(isinstance(lifecycle["lifecycle_id"],str) and lifecycle["lifecycle_id"].startswith("HLIFE-"),
        "Hunter lifecycle id invalid")
    req(isinstance(lifecycle["proposal_id"],str) and lifecycle["proposal_id"].startswith("HEXP-"),
        "Hunter lifecycle proposal id invalid")
    req(isinstance(lifecycle["finding_id"],str) and lifecycle["finding_id"],"Hunter lifecycle finding id invalid")
    req(isinstance(lifecycle["review_id"],str) and lifecycle["review_id"].startswith("HREV-"),
        "Hunter lifecycle review id invalid")
    req(isinstance(lifecycle["review_hash"],str) and lifecycle["review_hash"].startswith("sha256:"),
        "Hunter lifecycle review hash invalid")
    projects=lifecycle["project_ids"]
    req(isinstance(projects,list) and projects and len(projects)==len(set(projects)),
        "Hunter lifecycle project ids invalid")
    req(all(isinstance(x,str) and x.startswith("PRJ-") for x in projects),
        "Hunter lifecycle project id invalid")
    req(isinstance(lifecycle["source_repository_full_name"],str) and "/" in lifecycle["source_repository_full_name"],
        "Hunter lifecycle source repository invalid")
    revision=lifecycle["source_revision"]
    req(isinstance(revision,str) and len(revision)==40 and all(c in "0123456789abcdef" for c in revision),
        "Hunter lifecycle source revision invalid")
    stage=lifecycle["current_stage"]
    req(stage in STAGE_INDEX,"Hunter lifecycle current stage invalid")
    history=lifecycle["stage_history"]
    req(isinstance(history,list) and len(history)==STAGE_INDEX[stage]+1,
        "Hunter lifecycle stage history length invalid")
    for index,evidence in enumerate(history):
        req(isinstance(evidence,dict) and set(evidence)=={
            "stage","evidence_kind","evidence_refs","observed_at","payload","evidence_hash"
        },"Hunter lifecycle evidence fields changed")
        req(evidence["stage"]==STAGES[index],"Hunter lifecycle stage history skipped/reordered")
        refs=evidence["evidence_refs"]
        req(isinstance(refs,list) and refs and len(refs)==len(set(refs)),
            "Hunter lifecycle evidence refs invalid")
        body=dict(evidence);given=body.pop("evidence_hash")
        req(given==_hash(body),"Hunter lifecycle evidence hash mismatch")
    work_id=lifecycle["factory_work_id"]
    req(work_id is None or (
        isinstance(work_id,str)
        and (work_id.startswith("SFW-HUNTER-") or work_id.startswith("AUTO-REPAIR-"))
    ), "Hunter lifecycle factory work id invalid")
    if STAGE_INDEX[stage]>=STAGE_INDEX["IMPLEMENTED"]:
        req(work_id is not None,"implemented Hunter lifecycle missing factory work")
    req(lifecycle["market_verified"]==(STAGE_INDEX[stage]>=STAGE_INDEX["MARKET_VERIFIED"]),
        "Hunter lifecycle market verification projection mismatch")
    req(lifecycle["revenue_verified"]==(stage=="REVENUE_VERIFIED"),
        "Hunter lifecycle revenue verification projection mismatch")
    req(lifecycle["merge_authority_granted"] is False and lifecycle["deployment_authority_granted"] is False,
        "Hunter lifecycle widened merge/deploy authority")
    body=dict(lifecycle);given=body.pop("lifecycle_hash")
    req(given==_hash(body),"Hunter lifecycle hash mismatch")

def lifecycle_from_review(review:dict[str,Any])->dict[str,Any]:
    body=dict(review);given=body.pop("review_hash",None)
    req(isinstance(given,str) and given==digest(body),"Hunter review hash invalid")
    req(review.get("reuse_authorized") is False,"Hunter review cannot grant reuse authority")
    req(review.get("implementation_authorized") is False,"Hunter review cannot self-authorize implementation")
    refs=list(dict.fromkeys([
      f"hunter-proposal:{review['proposal_id']}",
      f"hunter-finding:{review['finding_id']}",
      f"hunter-review:{review['review_id']}",
      f"hunter-review-hash:{review['review_hash']}",
      f"github:{review['repository_full_name']}@{review['revision']}",
    ]))
    discovered=_evidence(
      "DISCOVERED","HUNTER_FINDING",refs,review["reviewed_at"],
      {"proposal_id":review["proposal_id"],"finding_id":review["finding_id"]},
    )
    reviewed=_evidence(
      "REVIEWED","PUBLIC_EVIDENCE_REVIEW",refs,review["reviewed_at"],
      {"review_id":review["review_id"],"review_hash":review["review_hash"],"rights_state":review["rights_state"]},
    )
    core={
      "schema_version":"1.0.0",
      "lifecycle_id":"HLIFE-"+hashlib.sha256(review["proposal_id"].encode()).hexdigest()[:20].upper(),
      "proposal_id":review["proposal_id"],
      "finding_id":review["finding_id"],
      "review_id":review["review_id"],
      "review_hash":review["review_hash"],
      "project_ids":list(review["project_ids"]),
      "source_repository_full_name":review["repository_full_name"],
      "source_revision":review["revision"],
      "current_stage":"REVIEWED",
      "stage_history":[discovered,reviewed],
      "factory_work_id":None,
      "market_verified":False,
      "revenue_verified":False,
      "merge_authority_granted":False,
      "deployment_authority_granted":False,
    }
    return {**core,"lifecycle_hash":_hash(core)}

def build_acceptance_receipt(
    lifecycle:dict[str,Any], *,
    acceptance_id:str,
    target_repository_id:str,
    project_id:str,
    verifier_agent_id:str,
    accepted_at:str,
    evidence_refs:list[str],
    external_milestone:str,
    implementation_target_paths:list[str],
    regression_requirement:str,
    controlled_proof:bool=False,
)->dict[str,Any]:
    req(lifecycle["current_stage"]=="REVIEWED","only REVIEWED findings can be accepted for work")
    req(project_id in lifecycle["project_ids"],"acceptance project not bound to Hunter finding")
    core={
      "schema_version":"1.0.0","acceptance_id":acceptance_id,
      "proposal_id":lifecycle["proposal_id"],"finding_id":lifecycle["finding_id"],
      "review_id":lifecycle["review_id"],"review_hash":lifecycle["review_hash"],
      "project_id":project_id,"target_repository_id":target_repository_id,
      "verifier_agent_id":verifier_agent_id,"decision":"ACCEPTED_FOR_WORK",
      "implementation_mode":"ISOLATED_REIMPLEMENTATION_NO_SOURCE_COPY",
      "external_milestone":external_milestone,
      "implementation_target_paths":list(dict.fromkeys(implementation_target_paths)),
      "regression_requirement":regression_requirement,
      "accepted_at":accepted_at,"controlled_proof":bool(controlled_proof),
      "evidence_refs":list(dict.fromkeys(evidence_refs)),
      "merge_authority_granted":False,"deployment_authority_granted":False,
    }
    req(core["evidence_refs"],"acceptance provenance required")
    req(isinstance(external_milestone,str) and external_milestone,"acceptance external milestone required")
    req(core["implementation_target_paths"] and all(
        isinstance(path,str) and path and not path.startswith("/") and ".." not in path.split("/")
        for path in core["implementation_target_paths"]
    ),"acceptance implementation target paths invalid")
    req(isinstance(regression_requirement,str) and regression_requirement.strip(),
        "acceptance regression requirement required")
    return {**core,"acceptance_hash":_hash(core)}

def apply_acceptance(lifecycle:dict[str,Any], receipt:dict[str,Any])->dict[str,Any]:
    body=dict(receipt);given=body.pop("acceptance_hash",None)
    req(isinstance(given,str) and given==_hash(body),"Hunter work acceptance hash invalid")
    req(receipt.get("decision")=="ACCEPTED_FOR_WORK","Hunter work was not accepted")
    req(receipt.get("implementation_mode")=="ISOLATED_REIMPLEMENTATION_NO_SOURCE_COPY","unsafe Hunter implementation mode")
    req(receipt.get("merge_authority_granted") is False and receipt.get("deployment_authority_granted") is False,"acceptance widened authority")
    for field in ("proposal_id","finding_id","review_id","review_hash"):
        req(receipt.get(field)==lifecycle.get(field),f"acceptance {field} lineage mismatch")
    req(receipt["project_id"] in lifecycle["project_ids"],"acceptance project mismatch")
    evidence=_evidence(
      "ACCEPTED_FOR_WORK","EXPLICIT_WORK_ACCEPTANCE",
      [*receipt["evidence_refs"],f"hunter-acceptance:{receipt['acceptance_id']}",f"hunter-acceptance-hash:{receipt['acceptance_hash']}"],
      receipt["accepted_at"],
      {"acceptance_id":receipt["acceptance_id"],"target_repository_id":receipt["target_repository_id"],
       "project_id":receipt["project_id"],"external_milestone":receipt["external_milestone"],
       "implementation_target_paths":receipt["implementation_target_paths"],
       "controlled_proof":receipt["controlled_proof"]},
    )
    return _advance(lifecycle,evidence)

def enqueue_factory_work(
    factory:SoftwareFactory,
    lifecycle:dict[str,Any],
    acceptance:dict[str,Any],
    *,
    base_sha:str,
    now:float,
)->tuple[dict[str,Any],dict[str,Any]]:
    req(lifecycle["current_stage"]=="ACCEPTED_FOR_WORK","Hunter finding not accepted for implementation work")
    acceptance_hash_ref="hunter-acceptance-hash:"+acceptance["acceptance_hash"]
    req(acceptance["proposal_id"]==lifecycle["proposal_id"] and acceptance_hash_ref in lifecycle["stage_history"][-1]["evidence_refs"],"acceptance not bound to lifecycle")
    work_id="SFW-HUNTER-"+hashlib.sha256((lifecycle["lifecycle_id"]+"\0"+acceptance["acceptance_id"]).encode()).hexdigest()[:20].upper()
    provenance=[
      f"hunter-lifecycle:{lifecycle['lifecycle_id']}",
      f"hunter-proposal:{lifecycle['proposal_id']}",
      f"hunter-finding:{lifecycle['finding_id']}",
      f"hunter-review:{lifecycle['review_id']}",
      f"hunter-review-hash:{lifecycle['review_hash']}",
      f"hunter-acceptance:{acceptance['acceptance_id']}",
      f"hunter-acceptance-hash:{acceptance['acceptance_hash']}",
    ]
    factory.enqueue(
      work_id=work_id,project_id=acceptance["project_id"],
      repository_id=acceptance["target_repository_id"],base_sha=base_sha,
      title=f"Hunter accepted work {lifecycle['proposal_id']}",
      issue_ref=f"hunter:{lifecycle['proposal_id']}",
      verifier_agent_id=acceptance["verifier_agent_id"],
      provenance_refs=provenance,now=now,
    )
    work=factory.get(work_id)
    out=json.loads(json.dumps(lifecycle))
    out["factory_work_id"]=work_id
    out["lifecycle_hash"]=_hash({k:v for k,v in out.items() if k!="lifecycle_hash"})
    return out,work

def apply_factory_evidence(lifecycle:dict[str,Any],work:dict[str,Any],*,at:str)->dict[str,Any]:
    req(work.get("work_id")==lifecycle.get("factory_work_id"),"factory work lineage mismatch")
    refs=[f"factory:{work['work_id']}"]
    current=lifecycle["current_stage"]
    if current=="ACCEPTED_FOR_WORK":
        commit=work.get("commit_sha")
        req(work.get("state") in {"VERIFYING","READY_FOR_PR","PR_OPEN"} and isinstance(commit,str) and len(commit)==40,
            "factory evidence does not prove implementation")
        return _advance(lifecycle,_evidence(
          "IMPLEMENTED","FACTORY_CANDIDATE_COMMIT",[ *refs,f"commit:{commit}",f"diff:{work['diff_hash']}"],at,
          {"factory_work_id":work["work_id"],"commit_sha":commit,"state":work["state"]},
        ))
    if current=="IMPLEMENTED":
        req(work.get("state") in {"READY_FOR_PR","PR_OPEN"} and work.get("verification_id"),
            "factory evidence does not prove independent technical verification")
        return _advance(lifecycle,_evidence(
          "TECHNICALLY_VERIFIED","INDEPENDENT_FACTORY_VERIFICATION",
          [*refs,f"verification:{work['verification_id']}",f"commit:{work['commit_sha']}"],at,
          {"factory_work_id":work["work_id"],"verification_id":work["verification_id"],"state":work["state"]},
        ))
    raise HunterLifecycleError("factory evidence is not valid for current lifecycle stage")

def apply_governed_implementation_evidence(
    lifecycle:dict[str,Any], evidence:dict[str,Any]
)->dict[str,Any]:
    """Advance one technical stage from exact governed candidate/check evidence."""
    req(isinstance(evidence,dict),"governed implementation evidence missing")
    req(evidence.get("proposal_id")==lifecycle["proposal_id"],"implementation evidence proposal mismatch")
    acceptance_stage=next(
      (row for row in lifecycle["stage_history"] if row["stage"]=="ACCEPTED_FOR_WORK"),None
    )
    req(acceptance_stage is not None,"implementation evidence requires accepted work")
    acceptance_id=acceptance_stage["payload"]["acceptance_id"]
    req(evidence.get("acceptance_id")==acceptance_id,"implementation evidence acceptance mismatch")
    req(evidence.get("source_ref")==acceptance_id,"implementation evidence source ref mismatch")
    req(evidence.get("status")=="REPAIR_PR_FOUND","implementation candidate PR not found")
    pr_number=evidence.get("pr_number");head=evidence.get("head_sha")
    req(type(pr_number) is int and pr_number>0,"implementation PR identity invalid")
    req(isinstance(head,str) and len(head)==40 and all(c in "0123456789abcdef" for c in head),
        "implementation candidate SHA invalid")
    work_id=evidence.get("factory_work_id")
    req(isinstance(work_id,str) and work_id.startswith("AUTO-REPAIR-"),
        "implementation factory work identity missing")
    observed_at=evidence.get("observed_at")
    req(isinstance(observed_at,str) and observed_at.endswith("Z"),
        "implementation evidence time invalid")
    base_refs=evidence.get("evidence_refs")
    req(isinstance(base_refs,list) and base_refs and len(base_refs)==len(set(base_refs)),
        "implementation evidence refs invalid")
    if lifecycle["current_stage"]=="ACCEPTED_FOR_WORK":
        out=json.loads(json.dumps(lifecycle))
        out["factory_work_id"]=work_id
        out["lifecycle_hash"]=_hash({k:v for k,v in out.items() if k!="lifecycle_hash"})
        return _advance(out,_evidence(
          "IMPLEMENTED","GOVERNED_FACTORY_CANDIDATE",
          list(dict.fromkeys([*base_refs,f"factory:{work_id}",f"repair-pr:{pr_number}",f"commit:{head}"])),
          observed_at,
          {"factory_work_id":work_id,"pr_number":pr_number,"commit_sha":head},
        ))
    if lifecycle["current_stage"]=="IMPLEMENTED":
        req(lifecycle.get("factory_work_id")==work_id,"technical evidence factory work mismatch")
        req(evidence.get("foundation_success") is True and evidence.get("independent_success") is True,
            "technical checks do not prove independent verification")
        checks=evidence.get("checks")
        req(isinstance(checks,list) and checks,"technical check evidence missing")
        return _advance(lifecycle,_evidence(
          "TECHNICALLY_VERIFIED","PROTECTED_EXACT_HEAD_CHECKS",
          list(dict.fromkeys([*base_refs,f"factory:{work_id}",f"repair-pr:{pr_number}",f"commit:{head}"])),
          observed_at,
          {"factory_work_id":work_id,"pr_number":pr_number,"commit_sha":head,
           "foundation_success":True,"independent_success":True,"checks":checks},
        ))
    raise HunterLifecycleError("governed implementation evidence is not valid for current lifecycle stage")


def apply_external_evidence(lifecycle:dict[str,Any],evidence:dict[str,Any])->dict[str,Any]:
    req(evidence.get("verified") is True,"external lifecycle evidence is not verified")
    req(evidence.get("proposal_id")==lifecycle["proposal_id"],"external evidence proposal mismatch")
    target=evidence.get("target_stage")
    if target=="MARKET_VERIFIED":
        req(lifecycle["current_stage"]=="TECHNICALLY_VERIFIED","market evidence requires technical verification first")
        req(evidence.get("evidence_kind")=="MARKET_OUTCOME","technical/CI evidence cannot prove market value")
    elif target=="REVENUE_VERIFIED":
        req(lifecycle["current_stage"]=="MARKET_VERIFIED","revenue evidence requires market verification first")
        req(evidence.get("evidence_kind")=="REVENUE_OUTCOME","market/technical evidence cannot prove revenue")
        req(isinstance(evidence.get("transaction_ref"),str) and evidence["transaction_ref"],"revenue transaction reference required")
    else:
        raise HunterLifecycleError("unsupported external lifecycle stage")
    refs=evidence.get("evidence_refs")
    return _advance(lifecycle,_evidence(
      target,evidence["evidence_kind"],refs,evidence["observed_at"],
      {k:v for k,v in evidence.items() if k not in {"evidence_refs","observed_at"}},
    ))
