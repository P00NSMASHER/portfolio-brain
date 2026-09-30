#!/usr/bin/env python3
"""Controlled exact-main live acceptance for remediation Steps 10-12.

This harness exercises the production ingestion, learning/work-selection, Hunter
lifecycle, and SoftwareFactory code against isolated controlled state. It never
writes canonical state, merges code, deploys, or claims market/revenue value.
When explicitly run with --dispatch-live from exact protected main, it dispatches
one isolated Hunter acceptance into the governed repair/factory workflow; that
downstream lane still has no merge or deployment authority. The invoking workflow
fails closed unless the checked-out SHA is the current protected main head.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any

from hunting.autonomous_hunter import load_seed_state as hunter_seed
from hunting.downstream_lifecycle import (
    APPROVAL_CODE,
    acceptance_source_ref,
    apply_reviews_and_acceptances,
    load_seed_state as hunter_lifecycle_seed,
)
from hunting.lifecycle import HunterLifecycleError, apply_external_evidence
from hunting.proposal_review_state import digest as review_digest
from learning.continuous_learning import rebuild_from_sources
from learning.live_observations import load_seed_state as learning_seed
from model_router.feedback_state import load_seed_state as model_seed
from model_router.model_router import hashv
from scheduler.autonomous_scheduler import (
    build_context,
    load_state,
    policy as scheduler_policy,
    schedule_cycle,
)
from scheduler.work_executor import execute_cycle
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

def controlled_review_state(review:dict[str,Any])->dict[str,Any]:
    return {
      "schema_version":"1.0.0",
      "state_id":"portfolio-hunter-proposal-review-state",
      "sequence":1,
      "updated_at":review["reviewed_at"],
      "applied_execution_ids":[review["source_execution_id"]],
      "reviews":[review],
    }

def controlled_approval_ledger(review:dict[str,Any])->dict[str,Any]:
    return {
      "schema_version":"1.0.0",
      "ledger_id":"portfolio-owner-approvals",
      "approvals":[{
        "approval_id":"OAPR-LIVE-ACCEPT-STEP12",
        "source_ref":acceptance_source_ref(review),
        "project_ids":["PRJ-000"],
        "approval_requirements":[APPROVAL_CODE],
        "approved_by":"P00NSMASHER",
        "approved_at":"2026-09-30T14:05:00Z",
        "status":"ACTIVE",
        "reason_hash":H("d"),
      }],
    }

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

def build_receipt(*,source_sha:str,run_id:str,source_branch:str,dispatch_live:bool=False)->dict[str,Any]:
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
    lifecycle_state,lifecycle_report=apply_reviews_and_acceptances(
      hunter_lifecycle_seed(),
      controlled_review_state(review),
      controlled_approval_ledger(review),
      base_sha=source_sha,
      current_repository="P00NSMASHER/portfolio-brain",
      source_branch="main",
      current_external_milestone=scheduler_policy()["external_milestones"][0],
    )
    req(len(lifecycle_report["accepted_work"])==1,
        "controlled Hunter finding was not explicitly accepted for downstream work")
    record=lifecycle_state["records"][0]
    bound=record["lifecycle"]
    acceptance=record["acceptance_receipt"]
    req(bound["current_stage"]=="ACCEPTED_FOR_WORK" and isinstance(acceptance,dict),
        "Hunter lifecycle did not stop at ACCEPTED_FOR_WORK before implementation")

    hunter_context=build_context(
      learning_state=fresh_learning,
      hunter_lifecycle_state=lifecycle_state,
    )
    scheduled_hunter_state,hunter_schedule=schedule_cycle(
      load_state(),hunter_context,at="2026-09-30T14:05:30Z",
      candidate_filter=lambda row: (
        row["work_type"]=="IMPLEMENTATION"
        and row["source_ref"]==acceptance["acceptance_id"]
      ),
      max_new_items=1,
    )
    req(len(hunter_schedule["selected_work"])==1,
        "accepted Hunter finding did not create one scheduler IMPLEMENTATION item")
    implementation_work=hunter_schedule["selected_work"][0]
    req(
      implementation_work["required_authority"]=="MODIFY"
      and implementation_work["source_ref"]==acceptance["acceptance_id"],
      "Hunter implementation work lost acceptance authority/provenance",
    )

    def controlled_dispatch(request:dict[str,Any])->dict[str,Any]:
        return {
          "request_id":request["request_id"],
          "fingerprint":request["fingerprint"],
          "dispatch_status":"ACCEPTED",
          "authority_granted":False,
        }

    execution_context={
      "hunter_lifecycle_state":lifecycle_state,
      "main_sha":source_sha,
    }
    if not dispatch_live:
        execution_context["repair_dispatcher"]=controlled_dispatch

    executed_state,execution_receipts,executed_work,execution_meta=execute_cycle(
      scheduled_hunter_state,
      runtime_state={},
      max_items=1,
      at="2026-09-30T14:05:45Z",
      context_overrides=execution_context,
    )
    dispatched_requests=execution_meta["context"].get("hunter_implementation_dispatch_requests") or []
    accepted_dispatches=execution_meta["context"].get("hunter_implementation_dispatch_receipts") or []
    req(len(execution_receipts)==1 and execution_receipts[0]["status"]=="SUCCESS",
        "Hunter implementation scheduler work did not dispatch successfully")
    dispatch_receipt=execution_receipts[0]
    req(dispatch_receipt["result_kind"]=="HUNTER_IMPLEMENTATION_DISPATCHED",
        "Hunter work did not traverse the governed implementation handler")
    req(len(dispatched_requests)==1 and dispatched_requests[0]["source_kind"]=="HUNTER_ACCEPTED_WORK",
        "Hunter acceptance did not become governed factory-bound work")
    req(len(accepted_dispatches)==1 and accepted_dispatches[0]["dispatch_status"]=="ACCEPTED",
        "Hunter implementation did not retain one accepted downstream dispatch receipt")
    req(accepted_dispatches[0]["request_id"]==dispatched_requests[0]["request_id"]
        and accepted_dispatches[0]["fingerprint"]==dispatched_requests[0]["fingerprint"],
        "Hunter downstream dispatch receipt lost exact request identity")
    req(accepted_dispatches[0]["authority_granted"] is False,
        "Hunter downstream dispatch widened authority")
    if dispatch_live:
        req(accepted_dispatches[0].get("workflow_file")=="portfolio-autonomous-repair.yml",
            "live Hunter work did not dispatch the governed repair workflow")
    req(dispatched_requests[0]["base_sha"]==source_sha,
        "Hunter factory-bound work lost exact-main identity")
    req(dispatch_receipt["result"]["implementation_complete"] is False,
        "dispatch alone falsely claimed implementation completion")
    completed=[row for row in executed_state["work_items"] if row["scheduler_work_id"]==implementation_work["scheduler_work_id"]]
    req(len(completed)==1 and completed[0]["state"]=="COMPLETE",
        "scheduler did not durably complete only the dispatch work item")
    req(bound["market_verified"] is False and bound["revenue_verified"] is False,
        "Hunter implementation dispatch falsely claimed market/revenue verification")
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
        "current_stage":bound["current_stage"],
        "scheduler_work_id":implementation_work["scheduler_work_id"],
        "scheduler_work_type":implementation_work["work_type"],
        "scheduler_dispatch_status":dispatch_receipt["result"]["dispatch_status"],
        "dispatch_result_kind":dispatch_receipt["result_kind"],
        "factory_bound_source_kind":dispatched_requests[0]["source_kind"],
        "factory_bound_request_id":dispatched_requests[0]["request_id"],
        "factory_bound_request_fingerprint":dispatched_requests[0]["fingerprint"],
        "factory_bound_request":dispatched_requests[0],
        "dispatch_mode":"LIVE_GITHUB_WORKFLOW" if dispatch_live else "CONTROLLED_IN_PROCESS",
        "dispatch_workflow_file":accepted_dispatches[0].get("workflow_file"),
        "dispatch_authority_granted":accepted_dispatches[0]["authority_granted"],
        "implementation_complete":dispatch_receipt["result"]["implementation_complete"],
        "technical_verified":dispatch_receipt["result"]["technical_verified"],
        "market_verified":bound["market_verified"],"revenue_verified":bound["revenue_verified"],
        "merge_authority_granted":bound["merge_authority_granted"],
        "deployment_authority_granted":bound["deployment_authority_granted"],
        "ci_market_promotion_rejected":ci_market_rejected,
        "implementation_provenance_refs":dispatched_requests[0]["evidence_refs"],
        "executor_summary_hash":execution_meta["summary"]["receipt_hash"],
      },
      "authority_granted":False,"evidence_upgraded":False,
    }
    return {**core,"receipt_hash":canonical_hash(core)}

def main()->None:
    ap=argparse.ArgumentParser()
    ap.add_argument("--source-sha",required=True)
    ap.add_argument("--run-id",required=True)
    ap.add_argument("--source-branch",required=True)
    ap.add_argument("--dispatch-live",action="store_true")
    ap.add_argument("--output",type=Path,required=True)
    args=ap.parse_args()
    receipt=build_receipt(
      source_sha=args.source_sha,run_id=args.run_id,source_branch=args.source_branch,
      dispatch_live=args.dispatch_live,
    )
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(receipt,indent=2,sort_keys=True)+"\n")
    print(json.dumps({
      "status":receipt["status"],"source_sha":receipt["source_sha"],
      "first_ingestion_status":receipt["step10"]["first_ingestion_status"],
      "second_ingestion_status":receipt["step10"]["second_ingestion_status"],
      "hunter_stage":receipt["step12"]["current_stage"],
      "dispatch_status":receipt["step12"]["scheduler_dispatch_status"],
      "dispatch_mode":receipt["step12"]["dispatch_mode"],
      "market_verified":receipt["step12"]["market_verified"],
      "revenue_verified":receipt["step12"]["revenue_verified"],
      "receipt_hash":receipt["receipt_hash"],
    },sort_keys=True))

if __name__=="__main__":
    main()
