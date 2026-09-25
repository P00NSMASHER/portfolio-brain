#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,math
from datetime import datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
class TransferError(ValueError):pass
def req(ok,msg):
    if not ok:raise TransferError(msg)
def load(path):
    p=Path(path)
    if not p.is_absolute():p=ROOT/p
    return json.loads(p.read_text())
def canon(v):return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False)
def hashv(v):return "sha256:"+hashlib.sha256(canon(v).encode()).hexdigest()
def policy():return load("transfer/TRANSFER_POLICY.json")
def rules_doc():return load("transfer/CAPABILITY_TRANSFER_RULES.json")
def _time(v,field):
    req(isinstance(v,str) and v,f"{field} required")
    try:dt=datetime.fromisoformat(v.replace("Z","+00:00"))
    except ValueError as exc:raise TransferError(f"{field} invalid timestamp") from exc
    req(dt.tzinfo is not None,f"{field} requires timezone");return dt
def _project_doc(projects=None):return projects or load("registry/projects.json")["projects"]
def _graph_doc(graph=None):return graph or load("graph/UNIVERSAL_GRAPH_LEDGER.json")
def _uncertainty_doc(snapshot=None):
    if snapshot is not None:return snapshot
    from uncertainty.highest_value_uncertainty import build_snapshot
    return build_snapshot()
def _build_state_doc(build_state=None):return build_state or load("PORTFOLIO_BUILD_STATE.json")
def _rule_for(key,rules=None):
    rows=(rules or rules_doc())["rules"];matches=[r for r in rows if r["capability_key"]==key]
    return matches[0] if len(matches)==1 else None
def _target_matches_rule(project,rule):
    if rule["universal"]:return True
    if rule["repository_required"] and project.get("repository_bindings"):return True
    if set(project.get("categories") or []).intersection(set(rule.get("target_any_categories") or [])):return True
    return project.get("project_type") in set(rule.get("target_any_project_types") or [])
def _open_blockers_for_project(project,build):
    repo_ids={r["repository_id"] for r in project.get("repository_bindings") or []};out=[]
    for b in build.get("blockers") or []:
        if b.get("status")!="OPEN":continue
        if b.get("blocker_id")=="BLK-001" and "REPO-006" in repo_ids:out.append("BLK-001")
        if b.get("blocker_id")=="BLK-005":out.append("BLK-005-PUBLIC-REPO-SANITIZED-ONLY")
    return out

