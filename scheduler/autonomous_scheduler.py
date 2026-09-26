#!/usr/bin/env python3
"""Evidence-gated persistent portfolio work scheduler."""
from __future__ import annotations
import argparse,hashlib,json,os
from datetime import datetime,timezone
from pathlib import Path
from typing import Any

from allocator.portfolio_allocator import build_allocation_snapshot
from experiments.experiment_engine import build_experiment_portfolio
from hunting.autonomous_hunter import load_seed_state as hunter_seed, select_objectives
from learning.continuous_learning import rebuild_from_ledger
from repair.repair_engine import build_repair_state
from transfer.cross_project_transfer import build_transfer_state
from uncertainty.highest_value_uncertainty import build_snapshot as build_uncertainty_snapshot

ROOT=Path(__file__).resolve().parents[1]
class SchedulerError(ValueError):pass
def req(ok,msg):
    if not ok:raise SchedulerError(msg)
def load(path):
    p=Path(path)
    if not p.is_absolute():p=ROOT/p
    return json.loads(p.read_text())
def canon(v):return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False)
def hashv(v):return "sha256:"+hashlib.sha256(canon(v).encode()).hexdigest()
def now_iso():return datetime.now(timezone.utc).isoformat().replace("+00:00","Z")
def policy():return load("scheduler/SCHEDULER_POLICY.json")

def validate_state(state):
    required={"schema_version","state_id","sequence","updated_at","work_items","completed_fingerprints","recent_cycles"}
    req(isinstance(state,dict) and set(state)==required,"scheduler state fields changed")
    req(state["schema_version"]=="1.0.0" and state["state_id"]=="portfolio-scheduler-state","scheduler state identity mismatch")
    req(type(state["sequence"]) is int and state["sequence"]>=0,"scheduler sequence invalid")
    req(isinstance(state["work_items"],list) and len(state["work_items"])<=policy()["max_queue_items"],"scheduler queue invalid")
    req(isinstance(state["completed_fingerprints"],list) and len(state["completed_fingerprints"])==len(set(state["completed_fingerprints"])),"completed fingerprints invalid")
    req(isinstance(state["recent_cycles"],list) and len(state["recent_cycles"])<=20,"recent cycles invalid")

def load_state(path=None):
    if path is not None and Path(path).exists():
        s=json.loads(Path(path).read_text());validate_state(s);return s
    s=load("scheduler/SCHEDULER_STATE_SEED.json");validate_state(s);return s

def killed():
    k=load("scheduler/KILL_SWITCH.json")
    if k.get("disabled") is True:return True,k.get("reason") or "file kill switch"
    if os.environ.get("PORTFOLIO_SCHEDULER_DISABLED","").strip().lower()=="true":return True,"repository/environment kill switch"
    return False,None

def _agent_registry():
    return {r["agent_id"]:r for r in load("agents/AGENT_REGISTRY.json")["roles"]}

def _role_valid(candidate):
    roles=_agent_registry();agent=roles.get(candidate["assigned_agent_id"])
    if not agent or agent["status"]!="ACTIVE":return False,"AGENT_INACTIVE_OR_UNKNOWN"
    if candidate["agent_goal_type"] not in agent["allowed_goal_types"]:return False,"GOAL_TYPE_NOT_ALLOWED"
    ranks=load("agents/AGENT_POLICY.json")["authority_rank"]
    if candidate["required_authority"]=="ACT" or ranks[candidate["required_authority"]]>ranks[agent["max_autonomy"]]:return False,"AUTHORITY_EXCEEDS_ROLE"
    return True,None

def _allocation_maps(allocation):
    plans={p["resource_type"]:p for p in allocation["plans"]}
    rec={}
    for resource,plan in plans.items():
        rec[resource]={r["source_uncertainty_id"]:r for r in plan["recommendations"]}
    return plans,rec

def build_context(*,factory_work_items=None,learning_state=None):
    uncertainty=build_uncertainty_snapshot()
    experiments=build_experiment_portfolio(uncertainty)
    allocation=build_allocation_snapshot(uncertainty,experiments)
    learning=learning_state or rebuild_from_ledger()
    repair=build_repair_state(learning)
    transfer=build_transfer_state(uncertainty)
    factory=list(factory_work_items if factory_work_items is not None else load("software_factory/SOFTWARE_FACTORY_LEDGER.json")["work_items"])
    return {"uncertainty":uncertainty,"experiments":experiments,"allocation":allocation,"learning":learning,"repair":repair,"transfer":transfer,"factory_work_items":factory}

