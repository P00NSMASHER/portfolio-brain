#!/usr/bin/env python3
"""Durable bridge from reviewed Hunter findings to explicitly accepted factory work.

Review remains OBSERVE-only. Only an exact active owner approval bound to the review
hash may advance a finding to ACCEPTED_FOR_WORK, and only the existing SoftwareFactory
may create the downstream work item. This artifact is lifecycle continuity, not a new
state-journal domain.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from hunting.lifecycle import (
    _hash as lifecycle_hash,
    apply_acceptance,
    build_acceptance_receipt,
    enqueue_factory_work,
    lifecycle_from_review,
    validate_lifecycle,
)
from hunting.proposal_review_state import validate_state as validate_review_state
from operator_console.operator_console import validate_approval_ledger
from software_factory.software_factory import SoftwareFactory, policy as factory_policy

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

def _validate_factory_snapshot(work:dict[str,Any],lifecycle:dict[str,Any],acceptance:dict[str,Any])->None:
    req(isinstance(work,dict),"factory work snapshot missing")
    req(work.get("work_id")==lifecycle.get("factory_work_id"),"factory work identity mismatch")
    req(work.get("project_id")==acceptance["project_id"],"factory project mismatch")
    req(work.get("repository_id")==acceptance["target_repository_id"],"factory repository mismatch")
    req(work.get("builder_agent_id")=="AGT-ENGINEER","factory builder identity drifted")
    req(work.get("verifier_agent_id")==acceptance["verifier_agent_id"],"factory verifier mismatch")
    req(work.get("state")=="QUEUED","accepted Hunter factory work must remain QUEUED")
    refs=work.get("provenance_refs")
    req(isinstance(refs,list) and f"hunter-acceptance:{acceptance['acceptance_id']}" in refs,
        "factory work lost acceptance provenance")
    req(f"hunter-acceptance-hash:{acceptance['acceptance_hash']}" in refs,
        "factory work lost acceptance hash provenance")

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
            "proposal_id","review_hash","lifecycle","acceptance_receipt",
            "factory_work","factory_event_chain_valid"
        },"Hunter lifecycle record fields changed")
        lifecycle=record["lifecycle"]
        validate_lifecycle(lifecycle)
        req(record["proposal_id"]==lifecycle["proposal_id"],"Hunter lifecycle proposal projection mismatch")
        req(record["proposal_id"] not in seen,"duplicate Hunter lifecycle proposal")
        seen.add(record["proposal_id"])
        req(record["review_hash"]==lifecycle["review_hash"],"Hunter lifecycle review hash projection mismatch")
        acceptance=record["acceptance_receipt"]
        work=record["factory_work"]
        if lifecycle["current_stage"]=="REVIEWED":
            req(acceptance is None and work is None and record["factory_event_chain_valid"] is False,
                "review-only Hunter lifecycle created downstream work")
        else:
            req(isinstance(acceptance,dict) and _approval_hash_ok(acceptance),
                "Hunter acceptance receipt invalid")
            req(acceptance["proposal_id"]==lifecycle["proposal_id"] and
                acceptance["review_hash"]==lifecycle["review_hash"],
                "Hunter acceptance lineage mismatch")
            req(lifecycle["current_stage"]=="ACCEPTED_FOR_WORK",
                "durable acceptance bridge may persist only ACCEPTED_FOR_WORK")
            _validate_factory_snapshot(work,lifecycle,acceptance)
            req(record["factory_event_chain_valid"] is True,"factory event chain proof missing")

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

def apply_reviews_and_acceptances(
    state:dict[str,Any],reviews:dict[str,Any],approvals:dict[str,Any],*,
    base_sha:str,current_repository:str,source_branch:str,
)->tuple[dict[str,Any],dict[str,Any]]:
    validate_state(state)
    validate_review_state(reviews)
    validate_approval_ledger(approvals)
    req(isinstance(base_sha,str) and len(base_sha)==40 and
        all(c in "0123456789abcdef" for c in base_sha),"exact base SHA required")
    req(isinstance(current_repository,str) and "/" in current_repository,
        "current repository identity required")
    req(isinstance(source_branch,str) and source_branch,"source branch required")
    out=json.loads(json.dumps(state))
    records={row["proposal_id"]:row for row in out["records"]}
    added_reviews=[];accepted=[];blocked=[]
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
          "lifecycle":lifecycle,"acceptance_receipt":None,"factory_work":None,
          "factory_event_chain_valid":False,
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
        acceptance_id="HACC-"+hashlib.sha256(
            (approval["approval_id"]+"\0"+review["review_hash"]).encode("utf-8")
        ).hexdigest()[:20].upper()
        acceptance=build_acceptance_receipt(
          lifecycle,acceptance_id=acceptance_id,target_repository_id=repository_id,
          project_id=project_id,verifier_agent_id="AGT-TESTER",
          accepted_at=approval["approved_at"],
          evidence_refs=[
            f"owner-approval:{approval['approval_id']}",
            f"owner-approval-reason:{approval['reason_hash']}",
            f"hunter-review-hash:{review['review_hash']}",
          ],controlled_proof=False,
        )
        bound=apply_acceptance(lifecycle,acceptance)
        timestamp=datetime.fromisoformat(approval["approved_at"].replace("Z","+00:00")).timestamp()
        with tempfile.TemporaryDirectory() as td:
            factory=SoftwareFactory(Path(td)/"factory.sqlite3")
            try:
                bound,work=enqueue_factory_work(
                    factory,bound,acceptance,base_sha=base_sha,now=timestamp
                )
                chain_ok=factory.event_chain_valid()
            finally:
                factory.close()
        req(chain_ok,"Hunter factory queue event chain invalid")
        record["lifecycle"]=bound
        record["acceptance_receipt"]=acceptance
        record["factory_work"]=work
        record["factory_event_chain_valid"]=True
        out["sequence"]+=1;out["updated_at"]=approval["approved_at"]
        accepted.append({
          "acceptance_id":acceptance_id,"approval_id":approval["approval_id"],
          "proposal_id":review["proposal_id"],"factory_work_id":work["work_id"],
        })
    validate_state(out)
    report={
      "schema_version":"1.0.0",
      "status":"UPDATED" if added_reviews or accepted else "NO_CHANGE",
      "added_review_ids":added_reviews,
      "accepted_work":accepted,
      "blocked_acceptances":blocked,
      "record_count":len(out["records"]),
      "sequence":out["sequence"],
      "market_verified":False,
      "revenue_verified":False,
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
    args=ap.parse_args()
    state=_load(args.state) if args.state.exists() else load_seed_state()
    updated,report=apply_reviews_and_acceptances(
      state,_load(args.reviews),_load(args.approvals),
      base_sha=args.base_sha,current_repository=args.current_repository,
      source_branch=args.source_branch,
    )
    args.output_state.parent.mkdir(parents=True,exist_ok=True)
    args.output_state.write_text(json.dumps(updated,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps(report,sort_keys=True))

if __name__=="__main__":
    main()
