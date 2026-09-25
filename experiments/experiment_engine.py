#!/usr/bin/env python3
"""Deterministic bounded experiment planner and outcome validator."""
from __future__ import annotations
import copy, hashlib, json
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parents[1]
class ExperimentError(ValueError): pass
def req(ok,msg):
    if not ok:raise ExperimentError(msg)
def load(path):
    p=Path(path)
    if not p.is_absolute():p=ROOT/p
    return json.loads(p.read_text())
def canon(v):return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False)
def hashv(v):return "sha256:"+hashlib.sha256(canon(v).encode()).hexdigest()
def policy():return load("experiments/EXPERIMENT_POLICY.json")
def _time(value,field):
    req(isinstance(value,str) and value,f"{field} required")
    try:dt=datetime.fromisoformat(value.replace("Z","+00:00"))
    except ValueError as exc:raise ExperimentError(f"{field} invalid ISO-8601") from exc
    req(dt.tzinfo is not None,f"{field} requires timezone")
    return dt

def _project_map():
    return {p["project_id"]:p for p in load("registry/projects.json")["projects"]}

def _conditions(c,project):
    name=project["canonical_name"];qtype=c["question_type"]
    if qtype=="EXTERNAL_VALIDATION_GAP":
        return (
          f"An owner-approved bounded external validation can produce decision-changing VERIFIED outcome evidence for {name} without requiring a production deployment, payment, or uncontrolled system change.",
          "The current Portfolio Brain evidence graph contains no VERIFIED CUSTOMER, REVENUE, or OUTCOME node linked to this project; this is an evidence baseline, not a claim that no real-world validation exists elsewhere.",
          "A permitted validation yields independently VERIFIED evidence that materially supports the stated customer/value hypothesis and can be recorded as an external outcome event.",
          "A permitted validation yields independently VERIFIED disconfirming evidence or a predeclared negative result that falsifies the hypothesis.",
          "Silence, missing authority, ambiguous attribution, unavailable external state, or an incomplete validation window remains INCONCLUSIVE rather than being forced to PASSED or FAILED."
        )
    if qtype=="CAPABILITY_EVIDENCE_GAP":
        return (
          f"A bounded exact-revision evidence acquisition can establish or reject one reusable capability hypothesis relevant to {name} without modifying the downstream project.",
          "The universal graph currently has no evidence-backed HAS_CAPABILITY edge for this project; graph absence is uncertainty, not proof of capability absence.",
          "Independent inspection verifies implementation-level behavior, meaningful tests/negative controls, exact revision, and a lawful bounded reuse path relevant to the gap.",
          "The bounded search/inspection finds no candidate meeting the predeclared implementation/test/evidence gate or independently falsifies the candidate capability hypothesis.",
          "Insufficient public evidence, unresolved rights, correlated/self-authored proof, or ambiguous mapping remains INCONCLUSIVE."
        )
    if qtype=="LEARNING_MEASUREMENT_GAP":
        return (
          "Normalizing one existing VERIFIED receipt stream through the Step 10 observation contract can create a real production learning observation without reconstructing history or weakening evidence state.",
          "The production learning-observation ledger is empty and therefore has no empirical observations eligible for policy consideration.",
          "At least one existing independently VERIFIED receipt is mapped losslessly into a valid learning observation with source evidence, denominators/unknowns preserved, and zero fabricated historical fields.",
          "The chosen receipt cannot be mapped without inventing missing evidence, weakening verification, or conflating internal activity with external value.",
          "A candidate receipt is technically mappable but lacks enough provenance/denominator information to produce a decision-usable observation."
        )
    if qtype=="AUTONOMY_CANARY_GAP":
        return (
          "A bounded non-consequential canary can complete a no-prompt cycle with durable state restoration and zero authority violations.",
          "The runtime is CI-verified but recurring default-branch operation and the Step 24 complete canary have not been executed.",
          "The later authorized canary completes the full bounded loop, restores durable state, records evidence, and reports zero authority violations.",
          "The canary fails to restore state, exceeds a budget, duplicates work, violates an authority boundary, or cannot complete the required loop.",
          "Infrastructure/provider unavailability prevents a valid canary verdict."
        )
    return (
      "Resolving the blocked governance question can enable safe observation without weakening privacy or authority controls.",
      "The repository/source remains blocked by an explicit governance condition.",
      "The blocker is resolved by an explicit authorized decision with preserved privacy/access controls and a verifiable integration boundary.",
      "The proposed resolution would expose sensitive state, weaken access controls, or create unsupported authority.",
      "The owner has not yet supplied the decision needed to adjudicate the blocker."
    )

