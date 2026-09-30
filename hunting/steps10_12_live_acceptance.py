#!/usr/bin/env python3
"""Controlled exact-main live acceptance for remediation Steps 10-12.

This harness exercises the production ingestion, learning/work-selection, Hunter
lifecycle, and SoftwareFactory code against isolated controlled state. It never
writes canonical state, opens a PR, merges code, deploys, or claims market/revenue
value. The GitHub workflow that invokes it separately fails closed unless the
checked-out SHA is the current protected main head.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any

from hunting.autonomous_hunter import load_seed_state as hunter_seed
from hunting.lifecycle import (
    HunterLifecycleError,
    apply_acceptance,
    apply_external_evidence,
    build_acceptance_receipt,
    enqueue_factory_work,
    lifecycle_from_review,
)
from hunting.proposal_review_state import digest as review_digest
from learning.continuous_learning import rebuild_from_sources
from learning.live_observations import load_seed_state as learning_seed
from model_router.feedback_state import load_seed_state as model_seed
from model_router.model_router import hashv
from scheduler.autonomous_scheduler import build_context, load_state, schedule_cycle
from software_factory.software_factory import SoftwareFactory
from value_proof.model_task import digest as outcome_digest, load_contract
from value_proof.outcome_ingestion import ingest_verified_outcome
from value_proof.verifier import load_verifier_contract

ROOT=Path(__file__).resolve().parents[1]
H=lambda c:"sha256:"+c*64

class LiveAcceptanceError(ValueError):
    pass

def req(ok:bool,msg:str)->None:
    if not ok:
        raise LiveAcceptanceError(msg)

def canonical_hash(value:Any)->str:
    return "sha256:"+hashlib.sha256(
        json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()
    ).hexdigest()

def provider_receipt(invocation_id:str,tier:int,model_id:str,group:str)->dict[str,Any]:
    core={
      "schema_version":"1.0.0","invocation_id":invocation_id,
      "request_id":"MRQ-"+invocation_id,"route_id":"MRT-"+invocation_id,
      "tier":tier,"provider_id":"openai","model_id":model_id,"independence_group":group,
      "status":"SUCCESS","started_at":"2026-09-30T14:00:00Z","completed_at":"2026-09-30T14:00:10Z",
      "input_tokens":100,"output_tokens":20,"cost_usd":0.01,"cost_basis":"CONFIGURED_RATE",
      "latency_ms":1000,"input_hash":H("1"),"output_hash":H("2"),
      "authority_granted":False,"evidence_upgraded":False,"downstream_outcome_ids":[],
    }
    return {**core,"receipt_hash":hashv(core)}

def controlled_outcome(task:dict[str,Any],builder:dict[str,Any],verifier:dict[str,Any])->dict[str,Any]:
    source=task["source_candidate"]
    core={
      "schema_version":"1.0.0","outcome_id":"MVOUT-LIVE-ACCEPT-STEP10",
      "task_id":task["task_id"],"project_ids":task["project_ids"],
      "hunter_finding_id":source["finding_id"],
      "hunter_experiment_proposal_id":source["experiment_proposal_id"],
      "repository_full_name":source["repository_full_name"],"revision":source["revision"],
      "evidence_pack_hash":H("3"),"builder_execution_receipt_hash":H("4"),
      "builder_provider_receipt_hash":builder["receipt_hash"],"builder_model_id":builder["model_id"],
      "deterministic_verification_receipt_hash":H("5"),
      "independent_verification_receipt_hash":H("6"),
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
      "provenance_refs":["controlled-live-acceptance:issue-210:step10"],
    }
    return {**core,"outcome_hash":outcome_digest(core)}

def controlled_review()->dict[str,Any]:
    core={
      "review_id":"HREV-LIVE-ACCEPT-STEP12",
      "proposal_id":"HEXP-LIVE-ACCEPT-STEP12",
      "finding_id":"HFD-LIVE-ACCEPT-STEP12",
      "project_ids":["PRJ-000"],
      "repository_full_name":"HypothesisWorks/hypothesis","repository_id":8685799,
      "revision":"a"*40,"tree_sha":"b"*40,
      "rank_score":9,"rank_band":"HIGH",
      "capability_key":"capability-coverage:property-testing",
      "license_spdx_id":"MPL-2.0","license_name":"Mozilla Public License 2.0",
      "license_state":"LICENSE_METADATA_PRESENT_INFORMATIONAL",
      "rights_state":"OPERATOR_ASSUMED",
      "reuse_authorized":False,"implementation_authorized":False,
      "code_execution_performed":False,"downstream_mutation_performed":False,
      "source_execution_id":"WEXEC-LIVE-ACCEPT-STEP12",
      "source_execution_receipt_hash":H("c"),
      "reviewed_at":"2026-09-30T14:01:00Z",
      "evidence_refs":[
        "hunter-proposal:HEXP-LIVE-ACCEPT-STEP12",
        "hunter-finding:HFD-LIVE-ACCEPT-STEP12",
        "github:HypothesisWorks/hypothesis@"+"a"*40,
        "git-tree:"+"b"*40,
        "license-metadata:MPL-2.0",
      ],
    }
    return {**core,"review_hash":review_digest(core)}

def verify_scheduled_paths()->dict[str,Any]:
    feedback=(ROOT/".github/workflows/verified-feedback-bootstrap.yml").read_text()
    daily=(ROOT/".github/workflows/runtime-daily-learning.yml").read_text()
    worker=(ROOT/".github/workflows/runtime-worker.yml").read_text()
    runtime=(ROOT/"runtime/continuous_runtime.py").read_text()
    req('cron: "17 * * * *"' in feedback and "value_proof.outcome_ingestion" in feedback,
        "verified outcome recurring ingestion path missing")
    req('cron: "43 9 * * *"' in daily and "mode: daily" in daily,
        "scheduled daily learning path missing")
    req("--domain learning --output learning/live/learning_observation_state.json" in worker,
        "scheduled daily worker does not restore canonical learning")
    req("rebuild_from_sources(learning_live if learning_live.exists() else None)" in runtime,
        "daily runtime does not consume restored live learning")
    return {
      "verified_feedback_schedule":"17 * * * *",
      "daily_learning_schedule":"43 9 * * *",
      "canonical_learning_restore":True,
      "daily_runtime_consumes_live_learning":True,
      "refs":[
        ".github/workflows/verified-feedback-bootstrap.yml",
        ".github/workflows/runtime-daily-learning.yml",
        ".github/workflows/runtime-worker.yml",
        "runtime/continuous_runtime.py",
      ],
    }

def build_receipt(*,source_sha:str,run_id:str,source_branch:str)->dict[str,Any]:
    req(len(source_sha)==40 and all(c in "0123456789abcdef" for c in source_sha),
        "source_sha must be exact lowercase git SHA")
    req(source_branch=="main","live acceptance must execute from main")

    scheduled=verify_scheduled_paths()
    task=load_contract()
    verifier_contract=load_verifier_contract()
    builder=provider_receipt("MINV-LIVE-ACCEPT-B",2,"gpt-5.6-terra","openai-terra")
    verifier=provider_receipt("MINV-LIVE-ACCEPT-V",3,"gpt-5.6-sol","openai-sol")
    outcome=controlled_outcome(task,builder,verifier)
    cases=json.loads((ROOT/"hunting/CONTROLLED_PROOF_CASES.json").read_text())

    hunter0= hunter_seed()
    model0 = model_seed()
    learning0 = learning_seed()
    hunter1,model1,learning1,first=ingest_verified_outcome(
      task_contract=task,verifier_contract=verifier_contract,outcome=outcome,
      builder_provider_receipt=builder,verifier_provider_receipt=verifier,
      hunter_state=hunter0,model_feedback_state=model0,learning_state=learning0,
      controlled_cases=cases,at="2026-09-30T14:02:00Z",
    )
    hunter2,model2,learning2,second=ingest_verified_outcome(
      task_contract=task,verifier_contract=verifier_contract,outcome=outcome,
      builder_provider_receipt=builder,verifier_provider_receipt=verifier,
      hunter_state=hunter1,model_feedback_state=model1,learning_state=learning1,
      controlled_cases=cases,at="2026-09-30T14:03:00Z",
    )
    req(first["status"]=="INGESTED","controlled verified outcome was not ingested")
    req(second["status"]=="ALREADY_INGESTED","duplicate verified outcome was not idempotent")
    req(
      (hunter2["sequence"],model2["sequence"],learning2["sequence"])==
      (hunter1["sequence"],model1["sequence"],learning1["sequence"]),
      "duplicate ingestion changed logical projection sequence",
    )

    with tempfile.TemporaryDirectory() as td:
        learning_path=Path(td)/"learning_state.json"
        learning_path.write_text(json.dumps(learning1))
        fresh_learning=rebuild_from_sources(learning_path)
    baseline_learning=rebuild_from_sources(None)
    req(baseline_learning["fresh_learning_observation_count"]==0,
        "checked-in baseline received fresh-learning credit")
    req(fresh_learning["fresh_learning_observation_count"]>0,
        "verified outcome did not create fresh-learning evidence")

    baseline_context=build_context(learning_state=baseline_learning)
    fresh_context=build_context(learning_state=fresh_learning)
    baseline_ids={row["uncertainty_id"] for row in baseline_context["uncertainty"]["candidates"]}
    fresh_ids={row["uncertainty_id"] for row in fresh_context["uncertainty"]["candidates"]}
    req("UNC-LEARNING-PRJ-000" in baseline_ids,"baseline missing expected live-learning uncertainty")
    req("UNC-LEARNING-PRJ-000" not in fresh_ids,"fresh verified outcome failed to resolve learning uncertainty")
    _,baseline_cycle=schedule_cycle(load_state(),baseline_context,at="2026-09-30T14:04:00Z")
    _,fresh_cycle=schedule_cycle(load_state(),fresh_context,at="2026-09-30T14:04:00Z")
    req(baseline_cycle["fresh_learning_observation_count"]==0,
        "baseline work-selection cycle received fresh credit")
    req(fresh_cycle["fresh_learning_observation_count"]==fresh_learning["fresh_learning_observation_count"],
        "work-selection cycle did not consume fresh-learning count")
    req(baseline_cycle["uncertainty_snapshot_hash"]!=fresh_cycle["uncertainty_snapshot_hash"],
        "verified outcome did not alter downstream selection context")
    req(baseline_cycle["receipt_hash"]!=fresh_cycle["receipt_hash"],
        "verified outcome did not affect downstream cycle receipt")

    review=controlled_review()
    lifecycle=lifecycle_from_review(review)
    acceptance=build_acceptance_receipt(
      lifecycle,acceptance_id="HACC-LIVE-ACCEPT-STEP12",
      target_repository_id="REPO-008",project_id="PRJ-000",
      verifier_agent_id="AGT-TESTER",accepted_at="2026-09-30T14:05:00Z",
      evidence_refs=["issue:210","controlled-live-acceptance:step12"],controlled_proof=True,
    )
    accepted=apply_acceptance(lifecycle,acceptance)
    with tempfile.TemporaryDirectory() as td:
        factory=SoftwareFactory(Path(td)/"factory.sqlite3")
        try:
            bound,work=enqueue_factory_work(
              factory,accepted,acceptance,base_sha=source_sha,now=1.0
            )
            event_chain_valid=factory.event_chain_valid()
        finally:
            factory.close()
    req(work["state"]=="QUEUED" and work["work_id"].startswith("SFW-HUNTER-"),
        "accepted Hunter finding did not create governed factory work")
    req(event_chain_valid,"factory work event chain invalid")
    req(bound["market_verified"] is False and bound["revenue_verified"] is False,
        "factory enqueue falsely claimed market/revenue verification")
    req(bound["merge_authority_granted"] is False and bound["deployment_authority_granted"] is False,
        "Hunter lifecycle widened merge/deploy authority")
    ci_market_rejected=False
    try:
        apply_external_evidence(bound,{
          "proposal_id":bound["proposal_id"],"target_stage":"MARKET_VERIFIED",
          "evidence_kind":"CI_PASS","verified":True,
          "observed_at":"2026-09-30T14:06:00Z","evidence_refs":["ci:controlled-pass"],
        })
    except HunterLifecycleError:
        ci_market_rejected=True
    req(ci_market_rejected,"CI evidence was allowed to claim market verification")

    core={
      "schema_version":"1.0.0",
      "proof_id":"portfolio-steps10-12-controlled-live-acceptance-v1",
      "status":"PASS","source_sha":source_sha,"source_branch":source_branch,"workflow_run_id":str(run_id),
      "step10":{
        "outcome_id":outcome["outcome_id"],"outcome_hash":outcome["outcome_hash"],
        "first_ingestion_status":first["status"],"second_ingestion_status":second["status"],
        "first_sequences":{
          "hunter":hunter1["sequence"],"model_feedback":model1["sequence"],"learning":learning1["sequence"],
        },
        "second_sequences":{
          "hunter":hunter2["sequence"],"model_feedback":model2["sequence"],"learning":learning2["sequence"],
        },
        "fresh_learning_before":baseline_learning["fresh_learning_observation_count"],
        "fresh_learning_after":fresh_learning["fresh_learning_observation_count"],
        "baseline_uncertainty_present":True,"fresh_uncertainty_present":False,
        "baseline_uncertainty_snapshot_hash":baseline_cycle["uncertainty_snapshot_hash"],
        "fresh_uncertainty_snapshot_hash":fresh_cycle["uncertainty_snapshot_hash"],
        "baseline_cycle_receipt_hash":baseline_cycle["receipt_hash"],
        "fresh_cycle_receipt_hash":fresh_cycle["receipt_hash"],
        "scheduled_paths":scheduled,
      },
      "step11":{
        "baseline_or_seed_fresh_credit":baseline_learning["provenance_freshness"]["BASELINE_OR_SEED"]["fresh_learning_credit"],
        "pinned_upstream_fresh_credit":baseline_learning["provenance_freshness"]["PINNED_UPSTREAM"]["fresh_learning_credit"],
        "verified_outcome_fresh_credit":fresh_learning["provenance_freshness"]["VERIFIED_OUTCOME"]["fresh_learning_credit"],
        "fresh_learning_observation_count":fresh_learning["fresh_learning_observation_count"],
        "baseline_snapshot_hash":fresh_learning["baseline_snapshot_hash"],
      },
      "step12":{
        "proposal_id":bound["proposal_id"],"acceptance_id":acceptance["acceptance_id"],
        "current_stage":bound["current_stage"],"factory_work_id":work["work_id"],
        "factory_state":work["state"],"factory_repository_id":work["repository_id"],
        "factory_event_chain_valid":event_chain_valid,
        "market_verified":bound["market_verified"],"revenue_verified":bound["revenue_verified"],
        "merge_authority_granted":bound["merge_authority_granted"],
        "deployment_authority_granted":bound["deployment_authority_granted"],
        "ci_market_promotion_rejected":ci_market_rejected,
        "factory_provenance_refs":work["provenance_refs"],
      },
      "authority_granted":False,"evidence_upgraded":False,
    }
    return {**core,"receipt_hash":canonical_hash(core)}

def main()->None:
    ap=argparse.ArgumentParser()
    ap.add_argument("--source-sha",required=True)
    ap.add_argument("--run-id",required=True)
    ap.add_argument("--source-branch",required=True)
    ap.add_argument("--output",type=Path,required=True)
    args=ap.parse_args()
    receipt=build_receipt(
      source_sha=args.source_sha,run_id=args.run_id,source_branch=args.source_branch
    )
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(receipt,indent=2,sort_keys=True)+"\n")
    print(json.dumps({
      "status":receipt["status"],"source_sha":receipt["source_sha"],
      "first_ingestion_status":receipt["step10"]["first_ingestion_status"],
      "second_ingestion_status":receipt["step10"]["second_ingestion_status"],
      "hunter_stage":receipt["step12"]["current_stage"],
      "factory_state":receipt["step12"]["factory_state"],
      "market_verified":receipt["step12"]["market_verified"],
      "revenue_verified":receipt["step12"]["revenue_verified"],
      "receipt_hash":receipt["receipt_hash"],
    },sort_keys=True))

if __name__=="__main__":
    main()