def _candidate(work_type,source_ref,project_ids,assigned_agent_id,goal_type,authority,consequence,*,pareto=None,rank=None,share=None,approvals=None,blockers=None,reason,evidence_refs):
    core={"work_type":work_type,"source_ref":source_ref,"project_ids":sorted(project_ids),"assigned_agent_id":assigned_agent_id,"agent_goal_type":goal_type}
    return {"fingerprint":hashv(core),**core,"required_authority":authority,"consequence":consequence,"source_pareto_layer":pareto,"source_rank_order":rank,"allocation_share_basis_points":share,
            "approval_requirements":sorted(set(approvals or [])),"hard_blockers":sorted(set(blockers or [])),"selection_reason":reason,"evidence_refs":list(dict.fromkeys(evidence_refs))}

def _source_candidate(unc_by_id,rec,work_type,agent_id,goal_type,authority,consequence,reason):
    u=unc_by_id[rec["source_uncertainty_id"]]
    return _candidate(work_type,rec["source_experiment_id"],[rec["project_id"]],agent_id,goal_type,authority,consequence,
        pareto=rec["pareto_layer"],rank=rec["rank_order"],share=rec["share_basis_points"],approvals=u["approval_requirements"],blockers=u["hard_blockers"],
        reason=reason,evidence_refs=[*rec["evidence_refs"],f"uncertainty:{u['uncertainty_id']}",f"experiment:{rec['source_experiment_id']}"])

