#!/usr/bin/env python3
"""Controlled live proof for default REPAIR/TEST/VERIFICATION scheduler handlers."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from repair.repair_engine import failure_to_task
from runtime.state import bootstrap_state
from scheduler.autonomous_scheduler import _candidate, _work_packet, load_state
from scheduler.work_executor import execute_cycle

AT = "2026-09-30T13:30:00Z"


def _repair_task() -> dict:
    failure={
      "schema_version":"1.0.0",
      "failure_id":"RFAIL-STEP8-ACCEPTANCE",
      "source_type":"FAILURE_PACKET",
      "project_ids":["PRJ-000"],
      "target_repository_id":"REPO-008",
      "target_paths":["software_factory/scheduler_repair_bridge.py"],
      "failure_class":"EVIDENCE_IDENTITY",
      "observation":"submit_factory_candidate validates request_id and fingerprint but does not explicitly reject a diff-validation receipt whose base_sha differs from the admitted scheduler repair request.",
      "reproduction_steps":[
        "Construct a valid scheduler repair request and factory work item.",
        "Pass submit_factory_candidate a validation receipt with matching request_id/fingerprint but a different base_sha.",
        "Observe that the bridge does not explicitly reject the base identity mismatch before candidate commit."
      ],
      "evidence_refs":["acceptance:step8-default-handlers","acceptance:step9-factory-base-binding"],
      "regression_test_requirement":"Add a new regression-test file proving submit_factory_candidate rejects mismatched validation base_sha before candidate commit or PR creation while preserving the valid matching-base path.",
      "evidence_state":"VERIFIED",
      "sensitive_material_involved":False,
      "benchmark_contaminated":False,
      "reported_at":AT,
    }
    return failure_to_task(failure)


def _packet(work_type: str, source_ref: str) -> dict:
    roles={
      "REPAIR":("AGT-ENGINEER","ISOLATED_IMPLEMENTATION","MODIFY"),
      "TEST":("AGT-TESTER","REGRESSION_VALIDATION","EXPERIMENT"),
      "VERIFICATION":("AGT-AUDITOR","INDEPENDENT_AUDIT","EXPERIMENT"),
    }
    agent,goal,authority=roles[work_type]
    candidate=_candidate(
      work_type,source_ref,["PRJ-000"],agent,goal,authority,"HIGH",
      reason="Controlled live Step 8 default-handler acceptance.",
      evidence_refs=["acceptance:step8-default-handlers","external-milestone:PUBLISH_PRODUCT"],
      external_milestone="PUBLISH_PRODUCT",
      value_lane="INTERNAL_BLOCKER",
      signal_basis="CONTROLLED_LIVE_ACCEPTANCE",
    )
    return _work_packet(candidate,AT)


def prove(source_ref: str) -> dict:
    if not source_ref:
        raise ValueError("source_ref required")
    task=_repair_task()
    state=load_state()
    state["work_items"]=[
      _packet("REPAIR",task["repair_task_id"]),
      _packet("TEST",source_ref),
      _packet("VERIFICATION",source_ref),
    ]
    state["completed_fingerprints"]=[]
    state["sequence"]=0
    state["updated_at"]=AT
    main_sha=os.environ.get("GITHUB_SHA","")
    updated,receipts,executed,meta=execute_cycle(
      state,
      runtime_state=bootstrap_state(now=AT),
      max_items=3,
      at=AT,
      context_overrides={
        "repair_state":{"tasks":[task]},
        "main_sha":main_sha,
      },
    )
    kinds={row["work_type"]:row["result_kind"] for row in receipts}
    expected={
      "REPAIR":"AUTONOMOUS_REPAIR_DISPATCHED",
      "TEST":"REPAIR_FOUNDATION_TEST_VERIFIED",
      "VERIFICATION":"REPAIR_INDEPENDENTLY_VERIFIED",
    }
    if kinds!=expected:
        raise RuntimeError(f"Step 8 handler proof mismatch: {kinds!r}")
    if any(row["status"]!="SUCCESS" for row in receipts):
        raise RuntimeError("Step 8 handler proof did not complete every queued item")
    if any(row["state"]!="COMPLETE" for row in updated["work_items"]):
        raise RuntimeError("Step 8 handler proof left queued work")
    if len(executed)!=3 or meta["summary"]["completed_count"]!=3 or meta["summary"]["deferred_count"]!=0:
        raise RuntimeError("Step 8 execution accounting mismatch")
    if meta["summary"]["authority_granted"] is not False:
        raise RuntimeError("Step 8 acceptance unexpectedly granted authority")
    repair_requests=meta["context"].get("repair_dispatch_requests",[])
    repair_receipts=meta["context"].get("repair_dispatch_receipts",[])
    if len(repair_requests)!=1 or len(repair_receipts)!=1:
        raise RuntimeError("Step 8 REPAIR handler did not produce one request and one accepted dispatch receipt")
    return {
      "schema_version":"1.0.0",
      "status":"PASS",
      "source_ref":source_ref,
      "main_sha":main_sha,
      "queued_types":["REPAIR","TEST","VERIFICATION"],
      "completed_types":[row["work_type"] for row in executed],
      "result_kinds":kinds,
      "repair_request_id":repair_requests[0]["request_id"],
      "repair_fingerprint":repair_requests[0]["fingerprint"],
      "repair_dispatch_status":repair_receipts[0]["dispatch_status"],
      "test_pr_number":next(row["result"]["pr_number"] for row in receipts if row["work_type"]=="TEST"),
      "verification_pr_number":next(row["result"]["pr_number"] for row in receipts if row["work_type"]=="VERIFICATION"),
      "cycle_receipt":meta["summary"],
      "authority_granted":False,
      "canonical_state_mutated":False,
    }


def main() -> None:
    ap=argparse.ArgumentParser()
    ap.add_argument("--source-ref",required=True)
    ap.add_argument("--output",type=Path,required=True)
    args=ap.parse_args()
    result=prove(args.source_ref)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    print(json.dumps(result,sort_keys=True))


if __name__=="__main__":
    main()