def _mode_and_status(c):
    if c["actionability"]=="BLOCKED":return "BLOCKED","BLOCKED",False
    if c["authority_requirement"]=="HUMAN_GATED_ACT" or c["actionability"]=="HUMAN_APPROVAL_REQUIRED":
        return "HUMAN_GATED_EXTERNAL_VALIDATION","HUMAN_APPROVAL_REQUIRED",False
    if c["authority_requirement"]=="BOUNDED_EXPERIMENT":
        return "ISOLATED_SYNTHETIC_TEST","READY_FOR_ISOLATED_EXECUTION",True
    return "READ_ONLY_EVIDENCE_ACQUISITION","READY_FOR_ISOLATED_EXECUTION",True

def _rollback(mode,status):
    if status=="HUMAN_APPROVAL_REQUIRED":
        return {"mode":"NO_SIDE_EFFECTS","steps":["Do not initiate any external action before explicit approval.","If approval is not present, leave the experiment in planning state."]}
    if status=="BLOCKED":
        return {"mode":"NO_SIDE_EFFECTS","steps":["Preserve the blocker and do not execute.","Rebuild the plan only after the blocking evidence/state changes."]}
    if mode=="ISOLATED_SYNTHETIC_TEST":
        return {"mode":"DISCARD_ISOLATED_ARTIFACTS","steps":["Run only in an isolated/synthetic environment.","On failure, discard candidate artifacts and retain the evidence receipt."]}
    return {"mode":"NO_SIDE_EFFECTS","steps":["Perform read-only evidence acquisition only.","Persist only sanitized references/receipts; no downstream mutation requires rollback."]}

def plan_from_uncertainty(c):
    projects=_project_map();primary=projects[c["primary_project_id"]]
    mode,status,auto=_mode_and_status(c)
    hypothesis,baseline,success,failure,inconclusive=_conditions(c,primary)
    inputs=[{"kind":"PROJECT_REGISTRY","ref":f"registry:{pid}","required":True} for pid in c["project_ids"]]
    inputs += [{"kind":"UNCERTAINTY_EVIDENCE","ref":ref,"required":True} for ref in c["evidence_refs"]]
    if status=="HUMAN_APPROVAL_REQUIRED":
        inputs += [
          {"kind":"HUMAN_APPROVAL","ref":"explicit-approval-required-at-execution","required":True},
          {"kind":"PRIVATE_EXTERNAL_TARGET_REFERENCE","ref":"private-reference-required-at-execution","required":True}
        ]
    hard=sorted({b for pid in c["project_ids"] for b in projects[pid].get("hard_boundaries",[])})
    cost=c["components"]["test_cost"];tte=c["components"]["time_to_evidence"]
    req(cost["basis_type"]=="POLICY_ESTIMATE" and tte["basis_type"]=="POLICY_ESTIMATE","cost/time basis must remain policy estimate")
    base={
      "schema_version":"1.0.0","uncertainty_id":c["uncertainty_id"],"project_ids":c["project_ids"],
      "primary_project_id":c["primary_project_id"],"status":status,"execution_mode":mode,
      "authority_requirement":c["authority_requirement"],"autonomous_execution_allowed":auto,
      "approval_requirements":c["approval_requirements"],"hard_blockers":c["hard_blockers"],
      "inherited_hard_boundaries":hard,"hypothesis":hypothesis,"inputs":inputs,"baseline":baseline,
      "success_condition":success,"failure_condition":failure,"inconclusive_condition":inconclusive,
      "evidence_requirements":[
        "Exact source/experiment identity and immutable plan revision.",
        "Evidence IDs and event IDs sufficient to reproduce the verdict.",
        "Independent verifier for any definitive PASSED or FAILED result.",
        "Explicit preservation of UNKNOWN/INCONCLUSIVE when evidence is insufficient.",
        "Authority/approval receipt before any human-gated ACT."
      ],
      "cost_boundary":{
        "test_cost_ordinal":cost["value"],"time_to_evidence_ordinal":tte["value"],"basis_type":"POLICY_ESTIMATE",
        **policy()["hard_resource_ceiling"]
      },
      "rollback":_rollback(mode,status),
      "outcome_recording":{
        "ledger":"experiments/EXPERIMENT_OUTCOME_LEDGER.json","definitive_evidence_state":"VERIFIED",
        "independent_verifier_required":True,"allowed_results":policy()["outcome_results"]
      },
      "uncertainty_components":copy.deepcopy(c["components"]),
      "provenance_refs":list(dict.fromkeys([f"uncertainty:{c['uncertainty_id']}",*c["evidence_refs"]]))
    }
    semantic=hashv(base)
    exp_id="PEXP-"+hashlib.sha256((c["uncertainty_id"]+"\0"+semantic).encode()).hexdigest()[:16].upper()
    with_identity={"experiment_id":exp_id,"semantic_revision":semantic,**base}
    return {**with_identity,"experiment_hash":hashv(with_identity)}