def generate_candidates(context):
    p=policy();unc=context["uncertainty"];unc_by={c["uncertainty_id"]:c for c in unc["candidates"]}
    plans,alloc=_allocation_maps(context["allocation"]);candidates=[];blocked=[]
    # RESEARCH: evidence-backed read-only experiment/research demand.
    for rec in plans["RESEARCH"]["recommendations"]:
        candidates.append(_source_candidate(unc_by,rec,"RESEARCH","AGT-RESEARCHER","RESEARCH_EVIDENCE","OBSERVE","MEDIUM","Step 15 allocated RESEARCH capacity to read-only evidence acquisition."))
    # HUNT: capability-evidence gaps with explicit Hunter allocation.
    for rec in plans["HUNTER_RUNS"]["recommendations"]:
        candidates.append(_source_candidate(unc_by,rec,"HUNT","AGT-HUNTER","PUBLIC_HUNT","OBSERVE","MEDIUM","Step 15 allocated Hunter capacity to this capability-evidence gap."))
    # Human-gated experiments remain visible but never enter the autonomous queue.
    for exp in context["experiments"]["plans"]:
        if exp["status"]=="HUMAN_APPROVAL_REQUIRED":
            u=unc_by[exp["uncertainty_id"]]
            blocked.append(_candidate("EXPERIMENT",exp["experiment_id"],exp["project_ids"],"AGT-PORTFOLIO-MANAGER","WORK_COORDINATION","NONE","HIGH",
                pareto=u["ranking"]["pareto_layer"],rank=u["ranking"]["rank_order"],share=(alloc["HUMAN_REVIEW"].get(u["uncertainty_id"]) or {}).get("share_basis_points"),
                approvals=exp["approval_requirements"],blockers=exp["hard_blockers"],reason="Experiment is high-value but HUMAN_GATED_ACT; scheduler may surface it for review but cannot execute it.",
                evidence_refs=[*u["evidence_refs"],f"experiment:{exp['experiment_id']}"]))
        elif exp["status"]=="READY_FOR_BOUNDED_EXECUTION" and exp["execution_mode"]=="BOUNDED_EXTERNAL_VALIDATION":
            u=unc_by[exp["uncertainty_id"]]
            candidates.append(_candidate("EXPERIMENT",exp["experiment_id"],exp["project_ids"],"AGT-COMMERCIAL-ANALYST","EXTERNAL_EVIDENCE_ANALYSIS","OBSERVE","HIGH",
                pareto=u["ranking"]["pareto_layer"],rank=u["ranking"]["rank_order"],
                reason="Bounded commercial validation is ready; scheduler prepares evidence work while action_engine independently gates channel ACT.",
                evidence_refs=[*u["evidence_refs"],f"experiment:{exp['experiment_id']}","action-policy:action_engine/ACTION_POLICY.json"]))
        elif exp["status"]=="READY_FOR_ISOLATED_EXECUTION" and exp["execution_mode"]=="ISOLATED_SYNTHETIC_TEST":
            u=unc_by[exp["uncertainty_id"]]
            candidates.append(_candidate("EXPERIMENT",exp["experiment_id"],exp["project_ids"],"AGT-PRODUCT-ANALYST","EXPERIMENT_DESIGN","EXPERIMENT","HIGH",
                pareto=u["ranking"]["pareto_layer"],rank=u["ranking"]["rank_order"],reason="Bounded isolated experiment is execution-ready without ACT.",evidence_refs=[*u["evidence_refs"],f"experiment:{exp['experiment_id']}"]))
    # REPAIR/TEST/VERIFICATION from existing evidence chains.
    for task in context["repair"]["tasks"]:
        state=task["state"]
        projects=task["project_ids"]
        if state=="READY_FOR_REPAIR":
            candidates.append(_candidate("REPAIR",task["repair_task_id"],projects,"AGT-ENGINEER","ISOLATED_IMPLEMENTATION","MODIFY","HIGH",
                reason="Verified reproducible repair task is ready for the Step 16 isolated factory path.",evidence_refs=[*task["evidence_refs"],f"repair:{task['repair_task_id']}"]))
        elif state=="HELD_OUT_PENDING":
            candidates.append(_candidate("TEST",task["repair_task_id"],projects,"AGT-TESTER","REGRESSION_VALIDATION","EXPERIMENT","HIGH",
                reason="Repair candidate is awaiting held-out regression evaluation.",evidence_refs=[*task["evidence_refs"],f"repair:{task['repair_task_id']}"]))
        elif state=="INDEPENDENT_AUDIT_PENDING":
            candidates.append(_candidate("VERIFICATION",task["repair_task_id"],projects,"AGT-AUDITOR","INDEPENDENT_AUDIT","EXPERIMENT","CRITICAL",
                reason="Repair candidate passed held-out evaluation and awaits independent audit.",evidence_refs=[*task["evidence_refs"],f"repair:{task['repair_task_id']}"]))
        elif state=="CANARY_PENDING":
            candidates.append(_candidate("VERIFICATION",task["repair_task_id"],projects,"AGT-RED-TEAM","ADVERSARIAL_REVIEW","EXPERIMENT","CRITICAL",
                reason="Independently audited repair awaits bounded canary verification.",evidence_refs=[*task["evidence_refs"],f"repair:{task['repair_task_id']}"]))
    # Factory verification must honor the work-bound verifier exactly.
    goal_for={"AGT-TESTER":"REGRESSION_VALIDATION","AGT-AUDITOR":"INDEPENDENT_AUDIT","AGT-RED-TEAM":"ADVERSARIAL_REVIEW"}
    for work in context["factory_work_items"]:
        if work.get("state")!="VERIFYING":continue
        verifier=work.get("verifier_agent_id")
        if verifier not in goal_for:
            blocked.append(_candidate("VERIFICATION",str(work.get("work_id") or "unknown"),[work.get("project_id") or "PRJ-000"],"AGT-PORTFOLIO-MANAGER","WORK_COORDINATION","NONE","HIGH",
                reason="Factory work has no scheduler-compatible bound verifier.",blockers=["BOUND_VERIFIER_UNAVAILABLE"],evidence_refs=[f"factory:{work.get('work_id','unknown')}"]))
            continue
        candidates.append(_candidate("VERIFICATION",work["work_id"],[work["project_id"]],verifier,goal_for[verifier],"EXPERIMENT","CRITICAL",
            reason="Step 16 factory work is VERIFYING; exact bound verifier must act before any PR-ready state.",evidence_refs=[f"factory:{work['work_id']}",f"commit:{work.get('commit_sha')}"]))
    # INTEGRATION is read-only transfer assessment, not implementation.
    for proposal in context["transfer"]["proposals"]:
        if proposal["state"]!="ASSESSMENT_READY":continue
        u=unc_by.get(proposal["target_need_uncertainty_id"])
        candidates.append(_candidate("INTEGRATION",proposal["transfer_id"],[proposal["target_project_id"]],"AGT-PRODUCT-ANALYST","PRODUCT_ANALYSIS","OBSERVE","MEDIUM",
            pareto=None if u is None else u["ranking"]["pareto_layer"],rank=None if u is None else u["ranking"]["rank_order"],
            reason="Cross-project transfer hypothesis is assessment-ready; implementation remains prohibited.",evidence_refs=[*proposal["provenance_refs"],f"transfer:{proposal['transfer_id']}"]))
    return candidates,blocked

