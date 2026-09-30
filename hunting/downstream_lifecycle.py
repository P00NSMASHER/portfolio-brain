#!/usr/bin/env python3
"""Durable bridge from reviewed Hunter findings to governed implementation work.

Review remains OBSERVE-only. An exact active owner approval bound to the review
may advance a finding to ACCEPTED_FOR_WORK, but acceptance itself is not
implementation or value proof. The accepted lifecycle is persisted as a native
Hunter artifact and becomes IMPLEMENTATION work through the existing scheduler
on a later cycle. Candidate and exact-head check evidence may then advance only
the technical stages they actually prove.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from hunting.lifecycle import (
    _hash as lifecycle_hash,
    apply_acceptance,
    apply_governed_implementation_evidence,
    build_acceptance_receipt,
    lifecycle_from_review,
    validate_lifecycle,
)
from hunting.proposal_review_state import validate_state as validate_review_state
from operations.value_loop import build_value_loop_snapshot
from repair.autonomous_repair import find_repair_evidence, request_from_hunter_acceptance
from software_factory.software_factory import policy as factory_policy

ROOT=Path(__file__).resolve().parents[1]
SEED=ROOT/"hunting"/"HUNTER_LIFECYCLE_STATE_SEED.json"
STATE_ID="portfolio-hunter-lifecycle-state"
ARTIFACT_NAME="portfolio-hunter-lifecycle-state"
APPROVAL_CODE="HUNTER_ACCEPT_FOR_WORK"

class HunterDownstreamError(ValueError):
    pass

def req(ok:bool,msg:str)->None:
    if not ok:
        raise HunterDownstreamError(msg)

def load_seed_state()->dict[str,Any]:
    return json.loads(SEED.read_text(encoding="utf-8"))

def acceptance_source_ref(review:dict[str,Any])->str:
    return f"hunter-review:{review['review_id']}:{review['review_hash']}"

def _approval_hash_ok(receipt:dict[str,Any])->bool:
    given=receipt.get("acceptance_hash")
    if not isinstance(given,str):
        return False
    body=dict(receipt);body.pop("acceptance_hash",None)
    return given==lifecycle_hash(body)

def validate_state(state:dict[str,Any])->None:
    req(isinstance(state,dict),"Hunter lifecycle state must be object")
    req(set(state)=={"schema_version","state_id","sequence","updated_at","records"},
        "Hunter lifecycle state fields changed")
    req(state["schema_version"]=="1.0.0" and state["state_id"]==STATE_ID,
        "Hunter lifecycle state identity mismatch")
    req(type(state["sequence"]) is int and state["sequence"]>=0,"Hunter lifecycle sequence invalid")
    req(state["updated_at"] is None or isinstance(state["updated_at"],str),
        "Hunter lifecycle updated_at invalid")
    req(isinstance(state["records"],list) and len(state["records"])<=100,
        "Hunter lifecycle record capacity invalid")
    seen=set()
    for record in state["records"]:
        req(isinstance(record,dict) and set(record)=={
            "proposal_id","review_hash","lifecycle","acceptance_receipt","implementation_evidence"
        },"Hunter lifecycle record fields changed")
        lifecycle=record["lifecycle"]
        validate_lifecycle(lifecycle)
        req(record["proposal_id"]==lifecycle["proposal_id"],"Hunter lifecycle proposal projection mismatch")
        req(record["proposal_id"] not in seen,"duplicate Hunter lifecycle proposal")
        seen.add(record["proposal_id"])
        req(record["review_hash"]==lifecycle["review_hash"],"Hunter lifecycle review hash projection mismatch")
        acceptance=record["acceptance_receipt"]
        implementation=record["implementation_evidence"]
        stage=lifecycle["current_stage"]
        if stage=="REVIEWED":
            req(acceptance is None and implementation is None,
                "review-only Hunter lifecycle created downstream work")
            continue
        req(isinstance(acceptance,dict) and _approval_hash_ok(acceptance),
            "Hunter acceptance receipt invalid")
        req(acceptance["proposal_id"]==lifecycle["proposal_id"] and
            acceptance["review_hash"]==lifecycle["review_hash"],
            "Hunter acceptance lineage mismatch")
        req(isinstance(acceptance.get("external_milestone"),str) and acceptance["external_milestone"],
            "Hunter acceptance external milestone missing")
        req(isinstance(acceptance.get("implementation_target_paths"),list)
            and acceptance["implementation_target_paths"],
            "Hunter acceptance implementation targets missing")
        if stage=="ACCEPTED_FOR_WORK":
            req(implementation is None,"accepted Hunter work cannot claim implementation evidence")
        else:
            req(isinstance(implementation,dict),"implemented Hunter lifecycle evidence missing")
            req(implementation.get("proposal_id")==lifecycle["proposal_id"],
                "implementation evidence proposal projection mismatch")
            req(implementation.get("acceptance_id")==acceptance["acceptance_id"],
                "implementation evidence acceptance projection mismatch")

def _load(path:Path)->dict[str,Any]:
    return json.loads(path.read_text(encoding="utf-8"))

def _target_repository(project_id:str,current_repository:str)->str|None:
    projects=_load(ROOT/"registry"/"projects.json")["projects"]
    matches=[row for row in projects if row["project_id"]==project_id]
    req(len(matches)==1,"Hunter acceptance project missing/duplicate")
    enabled={
      row["repository_id"]:row
      for row in factory_policy()["repository_policies"]
      if row.get("candidate_modify_enabled") is True and row.get("pr_create_enabled") is True
    }
    candidates=[
      binding["repository_id"]
      for binding in matches[0]["repository_bindings"]
      if binding.get("integration_status")=="DECLARED"
      and binding["repository_id"] in enabled
      and enabled[binding["repository_id"]]["repository_full_name"]==current_repository
    ]
    req(len(candidates)<=1,"Hunter acceptance has ambiguous factory target")
    return candidates[0] if candidates else None

def _eligible_approvals(review:dict[str,Any],ledger:dict[str,Any])->list[dict[str,Any]]:
    operator_policy=_load(ROOT/"operator_console"/"OPERATOR_POLICY.json")
    allowed=set(operator_policy.get("allowed_approval_actors") or [])
    source=acceptance_source_ref(review)
    return [
      row for row in ledger["approvals"]
      if row["status"]=="ACTIVE"
      and row["source_ref"]==source
      and row["approval_requirements"]==[APPROVAL_CODE]
      and len(row["project_ids"])==1
      and row["project_ids"][0] in review["project_ids"]
      and row["approved_by"] in allowed
    ]

def _downstream_policy()->dict[str,Any]:
    doc=_load(ROOT/"hunting"/"HUNTER_POLICY.json")
    section=doc.get("downstream_lifecycle")
    req(isinstance(section,dict),"Hunter downstream lifecycle policy missing")
    return section

def _implementation_targets(repository_id:str)->list[str]:
    mapping=_downstream_policy().get("implementation_target_prefixes_by_repository")
    req(isinstance(mapping,dict),"Hunter implementation target policy missing")
    targets=mapping.get(repository_id)
    req(isinstance(targets,list) and targets,"Hunter implementation target scope missing")
    req(len(targets)==len(set(targets)) and all(
        isinstance(path,str) and path and not path.startswith("/") and ".." not in path.split("/")
        for path in targets
    ),"Hunter implementation target scope invalid")
    return list(targets)

def _regression_requirement()->str:
    value=_downstream_policy().get("implementation_regression_requirement")
    req(isinstance(value,str) and value.strip(),"Hunter implementation regression policy missing")
    return value

def _external_milestone(override:str|None=None)->str:
    allowed=set(_load(ROOT/"scheduler"/"SCHEDULER_POLICY.json")["external_milestones"])
    value=override
    if value is None:
        value=build_value_loop_snapshot()["closest_external_milestone"]
    req(isinstance(value,str) and value in allowed,
        "Hunter acceptance has no defensible scheduler external milestone")
    return value

def _implementation_refs(evidence:dict[str,Any])->list[str]:
    refs=evidence.get("evidence_refs")
    if isinstance(refs,list) and refs:
        return list(dict.fromkeys(refs))
    out=[]
    if type(evidence.get("pr_number")) is int:
        out.append(f"repair-pr:{evidence['pr_number']}")
    if isinstance(evidence.get("head_sha"),str):
        out.append(f"commit:{evidence['head_sha']}")
    for row in evidence.get("checks") or []:
        if isinstance(row,dict) and row.get("name"):
            out.append(f"check:{row.get('name')}:{row.get('app_id')}:{row.get('id','unknown')}")
    return list(dict.fromkeys(out))

def _verify_hunter_factory_evidence(record:dict[str,Any], evidence:dict[str,Any])->None:
    """Fail closed unless a repair PR is the exact factory continuation of this acceptance."""
    lifecycle=record["lifecycle"]
    acceptance=record["acceptance_receipt"]
    req(isinstance(acceptance,dict),"Hunter implementation evidence missing acceptance")
    req(evidence.get("source_ref")==acceptance["acceptance_id"],
        "Hunter implementation evidence source ref mismatch")
    head=evidence.get("head_sha")
    candidate=evidence.get("candidate_sha")
    base=evidence.get("base_sha")
    fingerprint=evidence.get("request_fingerprint")
    work_id=evidence.get("factory_work_id")
    head_ref=evidence.get("head_ref")
    req(isinstance(head,str) and len(head)==40 and all(c in "0123456789abcdef" for c in head),
        "Hunter implementation PR head invalid")
    req(candidate==head,"Hunter implementation candidate/head identity mismatch")
    req(isinstance(base,str) and len(base)==40 and all(c in "0123456789abcdef" for c in base),
        "Hunter implementation base SHA missing")
    req(isinstance(fingerprint,str) and fingerprint.startswith("sha256:") and len(fingerprint)==71,
        "Hunter implementation request fingerprint missing")
    req(isinstance(work_id,str) and work_id.startswith("AUTO-REPAIR-"),
        "Hunter implementation factory work identity missing")
    req(isinstance(head_ref,str) and head_ref.startswith("factory/auto-repair-"),
        "Hunter implementation PR did not originate from an isolated factory branch")

    if lifecycle["current_stage"]=="ACCEPTED_FOR_WORK":
        expected=request_from_hunter_acceptance(
          {"work_type":"IMPLEMENTATION","source_ref":acceptance["acceptance_id"]},
          {"records":[record]},
          base_sha=base,
        )
        req(fingerprint==expected["fingerprint"],
            "Hunter implementation request fingerprint mismatch")
        prefix="AUTO-REPAIR-"+fingerprint.split(":",1)[1][:16].upper()+"-"
        req(work_id.startswith(prefix),
            "Hunter implementation factory work/fingerprint mismatch")
        return

    req(lifecycle["current_stage"]=="IMPLEMENTED",
        "Hunter implementation evidence is not valid for current stage")
    prior=record.get("implementation_evidence")
    req(isinstance(prior,dict),"implemented Hunter lifecycle lost prior evidence")
    for key in (
        "pr_number","head_sha","head_ref","factory_work_id",
        "request_fingerprint","base_sha","candidate_sha",
    ):
        req(evidence.get(key)==prior.get(key),
            f"conflicting Hunter implementation evidence: {key}")

def _reconcile_record(
    record:dict[str,Any],
    provider:Callable[[str],dict[str,Any]],
    fallback_observed_at:str,
)->list[str]:
    lifecycle=record["lifecycle"]
    if lifecycle["current_stage"] not in {"ACCEPTED_FOR_WORK","IMPLEMENTED"}:
        return []
    acceptance=record["acceptance_receipt"]
    if not isinstance(acceptance,dict):
        return []
    evidence=provider(acceptance["acceptance_id"])
    if not isinstance(evidence,dict) or evidence.get("status")!="REPAIR_PR_FOUND":
        return []
    _verify_hunter_factory_evidence(record,evidence)
    enriched={
      **evidence,
      "proposal_id":lifecycle["proposal_id"],
      "acceptance_id":acceptance["acceptance_id"],
      "source_ref":acceptance["acceptance_id"],
      "observed_at":evidence.get("observed_at") or fallback_observed_at,
      "evidence_refs":_implementation_refs(evidence),
    }
    advanced=[]
    if lifecycle["current_stage"]=="ACCEPTED_FOR_WORK":
        lifecycle=apply_governed_implementation_evidence(lifecycle,enriched)
        advanced.append("IMPLEMENTED")
    if (
        lifecycle["current_stage"]=="IMPLEMENTED"
        and enriched.get("foundation_success") is True
        and enriched.get("independent_success") is True
    ):
        lifecycle=apply_governed_implementation_evidence(lifecycle,enriched)
        advanced.append("TECHNICALLY_VERIFIED")
    if advanced:
        record["lifecycle"]=lifecycle
        record["implementation_evidence"]=enriched
    return advanced

def apply_reviews_and_acceptances(
    state:dict[str,Any],reviews:dict[str,Any],approvals:dict[str,Any],*,
    base_sha:str,current_repository:str,source_branch:str,
    current_external_milestone:str|None=None,
    implementation_evidence_provider:Callable[[str],dict[str,Any]]|None=None,
    reconcile_implementation:bool=False,
    observed_at:str|None=None,
)->tuple[dict[str,Any],dict[str,Any]]:
    validate_state(state)
    validate_review_state(reviews)
    # Lazy import avoids downstream_lifecycle -> operator_console -> scheduler ->
    # downstream_lifecycle during module initialization while preserving the
    # canonical owner-approval validator at the mutation boundary.
    from operator_console.operator_console import validate_approval_ledger
    validate_approval_ledger(approvals)
    req(isinstance(base_sha,str) and len(base_sha)==40 and
        all(c in "0123456789abcdef" for c in base_sha),"exact base SHA required")
    req(isinstance(current_repository,str) and "/" in current_repository,
        "current repository identity required")
    req(isinstance(source_branch,str) and source_branch,"source branch required")
    out=json.loads(json.dumps(state))
    records={row["proposal_id"]:row for row in out["records"]}
    added_reviews=[];accepted=[];blocked=[];advancements=[]
    review_by_hash={}
    for review in reviews["reviews"]:
        review_by_hash[review["review_hash"]]=review
        prior=records.get(review["proposal_id"])
        if prior is not None:
            req(prior["review_hash"]==review["review_hash"],
                "conflicting Hunter review identity for existing lifecycle")
            continue
        lifecycle=lifecycle_from_review(review)
        record={
          "proposal_id":review["proposal_id"],"review_hash":review["review_hash"],
          "lifecycle":lifecycle,"acceptance_receipt":None,"implementation_evidence":None,
        }
        out["records"].append(record);records[review["proposal_id"]]=record
        out["sequence"]+=1;out["updated_at"]=review["reviewed_at"]
        added_reviews.append(review["review_id"])
    for record in out["records"]:
        lifecycle=record["lifecycle"]
        if lifecycle["current_stage"]!="REVIEWED":
            continue
        review=review_by_hash.get(record["review_hash"])
        req(review is not None,"durable Hunter lifecycle review no longer exists")
        matches=_eligible_approvals(review,approvals)
        req(len(matches)<=1,"multiple active Hunter work acceptances conflict")
        if not matches:
            continue
        approval=matches[0]
        if source_branch!="main":
            blocked.append({"approval_id":approval["approval_id"],"reason":"NON_MAIN_ACCEPTANCE_DISABLED"})
            continue
        project_id=approval["project_ids"][0]
        repository_id=_target_repository(project_id,current_repository)
        if repository_id is None:
            blocked.append({"approval_id":approval["approval_id"],"reason":"NO_CURRENT_REPOSITORY_FACTORY_TARGET"})
            continue
        try:
            milestone=_external_milestone(current_external_milestone)
            targets=_implementation_targets(repository_id)
        except HunterDownstreamError as exc:
            blocked.append({"approval_id":approval["approval_id"],"reason":str(exc)})
            continue
        acceptance_id="HACC-"+hashlib.sha256(
            (approval["approval_id"]+"\0"+review["review_hash"]).encode("utf-8")
        ).hexdigest()[:20].upper()
        acceptance=build_acceptance_receipt(
          lifecycle,acceptance_id=acceptance_id,target_repository_id=repository_id,
          project_id=project_id,verifier_agent_id="AGT-TESTER",
          accepted_at=approval["approved_at"],
          external_milestone=milestone,
          implementation_target_paths=targets,
          regression_requirement=_regression_requirement(),
          evidence_refs=[
            f"owner-approval:{approval['approval_id']}",
            f"owner-approval-reason:{approval['reason_hash']}",
            f"hunter-review-hash:{review['review_hash']}",
            f"accepted-base:{base_sha}",
            f"external-milestone:{milestone}",
          ],controlled_proof=False,
        )
        record["lifecycle"]=apply_acceptance(lifecycle,acceptance)
        record["acceptance_receipt"]=acceptance
        out["sequence"]+=1;out["updated_at"]=approval["approved_at"]
        accepted.append({
          "acceptance_id":acceptance_id,"approval_id":approval["approval_id"],
          "proposal_id":review["proposal_id"],"external_milestone":milestone,
          "scheduler_work_type":"IMPLEMENTATION",
        })
    if reconcile_implementation:
        provider=implementation_evidence_provider or find_repair_evidence
        stamp=observed_at or datetime.now(timezone.utc).isoformat().replace("+00:00","Z")
        for record in out["records"]:
            stages=_reconcile_record(record,provider,stamp)
            for stage in stages:
                out["sequence"]+=1
                out["updated_at"]=record["implementation_evidence"]["observed_at"]
                advancements.append({
                  "proposal_id":record["proposal_id"],
                  "acceptance_id":record["acceptance_receipt"]["acceptance_id"],
                  "stage":stage,
                  "factory_work_id":record["lifecycle"]["factory_work_id"],
                })
    validate_state(out)
    report={
      "schema_version":"1.0.0",
      "status":"UPDATED" if added_reviews or accepted or advancements else "NO_CHANGE",
      "added_review_ids":added_reviews,
      "accepted_work":accepted,
      "implementation_advancements":advancements,
      "blocked_acceptances":blocked,
      "record_count":len(out["records"]),
      "sequence":out["sequence"],
      "market_verified":any(r["lifecycle"]["market_verified"] for r in out["records"]),
      "revenue_verified":any(r["lifecycle"]["revenue_verified"] for r in out["records"]),
      "merge_authority_granted":False,
      "deployment_authority_granted":False,
      "new_state_journal_domain_created":False,
    }
    return out,report

def main()->None:
    ap=argparse.ArgumentParser()
    ap.add_argument("--state",type=Path,required=True)
    ap.add_argument("--reviews",type=Path,required=True)
    ap.add_argument("--approvals",type=Path,default=ROOT/"operator_console"/"OWNER_APPROVALS.json")
    ap.add_argument("--base-sha",required=True)
    ap.add_argument("--current-repository",required=True)
    ap.add_argument("--source-branch",required=True)
    ap.add_argument("--output-state",type=Path,required=True)
    ap.add_argument("--report",type=Path,required=True)
    ap.add_argument("--reconcile-implementation",action="store_true")
    args=ap.parse_args()
    state=_load(args.state) if args.state.exists() else load_seed_state()
    updated,report=apply_reviews_and_acceptances(
      state,_load(args.reviews),_load(args.approvals),
      base_sha=args.base_sha,current_repository=args.current_repository,
      source_branch=args.source_branch,
      reconcile_implementation=args.reconcile_implementation,
    )
    args.output_state.parent.mkdir(parents=True,exist_ok=True)
    args.output_state.write_text(json.dumps(updated,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps(report,sort_keys=True))

if __name__=="__main__":
    main()
