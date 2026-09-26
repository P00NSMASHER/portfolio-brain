#!/usr/bin/env python3
"""Transparent highest-value uncertainty engine.

Selection uses Pareto dominance over eight explicit components, followed by a
documented lexicographic tie-break. No hidden scalar score is computed.
"""
from __future__ import annotations
import copy, json
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parents[1]
COMPONENTS=("importance","uncertainty","test_cost","time_to_evidence","reversibility","downstream_impact","strategic_reuse","external_validation_value")
BENEFITS=("importance","uncertainty","reversibility","downstream_impact","strategic_reuse","external_validation_value")
BURDENS=("test_cost","time_to_evidence")

class UncertaintyError(ValueError): pass
def req(ok,msg):
    if not ok: raise UncertaintyError(msg)
def load(path):
    p=Path(path)
    if not p.is_absolute():p=ROOT/p
    return json.loads(p.read_text())

def policy():return load("uncertainty/UNCERTAINTY_POLICY.json")

def component(value,basis_type,rationale,*refs):
    return {"value":int(value),"basis_type":basis_type,"rationale":rationale,"evidence_refs":list(refs)}

def _project_maps():
    projects=load("registry/projects.json")["projects"]
    graph=load("graph/UNIVERSAL_GRAPH_LEDGER.json")
    by_project={p["project_id"]:p for p in projects}
    node_by_id={n["node_id"]:n for n in graph["nodes"]}
    cap_count={pid:0 for pid in by_project}
    commercial_verified={pid:0 for pid in by_project}
    for e in graph["edges"]:
        if e["status"]!="ACTIVE":continue
        s=node_by_id[e["source_node_id"]];t=node_by_id[e["target_node_id"]]
        if e["edge_type"]=="HAS_CAPABILITY" and e["verification_state"]=="VERIFIED" and s["node_type"]=="PROJECT" and t["node_type"]=="CAPABILITY" and t["verification_state"]=="VERIFIED" and s["canonical_key"] in cap_count:
            cap_count[s["canonical_key"]]+=1
    for n in graph["nodes"]:
        if n["node_type"] in {"OUTCOME","REVENUE","CUSTOMER"} and n["verification_state"]=="VERIFIED":
            for pid in n["project_ids"]:
                if pid in commercial_verified:commercial_verified[pid]+=1
    children={pid:0 for pid in by_project}
    for p in projects:
        if p["parent_project_id"] in children:children[p["parent_project_id"]]+=1
    return projects,by_project,cap_count,commercial_verified,children

def _candidate(uid,qtype,question,pids,components,authority,actionability,approvals,blockers,refs):
    return {
      "schema_version":"1.0.0","uncertainty_id":uid,"question_type":qtype,"question":question,
      "project_ids":pids,"primary_project_id":pids[0],"components":components,
      "authority_requirement":authority,"actionability":actionability,
      "approval_requirements":approvals,"hard_blockers":blockers,"evidence_refs":refs,
      "ranking":{"eligible":actionability!="BLOCKED","pareto_layer":None,"rank_order":None,"selection_reason":None}
    }