def detect_transfer_hypotheses(graph=None,projects=None,uncertainty_snapshot=None,build_state=None,rules=None):
    graph=_graph_doc(graph);projects=_project_doc(projects);uncertainty=_uncertainty_doc(uncertainty_snapshot);build=_build_state_doc(build_state)
    node={n["node_id"]:n for n in graph["nodes"]};project_by={p["project_id"]:p for p in projects}
    cap_nodes={n["node_id"]:n for n in graph["nodes"] if n["node_type"]=="CAPABILITY" and n["verification_state"]=="VERIFIED"}
    need_by={c["primary_project_id"]:c for c in uncertainty["candidates"] if c["question_type"]=="CAPABILITY_EVIDENCE_GAP"}
    held={}
    for e in graph["edges"]:
        if e["status"]=="ACTIVE" and e["edge_type"]=="HAS_CAPABILITY" and e["verification_state"]=="VERIFIED":
            s=node.get(e["source_node_id"]);c=node.get(e["target_node_id"])
            if s and c and s["node_type"]=="PROJECT" and c["node_type"]=="CAPABILITY":held.setdefault(s["canonical_key"],set()).add(c["canonical_key"])
    proposals=[]
    for e in graph["edges"]:
        if e["status"]!="ACTIVE" or e["edge_type"]!="HAS_CAPABILITY" or e["verification_state"]!="VERIFIED":continue
        source=node.get(e["source_node_id"]);cap=cap_nodes.get(e["target_node_id"])
        if not source or not cap or source["node_type"]!="PROJECT":continue
        source_pid=source["canonical_key"]
        if source_pid not in project_by:continue
        rule=_rule_for(cap["canonical_key"],rules)
        if rule is None:continue
        source_refs=list(dict.fromkeys([*cap["provenance_refs"],*e["provenance_refs"]]))
        req(source_refs,"verified source capability missing provenance")
        for target in projects:
            tid=target["project_id"]
            if tid==source_pid or target["registration_state"]!="REGISTERED" or target["lifecycle_status"] in {"PAUSED","RETIRED"}:continue
            if cap["canonical_key"] in held.get(tid,set()):continue
            need=need_by.get(tid)
            if need is None or not _target_matches_rule(target,rule):continue
            blockers=_open_blockers_for_project(target,build);state="BLOCKED" if "BLK-001" in blockers else "ASSESSMENT_READY"
            core={"schema_version":"1.0.0","source_project_id":source_pid,"source_capability_node_id":cap["node_id"],"source_capability_key":cap["canonical_key"],
                  "target_project_id":tid,"target_need_uncertainty_id":need["uncertainty_id"],"applicability_rule_id":rule["rule_id"],"experiment_kind":rule["experiment_kind"],
                  "state":state,"authority_requirement":"OBSERVE_ONLY","implementation_allowed":False,"hard_blockers":blockers,"rights_review_required":True,
                  "source_capability_provenance":source_refs,"target_need_evidence_refs":list(dict.fromkeys([*need["evidence_refs"],f"uncertainty:{need['uncertainty_id']}"])),
                  "hypothesis":f"Capability {cap['canonical_key']} from {source_pid} may reduce the evidenced capability gap in {tid}; applicability and value remain unverified until a target-context experiment succeeds.",
                  "bounded_experiment":{
                    "baseline":"Target has an evidenced capability-coverage uncertainty and no VERIFIED matching HAS_CAPABILITY edge.",
                    "success_condition":"A bounded target-context implementation or interface experiment produces independently VERIFIED measurable improvement on a predeclared target metric with zero authority violations.",
                    "failure_condition":"The target-context experiment produces independently VERIFIED no-value or regression evidence, or the capability cannot satisfy the target need without violating rights/data/authority boundaries.",
                    "inconclusive_condition":"Target evidence, rights, implementation identity, measurement window, or verifier evidence is insufficient for a definitive value conclusion.",
                    "evidence_requirements":["Exact source capability provenance and source project identity.","Target need evidence and predeclared target metric.","Rights/license verification before code or asset reuse.","Step 16 target-repository onboarding before any MODIFY.","Independent verifier receipt for a definitive target outcome."],
                    "measurement_requirement":"Record one predeclared numeric target metric with baseline, observed value, unit, direction, measurable delta, evidence IDs and target outcome event.",
                    "rollback":"Assessment is read-only. Any later implementation must be isolated/reversible through Step 16 and may not bypass Step 17 repair or human ACT gates."},
                  "provenance_refs":list(dict.fromkeys([*source_refs,*need["evidence_refs"],f"transfer-rule:{rule['rule_id']}"]))}
            transfer_id="XFER-"+hashlib.sha256(canon(core).encode()).hexdigest()[:20].upper();packet={"transfer_id":transfer_id,**core}
            proposals.append({**packet,"proposal_hash":hashv(packet)})
    return sorted(proposals,key=lambda x:(x["state"]!="ASSESSMENT_READY",x["target_project_id"],x["source_capability_key"],x["transfer_id"]))

def validate_proposal(p):
    req(p["proposal_hash"]==hashv({k:v for k,v in p.items() if k!="proposal_hash"}),"proposal hash mismatch")
    req(p["source_project_id"]!=p["target_project_id"],"self transfer prohibited");req(p["state"] in policy()["proposal_states"],"invalid proposal state")
    req(p["authority_requirement"]=="OBSERVE_ONLY" and p["implementation_allowed"] is False,"proposal granted implementation authority")
    req(p["rights_review_required"] is True,"rights review gate missing");req(p["source_capability_provenance"] and p["target_need_evidence_refs"] and p["provenance_refs"],"proposal provenance incomplete")