def _sort_key(c):
    p=policy();return (p["gate_precedence"][c["work_type"]],99 if c["source_pareto_layer"] is None else c["source_pareto_layer"],
        9999 if c["source_rank_order"] is None else c["source_rank_order"],-(c["allocation_share_basis_points"] or 0),c["source_ref"],c["fingerprint"])

def _work_packet(c,created_at,state="QUEUED"):
    core={"schema_version":"1.0.0","scheduler_work_id":"SWORK-"+hashlib.sha256(c["fingerprint"].encode()).hexdigest()[:20].upper(),
          **c,"state":state,"created_at":created_at,"lease_generation":0,"lease_owner":None,"lease_expires_at":None}
    return {**core,"work_hash":hashv(core)}

def _nonterminal_fingerprints(state):
    return {w["fingerprint"] for w in state["work_items"] if w["state"] in {"QUEUED","ACTIVE"}}

def _open_agent_counts(state):
    counts={}
    for w in state["work_items"]:
        if w["state"] in {"QUEUED","ACTIVE"}:
            agent=w["assigned_agent_id"]
            counts[agent]=counts.get(agent,0)+1
    return counts

def _compact_terminal_history(work_items,*,incoming_count,max_items):
    """Retain every open item and only the newest terminal history that fits."""
    open_states={"QUEUED","ACTIVE"}
    open_count=sum(1 for w in work_items if w["state"] in open_states)
    req(open_count+incoming_count<=max_items,"scheduler open queue capacity exceeded")
    terminal_capacity=max_items-open_count-incoming_count
    terminal_indices=[i for i,w in enumerate(work_items) if w["state"] not in open_states]
    keep_terminal=set(terminal_indices[-terminal_capacity:]) if terminal_capacity else set()
    retained=[w for i,w in enumerate(work_items) if w["state"] in open_states or i in keep_terminal]
    evicted=[w["fingerprint"] for i,w in enumerate(work_items) if w["state"] not in open_states and i not in keep_terminal]
    return retained,evicted