def generate_candidates():
    projects,by_project,cap_count,commercial,children=_project_maps()
    candidates=[]
    # Real-world evidence gaps for businesses/products.
    for p in projects:
        pid=p["project_id"]
        if p["registration_state"]!="REGISTERED" or p["lifecycle_status"] in {"PAUSED","RETIRED"}:continue
        if p["project_type"] in {"BUSINESS","PRODUCT"} and commercial[pid]==0:
            business=p["project_type"]=="BUSINESS"
            bounded_commercial=pid in {"PRJ-001","PRJ-002","PRJ-003","PRJ-004"}
            approvals=[] if bounded_commercial else ["CUSTOMER_COMMUNICATION"]
            if "education" in p["categories"]:approvals.append("CONSEQUENTIAL_CHILD_FACING_CHANGE")
            comps={
              "importance":component(5 if business else 4,"DERIVED","Active business/product lacks a verified external outcome in the current graph.",f"registry:{pid}","graph:no-verified-commercial-node"),
              "uncertainty":component(5,"DERIVED","No verified customer/revenue/outcome node is currently linked to this project.",f"graph:project:{pid}","graph:no-verified-commercial-node"),
              "test_cost":component(2,"POLICY_ESTIMATE","A bounded external validation can often be designed before additional product construction; ordinal estimate, not a dollar claim.","policy:cheap-decisive-experiment"),
              "time_to_evidence":component(2,"POLICY_ESTIMATE","A focused validation is expected to reach evidence faster than broad feature construction; ordinal estimate only.","policy:time-to-evidence"),
              "reversibility":component(5,"POLICY_ESTIMATE","A bounded validation can be stopped without production deployment or irreversible system change.","policy:reversibility"),
              "downstream_impact":component(5 if business else 4,"DERIVED","Verified external evidence would materially change commercial/product prioritization.",f"registry:{pid}","policy:outcomes-over-activity"),
              "strategic_reuse":component(5 if children[pid]>0 else 4,"DERIVED","Evidence can inform the project and related portfolio allocation; parent projects receive broader reuse credit.",f"registry:{pid}",f"registry:child-count:{children[pid]}"),
              "external_validation_value":component(5,"DERIVED","This question directly targets real external outcome evidence, which outranks internal activity.","policy:verified-external-value","learning:reward-weight:VERIFIED_EXTERNAL_VALUE=1.0")
            }
            candidates.append(_candidate(
              f"UNC-EXTERNAL-{pid}",
              "EXTERNAL_VALIDATION_GAP",
              f"What is the smallest reversible external validation that can produce the first VERIFIED customer/value outcome for {p['canonical_name']}?",
              [pid],comps,
              "BOUNDED_ACT" if bounded_commercial else "HUMAN_GATED_ACT",
              "READY_FOR_BOUNDED_EXTERNAL_EXECUTION" if bounded_commercial else "HUMAN_APPROVAL_REQUIRED",
              approvals,[],
              [f"registry:{pid}","graph:no-verified-commercial-node","learning:external-value-weight"]
            ))
    # Structural capability-evidence gaps. Absence is explicitly not proof of missing capability.
    for p in projects:
        pid=p["project_id"]
        if p["registration_state"]!="REGISTERED" or p["lifecycle_status"] in {"PAUSED","RETIRED"} or cap_count[pid]>0:continue
        importance=4 if p["project_type"] in {"BUSINESS","PRODUCT"} else 3
        comps={
          "importance":component(importance,"DERIVED","Project currently has no evidence-backed HAS_CAPABILITY edge in the universal graph.",f"registry:{pid}","graph:no-HAS_CAPABILITY-edge"),
          "uncertainty":component(4,"DERIVED","Graph absence means capability coverage is unresolved, not that the capability is absent.",f"graph:project:{pid}"),
          "test_cost":component(1,"POLICY_ESTIMATE","Read-only Hunter search/inspection can narrow this uncertainty without downstream modification.","hunter:observe-only"),
          "time_to_evidence":component(1,"POLICY_ESTIMATE","A bounded exact-revision search can often return structural evidence in one cycle; ordinal estimate only.","hunter:bounded-cycle"),
          "reversibility":component(5,"DERIVED","Information gathering has no downstream modification authority.","hunter:OBSERVE"),
          "downstream_impact":component(4,"DERIVED","Verified reusable capability evidence could change build-vs-reuse decisions.",f"registry:{pid}","policy:reuse-over-duplication"),
          "strategic_reuse":component(4,"DERIVED","A reusable capability may transfer across multiple registered projects.","graph:universal-capability"),
          "external_validation_value":component(2,"DERIVED","This resolves technical uncertainty but does not itself create customer/value evidence.","policy:outcomes-over-activity")
        }
        candidates.append(_candidate(
          f"UNC-CAPABILITY-{pid}","CAPABILITY_EVIDENCE_GAP",
          f"What exact evidence would establish or reject a reusable capability that materially reduces the current build gap for {p['canonical_name']}?",
          [pid],comps,"OBSERVE_ONLY","READY_FOR_INFORMATION_GATHERING",[],[],
          [f"registry:{pid}","graph:no-HAS_CAPABILITY-edge","hunter:public-exact-revision"]
        ))
    # Empty learning ledger: instrument first decision-relevant evidence stream.
    learning=load("learning/LEARNING_OBSERVATION_LEDGER.json")
    if not learning["observations"]:
        comps={
          "importance":component(5,"DERIVED","Portfolio learning cannot become empirical until at least one real observation stream is instrumented.","learning:ledger-empty"),
          "uncertainty":component(5,"DERIVED","No production learning observations exist yet, so cross-domain learning effectiveness is unknown.","learning:source-observations=0"),
          "test_cost":component(1,"POLICY_ESTIMATE","Instrumenting one existing verified receipt stream is lower cost than broad feature construction.","policy:instrument-one-stream"),
          "time_to_evidence":component(1,"POLICY_ESTIMATE","One existing receipt stream can provide evidence quickly once normalized; ordinal estimate only.","policy:time-to-evidence"),
          "reversibility":component(5,"DERIVED","Observation instrumentation is additive and advisory.","learning:policy-effect=NONE"),
          "downstream_impact":component(5,"DERIVED","A real observation stream unlocks evidence-based learning across later scheduling/allocation decisions.","learning:nine-domain-engine"),
          "strategic_reuse":component(5,"DERIVED","The normalized observation contract is reusable across all nine learning domains.","learning:domains=9"),
          "external_validation_value":component(3,"DERIVED","Instrumentation can carry external outcomes when available but does not itself create them.","learning:external-value-weight")
        }
        candidates.append(_candidate(
          "UNC-LEARNING-PRJ-000","LEARNING_MEASUREMENT_GAP",
          "Which existing verified receipt stream should be instrumented first to create the highest-information production learning observation without reconstructing history?",
          ["PRJ-000"],comps,"OBSERVE_ONLY","READY_FOR_INFORMATION_GATHERING",[],[],
          ["learning:ledger-empty","learning:nine-domain-contract","policy:evidence-over-confidence"]
        ))
    # Canary is important but gated by the explicit build sequence.
    build=load("PORTFOLIO_BUILD_STATE.json")
    if (build.get("step_progress",{}).get("8",{}).get("activation_status")=="STAGED_ON_ISOLATED_BRANCH_NOT_SCHEDULED_ON_DEFAULT_BRANCH"):
        comps={
          "importance":component(5,"DERIVED","The end state requires ordinary operation without an interactive prompt.","step8:staged-runtime","mission:self-triggering"),
          "uncertainty":component(4,"DERIVED","CI validates the runtime code, but the complete autonomous canary loop has not yet been executed.","step8:ci-pass","step24:not-yet-run"),
          "test_cost":component(1,"POLICY_ESTIMATE","A bounded canary is low-cost once later gates are complete.","policy:bounded-canary"),
          "time_to_evidence":component(1,"POLICY_ESTIMATE","A single bounded runtime cycle is a short evidence path once authorized.","policy:time-to-evidence"),
          "reversibility":component(5,"DERIVED","Canary/shadow execution is designed to be non-consequential and kill-switchable.","runtime:kill-switch"),
          "downstream_impact":component(5,"DERIVED","A successful no-prompt cycle is prerequisite evidence for autonomous operating mode.","step24:autonomous-learning-canary"),
          "strategic_reuse":component(5,"DERIVED","Runtime canary evidence applies to the whole Portfolio Brain.","project:PRJ-000"),
          "external_validation_value":component(1,"DERIVED","This is infrastructure evidence, not customer/value validation.","policy:outcomes-over-activity")
        }
        candidates.append(_candidate(
          "UNC-CANARY-PRJ-000","AUTONOMY_CANARY_GAP",
          "Can Portfolio Brain complete one fully bounded no-prompt autonomous cycle with durable state restoration and zero authority violations?",
          ["PRJ-000"],comps,"BOUNDED_EXPERIMENT","BLOCKED",[],["STEP-24-CANARY-GATE"],
          ["step8:runtime-staged","step24:future-gate"]
        ))
    # Known source/governance blocker remains visible rather than disappearing from prioritization.
    blockers={b["blocker_id"]:b for b in build["blockers"] if b["status"]=="OPEN"}
    if "BLK-001" in blockers:
        comps={
          "importance":component(4,"DERIVED","The blocker prevents full PermitPlate repository observation.","blocker:BLK-001","registry:PRJ-003"),
          "uncertainty":component(4,"DERIVED","Safe intended visibility/access controls remain unresolved.","blocker:BLK-001"),
          "test_cost":component(1,"POLICY_ESTIMATE","The next step is a human governance decision, not engineering work.","policy:human-decision"),
          "time_to_evidence":component(1,"POLICY_ESTIMATE","Resolution can be immediate once the owner decides intended visibility/control.","policy:human-decision"),
          "reversibility":component(5,"POLICY_ESTIMATE","Visibility/integration can remain blocked until a safe decision is made.","adapter:REPO-006-blocked"),
          "downstream_impact":component(4,"DERIVED","Resolution would unlock complete PermitPlate observation while preserving sensitive-state controls.","registry:PRJ-003","adapter:REPO-006"),
          "strategic_reuse":component(3,"DERIVED","The visibility decision pattern informs other sensitive state repositories.","policy:data-boundary"),
          "external_validation_value":component(1,"DERIVED","This is governance/integration uncertainty, not market validation.","policy:outcomes-over-activity")
        }
        candidates.append(_candidate(
          "UNC-BLOCKER-PRJ-003","BLOCKED_SOURCE_GAP",
          "What repository visibility and access-control decision safely resolves PermitPlate state integration without exposing sensitive operational state?",
          ["PRJ-003"],comps,"HUMAN_GATED_ACT","BLOCKED",["REPOSITORY_VISIBILITY_OR_ACCESS_CONTROL_DECISION"],["BLK-001"],
          ["blocker:BLK-001","registry:PRJ-003","adapter:REPO-006"]
        ))
    return candidates

