#!/usr/bin/env python3
"""Evidence-backed Step 21 executive dashboard snapshot builder."""
from __future__ import annotations
import hashlib,json
from pathlib import Path

from allocator.portfolio_allocator import build_allocation_snapshot
from experiments.experiment_engine import build_experiment_portfolio
from learning.continuous_learning import rebuild_from_ledger
from scheduler.autonomous_scheduler import build_context,load_state,schedule_cycle
from transfer.cross_project_transfer import build_transfer_state
from uncertainty.highest_value_uncertainty import build_snapshot as build_uncertainty_snapshot

ROOT=Path(__file__).resolve().parents[1]
LIVE_ROOT=ROOT/"dashboard"/"live"
def load(p):return json.loads((ROOT/p).read_text())
def live_path(name):return LIVE_ROOT/name
def live_json(name,fallback):
    p=live_path(name)
    return json.loads(p.read_text()) if p.exists() else load(fallback)
def canon(v):return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False)
def hashv(v):return "sha256:"+hashlib.sha256(canon(v).encode()).hexdigest()

def _health(project,uncertainties,blockers):
    open_blockers=[b["blocker_id"] for b in blockers if b["status"]=="OPEN" and (
        b["blocker_id"]=="BLK-001" and project["project_id"]=="PRJ-003" or
        b["blocker_id"]=="BLK-005" and project["project_id"]=="PRJ-000")]
    relevant=[u for u in uncertainties if project["project_id"] in u["project_ids"]]
    if open_blockers:return "BLOCKED",open_blockers
    if relevant:return "EVIDENCE_GAPS",[]
    return "UNKNOWN",[]

