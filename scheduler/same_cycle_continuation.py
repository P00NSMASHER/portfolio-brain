#!/usr/bin/env python3
"""Reuse spare scheduler capacity for Hunter proposal review continuation.

This is intentionally a single bounded second pass inside the existing scheduler
workflow run. It cannot increase the configured total attempt ceiling, cannot
retry primary deferred work in the same cycle, and can schedule only OBSERVE-
class Hunter proposal continuation work.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from hunting.autonomous_hunter import load_seed_state as hunter_seed_state
from hunting.proposal_state import validate_state as validate_hunter_proposal_state
from scheduler.autonomous_scheduler import (
    build_context,
    is_hunter_proposal_continuation,
    load_state as load_scheduler_state,
    now_iso,
    policy as scheduler_policy,
    schedule_cycle,
    validate_state as validate_scheduler_state,
)
from scheduler.work_executor import canon, execute_cycle, hashv

ROOT=Path(__file__).resolve().parents[1]


class SameCycleContinuationError(RuntimeError):
    pass


def req(ok:bool,msg:str)->None:
    if not ok:
        raise SameCycleContinuationError(msg)


def load_json(path:str|Path)->Any:
    p=Path(path)
    if not p.is_absolute():
        p=ROOT/p
    return json.loads(p.read_text(encoding="utf-8"))


def _first_existing(primary:str|Path,fallback:str|Path|None=None)->Path|None:
    first=Path(primary)
    if not first.is_absolute():
        first=ROOT/first
    if first.exists():
        return first
    if fallback is None:
        return None
    second=Path(fallback)
    if not second.is_absolute():
        second=ROOT/second
    return second if second.exists() else None


def _validate_primary(
    state:dict[str,Any],
    receipts:list[dict[str,Any]],
    executed:list[dict[str,Any]],
    summary:dict[str,Any],
    *,
    max_items:int,
)->None:
    validate_scheduler_state(state)
    req(isinstance(receipts,list) and isinstance(executed,list),"primary execution artifacts invalid")
    req(isinstance(summary,dict) and summary.get("schema_version")=="1.0.0","primary cycle receipt invalid")
    expected=summary.get("receipt_hash")
    req(isinstance(expected,str) and expected.startswith("sha256:"),"primary cycle receipt hash missing")
    body={key:value for key,value in summary.items() if key!="receipt_hash"}
    req(hashv(body)==expected,"primary cycle receipt hash mismatch")
    attempted=summary.get("attempted_count")
    completed=summary.get("completed_count")
    deferred=summary.get("deferred_count")
    req(type(attempted) is int and 0<=attempted<=max_items,"primary attempted count outside bound")
    req(type(completed) is int and type(deferred) is int and completed>=0 and deferred>=0,"primary disposition counts invalid")
    req(completed+deferred==attempted==len(receipts),"primary execution accounting mismatch")
    req(len(executed)==completed,"primary executed-work count mismatch")
    open_count=sum(1 for row in state["work_items"] if row["state"] in {"QUEUED","ACTIVE"})
    req(summary.get("remaining_queued_count")==sum(1 for row in state["work_items"] if row["state"]=="QUEUED"),"primary queued count mismatch")
    if scheduler_policy()["same_cycle_continuation"]["require_primary_queue_drained"]:
        req(open_count==0 or summary.get("remaining_queued_count",0)>0,"primary active work remained without queued accounting")


def _combined_summary(
    receipts:list[dict[str,Any]],
    state:dict[str,Any],
    *,
    at:str,
    primary_attempted:int,
    continuation_selected:int,
    continuation_pass_count:int,
)->dict[str,Any]:
    summary={
        "schema_version":"1.0.0",
        "cycle_id":"wexec-"+hashlib.sha256(
            canon([row["execution_id"] for row in receipts]).encode("utf-8")
        ).hexdigest()[:24],
        "finished_at":at,
        "attempted_count":len(receipts),
        "completed_count":sum(1 for row in receipts if row.get("status")=="SUCCESS"),
        "deferred_count":sum(1 for row in receipts if row.get("status")=="DEFERRED"),
        "remaining_queued_count":sum(1 for row in state["work_items"] if row["state"]=="QUEUED"),
        "primary_attempted_count":primary_attempted,
        "continuation_selected_count":continuation_selected,
        "continuation_attempted_count":len(receipts)-primary_attempted,
        "continuation_pass_count":continuation_pass_count,
        "authority_granted":False,
    }
    summary["receipt_hash"]=hashv(summary)
    return summary


def run_same_cycle_continuation(
    state:dict[str,Any],
    *,
    runtime_state:dict[str,Any],
    hunter_state:dict[str,Any],
    hunter_proposal_state:dict[str,Any],
    primary_receipts:list[dict[str,Any]],
    primary_executed:list[dict[str,Any]],
    primary_summary:dict[str,Any],
    max_items:int=8,
    worker_instance_id:str="scheduler-same-cycle-continuation",
    at:str|None=None,
    context_overrides:dict[str,Any]|None=None,
)->tuple[dict[str,Any],list[dict[str,Any]],list[dict[str,Any]],dict[str,Any],dict[str,Any],list[dict[str,Any]]]:
    policy=scheduler_policy()
    cfg=policy["same_cycle_continuation"]
    req(cfg["enabled"] is True,"same-cycle continuation disabled")
    req(cfg["continuation_class"]=="HUNTER_PROPOSAL_REVIEW","same-cycle continuation class drifted")
    req(cfg["max_passes"]==2,"same-cycle continuation pass count drifted")
    req(cfg["authority_class"]=="OBSERVE","same-cycle continuation authority widened")
    req(cfg["reuse_spare_capacity_only"] is True,"same-cycle continuation spare-capacity boundary disabled")
    req(type(max_items) is int and 0<=max_items<=policy["max_new_work_per_cycle"],"same-cycle max_items outside scheduler bound")
    req(max_items<=cfg["max_total_attempts_per_cycle"],"same-cycle total attempt ceiling widened")
    validate_scheduler_state(state)
    validate_hunter_proposal_state(hunter_proposal_state)
    _validate_primary(state,primary_receipts,primary_executed,primary_summary,max_items=max_items)

    at=at or now_iso()
    primary_attempted=len(primary_receipts)
    initial_spare=max_items-primary_attempted
    open_work=[row for row in state["work_items"] if row["state"] in {"QUEUED","ACTIVE"}]

    base_report={
        "schema_version":"1.0.0",
        "policy":"HUNTER_PROPOSAL_REVIEW_SPARE_CAPACITY_ONLY",
        "max_total_attempts":max_items,
        "max_passes":cfg["max_passes"],
        "primary_attempted_count":primary_attempted,
        "spare_capacity":initial_spare,
        "authority_granted":False,
    }
    if initial_spare<=0:
        return state,primary_receipts,primary_executed,primary_summary,{
            **base_report,"status":"NO_SPARE_CAPACITY","pass_count":0,"passes":[],
            "selected_count":0,"attempted_count":0,"completed_count":0,"deferred_count":0,
            "unused_capacity":0,
        },[]
    if open_work:
        return state,primary_receipts,primary_executed,primary_summary,{
            **base_report,"status":"SKIPPED_PRIMARY_QUEUE_NOT_DRAINED","pass_count":0,"passes":[],
            "selected_count":0,"attempted_count":0,"completed_count":0,"deferred_count":0,
            "unused_capacity":initial_spare,
        },[]

    context=build_context(hunter_proposal_state=hunter_proposal_state)
    overrides={"hunter_proposal_state":hunter_proposal_state}
    if context_overrides:
        overrides.update(context_overrides)

    current_state=json.loads(json.dumps(state))
    merged_receipts=list(primary_receipts)
    merged_executed=list(primary_executed)
    all_selected:list[dict[str,Any]]=[]
    pass_reports:list[dict[str,Any]]=[]
    stop_reason=None

    for pass_index in range(1,cfg["max_passes"]+1):
        remaining=max_items-len(merged_receipts)
        if remaining<=0:
            stop_reason="ATTEMPT_CEILING_REACHED"
            break
        if any(row["state"] in {"QUEUED","ACTIVE"} for row in current_state["work_items"]):
            stop_reason="CONTINUATION_QUEUE_NOT_DRAINED"
            break

        scheduled,schedule_receipt=schedule_cycle(
            current_state,
            context,
            at=at,
            candidate_filter=is_hunter_proposal_continuation,
            max_new_items=remaining,
        )
        selected=schedule_receipt["selected_work"]
        req(all(is_hunter_proposal_continuation(row) for row in selected),"same-cycle scheduler selected non-Hunter continuation work")
        req(len(selected)<=policy["max_open_work_per_agent"],"same-cycle continuation exceeded per-agent open-work ceiling")
        if not selected:
            stop_reason="NO_ELIGIBLE_CONTINUATION"
            break

        updated,secondary_receipts,secondary_executed,_=execute_cycle(
            scheduled,
            runtime_state=runtime_state,
            hunter_state=hunter_state,
            max_items=remaining,
            worker_instance_id=f"{worker_instance_id}:pass-{pass_index}",
            at=at,
            context_overrides=overrides,
        )
        req(len(secondary_receipts)<=remaining,"same-cycle continuation exceeded spare capacity")
        req(all(
            any(row["scheduler_work_id"]==receipt["scheduler_work_id"] for row in selected)
            for receipt in secondary_receipts
        ),"same-cycle executor attempted work outside continuation selection")

        pass_reports.append({
            "pass_index":pass_index,
            "selected_count":len(selected),
            "attempted_count":len(secondary_receipts),
            "completed_count":len(secondary_executed),
            "deferred_count":sum(1 for row in secondary_receipts if row.get("status")=="DEFERRED"),
            "proposal_ids":[row["source_ref"] for row in selected],
            "execution_ids":[row["execution_id"] for row in secondary_receipts],
            "receipt_hashes":[row["receipt_hash"] for row in secondary_receipts],
        })
        all_selected.extend(selected)
        merged_receipts.extend(secondary_receipts)
        merged_executed.extend(secondary_executed)
        current_state=updated

        req(len(merged_receipts)<=max_items,"same-cycle total attempts exceeded scheduler cycle bound")
        if any(row.get("status")=="DEFERRED" for row in secondary_receipts):
            stop_reason="DEFERRED_CONTINUATION_STOPS_FURTHER_PASSES"
            break

    if not pass_reports:
        return state,primary_receipts,primary_executed,primary_summary,{
            **base_report,"status":"NO_ELIGIBLE_CONTINUATION","pass_count":0,"passes":[],
            "selected_count":0,"attempted_count":0,"completed_count":0,"deferred_count":0,
            "unused_capacity":initial_spare,"stop_reason":stop_reason or "NO_ELIGIBLE_CONTINUATION",
        },[]

    summary=_combined_summary(
        merged_receipts,
        current_state,
        at=at,
        primary_attempted=primary_attempted,
        continuation_selected=len(all_selected),
        continuation_pass_count=len(pass_reports),
    )
    validate_scheduler_state(current_state)
    continuation_receipts=merged_receipts[primary_attempted:]
    continuation_executed=merged_executed[len(primary_executed):]
    report={
        **base_report,
        "status":"EXECUTED",
        "pass_count":len(pass_reports),
        "passes":pass_reports,
        "selected_count":len(all_selected),
        "attempted_count":len(continuation_receipts),
        "completed_count":len(continuation_executed),
        "deferred_count":sum(1 for row in continuation_receipts if row.get("status")=="DEFERRED"),
        "remaining_queued_count":summary["remaining_queued_count"],
        "unused_capacity":max_items-len(merged_receipts),
        "stop_reason":stop_reason,
        "proposal_ids":[row["source_ref"] for row in all_selected],
    }
    return current_state,merged_receipts,merged_executed,summary,report,all_selected


def main()->None:
    ap=argparse.ArgumentParser(description="Reuse spare scheduler capacity for Hunter proposal continuation")
    ap.add_argument("--scheduler-state",default="scheduler/out/scheduler_state.json")
    ap.add_argument("--runtime-state",default="runtime/live/runtime_state.json")
    ap.add_argument("--hunter-state",default="hunting/out/hunter_state.json")
    ap.add_argument("--hunter-state-fallback",default="hunting/live/hunter_state.json")
    ap.add_argument("--hunter-proposal-state",default="hunting/out/hunter_proposal_state.json")
    ap.add_argument("--hunter-proposal-state-fallback",default="hunting/live/hunter_proposal_state.json")
    ap.add_argument("--primary-receipts",default="scheduler/out/execution_receipts.json")
    ap.add_argument("--primary-executed",default="scheduler/out/executed_work.json")
    ap.add_argument("--primary-cycle-receipt",default="scheduler/out/execution_cycle_receipt.json")
    ap.add_argument("--output-dir",default="scheduler/out")
    ap.add_argument("--max-items",type=int,default=8)
    ap.add_argument("--at",default=None)
    args=ap.parse_args()

    state=load_scheduler_state(args.scheduler_state)
    runtime_state=load_json(args.runtime_state)
    hunter_path=_first_existing(args.hunter_state,args.hunter_state_fallback)
    hunter_state=load_json(hunter_path) if hunter_path is not None else hunter_seed_state()
    proposal_path=_first_existing(args.hunter_proposal_state,args.hunter_proposal_state_fallback)
    req(proposal_path is not None,"Hunter proposal state unavailable for same-cycle continuation")
    proposal_state=load_json(proposal_path)
    primary_receipts=load_json(args.primary_receipts)
    primary_executed=load_json(args.primary_executed)
    primary_summary=load_json(args.primary_cycle_receipt)
    run_id=os.environ.get("GITHUB_RUN_ID") or "local"

    updated,receipts,executed,summary,report,selected=run_same_cycle_continuation(
        state,
        runtime_state=runtime_state,
        hunter_state=hunter_state,
        hunter_proposal_state=proposal_state,
        primary_receipts=primary_receipts,
        primary_executed=primary_executed,
        primary_summary=primary_summary,
        max_items=args.max_items,
        worker_instance_id=f"portfolio-scheduler:{run_id}:continuation",
        at=args.at,
    )

    out=Path(args.output_dir)
    out.mkdir(parents=True,exist_ok=True)
    if report["status"]=="EXECUTED":
        (out/"scheduler_state.json").write_text(json.dumps(updated,indent=2)+"\n",encoding="utf-8")
        (out/"execution_receipts.json").write_text(json.dumps(receipts,indent=2)+"\n",encoding="utf-8")
        (out/"executed_work.json").write_text(json.dumps(executed,indent=2)+"\n",encoding="utf-8")
        (out/"execution_cycle_receipt.json").write_text(json.dumps(summary,indent=2)+"\n",encoding="utf-8")
        (out/"same_cycle_scheduled_work.json").write_text(json.dumps(selected,indent=2)+"\n",encoding="utf-8")
    (out/"same_cycle_continuation_report.json").write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf-8")

    github_output=os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output,"a",encoding="utf-8") as fh:
            fh.write(f"status={report['status']}\n")
            fh.write(f"attempted_count={report['attempted_count']}\n")
            fh.write(f"completed_count={report['completed_count']}\n")
    print(json.dumps(report,sort_keys=True))


if __name__=="__main__":
    main()