def component_values(c):
    return {k:c["components"][k]["value"] for k in COMPONENTS}

def dominates(a,b):
    av=component_values(a);bv=component_values(b)
    no_worse=all(av[k]>=bv[k] for k in BENEFITS) and all(av[k]<=bv[k] for k in BURDENS)
    strictly=any(av[k]>bv[k] for k in BENEFITS) or any(av[k]<bv[k] for k in BURDENS)
    return no_worse and strictly

def pareto_layers(candidates):
    remaining=[c for c in candidates if c["ranking"]["eligible"]]
    layer=0;layers={}
    while remaining:
        front=[c for c in remaining if not any(dominates(other,c) for other in remaining if other is not c)]
        req(front,"pareto ranking failed to find a front")
        for c in front:layers[c["uncertainty_id"]]=layer
        ids={c["uncertainty_id"] for c in front}
        remaining=[c for c in remaining if c["uncertainty_id"] not in ids]
        layer+=1
    return layers

def _tie_key(c):
    v=component_values(c)
    return (
      -v["external_validation_value"],-v["importance"],-v["uncertainty"],
      -v["downstream_impact"],-v["strategic_reuse"],v["test_cost"],v["time_to_evidence"],
      -v["reversibility"],c["primary_project_id"],c["uncertainty_id"]
    )

