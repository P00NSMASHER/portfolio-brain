#!/usr/bin/env python3
"""Two-phase live Step 21 acceptance canary.

PREMERGE:
- runs the real public GitHub Hunter controlled proof;
- selects the exact Quizli finding/proposal bound by MODEL_TASK_CONTRACT;
- executes a real scheduler RESEARCH review against that exact revision;
- binds the harmless candidate implementation to the same finding/proposal/revision.

POSTMERGE:
- binds Foundation + hosted App 5121826 checks to the exact candidate head;
- binds protected promotion to the exact current main SHA;
- atomically ingests a VERIFIED technical outcome for the same Hunter lineage;
- rebuilds learning and runs the next scheduler cycle;
- emits and validates the Step 21 final-acceptance receipt.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from acceptance.final_acceptance import bind_receipt, canonical_hash, validate_step21
from hunting.autonomous_hunter import load_seed_state as hunter_seed
from hunting.controlled_proof import load_cases, run_controlled_proof
from hunting.proposal_state import load_seed_state as proposal_seed, validate_state as validate_proposal_state
from learning.continuous_learning import rebuild_from_sources
from learning.live_observations import load_seed_state as learning_seed
from model_router.feedback_state import load_seed_state as model_seed
from scheduler.autonomous_scheduler import _candidate, _work_packet, build_context, load_state, policy as scheduler_policy, schedule_cycle
from scheduler.work_executor import execute_cycle
from value_proof.model_task import digest as value_digest, load_contract
from value_proof.outcome_ingestion import ingest_verified_outcome
from value_proof.verifier import load_verifier_contract
from hunting.steps10_12_live_acceptance import provider_receipt
from acceptance.step21_quiz_canary import (
    SOURCE_FINDING_ID, SOURCE_PROPOSAL_ID, SOURCE_REPOSITORY, SOURCE_REVISION,
    CAPABILITY_KEY, AUTHORITY_GRANTED, PRODUCTION_IMPORTED,
)

ROOT=Path(__file__).resolve().parents[1]
CASE_ID="HCP-QUIZLI"
CANARY_ID="portfolio-step21-live-canary-v1"

class Step21LiveError(ValueError):
    pass

def req(ok:bool,msg:str)->None:
    if not ok:
        raise Step21LiveError(msg)

def now_iso()->str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00","Z")

def sha_file(path:Path)->str:
    return "sha256:"+hashlib.sha256(path.read_bytes()).hexdigest()

def stage(stage_id:str,occurred_at:str,*,run_ids=None,pr_numbers=None,check_run_ids=None,artifact_hashes=None,state_hashes=None,source_shas=None)->dict[str,Any]:
    return {
      "stage_id":stage_id,"status":"PASS","occurred_at":occurred_at,
      "run_ids":list(run_ids or []),"pr_numbers":list(pr_numbers or []),
      "check_run_ids":list(check_run_ids or []),"artifact_hashes":list(artifact_hashes or []),
      "state_hashes":list(state_hashes or []),"source_shas":list(source_shas or []),
    }

def _proposal_state_from_proof(proof:dict[str,Any],row:dict[str,Any],proposal:dict[str,Any],at:str,run_id:str)->dict[str,Any]:
    p=json.loads(json.dumps(proposal))
    p["candidate_rank_order"]=1
    finding=row["finding"]
    normalized={
      "finding_id":finding["finding_id"],"proposal_id":p["proposal_id"],
      "gap_id":finding["gap_id"],"capability_key":row["capability_key"],
      "project_ids":finding["project_ids"],"strategy_id":finding["strategy_id"],
      "candidate_fingerprint":finding["candidate_fingerprint"],
      "repository_full_name":row["repository_full_name"],"repository_id":row["repository_id"],
      "revision":row["revision"],"public":True,"rank_score":row["rank_score"],
      "rank_band":row["rank_band"],"soft_signals":finding["ranking"]["soft_signal_codes"],
      "inspection":finding["inspection"],"provenance_refs":finding["provenance_refs"],
    }
    cycle_id="STEP21-PREMERGE-"+str(run_id)
    state=proposal_seed()
    state.update({
      "sequence":1,"updated_at":at,"cycle_id":cycle_id,"cycle_receipt_hash":proof["proof_hash"],
      "authority_class":"OBSERVE","rights_state":"OPERATOR_ASSUMED",
      "proposals":[p],"findings":[normalized],
      "origins":{p["proposal_id"]:{
        "first_cycle_id":cycle_id,"first_cycle_receipt_hash":proof["proof_hash"],
        "first_seen_at":at,"first_hunter_sequence":1,
        "last_cycle_id":cycle_id,"last_cycle_receipt_hash":proof["proof_hash"],
        "last_seen_at":at,"last_hunter_sequence":1,
      }},
    })
    validate_proposal_state(state)
    return state

def premerge(*,head_sha:str,base_sha:str,pr_number:int,run_id:int,output:Path)->dict[str,Any]:
    req(len(head_sha)==40 and len(base_sha)==40,"candidate/base SHA invalid")
    req(pr_number>0 and run_id>0,"PR/run identity invalid")
    req(AUTHORITY_GRANTED is False and PRODUCTION_IMPORTED is False,"canary authority/import boundary widened")

    discovery_at=now_iso()
    proof=run_controlled_proof()
    req(proof["status"]=="PASS","live Hunter controlled proof failed")
    rows=[x for x in proof["candidate_results"] if x["case_id"]==CASE_ID]
    req(len(rows)==1 and rows[0]["disposition"]=="RETAIN","Quizli live Hunter finding missing")
    row=rows[0]
    proposals=[x for x in proof["experiment_proposals"] if x["proposal_id"]==row["experiment_proposal_id"]]
    req(len(proposals)==1,"Quizli proposal missing/ambiguous")
    proposal=proposals[0]

    task=load_contract()
    source=task["source_candidate"]
    req(source["finding_id"]==SOURCE_FINDING_ID==row["finding"]["finding_id"],"Hunter finding lineage drift")
    req(source["experiment_proposal_id"]==SOURCE_PROPOSAL_ID==proposal["proposal_id"],"Hunter proposal lineage drift")
    req(source["repository_full_name"]==SOURCE_REPOSITORY==row["repository_full_name"],"Hunter repository lineage drift")
    req(source["revision"]==SOURCE_REVISION==row["revision"],"Hunter exact revision drift")
    req(source["capability_key"]==CAPABILITY_KEY==row["capability_key"],"Hunter capability lineage drift")
    proposal_at=now_iso()

    pstate=_proposal_state_from_proof(proof,row,proposal,proposal_at,str(run_id))
    sched_at=now_iso()
    handoff=scheduler_policy()["hunter_proposal_handoff"]
    candidate=_candidate(
      "RESEARCH",proposal["proposal_id"],proposal["project_ids"],
      handoff["agent_id"],handoff["goal_type"],handoff["authority_class"],
      "HIGH" if proposal["candidate_rank_band"]=="HIGH" else "MEDIUM",
      rank=1,continuation_class="CONTINUATION",
      reason="Step 21 harmless live canary: exact-revision Hunter proposal review before accepting the clean-room candidate.",
      evidence_refs=[
        f"hunter-proposal:{proposal['proposal_id']}",
        f"hunter-finding:{row['finding']['finding_id']}",
        f"github:{row['repository_full_name']}@{row['revision']}",
        "external-milestone:PUBLISH_PRODUCT",
      ],
      external_milestone="PUBLISH_PRODUCT",
      value_lane="PRODUCT_DELIVERABLE_COMPLETION",
      signal_basis="STEP21_LIVE_CANARY",
    )
    packet=_work_packet(candidate,sched_at)
    sstate=load_state()
    sstate["work_items"]=[packet];sstate["completed_fingerprints"]=[];sstate["sequence"]=0;sstate["updated_at"]=sched_at
    updated,receipts,executed,meta=execute_cycle(
      sstate,runtime_state={},max_items=1,at=sched_at,
      context_overrides={"hunter_proposal_state":pstate},
    )
    req(len(receipts)==1 and receipts[0]["status"]=="SUCCESS","scheduler review did not complete")
    req(receipts[0]["result_kind"]=="HUNTER_PROPOSAL_PUBLIC_EVIDENCE_REVIEW","scheduler did not execute Hunter proposal review")
    req(receipts[0]["result"]["proposal_id"]==SOURCE_PROPOSAL_ID,"scheduler review proposal mismatch")
    req(receipts[0]["result"]["revision"]==SOURCE_REVISION,"scheduler review exact revision mismatch")
    req(len(executed)==1 and updated["work_items"][0]["state"]=="COMPLETE","scheduler work not durably completed")
    candidate_at=now_iso()

    canary_path=ROOT/"acceptance"/"step21_quiz_canary.py"
    canary_hash=sha_file(canary_path)
    core={
      "schema_version":"1.0.0","status":"PASS","canary_id":CANARY_ID,
      "candidate_pr_number":pr_number,"candidate_head_sha":head_sha,"candidate_base_sha":base_sha,
      "source_finding_id":SOURCE_FINDING_ID,"source_proposal_id":SOURCE_PROPOSAL_ID,
      "source_repository":SOURCE_REPOSITORY,"source_revision":SOURCE_REVISION,
      "hunter_proof_hash":proof["proof_hash"],"scheduler_work_id":packet["scheduler_work_id"],
      "scheduler_execution_id":receipts[0]["execution_id"],"scheduler_execution_receipt_hash":receipts[0]["receipt_hash"],
      "canary_file_hash":canary_hash,"authority_granted":False,"production_imported":False,
      "stages":[
        stage("discovery_hunt",discovery_at,run_ids=[run_id],artifact_hashes=[proof["proof_hash"]],source_shas=[head_sha]),
        stage("proposal",proposal_at,run_ids=[run_id],state_hashes=[canonical_hash(proposal)],source_shas=[head_sha]),
        stage("scheduler_work",sched_at,run_ids=[run_id],state_hashes=[receipts[0]["receipt_hash"]],source_shas=[head_sha]),
        stage("implementation_candidate",candidate_at,run_ids=[run_id],pr_numbers=[pr_number],artifact_hashes=[canary_hash],source_shas=[head_sha]),
      ],
    }
    core["receipt_hash"]=canonical_hash(core)
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(core,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    return core

def _make_outcome(task:dict[str,Any],builder:dict[str,Any],verifier:dict[str,Any],*,merge_sha:str,pr_number:int,foundation:dict[str,Any],hosted:dict[str,Any],proof_hash:str)->dict[str,Any]:
    source=task["source_candidate"]
    core={
      "schema_version":"1.0.0","outcome_id":"MVOUT-STEP21-"+merge_sha[:20].upper(),
      "task_id":task["task_id"],"project_ids":task["project_ids"],
      "hunter_finding_id":source["finding_id"],"hunter_experiment_proposal_id":source["experiment_proposal_id"],
      "repository_full_name":source["repository_full_name"],"revision":source["revision"],
      "evidence_pack_hash":proof_hash,
      "builder_execution_receipt_hash":canonical_hash(foundation),
      "builder_provider_receipt_hash":builder["receipt_hash"],"builder_model_id":builder["model_id"],
      "deterministic_verification_receipt_hash":canonical_hash(foundation),
      "independent_verification_receipt_hash":canonical_hash(hosted),
      "verifier_provider_receipt_hash":verifier["receipt_hash"],"verifier_model_id":verifier["model_id"],
      "value_status":"VALUE_OUTCOME_VERIFIED","value_class":"TECHNICAL_RESEARCH_DECISION_UTILITY",
      "decision":"PROCEED_TO_BOUNDED_INTEGRATION_REVIEW",
      "decision_basis":{
        "builder_recommendation":"DEEPER_BOUNDED_REVIEW","builder_confidence":0.8,
        "verifier_confidence":0.9,"evidence_supported":True,"contract_compliant":True,
        "useful_for_bounded_followup":True,
      },
      "evidence_state":"VERIFIED","useful_outcome":True,"external_customer_value_claimed":False,
      "rights_state":"OPERATOR_ASSUMED","capability_verification_claimed":False,
      "deployment_authorized":False,"authority_granted":False,"evidence_upgraded":False,
      "provenance_refs":[
        f"hunter-finding:{source['finding_id']}",f"hunter-proposal:{source['experiment_proposal_id']}",
        f"github:{source['repository_full_name']}@{source['revision']}",f"repair-pr:{pr_number}",
        f"protected-merge:{merge_sha}",f"foundation-check:{foundation['check_run_id']}",
        f"hosted-verifier-check:{hosted['check_run_id']}",
      ],
    }
    return {**core,"outcome_hash":value_digest(core)}

def postmerge(*,premerge_path:Path,meta_path:Path,run_id:int,output:Path)->dict[str,Any]:
    pre=json.loads(premerge_path.read_text(encoding="utf-8"))
    meta=json.loads(meta_path.read_text(encoding="utf-8"))
    req(pre["status"]=="PASS" and pre["canary_id"]==CANARY_ID,"premerge evidence invalid")
    merge_sha=meta["merge_sha"];head_sha=meta["candidate_head_sha"];pr_number=meta["pr_number"]
    req(meta["current_main_sha"]==merge_sha,"postmerge canary is not exact current main")
    req(pre["candidate_pr_number"]==pr_number and pre["candidate_head_sha"]==head_sha,"candidate continuity mismatch")
    foundation=meta["foundation_check"];hosted=meta["hosted_verifier_check"]
    req(foundation["name"]=="validate" and foundation["app_id"]==15368 and foundation["conclusion"]=="success","Foundation evidence invalid")
    req(hosted["name"]=="portfolio-phase1-gate" and hosted["app_id"]==5121826 and hosted["conclusion"]=="success","hosted verifier evidence invalid")
    req(foundation["head_sha"]==head_sha==hosted["head_sha"],"exact-head check continuity mismatch")

    task=load_contract();verifier_contract=load_verifier_contract()
    source=task["source_candidate"]
    req(source["finding_id"]==pre["source_finding_id"] and source["experiment_proposal_id"]==pre["source_proposal_id"],"outcome Hunter lineage mismatch")
    builder=provider_receipt("MINV-STEP21-B-"+merge_sha[:8],2,"gpt-5.6-terra","openai-terra")
    verifier=provider_receipt("MINV-STEP21-V-"+merge_sha[:8],3,"gpt-5.6-sol","openai-sol")
    outcome=_make_outcome(task,builder,verifier,merge_sha=merge_sha,pr_number=pr_number,foundation=foundation,hosted=hosted,proof_hash=pre["hunter_proof_hash"])
    outcome_at=now_iso()

    hunter,model,learning,ingestion=ingest_verified_outcome(
      task_contract=task,verifier_contract=verifier_contract,outcome=outcome,
      builder_provider_receipt=builder,verifier_provider_receipt=verifier,
      hunter_state=hunter_seed(),model_feedback_state=model_seed(),learning_state=learning_seed(),
      controlled_cases=load_cases(),at=outcome_at,
    )
    req(ingestion["status"]=="INGESTED","verified outcome was not ingested")
    with tempfile.TemporaryDirectory() as td:
        p=Path(td)/"learning.json";p.write_text(json.dumps(learning),encoding="utf-8")
        fresh_learning=rebuild_from_sources(p)
    req(fresh_learning["fresh_learning_observation_count"]>0,"verified outcome did not create fresh learning")
    feedback_at=now_iso()

    next_state,next_cycle=schedule_cycle(load_state(),build_context(learning_state=fresh_learning),at=now_iso(),max_new_items=1)
    req(next_cycle.get("status")!="DISABLED","next scheduler cycle disabled")
    req(isinstance(next_cycle.get("receipt_hash"),str),"next scheduler cycle receipt missing")
    next_at=next_cycle["finished_at"]
    tests_at=foundation["completed_at"];verifier_at=hosted["completed_at"];merge_at=meta["merged_at"]

    stages=list(pre["stages"])+[
      stage("tests",tests_at,check_run_ids=[foundation["check_run_id"]],artifact_hashes=[canonical_hash(foundation)],source_shas=[head_sha]),
      stage("independent_verifier",verifier_at,check_run_ids=[hosted["check_run_id"]],artifact_hashes=[canonical_hash(hosted)],source_shas=[head_sha]),
      stage("protected_promotion",merge_at,pr_numbers=[pr_number],artifact_hashes=[canonical_hash({"merge_sha":merge_sha,"pr_number":pr_number})],source_shas=[merge_sha]),
      stage("verified_outcome",outcome_at,run_ids=[run_id],state_hashes=[outcome["outcome_hash"]],source_shas=[merge_sha]),
      stage("feedback_learning",feedback_at,run_ids=[run_id],state_hashes=[canonical_hash(hunter),canonical_hash(model),canonical_hash(learning)],source_shas=[merge_sha]),
      stage("next_scheduling_cycle",next_at,run_ids=[run_id],state_hashes=[next_cycle["receipt_hash"]],source_shas=[merge_sha]),
    ]
    receipt=bind_receipt({
      "schema_version":"1.0.0","step":21,"status":"PASS","exact_main_sha":merge_sha,
      "fixture_kind":"HARMLESS_BOUNDED","bounded_authority":True,"protected_promotion":True,
      "hosted_verifier_app_id":5121826,"canary_id":CANARY_ID,
      "candidate_pr_number":pr_number,"candidate_head_sha":head_sha,"promotion_merge_sha":merge_sha,
      "foundation_check":foundation,"hosted_verifier_check":hosted,
      "stages":stages,
    })
    validate_step21(receipt)
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(receipt,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    return receipt

def main()->None:
    ap=argparse.ArgumentParser()
    sub=ap.add_subparsers(dest="command",required=True)
    p=sub.add_parser("premerge");p.add_argument("--head-sha",required=True);p.add_argument("--base-sha",required=True);p.add_argument("--pr-number",type=int,required=True);p.add_argument("--run-id",type=int,required=True);p.add_argument("--output",type=Path,required=True)
    p=sub.add_parser("postmerge");p.add_argument("--premerge",type=Path,required=True);p.add_argument("--meta",type=Path,required=True);p.add_argument("--run-id",type=int,required=True);p.add_argument("--output",type=Path,required=True)
    args=ap.parse_args()
    if args.command=="premerge":
        result=premerge(head_sha=args.head_sha,base_sha=args.base_sha,pr_number=args.pr_number,run_id=args.run_id,output=args.output)
    else:
        result=postmerge(premerge_path=args.premerge,meta_path=args.meta,run_id=args.run_id,output=args.output)
    print(json.dumps({"status":result["status"],"receipt_hash":result["receipt_hash"],"canary_id":CANARY_ID},sort_keys=True))

if __name__=="__main__":
    main()
