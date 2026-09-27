#!/usr/bin/env python3
"""Durable sanitized backlog of quality-gated Hunter experiment proposals.

The proposal artifact is a continuation inbox, not a snapshot of only the most
recent Hunter cycle. New quality-gated proposals are merged into the prior
validated backlog, deduplicated by proposal_id, and retained under a bounded
capacity so a delayed scheduler cannot silently lose useful discoveries.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hunting.autonomous_hunter import digest, load_policy, validate_state as validate_hunter_state

ROOT=Path(__file__).resolve().parents[1]
SEED_PATH=ROOT/"hunting"/"HUNTER_PROPOSAL_STATE_SEED.json"
STATE_ID="portfolio-hunter-proposal-state"
ARTIFACT_NAME="portfolio-hunter-proposal-state"

LEGACY_FIELDS={
  "schema_version","state_id","sequence","updated_at","cycle_id","cycle_receipt_hash",
  "authority_class","rights_state","proposals","findings"
}
CURRENT_FIELDS=LEGACY_FIELDS|{"origins"}
ORIGIN_FIELDS={
  "first_cycle_id","first_cycle_receipt_hash","first_seen_at","first_hunter_sequence",
  "last_cycle_id","last_cycle_receipt_hash","last_seen_at","last_hunter_sequence"
}

class HunterProposalStateError(ValueError):
    pass

def req(ok:bool,msg:str)->None:
    if not ok:
        raise HunterProposalStateError(msg)

def _time(value:Any,field:str)->datetime:
    req(isinstance(value,str) and value.endswith("Z"),f"Hunter proposal {field} must be UTC ISO-8601")
    try:
        parsed=datetime.fromisoformat(value[:-1]+"+00:00")
    except ValueError as exc:
        raise HunterProposalStateError(f"Hunter proposal {field} invalid") from exc
    return parsed.astimezone(timezone.utc)

def load_seed_state()->dict[str,Any]:
    return json.loads(SEED_PATH.read_text(encoding="utf-8"))

def _rank_value(band:str)->int:
    order={"LOW":0,"MEDIUM":1,"HIGH":2}
    req(band in order,"proposal rank band invalid")
    return order[band]

def normalize_state(state:dict[str,Any])->dict[str,Any]:
    """Upgrade the original single-cycle artifact shape in memory.

    Existing durable artifacts from before backlog continuity remain admissible.
    Because the old artifact held exactly one cycle, every contained proposal can
    be bound to the old top-level cycle metadata without inventing provenance.
    """
    req(isinstance(state,dict),"Hunter proposal state must be object")
    out=json.loads(json.dumps(state))
    fields=set(out)
    if fields==LEGACY_FIELDS:
        origins={}
        proposals=out.get("proposals") or []
        if proposals:
            req(out.get("cycle_id") is not None,"legacy proposal state missing cycle id")
            req(out.get("cycle_receipt_hash") is not None,"legacy proposal state missing cycle receipt hash")
            req(out.get("updated_at") is not None,"legacy proposal state missing updated_at")
            req(type(out.get("sequence")) is int and out["sequence"]>0,"legacy proposal state sequence invalid")
        for proposal in proposals:
            proposal_id=proposal.get("proposal_id")
            req(isinstance(proposal_id,str) and proposal_id,"legacy proposal id missing")
            origins[proposal_id]={
              "first_cycle_id":out["cycle_id"],
              "first_cycle_receipt_hash":out["cycle_receipt_hash"],
              "first_seen_at":out["updated_at"],
              "first_hunter_sequence":out["sequence"],
              "last_cycle_id":out["cycle_id"],
              "last_cycle_receipt_hash":out["cycle_receipt_hash"],
              "last_seen_at":out["updated_at"],
              "last_hunter_sequence":out["sequence"],
            }
        out["origins"]=origins
    return out

def validate_state(state:dict[str,Any])->None:
    state=normalize_state(state)
    req(set(state)==CURRENT_FIELDS,"Hunter proposal state fields changed")
    req(state["schema_version"]=="1.0.0" and state["state_id"]==STATE_ID,"Hunter proposal state identity mismatch")
    req(type(state["sequence"]) is int and state["sequence"]>=0,"Hunter proposal state sequence invalid")
    req(state["updated_at"] is None or isinstance(state["updated_at"],str),"Hunter proposal state updated_at invalid")
    req(state["cycle_id"] is None or isinstance(state["cycle_id"],str),"Hunter proposal cycle id invalid")
    req(state["cycle_receipt_hash"] is None or (isinstance(state["cycle_receipt_hash"],str) and state["cycle_receipt_hash"].startswith("sha256:")),"Hunter proposal cycle receipt hash invalid")
    req(state["authority_class"]=="OBSERVE","Hunter proposal inbox authority widened")
    req(state["rights_state"]=="NOT_GRANTED_BY_DISCOVERY","Hunter proposal inbox improperly granted reuse rights")
    req(isinstance(state["proposals"],list) and isinstance(state["findings"],list),"Hunter proposal inbox lists invalid")
    req(isinstance(state["origins"],dict),"Hunter proposal origin map invalid")

    persistence=load_policy()["proposal_persistence"]
    maxn=persistence["max_backlog_proposals"]
    req(type(maxn) is int and 6<=maxn<=256,"Hunter proposal backlog capacity invalid")
    req(persistence["carry_forward_prior_proposals"] is True,"Hunter proposal carry-forward disabled")
    req(persistence["origin_metadata_required"] is True,"Hunter proposal origin metadata disabled")
    req(persistence["compaction_policy"]=="DROP_OLDEST_LAST_SEEN_ONLY_AFTER_BACKLOG_CAP","Hunter proposal compaction policy drifted")
    req(len(state["proposals"])<=maxn,"Hunter proposal inbox exceeds backlog cap")
    if state["sequence"]==0:
        req(state["cycle_id"] is None and state["cycle_receipt_hash"] is None,"seed proposal state may not claim a cycle")
        req(state["updated_at"] is None,"seed proposal state may not claim updated_at")
        req(state["proposals"]==[] and state["findings"]==[] and state["origins"]=={},"seed proposal state must be empty")
    else:
        req(isinstance(state["cycle_id"],str) and state["cycle_id"],"nonempty Hunter sequence requires latest cycle id")
        req(isinstance(state["cycle_receipt_hash"],str) and state["cycle_receipt_hash"].startswith("sha256:"),"nonempty Hunter sequence requires latest cycle receipt")
        _time(state["updated_at"],"updated_at")

    gate=load_policy()["candidate_evaluation"]["proposal_gate"]
    proposal_ids=set()
    proposal_by_finding={}
    proposal_by_id={}
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
        proposal_by_id[proposal["proposal_id"]]=proposal
        req(isinstance(proposal["finding_id"],str) and proposal["finding_id"],"Hunter proposal finding id missing")
        req(proposal["finding_id"] not in proposal_by_finding,"multiple proposals reference one finding")
        proposal_by_finding[proposal["finding_id"]]=proposal
        req(isinstance(proposal["project_ids"],list) and proposal["project_ids"],"Hunter proposal projects missing")
        req(type(proposal["candidate_rank_score"]) is int and 0<=proposal["candidate_rank_score"]<=10,"Hunter proposal rank score invalid")
        req(_rank_value(proposal["candidate_rank_band"])>=_rank_value(gate["minimum_rank_band"]),"Hunter proposal below quality gate")
        req(type(proposal["candidate_rank_order"]) is int and proposal["candidate_rank_order"]>=1,"Hunter proposal rank order invalid")
        req(isinstance(proposal["candidate_soft_signals"],list),"Hunter proposal soft signals invalid")
        req(isinstance(proposal["evidence_requirements"],list) and proposal["evidence_requirements"],"Hunter proposal evidence requirements missing")

    req(set(state["origins"])==proposal_ids,"Hunter proposal origin coverage mismatch")
    updated_at=None if state["updated_at"] is None else _time(state["updated_at"],"updated_at")
    for proposal_id,origin in state["origins"].items():
        req(isinstance(origin,dict) and set(origin)==ORIGIN_FIELDS,"Hunter proposal origin fields changed")
        for field in ("first_cycle_id","last_cycle_id"):
            req(isinstance(origin[field],str) and origin[field],"Hunter proposal origin cycle id invalid")
        for field in ("first_cycle_receipt_hash","last_cycle_receipt_hash"):
            req(isinstance(origin[field],str) and origin[field].startswith("sha256:"),"Hunter proposal origin receipt hash invalid")
        first_at=_time(origin["first_seen_at"],"first_seen_at")
        last_at=_time(origin["last_seen_at"],"last_seen_at")
        req(first_at<=last_at,"Hunter proposal origin chronology invalid")
        if updated_at is not None:
            req(last_at<=updated_at,"Hunter proposal origin newer than state")
        req(type(origin["first_hunter_sequence"]) is int and origin["first_hunter_sequence"]>=1,"Hunter proposal first sequence invalid")
        req(type(origin["last_hunter_sequence"]) is int and origin["last_hunter_sequence"]>=origin["first_hunter_sequence"],"Hunter proposal last sequence invalid")
        req(origin["last_hunter_sequence"]<=state["sequence"],"Hunter proposal origin sequence exceeds state")
        req(proposal_id in proposal_by_id,"Hunter proposal origin references missing proposal")

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

def _cycle_entries(receipt:dict[str,Any])->tuple[list[dict[str,Any]],list[dict[str,Any]]]:
    proposals=list(receipt.get("experiment_proposals") or [])
    all_findings=list(receipt.get("findings") or [])
    by_objective={row["objective_id"]:row for row in receipt.get("objectives") or []}
    findings=[]
    for proposal in proposals:
        matches=[
          row for row in all_findings
          if row.get("finding_id")==proposal["finding_id"]
          and row.get("experiment_proposal_id")==proposal["proposal_id"]
          and row.get("proposal_eligibility")=="SELECTED"
          and row.get("disposition")=="RETAIN"
        ]
        req(len(matches)==1,"Hunter proposal must bind exactly one selected retained finding")
        finding=matches[0]
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
    return proposals,findings

def build_proposal_state(
    hunter_state:dict[str,Any],
    receipt:dict[str,Any],
    *,
    prior_state:dict[str,Any]|None=None,
)->dict[str,Any]:
    validate_hunter_state(hunter_state)
    req(receipt.get("status")=="PASS","Hunter proposal state requires PASS cycle")
    body=dict(receipt);given=body.pop("receipt_hash",None)
    req(isinstance(given,str) and given==digest(body),"Hunter cycle receipt hash mismatch")
    prior=normalize_state(prior_state if prior_state is not None else load_seed_state())
    validate_state(prior)
    req(hunter_state["sequence"]>=prior["sequence"],"Hunter proposal state sequence rollback")

    current_proposals,current_findings=_cycle_entries(receipt)
    proposal_by_id={row["proposal_id"]:json.loads(json.dumps(row)) for row in prior["proposals"]}
    finding_by_proposal={row["proposal_id"]:json.loads(json.dumps(row)) for row in prior["findings"]}
    origins=json.loads(json.dumps(prior["origins"]))
    order=[row["proposal_id"] for row in prior["proposals"]]
    current_findings_by_id={row["proposal_id"]:row for row in current_findings}
    for proposal in current_proposals:
        proposal_id=proposal["proposal_id"]
        proposal_by_id[proposal_id]=json.loads(json.dumps(proposal))
        finding_by_proposal[proposal_id]=json.loads(json.dumps(current_findings_by_id[proposal_id]))
        if proposal_id not in order:
            order.append(proposal_id)
        existing=origins.get(proposal_id)
        if existing is None:
            origins[proposal_id]={
              "first_cycle_id":receipt["cycle_id"],
              "first_cycle_receipt_hash":receipt["receipt_hash"],
              "first_seen_at":receipt["finished_at"],
              "first_hunter_sequence":hunter_state["sequence"],
              "last_cycle_id":receipt["cycle_id"],
              "last_cycle_receipt_hash":receipt["receipt_hash"],
              "last_seen_at":receipt["finished_at"],
              "last_hunter_sequence":hunter_state["sequence"],
            }
        else:
            existing["last_cycle_id"]=receipt["cycle_id"]
            existing["last_cycle_receipt_hash"]=receipt["receipt_hash"]
            existing["last_seen_at"]=receipt["finished_at"]
            existing["last_hunter_sequence"]=hunter_state["sequence"]

    maxn=load_policy()["proposal_persistence"]["max_backlog_proposals"]
    if len(order)>maxn:
        keep=set(sorted(
          order,
          key=lambda proposal_id:(
            origins[proposal_id]["last_hunter_sequence"],
            origins[proposal_id]["last_seen_at"],
            proposal_id,
          ),
          reverse=True,
        )[:maxn])
        order=[proposal_id for proposal_id in order if proposal_id in keep]
        proposal_by_id={proposal_id:row for proposal_id,row in proposal_by_id.items() if proposal_id in keep}
        finding_by_proposal={proposal_id:row for proposal_id,row in finding_by_proposal.items() if proposal_id in keep}
        origins={proposal_id:row for proposal_id,row in origins.items() if proposal_id in keep}

    state={
      "schema_version":"1.0.0",
      "state_id":STATE_ID,
      "sequence":hunter_state["sequence"],
      "updated_at":hunter_state["updated_at"],
      "cycle_id":receipt["cycle_id"],
      "cycle_receipt_hash":receipt["receipt_hash"],
      "authority_class":"OBSERVE",
      "rights_state":"NOT_GRANTED_BY_DISCOVERY",
      "proposals":[proposal_by_id[proposal_id] for proposal_id in order],
      "findings":[finding_by_proposal[proposal_id] for proposal_id in order],
      "origins":{proposal_id:origins[proposal_id] for proposal_id in order},
    }
    validate_state(state)
    return state