def rank_candidates(candidates):
    rows=copy.deepcopy(candidates);layers=pareto_layers(rows)
    eligible=[c for c in rows if c["ranking"]["eligible"]]
    eligible.sort(key=lambda c:(layers[c["uncertainty_id"]],*_tie_key(c)))
    for i,c in enumerate(eligible,1):
        c["ranking"]["pareto_layer"]=layers[c["uncertainty_id"]]
        c["ranking"]["rank_order"]=i
        c["ranking"]["selection_reason"]=(
          "Pareto layer first; ties use the explicit component order in UNCERTAINTY_POLICY.json. "
          "No scalar score is computed."
        )
    by_id={c["uncertainty_id"]:c for c in eligible}
    for c in rows:
        if c["uncertainty_id"] in by_id:
            c["ranking"]=by_id[c["uncertainty_id"]]["ranking"]
        else:
            c["ranking"]["selection_reason"]="Blocked candidates remain visible but are excluded from actionable ranking."
    rows.sort(key=lambda c:(c["ranking"]["rank_order"] is None,c["ranking"]["rank_order"] or 9999,c["uncertainty_id"]))
    return rows

def build_snapshot(generated_at=None):
    candidates=rank_candidates(generate_candidates())
    eligible=[c for c in candidates if c["ranking"]["eligible"]]
    req(eligible,"no eligible uncertainty candidates")
    selected=min(eligible,key=lambda c:c["ranking"]["rank_order"])
    front=[c["uncertainty_id"] for c in eligible if c["ranking"]["pareto_layer"]==0]
    return {
      "schema_version":"1.0.0","generated_at":generated_at,
      "ranking_method":policy()["ranking"]["method"],
      "candidate_count":len(candidates),"eligible_candidate_count":len(eligible),
      "pareto_front_candidate_ids":front,
      "selected_uncertainty_id":selected["uncertainty_id"],
      "selected_question":selected["question"],
      "selected_components":component_values(selected),
      "selected_authority_requirement":selected["authority_requirement"],
      "selected_actionability":selected["actionability"],
      "selected_approval_requirements":selected["approval_requirements"],
      "candidates":candidates
    }

def summary(snapshot):
    return {
      "schema_version":"1.0.0",
      "candidate_count":snapshot["candidate_count"],
      "eligible_candidate_count":snapshot["eligible_candidate_count"],
      "pareto_front_candidate_ids":snapshot["pareto_front_candidate_ids"],
      "selected_uncertainty_id":snapshot["selected_uncertainty_id"],
      "selected_question":snapshot["selected_question"],
      "selected_components":snapshot["selected_components"],
      "selected_authority_requirement":snapshot["selected_authority_requirement"],
      "selected_actionability":snapshot["selected_actionability"],
      "selected_approval_requirements":snapshot["selected_approval_requirements"]
    }