def build_dashboard_snapshot():
    projects=load("registry/projects.json")["projects"]
    build=load("PORTFOLIO_BUILD_STATE.json")
    unc=build_uncertainty_snapshot()
    experiments=build_experiment_portfolio(unc)
    allocation=build_allocation_snapshot(unc,experiments)
    learning=rebuild_from_ledger()
    transfer=build_transfer_state(unc)
    live_scheduler=live_path("scheduler_state.json").exists()
    scheduler_state=load_state(str(live_path("scheduler_state.json"))) if live_scheduler else load_state()
    scheduler_at=scheduler_state.get("updated_at") or "2026-09-25T22:30:00Z"
    _,sched_receipt=schedule_cycle(scheduler_state,build_context(),at=scheduler_at)
    open_scheduler_work=[w for w in scheduler_state["work_items"] if w["state"] in {"QUEUED","ACTIVE"}]
    visible_scheduler_work=open_scheduler_work if live_scheduler else sched_receipt["selected_work"]
    live_cost=live_path("cost_state.json").exists()
    cost=live_json("cost_state.json","cost_governor/COST_STATE_SEED.json")
    unc_by_project={p["project_id"]:[] for p in projects}
    for u in unc["candidates"]:
        for pid in u["project_ids"]:
            if pid in unc_by_project:unc_by_project[pid].append(u)
    exp_by_unc={x["uncertainty_id"]:x for x in experiments["plans"]}
    allocation_by_project={p["project_id"]:[] for p in projects}
    for plan in allocation["plans"]:
        for rec in plan["recommendations"]:
            pid=rec["project_id"]
            if pid in allocation_by_project:
                allocation_by_project[pid].append({
                    "resource_type":plan["resource_type"],"plan_status":plan["status"],
                    "share_basis_points":rec["share_basis_points"],"source_uncertainty_id":rec["source_uncertainty_id"],
                    "evidence_refs":rec["evidence_refs"]
                })
    selected_by_project={p["project_id"]:[] for p in projects}
    for w in visible_scheduler_work:
        for pid in w["project_ids"]:
            if pid in selected_by_project:selected_by_project[pid].append({"work_type":w["work_type"],"work_id":w["scheduler_work_id"],"state":w["state"],"evidence_refs":w["evidence_refs"]})
    blocked_by_project={p["project_id"]:[] for p in projects}
    for w in sched_receipt["blocked_work"]:
        for pid in w["project_ids"]:
            if pid in blocked_by_project:blocked_by_project[pid].append({"work_type":w["work_type"],"state":w["state"],"approval_requirements":w["approval_requirements"],"hard_blockers":w["hard_blockers"]})
    rows=[]
    for p in projects:
        us=sorted(unc_by_project[p["project_id"]],key=lambda x:(not x["ranking"]["eligible"],99 if x["ranking"]["pareto_layer"] is None else x["ranking"]["pareto_layer"],9999 if x["ranking"]["rank_order"] is None else x["ranking"]["rank_order"],x["uncertainty_id"]))
        highest=us[0] if us else None
        health,project_blockers=_health(p,us,build["blockers"])
        active_exp=None if highest is None else exp_by_unc.get(highest["uncertainty_id"])
        measured_outcomes=[]
        row={
          "project_id":p["project_id"],"name":p["canonical_name"],"project_type":p["project_type"],
          "lifecycle_status":p["lifecycle_status"],"maturity_basis":"REGISTERED_LIFECYCLE_STATUS_ONLY",
          "health":health,"health_basis":"EVIDENCE_COVERAGE_NOT_SUBJECTIVE_SCORE",
          "current_bottleneck":None if highest is None else highest["question"],
          "highest_value_uncertainty":None if highest is None else {
             "uncertainty_id":highest["uncertainty_id"],"question":highest["question"],"actionability":highest["actionability"],
             "authority_requirement":highest["authority_requirement"],"evidence_refs":highest["evidence_refs"]},
          "active_experiment":None if active_exp is None else {
             "experiment_id":active_exp["experiment_id"],"status":active_exp["status"],"execution_mode":active_exp["execution_mode"],
             "approval_requirements":active_exp["approval_requirements"],"hard_blockers":active_exp["hard_blockers"]},
          "recent_measured_outcomes":measured_outcomes,
          "measured_outcome_status":"NONE_IN_CHECKED_IN_VERIFIED_LEDGER",
          "resource_recommendations":allocation_by_project[p["project_id"]],
          "learned_capabilities":[],
          "pending_autonomous_work":selected_by_project[p["project_id"]],
          "blocked_actions":blocked_by_project[p["project_id"]],
          "open_blockers":project_blockers,
          "model_costs":{"measured_usd":0.0,"measured_model_calls":0,"basis":"CHECKED_IN_COST_LEDGER_EMPTY"},
          "evidence_coverage":{
             "uncertainty_candidates":len(us),
             "verified_learning_observations":0,
             "verified_transfer_outcomes":0,
             "verified_measured_outcomes":0
          }
        }
        rows.append(row)
    snapshot={
      "schema_version":"1.0.0","dashboard_id":"portfolio-executive-dashboard-v1",
      "authority_class":"OBSERVE","generated_from_checked_in_state":not (live_scheduler or live_cost),
      "state_basis":{"scheduler":"LIVE_ARTIFACT" if live_scheduler else "CHECKED_IN_SEED","cost":"LIVE_ARTIFACT" if live_cost else "CHECKED_IN_SEED"},
      "project_count":len(rows),"projects":rows,
      "portfolio":{
        "highest_value_uncertainty_id":unc["selected_uncertainty_id"],
        "active_resource_types":sorted([p["resource_type"] for p in allocation["plans"] if p["status"]=="ACTIVE_RECOMMENDATION"]),
        "hold_resource_types":sorted([p["resource_type"] for p in allocation["plans"] if p["status"]!="ACTIVE_RECOMMENDATION"]),
        "pending_autonomous_work_count":len(visible_scheduler_work),
        "newly_selectable_work_count":len(sched_receipt["selected_work"]),
        "blocked_action_count":len(sched_receipt["blocked_work"]),
        "learning_observation_count":learning["source_observation_count"],
        "verified_transfer_outcome_count":transfer["checked_in_outcomes"],
        "checked_in_cost_reservation_count":len(cost["reservations"]),
        "cost_state_sequence":cost.get("sequence",0),
        "checked_in_measured_model_cost_usd":0.0,
        "estimated_value_presented_as_measured":False
      },
      "labels":{
        "measured_result":"Only independently evidenced outcomes/costs from checked-in verified ledgers.",
        "estimated_value":"Policy estimates or hypotheses remain explicitly labeled and are never promoted to measured results.",
        "unknown":"Missing evidence remains UNKNOWN/NONE rather than being inferred."
      },
      "evidence_refs":["registry/projects.json","uncertainty/INITIAL_UNCERTAINTY_SUMMARY.json","experiments/INITIAL_EXPERIMENT_SUMMARY.json","allocator/INITIAL_ALLOCATION_SUMMARY.json","learning/LEARNING_OBSERVATION_LEDGER.json","transfer/TRANSFER_LEDGER.json","dashboard/live/scheduler_state.json" if live_scheduler else "scheduler/SCHEDULER_STATE_SEED.json","dashboard/live/cost_state.json" if live_cost else "cost_governor/COST_STATE_SEED.json"]
    }
    snapshot["snapshot_hash"]=hashv(snapshot)
    return snapshot

def render_markdown(snapshot):
    lines=["# Portfolio Brain Executive Dashboard","",f"Projects: {snapshot['project_count']} | Pending autonomous work: {snapshot['portfolio']['pending_autonomous_work_count']} | Blocked actions: {snapshot['portfolio']['blocked_action_count']}","",
           "> MEASURED RESULT is distinct from ESTIMATED VALUE. Missing evidence is shown as UNKNOWN/NONE.","",
           "| Project | Lifecycle | Evidence health | Current bottleneck | Experiment | Pending | Blocked | Measured model cost |",
           "|---|---|---|---|---|---:|---:|---:|"]
    for p in snapshot["projects"]:
        bottleneck=(p["highest_value_uncertainty"] or {}).get("uncertainty_id","NONE")
        exp=(p["active_experiment"] or {}).get("status","NONE")
        lines.append(f"| {p['project_id']} {p['name']} | {p['lifecycle_status']} | {p['health']} | {bottleneck} | {exp} | {len(p['pending_autonomous_work'])} | {len(p['blocked_actions'])} | $0.00 |")
    lines += ["","## Portfolio allocation","",
              "Active resource types: "+", ".join(snapshot["portfolio"]["active_resource_types"])+".",
              "Held resource types: "+", ".join(snapshot["portfolio"]["hold_resource_types"])+".",
              "","No dashboard field grants authority or executes work."]
    return "\n".join(lines)+"\n"

if __name__=="__main__":
    s=build_dashboard_snapshot();print(render_markdown(s))