def validate_outcome(o,proposal):
    required={"schema_version","outcome_id","transfer_id","source_capability_key","target_project_id","result","evidence_state","actor_agent_id","verifier_agent_id","implementation_evidence_ids","measurement_evidence_ids","metric_name","metric_unit","metric_direction","baseline_value","observed_value","measurable_delta","authority_violations","started_at","completed_at","outcome_event_id","provenance_refs","outcome_hash"}
    req(isinstance(o,dict) and set(o)==required,"outcome fields changed");req(o["outcome_hash"]==hashv({k:v for k,v in o.items() if k!="outcome_hash"}),"outcome hash mismatch")
    req(o["transfer_id"]==proposal["transfer_id"] and o["source_capability_key"]==proposal["source_capability_key"] and o["target_project_id"]==proposal["target_project_id"],"outcome/proposal binding mismatch")
    req(o["result"] in policy()["outcome_results"],"invalid outcome result");req(o["implementation_evidence_ids"] and o["measurement_evidence_ids"] and o["provenance_refs"],"outcome evidence missing")
    req(_time(o["completed_at"],"completed_at")>=_time(o["started_at"],"started_at"),"outcome completes before start")
    for k in ["baseline_value","observed_value","measurable_delta"]:req(type(o[k]) in {int,float} and math.isfinite(float(o[k])),"invalid metric value")
    req(o["measurable_delta"]>=0 and o["authority_violations"]>=0,"invalid delta/authority counter")
    if o["result"] in {"VERIFIED_EFFECTIVE","VERIFIED_NO_VALUE"}:
        req(o["evidence_state"]=="VERIFIED","definitive transfer outcome must be VERIFIED");req(o["verifier_agent_id"] in policy()["independent_verifier_agent_ids"],"independent verifier required");req(o["verifier_agent_id"]!=o["actor_agent_id"],"actor cannot independently verify own transfer")
    if o["result"]=="VERIFIED_EFFECTIVE":
        req(o["authority_violations"]==0,"effective transfer cannot contain authority violations")
        expected=float(o["observed_value"])-float(o["baseline_value"]) if o["metric_direction"]=="HIGHER_BETTER" else float(o["baseline_value"])-float(o["observed_value"])
        req(expected>0 and abs(float(o["measurable_delta"])-expected)<1e-9,"effective metric improvement mismatch")
    if o["result"]=="VERIFIED_NO_VALUE":req(o["measurable_delta"]==0,"no-value outcome must have zero improvement")
    if o["result"]=="INCONCLUSIVE":req(o["measurable_delta"]==0,"inconclusive outcome cannot claim improvement")

def verified_success_edge_candidates(proposals,outcomes,graph=None):
    graph=_graph_doc(graph);proposal_by={p["transfer_id"]:p for p in proposals};project_node={n["canonical_key"]:n["node_id"] for n in graph["nodes"] if n["node_type"]=="PROJECT"};edges=[]
    for o in outcomes:
        p=proposal_by.get(o["transfer_id"]);req(p is not None,"outcome references unknown transfer");validate_outcome(o,p)
        if o["result"]!="VERIFIED_EFFECTIVE":continue
        target=project_node.get(p["target_project_id"]);req(target is not None,"target project graph node missing")
        refs=list(dict.fromkeys([*o["implementation_evidence_ids"],*o["measurement_evidence_ids"],*o["provenance_refs"],f"transfer-outcome:{o['outcome_id']}"]))
        for edge_type in ["REUSED_BY","GENERATED_VALUE_FOR"]:
            core={"source_node_id":p["source_capability_node_id"],"target_node_id":target,"edge_type":edge_type,"verification_state":"VERIFIED","status":"ACTIVE","provenance_refs":refs,"transfer_id":p["transfer_id"],"outcome_id":o["outcome_id"]}
            edges.append({**core,"edge_candidate_hash":hashv(core)})
    return edges

def build_transfer_state(uncertainty_snapshot=None):
    proposals=detect_transfer_hypotheses(uncertainty_snapshot=uncertainty_snapshot)
    for p in proposals:validate_proposal(p)
    ledger=load("transfer/TRANSFER_LEDGER.json");edges=verified_success_edge_candidates(proposals,ledger["outcomes"])
    return {"schema_version":"1.0.0","proposal_count":len(proposals),"assessment_ready":sum(1 for p in proposals if p["state"]=="ASSESSMENT_READY"),"blocked":sum(1 for p in proposals if p["state"]=="BLOCKED"),"checked_in_outcomes":len(ledger["outcomes"]),"verified_success_edge_candidates":len(edges),"proposals":proposals,"success_edge_candidates":edges}
