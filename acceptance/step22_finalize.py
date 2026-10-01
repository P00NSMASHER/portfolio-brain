#!/usr/bin/env python3
"""Build and validate the final Step 22 autonomous self-repair receipt."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any
from acceptance.final_acceptance import bind_receipt, validate_step22

def req(ok:bool,msg:str)->None:
    if not ok:
        raise ValueError(msg)

def _stage(stage_id:str,at:str,*,run_ids=None,pr_numbers=None,check_run_ids=None,artifact_hashes=None,state_hashes=None,source_shas=None)->dict[str,Any]:
    return {
      "stage_id":stage_id,"status":"PASS","occurred_at":at,
      "run_ids":list(run_ids or []),"pr_numbers":list(pr_numbers or []),
      "check_run_ids":list(check_run_ids or []),"artifact_hashes":list(artifact_hashes or []),
      "state_hashes":list(state_hashes or []),"source_shas":list(source_shas or []),
    }

def build_receipt(meta:dict[str,Any])->dict[str,Any]:
    req(meta.get("schema_version")=="1.0.0","Step22 metadata schema mismatch")
    fault=meta["fault"];repair=meta["repair"];cycles=meta["cycles"]
    merge_sha=repair["merge_sha"];head=repair["candidate_head_sha"];pr=repair["pr_number"]
    foundation=repair["foundation_check"];hosted=repair["hosted_verifier_check"]
    req(meta["current_main_sha"]==merge_sha,"Step22 finalization not on repair exact main")
    req(fault["base_sha"]==repair["base_sha"],"Step22 repair base lost fault identity")
    req(repair["new_regression_added"] is True,"Step22 new regression missing")
    req(repair["full_test_suite_passed"] is True,"Step22 full suite proof missing")
    req(repair["actor_login"]=="github-actions[bot]","Step22 repair PR actor mismatch")
    req(repair["branch"].startswith("factory/auto-repair-"),"Step22 repair branch not isolated")
    for name,row in cycles.items():
        req(row["head_sha"]==merge_sha,f"Step22 {name} cycle is not on repair main")
        req(row["conclusion"]=="success",f"Step22 {name} cycle failed")
    stages=[
      _stage("fault_detected",fault["detected_at"],run_ids=[fault["dispatch_run_id"]],artifact_hashes=[fault["receipt_hash"]],source_shas=[fault["base_sha"]]),
      _stage("repair_dispatched",fault["dispatched_at"],run_ids=[repair["workflow_run_id"]],state_hashes=[fault["fingerprint"]],source_shas=[fault["base_sha"]]),
      _stage("isolated_implementation",repair["workflow_created_at"],run_ids=[repair["workflow_run_id"]],artifact_hashes=[repair["handoff_artifact_digest"]],source_shas=[head]),
      _stage("new_regression_added",repair["pr_created_at"],pr_numbers=[pr],source_shas=[head]),
      _stage("full_test_suite",repair["pr_created_at"],run_ids=[repair["workflow_run_id"]],artifact_hashes=[repair["independent_review_artifact_digest"]],source_shas=[head]),
      _stage("repair_pr_opened",repair["pr_created_at"],pr_numbers=[pr],source_shas=[head]),
      _stage("foundation_exact_head",foundation["completed_at"],check_run_ids=[foundation["check_run_id"]],source_shas=[head]),
      _stage("hosted_verifier_gate",hosted["completed_at"],check_run_ids=[hosted["check_run_id"]],source_shas=[head]),
      _stage("protected_merge",repair["merged_at"],pr_numbers=[pr],artifact_hashes=[repair["merge_receipt_hash"]],source_shas=[merge_sha]),
      _stage("subsequent_runtime_cycle",cycles["runtime"]["completed_at"],run_ids=[cycles["runtime"]["run_id"]],artifact_hashes=cycles["runtime"].get("artifact_hashes",[]),source_shas=[merge_sha]),
      _stage("subsequent_reducer_cycle",cycles["reducer"]["completed_at"],run_ids=[cycles["reducer"]["run_id"]],artifact_hashes=cycles["reducer"].get("artifact_hashes",[]),source_shas=[merge_sha]),
      _stage("subsequent_scheduler_cycle",cycles["scheduler"]["completed_at"],run_ids=[cycles["scheduler"]["run_id"]],artifact_hashes=cycles["scheduler"].get("artifact_hashes",[]),source_shas=[merge_sha]),
    ]
    receipt=bind_receipt({
      "schema_version":"1.0.0","step":22,"status":"PASS","exact_main_sha":merge_sha,
      "fault_mechanism":"CONTROLLED_REPRODUCIBLE_FIXTURE","production_main_damaged":False,
      "fault_reversible":True,"new_regression_added":True,"full_test_suite_passed":True,
      "repair_branch_prefix":"factory/auto-repair-","hosted_verifier_app_id":5121826,
      "human_verifier_required":False,"laptop_verifier_required":False,
      "repair_pr_actor_kind":"BOT","repair_pr_actor_login":"github-actions[bot]",
      "repair_pr_number":pr,"repair_head_sha":head,"repair_merge_sha":merge_sha,
      "protected_merge":True,"foundation_check":foundation,"hosted_verifier_check":hosted,
      "stages":stages,
    })
    validate_step22(receipt)
    return receipt

def main()->None:
    import argparse
    ap=argparse.ArgumentParser();ap.add_argument("--meta",type=Path,required=True);ap.add_argument("--output",type=Path,required=True)
    args=ap.parse_args();meta=json.loads(args.meta.read_text(encoding="utf-8"));receipt=build_receipt(meta)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(receipt,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps({"status":receipt["status"],"receipt_hash":receipt["receipt_hash"],"exact_main_sha":receipt["exact_main_sha"]},sort_keys=True))
if __name__=="__main__": main()
