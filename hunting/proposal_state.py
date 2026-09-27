#!/usr/bin/env python3
"""Durable sanitized inbox of quality-gated Hunter experiment proposals."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hunting.autonomous_hunter import digest, load_policy, validate_state as validate_hunter_state

ROOT=Path(__file__).resolve().parents[1]
SEED_PATH=ROOT/"hunting"/"HUNTER_PROPOSAL_STATE_SEED.json"
STATE_ID="portfolio-hunter-proposal-state"
ARTIFACT_NAME="portfolio-hunter-proposal-state"

class HunterProposalStateError(ValueError):
    pass

def req(ok:bool,msg:str)->None:
    if not ok:
        raise HunterProposalStateError(msg)

def load_seed_state()->dict[str,Any]:
    return json.loads(SEED_PATH.read_text(encoding="utf-8"))

def _rank_value(band:str)->int:
    order={"LOW":0,"MEDIUM":1,"HIGH":2}
    req(band in order,"proposal rank band invalid")
    return order[band]

def validate_state(state:dict[str,Any])->None:
    required={
      "schema_version","state_id","sequence","updated_at","cycle_id","cycle_receipt_hash",
      "authority_class","rights_state","proposals","findings"
    }
    req(isinstance(state,dict) and set(state)==required,"Hunter proposal state fields changed")
    req(state["schema_version"]=="1.0.0" and state["state_id"]==STATE_ID,"Hunter proposal state identity mismatch")
    req(type(state["sequence"]) is int and state["sequence"]>=0,"Hunter proposal state sequence invalid")
    req(state["updated_at"] is None or isinstance(state["updated_at"],str),"Hunter proposal state updated_at invalid")
    req(state["cycle_id"] is None or isinstance(state["cycle_id"],str),"Hunter proposal cycle id invalid")
    req(state["cycle_receipt_hash"] is None or (isinstance(state["cycle_receipt_hash"],str) and state["cycle_receipt_hash"].startswith("sha256:")),"Hunter proposal cycle receipt hash invalid")
    req(state["authority_class"]=="OBSERVE","Hunter proposal inbox authority widened")
    req(state["rights_state"]=="NOT_GRANTED_BY_DISCOVERY","Hunter proposal inbox improperly granted reuse rights")
    req(isinstance(state["proposals"],list) and isinstance(state["findings"],list),"Hunter proposal inbox lists invalid")

    gate=load_policy()["candidate_evaluation"]["proposal_gate"]
    maxn=gate["max_experiment_proposals_per_cycle"]
    req(len(state["proposals"])<=maxn,"Hunter proposal inbox exceeds cycle proposal cap")
    if state["sequence"]==0:
        req(state["cycle_id"] is None and state["cycle_receipt_hash"] is None,"seed proposal state may not claim a cycle")
        req(state["proposals"]==[] and state["findings"]==[],"seed proposal state must be empty")

    proposal_ids=set()
    proposal_by_finding={}
    for proposal in state["proposals"]:
        expected={
          "schema_version","proposal_id","finding_id","gap_id","project_ids",
          "candidate_rank_score","candidate_rank_band","candidate_soft_signals",
          "hypothesis","baseline","success_condition","failure_condition",
          "evidence_requirements","cost_boundary","rollback","candidate_rank_order"
        }
        req(isinstance(proposal,dict) and set(proposal)==expected,"Hunter proposal fields changed")
        req(proposal["schema_version"]=="1.0.0","Hunter proposal schema mismatch")
        req(isinstance(proposal["proposal_id"],str) and proposal["proposal_id"].startswith("HEXP-"),"Hunter proposal id invalid")
        req(proposal["proposal_id"] not in proposal_ids,"duplicate Hunter proposal id");proposal_ids.add(proposal["proposal_id"])
        req(isinstance(proposal["finding_id"],str) and proposal["finding_id"],"Hunter proposal finding id missing")
        req(proposal["finding_id"] not in proposal_by_finding,"multiple proposals reference one finding")
        proposal_by_finding[proposal["finding_id"]]=proposal
        req(isinstance(proposal["project_ids"],list) and proposal["project_ids"],"Hunter proposal projects missing")
        req(type(proposal["candidate_rank_score"]) is int and 0<=proposal["candidate_rank_score"]<=10,"Hunter proposal rank score invalid")
        req(_rank_value(proposal["candidate_rank_band"])>=_rank_value(gate["minimum_rank_band"]),"Hunter proposal below quality gate")
        req(type(proposal["candidate_rank_order"]) is int and proposal["candidate_rank_order"]>=1,"Hunter proposal rank order invalid")
        req(isinstance(proposal["candidate_soft_signals"],list),"Hunter proposal soft signals invalid")
        req(isinstance(proposal["evidence_requirements"],list) and proposal["evidence_requirements"],"Hunter proposal evidence requirements missing")

    finding_ids=set()
    for finding in state["findings"]:
        expected={
          "finding_id","proposal_id","gap_id","capability_key","project_ids","strategy_id","candidate_fingerprint",
          "repository_full_name","repository_id","revision","public","rank_score","rank_band",
          "soft_signals","inspection","provenance_refs"
        }
        req(isinstance(finding,dict) and set(finding)==expected,"Hunter proposal finding fields changed")
        req(finding["finding_id"] not in finding_ids,"duplicate Hunter proposal finding");finding_ids.add(finding["finding_id"])
        req(finding["finding_id"] in proposal_by_finding,"proposal finding has no matching proposal")
        proposal=proposal_by_finding[finding["finding_id"]]
        req(finding["proposal_id"]==proposal["proposal_id"],"proposal/finding id lineage mismatch")
        req(isinstance(finding["capability_key"],str) and finding["capability_key"].startswith("capability-coverage:"),"proposal finding capability key invalid")
        req(finding["project_ids"]==proposal["project_ids"],"proposal/finding project lineage mismatch")
        req(finding["rank_score"]==proposal["candidate_rank_score"] and finding["rank_band"]==proposal["candidate_rank_band"],"proposal/finding rank lineage mismatch")
        req(finding["public"] is True,"proposal finding source is not public")
        req(isinstance(finding["repository_full_name"],str) and "/" in finding["repository_full_name"],"proposal finding repository invalid")
        req(type(finding["repository_id"]) is int and finding["repository_id"]>0,"proposal finding repository id invalid")
        req(isinstance(finding["revision"],str) and len(finding["revision"])==40 and all(c in "0123456789abcdef" for c in finding["revision"]),"proposal finding exact revision invalid")
        req(isinstance(finding["provenance_refs"],list) and finding["provenance_refs"],"proposal finding provenance missing")
        inspection=finding["inspection"]
        req(isinstance(inspection,dict),"proposal finding inspection missing")
        req(inspection.get("source_path_count",0)>0,"proposal finding lacks implementation evidence")
    req(finding_ids==set(proposal_by_finding),"Hunter proposal inbox proposal/finding coverage mismatch")

def build_proposal_state(hunter_state:dict[str,Any],receipt:dict[str,Any])->dict[str,Any]:
    validate_hunter_state(hunter_state)
    req(receipt.get("status")=="PASS","Hunter proposal state requires PASS cycle")
    body=dict(receipt);given=body.pop("receipt_hash",None)
    req(isinstance(given,str) and given==digest(body),"Hunter cycle receipt hash mismatch")
    proposals=list(receipt.get("experiment_proposals") or [])
    by_finding={row["finding_id"]:row for row in receipt.get("findings") or []}
    by_objective={row["objective_id"]:row for row in receipt.get("objectives") or []}
    findings=[]
    for proposal in proposals:
        finding=by_finding.get(proposal["finding_id"])
        req(finding is not None,"Hunter proposal references missing finding")
        req(finding.get("disposition")=="RETAIN","Hunter proposal finding is not retained")
        req(finding.get("proposal_eligibility")=="SELECTED","Hunter proposal finding did not pass proposal selection")
        req(finding.get("experiment_proposal_id")==proposal["proposal_id"],"Hunter proposal finding linkage mismatch")
        source=finding["source"];ranking=finding["ranking"]
        objective=by_objective.get(finding["objective_id"])
        req(objective is not None,"Hunter proposal finding objective missing")
        findings.append({
          "finding_id":finding["finding_id"],
          "proposal_id":proposal["proposal_id"],
          "gap_id":finding["gap_id"],
          "capability_key":objective["capability_key"],
          "project_ids":finding["project_ids"],
          "strategy_id":finding["strategy_id"],
          "candidate_fingerprint":finding["candidate_fingerprint"],
          "repository_full_name":source["repository_full_name"],
          "repository_id":int(source["repository_id"]),
          "revision":source["revision"],
          "public":source["public"],
          "rank_score":ranking["score"],
          "rank_band":ranking["band"],
          "soft_signals":ranking["soft_signal_codes"],
          "inspection":finding["inspection"],
          "provenance_refs":finding["provenance_refs"],
        })
    state={
      "schema_version":"1.0.0",
      "state_id":STATE_ID,
      "sequence":hunter_state["sequence"],
      "updated_at":hunter_state["updated_at"],
      "cycle_id":receipt["cycle_id"],
      "cycle_receipt_hash":receipt["receipt_hash"],
      "authority_class":"OBSERVE",
      "rights_state":"NOT_GRANTED_BY_DISCOVERY",
      "proposals":proposals,
      "findings":findings,
    }
    validate_state(state)
    return state