def validate_plan(plan):
    required={
      "schema_version","experiment_id","semantic_revision","uncertainty_id","project_ids","primary_project_id",
      "status","execution_mode","authority_requirement","autonomous_execution_allowed","approval_requirements",
      "hard_blockers","inherited_hard_boundaries","hypothesis","inputs","baseline","success_condition",
      "failure_condition","inconclusive_condition","evidence_requirements","cost_boundary","rollback",
      "outcome_recording","uncertainty_components","provenance_refs","experiment_hash"
    }
    req(isinstance(plan,dict) and set(plan)==required,"experiment plan fields changed")
    req(plan["status"] in policy()["plan_statuses"],"invalid experiment status")
    req(plan["execution_mode"] in policy()["execution_modes"],"invalid execution mode")
    if plan["status"]!="READY_FOR_ISOLATED_EXECUTION":req(plan["autonomous_execution_allowed"] is False,"gated/blocked experiment cannot be autonomous")
    if plan["authority_requirement"]=="HUMAN_GATED_ACT":
        req(plan["status"]=="HUMAN_APPROVAL_REQUIRED","human-gated ACT must remain approval-required")
        req(plan["approval_requirements"],"human-gated ACT requires approval requirements")
    if "NO_AUTONOMOUS_TRADING" in plan["inherited_hard_boundaries"]:
        req(plan["authority_requirement"]!="HUMAN_GATED_ACT","trading research plan cannot create ACT authority")
    c=plan["cost_boundary"]
    req(c["autonomous_cash_spend_usd_max"]==0 and c["model_calls_max"]==0 and c["external_messages_max"]==0 and c["downstream_writes_max"]==0,"resource authority widened")
    req(c["basis_type"]=="POLICY_ESTIMATE","cost basis changed")
    copy_plan=dict(plan);given=copy_plan.pop("experiment_hash")
    req(given==hashv(copy_plan),"experiment_hash mismatch")
    semantic_body={k:v for k,v in copy_plan.items() if k not in {"experiment_id","semantic_revision"}}
    req(plan["semantic_revision"]==hashv(semantic_body),"semantic_revision mismatch")

def build_experiment_portfolio(uncertainty_snapshot):
    plans=[plan_from_uncertainty(c) for c in uncertainty_snapshot["candidates"]]
    for p in plans:validate_plan(p)
    by_unc={p["uncertainty_id"]:p for p in plans}
    selected=by_unc[uncertainty_snapshot["selected_uncertainty_id"]]
    return {
      "schema_version":"1.0.0",
      "source_ranking_method":uncertainty_snapshot["ranking_method"],
      "selected_uncertainty_id":uncertainty_snapshot["selected_uncertainty_id"],
      "selected_experiment_id":selected["experiment_id"],
      "plan_count":len(plans),
      "status_counts":{s:sum(1 for p in plans if p["status"]==s) for s in policy()["plan_statuses"]},
      "plans":plans
    }

def validate_outcome(o,plans_by_id=None):
    required={"schema_version","outcome_id","experiment_id","result","evidence_state","evidence_ids","event_ids","actor_id","verifier_actor_id","started_at","completed_at","observed_metrics","decision_effect","provenance_refs","outcome_hash"}
    req(isinstance(o,dict) and set(o)==required,"experiment outcome fields changed")
    req(o["result"] in policy()["outcome_results"],"invalid outcome result")
    req(o["evidence_state"] in {"OBSERVED","VERIFIED","INFERRED","UNKNOWN","CONTRADICTED","STALE","INVALID"},"invalid outcome evidence state")
    req(o["evidence_ids"] and o["event_ids"] and o["provenance_refs"],"outcome provenance/evidence required")
    start=_time(o["started_at"],"started_at");end=_time(o["completed_at"],"completed_at");req(end>=start,"outcome completes before start")
    if o["result"] in {"PASSED","FAILED"}:
        req(o["evidence_state"]=="VERIFIED","definitive outcome requires VERIFIED evidence")
        req(isinstance(o["verifier_actor_id"],str) and o["verifier_actor_id"],"definitive outcome requires verifier")
        req(o["verifier_actor_id"]!=o["actor_id"],"builder/actor cannot solely verify definitive outcome")
    if o["result"]=="INCONCLUSIVE":req(o["decision_effect"]=="NO_DECISION_CHANGE","inconclusive outcome cannot claim decision change")
    if o["result"]=="INVALID":req(o["decision_effect"]=="INVALID_EXPERIMENT","invalid outcome effect mismatch")
    if plans_by_id is not None:req(o["experiment_id"] in plans_by_id,"outcome references unknown experiment")
    body=dict(o);given=body.pop("outcome_hash");req(given==hashv(body),"outcome_hash mismatch")