def schedule_cycle(state,context=None,*,at=None):
    validate_state(state);at=at or now_iso();disabled,reason=killed()
    if disabled:
        receipt={"schema_version":"1.0.0","cycle_id":"disabled","status":"DISABLED","reason":reason,"finished_at":at,"selected_work":[],"blocked_work":[],"suppressed_duplicates":[],"stale_lease_holds":[]}
        return state,receipt
    context=context or build_context();candidates,blocked=generate_candidates(context)
    completed=set(state["completed_fingerprints"]);open_fp=_nonterminal_fingerprints(state);open_counts=_open_agent_counts(state)
    suppressed=[];stale=[];eligible=[]
    for c in candidates:
        ok,why=_role_valid(c)
        if not ok:
            blocked.append({**c,"selection_reason":c["selection_reason"]+" BLOCKED: "+why,"hard_blockers":sorted(set([*c["hard_blockers"],why]))});continue
        if c["fingerprint"] in completed or c["fingerprint"] in open_fp:
            suppressed.append(c["fingerprint"]);continue
        eligible.append(c)
    # Preserve stale external leases as holds rather than creating overlapping work.
    for w in state["work_items"]:
        if w["state"]=="ACTIVE" and w["lease_expires_at"] is not None:
            try: expired=float(w["lease_expires_at"])<=datetime.fromisoformat(at.replace("Z","+00:00")).timestamp()
            except Exception: expired=False
            if expired:stale.append(w["fingerprint"])
    selected=[];new_counts={}
    scheduler_policy=policy();per_agent_limit=scheduler_policy["max_open_work_per_agent"]
    open_capacity=scheduler_policy["max_queue_items"]-sum(open_counts.values())
    selection_limit=min(scheduler_policy["max_new_work_per_cycle"],open_capacity)
    for c in sorted(eligible,key=_sort_key):
        if len(selected)>=selection_limit:break
        agent=c["assigned_agent_id"]
        if open_counts.get(agent,0)+new_counts.get(agent,0)>=per_agent_limit:continue
        selected.append(_work_packet(c,at));new_counts[agent]=new_counts.get(agent,0)+1
    new_state=json.loads(json.dumps(state))
    new_state["sequence"]+=1;new_state["updated_at"]=at
    retained,compacted=_compact_terminal_history(new_state["work_items"],incoming_count=len(selected),max_items=scheduler_policy["max_queue_items"])
    new_state["work_items"]=[*retained,*selected]
    cycle_seed={"prior_sequence":state["sequence"],"selected":[w["fingerprint"] for w in selected],"blocked":[b["fingerprint"] for b in blocked],"suppressed":sorted(suppressed),"compacted":compacted}
    cid="sched-"+hashlib.sha256(canon(cycle_seed).encode()).hexdigest()[:24]
    receipt={"schema_version":"1.0.0","cycle_id":cid,"status":"PASS","reason":None,"finished_at":at,
             "candidate_count":len(candidates),"selected_work":selected,
             "blocked_work":[_work_packet(b,at,"BLOCKED_APPROVAL" if b["approval_requirements"] else "BLOCKED_POLICY") for b in blocked],
             "suppressed_duplicates":sorted(suppressed),"stale_lease_holds":sorted(stale),"compacted_terminal_work":compacted,
             "selection_method":"EXPLICIT_GATE_PRECEDENCE_THEN_SOURCE_PARETO_RANK_ALLOCATION_SHARE_NO_SCALAR_SCORE"}
    receipt["receipt_hash"]=hashv(receipt)
    new_state["recent_cycles"]=([*new_state["recent_cycles"],{"cycle_id":cid,"finished_at":at,"receipt_hash":receipt["receipt_hash"],"selected_count":len(selected)}])[-20:]
    validate_state(new_state);return new_state,receipt

def mark_work(state,fingerprint,new_state_name):
    validate_state(state);req(new_state_name in {"ACTIVE","COMPLETE","CANCELLED"},"invalid scheduler work transition")
    out=json.loads(json.dumps(state));matches=[w for w in out["work_items"] if w["fingerprint"]==fingerprint];req(len(matches)==1,"scheduler work fingerprint missing/duplicate")
    work=matches[0];allowed={"QUEUED":{"ACTIVE","CANCELLED"},"ACTIVE":{"COMPLETE","CANCELLED"}}
    req(new_state_name in allowed.get(work["state"],set()),"invalid scheduler work state transition");work["state"]=new_state_name
    if new_state_name=="COMPLETE" and fingerprint not in out["completed_fingerprints"]:out["completed_fingerprints"].append(fingerprint)
    validate_state(out);return out

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--state",default="scheduler/live/scheduler_state.json");ap.add_argument("--output-dir",default="scheduler/out")
    args=ap.parse_args();out=Path(args.output_dir);out.mkdir(parents=True,exist_ok=True);state=load_state(args.state)
    state,receipt=schedule_cycle(state)
    (out/"scheduler_state.json").write_text(json.dumps(state,indent=2)+"\n")
    (out/"scheduled_work.json").write_text(json.dumps(receipt["selected_work"],indent=2)+"\n")
    (out/"blocked_work.json").write_text(json.dumps(receipt["blocked_work"],indent=2)+"\n")
    (out/"scheduler_cycle_receipt.json").write_text(json.dumps(receipt,indent=2)+"\n")
    print(json.dumps({"cycle_id":receipt["cycle_id"],"status":receipt["status"],"selected":len(receipt["selected_work"]),"blocked":len(receipt["blocked_work"])}))
if __name__=="__main__":main()
