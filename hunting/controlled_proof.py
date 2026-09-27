#!/usr/bin/env python3
"""Live controlled proof for Portfolio Brain Hunter.

The proof exercises real public GitHub metadata and exact-revision tree reads
through the same bounded provider and classifier used by Hunter. It does not
execute discovered code, mutate downstream systems, or infer reuse rights.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from hunting.autonomous_hunter import (
    GitHubPublicProvider,
    candidate_fingerprint,
    classify_candidate,
    digest,
    experiment_proposal,
    load_policy,
    load_seed_state,
    load_strategies,
    structural_inspection,
)

ROOT=Path(__file__).resolve().parents[1]
CASES_PATH=ROOT/"hunting"/"CONTROLLED_PROOF_CASES.json"

class ControlledProofError(ValueError):
    pass

def req(ok: bool,msg: str)->None:
    if not ok:
        raise ControlledProofError(msg)

def load_cases(path:Path=CASES_PATH)->dict[str,Any]:
    doc=json.loads(path.read_text(encoding="utf-8"))
    req(set(doc)=={"schema_version","proof_id","authority_class","purpose","completion_gate","cases"},"controlled proof fields changed")
    req(doc["schema_version"]=="1.0.0","controlled proof schema mismatch")
    req(doc["authority_class"]=="OBSERVE","controlled proof authority widened")
    gate=doc["completion_gate"]
    req(type(gate.get("min_retained_candidates")) is int and gate["min_retained_candidates"]>=3,"controlled proof retained gate too weak")
    req(type(gate.get("min_distinct_strategies")) is int and gate["min_distinct_strategies"]>=2,"controlled proof strategy gate too weak")
    req(gate.get("require_exact_revision") is True and gate.get("require_public_source") is True,"controlled proof source gates weakened")
    req(gate.get("require_downstream_experiment_acceptance") is True,"controlled proof downstream gate missing")
    strategies={x["strategy_id"] for x in load_strategies()}
    ids=set()
    for case in doc["cases"]:
        required={"case_id","repository_full_name","expected_repository_id","strategy_id","project_ids","gap_id","capability_key","expected_min_rank"}
        req(set(case)==required,f"controlled proof case fields changed: {case.get('case_id')}")
        req(case["case_id"] not in ids,"duplicate controlled proof case");ids.add(case["case_id"])
        req(case["strategy_id"] in strategies,"unknown controlled proof strategy")
        req(case["project_ids"] and len(case["project_ids"])==len(set(case["project_ids"])),"controlled proof projects invalid")
        req(case["capability_key"].startswith("capability-coverage:"),"controlled proof capability invalid")
        req(case["expected_min_rank"] in {"LOW","MEDIUM","HIGH"},"controlled proof rank gate invalid")
    return doc

def _objective(case:dict[str,Any])->dict[str,Any]:
    return {
      "schema_version":"1.0.0",
      "objective_id":"HOBJ-CONTROLLED-"+case["case_id"],
      "gap_id":case["gap_id"],
      "project_ids":case["project_ids"],
      "need_type":"CONTROLLED_PROOF",
      "capability_key":case["capability_key"],
      "strategy_id":case["strategy_id"],
      "exploration":False,
      "priority_components":{"importance":5,"uncertainty":3,"downstream_reuse":4,"external_validation_value":3,"dead_end_penalty":0},
      "queries":[],
      "acceptance_target":"Retain an exact public repository revision with implementation-level structural evidence and route it only to bounded experiment review.",
      "stop_conditions":["Public GitHub only.","Do not execute discovered code.","Do not infer reuse rights.","Do not modify downstream systems."],
      "authority_class":"OBSERVE",
    }

def _rank_value(band:str)->int:
    return {"LOW":0,"MEDIUM":1,"HIGH":2}[band]

def run_controlled_proof(provider:Any|None=None,cases_doc:dict[str,Any]|None=None)->dict[str,Any]:
    cases_doc=cases_doc or load_cases()
    provider=provider or GitHubPublicProvider(os.environ.get("PORTFOLIO_GITHUB_TOKEN"),load_policy())
    state=load_seed_state()
    rows=[]
    proposals=[]
    for case in cases_doc["cases"]:
        metadata=provider.repository_metadata(case["repository_full_name"])
        req(metadata.get("private") is False,"controlled proof repository is not public")
        req(int(metadata.get("id"))==int(case["expected_repository_id"]),"controlled proof repository identity drift")
        candidate={
          "id":int(metadata["id"]),
          "full_name":metadata["full_name"],
          "default_branch":metadata.get("default_branch") or "main",
          "private":False,
        }
        inspection=provider.inspect(candidate)
        objective=_objective(case)
        structural=structural_inspection(candidate,inspection,objective)
        fp=candidate_fingerprint(candidate,inspection["revision"],objective)
        disposition,negative,trace=classify_candidate(state,fp,structural,load_policy())
        rank=trace["ranking"]
        finding_id="HFD-CONTROLLED-"+case["case_id"]
        finding={
          "schema_version":"1.0.0",
          "finding_id":finding_id,
          "objective_id":objective["objective_id"],
          "gap_id":case["gap_id"],
          "project_ids":case["project_ids"],
          "strategy_id":case["strategy_id"],
          "candidate_fingerprint":fp,
          "source":{
            "source_kind":"PUBLIC_GITHUB",
            "repository_full_name":candidate["full_name"],
            "repository_id":candidate["id"],
            "revision":inspection["revision"],
            "public":True,
          },
          "inspection":structural,
          "capability_hypothesis":f"{candidate['full_name']}@{inspection['revision']} contains implementation structure worth bounded evaluation for {case['capability_key']}.",
          "evidence_state":"OBSERVED" if disposition=="RETAIN" else "UNKNOWN",
          "disposition":disposition,
          "provenance_refs":[
            f"github:{candidate['full_name']}@{inspection['revision']}",
            f"hunter-controlled-proof:{case['case_id']}",
          ],
          "negative_reason":negative,
          "ranking":rank,
          "decision_trace":{
            **trace,
            "public_source_gate":True,
            "exact_revision_gate":isinstance(inspection["revision"],str) and len(inspection["revision"])==40,
          },
          "experiment_proposal_id":None,
        }
        proposal=None
        if disposition=="RETAIN":
            proposal=experiment_proposal(finding)
            finding["experiment_proposal_id"]=proposal["proposal_id"]
            proposals.append(proposal)
        rows.append({
          "case_id":case["case_id"],
          "repository_full_name":candidate["full_name"],
          "repository_id":candidate["id"],
          "revision":inspection["revision"],
          "strategy_id":case["strategy_id"],
          "project_ids":case["project_ids"],
          "capability_key":case["capability_key"],
          "disposition":disposition,
          "negative_reason":negative,
          "rank_score":rank["score"],
          "rank_band":rank["band"],
          "expected_min_rank":case["expected_min_rank"],
          "rank_gate_passed":_rank_value(rank["band"])>=_rank_value(case["expected_min_rank"]),
          "public_source":True,
          "exact_revision":len(inspection["revision"])==40,
          "implementation_path_count":structural["source_path_count"],
          "test_path_count":structural["test_path_count"],
          "provenance_refs":finding["provenance_refs"],
          "experiment_proposal_id":finding["experiment_proposal_id"],
          "finding":finding,
        })
    retained=[x for x in rows if x["disposition"]=="RETAIN"]
    distinct_strategies=sorted({x["strategy_id"] for x in retained})
    downstream=[
        {
          "acceptance_id":"HACC-"+x["case_id"],
          "finding_id":x["finding"]["finding_id"],
          "proposal_id":x["experiment_proposal_id"],
          "project_ids":x["project_ids"],
          "status":"ACCEPTED_FOR_BOUNDED_EXPERIMENT_REVIEW",
          "authority_granted":False,
          "evidence_upgraded":False,
        }
        for x in retained if x["experiment_proposal_id"]
    ]
    gate=cases_doc["completion_gate"]
    checks={
      "retained_candidate_gate":len(retained)>=gate["min_retained_candidates"],
      "distinct_strategy_gate":len(distinct_strategies)>=gate["min_distinct_strategies"],
      "public_source_gate":all(x["public_source"] for x in retained),
      "exact_revision_gate":all(x["exact_revision"] for x in retained),
      "implementation_evidence_gate":all(x["implementation_path_count"]>0 for x in retained),
      "rank_gate":all(x["rank_gate_passed"] for x in retained),
      "downstream_acceptance_gate":bool(downstream),
      "provenance_gate":all(x["provenance_refs"] for x in retained),
    }
    status="PASS" if all(checks.values()) else "FAIL"
    report={
      "schema_version":"1.0.0",
      "proof_id":cases_doc["proof_id"],
      "authority_class":"OBSERVE",
      "status":status,
      "completion_gate":gate,
      "checks":checks,
      "retained_candidate_count":len(retained),
      "distinct_strategy_count":len(distinct_strategies),
      "distinct_strategies":distinct_strategies,
      "provider_api_requests":getattr(provider,"requests",None),
      "candidate_results":rows,
      "experiment_proposals":proposals,
      "downstream_acceptances":downstream,
      "rights_state":"NOT_GRANTED_BY_DISCOVERY",
      "code_execution_performed":False,
      "downstream_mutation_performed":False,
    }
    report["proof_hash"]=digest(report)
    return report

def main()->None:
    ap=argparse.ArgumentParser()
    ap.add_argument("--output",type=Path,default=Path("hunting/out/controlled_proof.json"))
    args=ap.parse_args()
    report=run_controlled_proof()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps({
      "status":report["status"],
      "retained_candidates":report["retained_candidate_count"],
      "distinct_strategies":report["distinct_strategy_count"],
      "downstream_acceptances":len(report["downstream_acceptances"]),
      "proof_hash":report["proof_hash"],
    },sort_keys=True))
    if report["status"]!="PASS":
        raise SystemExit(1)

if __name__=="__main__":
    main()
