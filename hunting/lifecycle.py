#!/usr/bin/env python3
"""Deterministic Hunter lifecycle projection with explicit evidence gates.

This is a projection over the existing Hunter proposal/review streams plus an
explicit evidence ledger. It is not a second Hunter, learning, memory, graph,
or factory engine, and it grants no merge/deploy authority.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from hunting.proposal_review_state import validate_state as validate_review_state
from hunting.proposal_state import normalize_state as normalize_proposal_state
from hunting.proposal_state import validate_state as validate_proposal_state

ROOT=Path(__file__).resolve().parents[1]
LEDGER_PATH=ROOT/"hunting"/"HUNTER_LIFECYCLE_EVIDENCE_LEDGER.json"
PROJECTION_ID="portfolio-hunter-lifecycle-v1"
STAGES=(
    "DISCOVERED",
    "REVIEWED",
    "ACCEPTED_FOR_WORK",
    "IMPLEMENTED",
    "TECHNICALLY_VERIFIED",
    "MARKET_VERIFIED",
    "REVENUE_VERIFIED",
)
EVIDENCE_STAGES=STAGES[2:]
PREFIX_BY_STAGE={
    "ACCEPTED_FOR_WORK":"acceptance:",
    "IMPLEMENTED":"implementation:",
    "TECHNICALLY_VERIFIED":"technical-verification:",
    "MARKET_VERIFIED":"market-verification:",
    "REVENUE_VERIFIED":"revenue-verification:",
}
FORBIDDEN_VALUE_REFS=("heartbeat:","notification:","ci-green:","workflow-success:")


class HunterLifecycleError(ValueError):
    pass


def req(ok:bool,msg:str)->None:
    if not ok:
        raise HunterLifecycleError(msg)


def canon(value:Any)->str:
    return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False)


def digest(value:Any)->str:
    return "sha256:"+hashlib.sha256(canon(value).encode("utf-8")).hexdigest()


def _time(value:Any,field:str)->datetime:
    req(isinstance(value,str) and value.endswith("Z"),f"{field} must be UTC ISO-8601")
    try:
        parsed=datetime.fromisoformat(value[:-1]+"+00:00")
    except ValueError as exc:
        raise HunterLifecycleError(f"{field} invalid ISO-8601") from exc
    req(parsed.tzinfo is not None,f"{field} requires timezone")
    return parsed


def load_evidence_ledger(path:Path|None=None)->dict[str,Any]:
    return json.loads((path or LEDGER_PATH).read_text(encoding="utf-8"))


def validate_evidence_record(record:dict[str,Any])->None:
    fields={
        "schema_version","evidence_id","proposal_id","stage","status",
        "source_stage_evidence_hash","observed_at","evidence_refs",
        "market_value_claimed","revenue_value_claimed","evidence_hash",
    }
    req(isinstance(record,dict) and set(record)==fields,"Hunter lifecycle evidence fields changed")
    req(record["schema_version"]=="1.0.0","Hunter lifecycle evidence schema mismatch")
    req(isinstance(record["evidence_id"],str) and record["evidence_id"].startswith("HLEV-"),"Hunter lifecycle evidence id invalid")
    req(isinstance(record["proposal_id"],str) and record["proposal_id"].startswith("HEXP-"),"Hunter lifecycle proposal id invalid")
    req(record["stage"] in EVIDENCE_STAGES,"Hunter lifecycle evidence stage invalid")
    req(record["status"]=="VERIFIED","Hunter lifecycle stage requires VERIFIED evidence")
    req(isinstance(record["source_stage_evidence_hash"],str) and record["source_stage_evidence_hash"].startswith("sha256:"),"Hunter lifecycle predecessor hash invalid")
    _time(record["observed_at"],"Hunter lifecycle observed_at")
    refs=record["evidence_refs"]
    req(isinstance(refs,list) and refs and len(refs)==len(set(refs)) and all(isinstance(x,str) and x for x in refs),"Hunter lifecycle evidence refs invalid")
    required_prefix=PREFIX_BY_STAGE[record["stage"]]
    req(any(ref.startswith(required_prefix) for ref in refs),f"{record['stage']} lacks stage-specific evidence")
    req(not any(ref.startswith(FORBIDDEN_VALUE_REFS) for ref in refs),"heartbeat/notification/green-CI cannot be lifecycle value evidence")
    expected_market=record["stage"] in {"MARKET_VERIFIED","REVENUE_VERIFIED"}
    expected_revenue=record["stage"]=="REVENUE_VERIFIED"
    req(record["market_value_claimed"] is expected_market,"market-value claim does not match evidence stage")
    req(record["revenue_value_claimed"] is expected_revenue,"revenue-value claim does not match evidence stage")
    body=dict(record);given=body.pop("evidence_hash")
    req(given==digest(body),"Hunter lifecycle evidence hash mismatch")


def validate_evidence_ledger(ledger:dict[str,Any])->None:
    req(isinstance(ledger,dict) and set(ledger)=={"schema_version","ledger_id","records"},"Hunter lifecycle ledger fields changed")
    req(ledger["schema_version"]=="1.0.0" and ledger["ledger_id"]=="portfolio-hunter-lifecycle-evidence","Hunter lifecycle ledger identity mismatch")
    req(isinstance(ledger["records"],list),"Hunter lifecycle records invalid")
    ids={}
    for record in ledger["records"]:
        validate_evidence_record(record)
        prior=ids.get(record["evidence_id"])
        req(prior is None or prior==record["evidence_hash"],"conflicting Hunter lifecycle evidence identity")
        ids[record["evidence_id"]]=record["evidence_hash"]


def build_lifecycle(
    proposal_state:dict[str,Any],
    review_state:dict[str,Any],
    evidence_ledger:dict[str,Any]|None=None,
)->dict[str,Any]:
    validate_proposal_state(proposal_state)
    proposal_state=normalize_proposal_state(proposal_state)
    validate_review_state(review_state)
    ledger=evidence_ledger if evidence_ledger is not None else load_evidence_ledger()
    validate_evidence_ledger(ledger)

    findings={row["proposal_id"]:row for row in proposal_state["findings"]}
    reviews={row["proposal_id"]:row for row in review_state["reviews"]}
    evidence_by_proposal:dict[str,list[dict[str,Any]]]={}
    for record in ledger["records"]:
        evidence_by_proposal.setdefault(record["proposal_id"],[]).append(record)

    proposal_ids={row["proposal_id"] for row in proposal_state["proposals"]}
    req(set(reviews)<=proposal_ids,"Hunter review refers to missing proposal")
    req(set(evidence_by_proposal)<=proposal_ids,"Hunter lifecycle evidence refers to missing proposal")

    rows=[]
    for proposal in proposal_state["proposals"]:
        pid=proposal["proposal_id"]
        finding=findings.get(pid)
        req(finding is not None,"Hunter lifecycle finding missing")
        proposal_hash=digest(proposal)
        finding_hash=digest(finding)
        current_stage="DISCOVERED"
        current_hash=proposal_hash
        review_id=None
        review_hash=None

        review=reviews.get(pid)
        if review is not None:
            req(review["finding_id"]==finding["finding_id"],"Hunter review finding identity conflict")
            req(review["project_ids"]==proposal["project_ids"],"Hunter review project identity conflict")
            req(review["repository_full_name"]==finding["repository_full_name"],"Hunter review repository identity conflict")
            req(review["revision"]==finding["revision"],"Hunter review revision identity conflict")
            review_id=review["review_id"]
            review_hash=review["review_hash"]
            current_stage="REVIEWED"
            current_hash=review_hash

        stage_evidence_ids=[]
        records=evidence_by_proposal.get(pid,[])
        records=sorted(records,key=lambda r:(_time(r["observed_at"],"Hunter lifecycle observed_at"),STAGES.index(r["stage"]),r["evidence_id"]))
        seen_stage=set()
        for record in records:
            req(review is not None,"Hunter lifecycle cannot advance an unreviewed finding")
            stage=record["stage"]
            req(stage not in seen_stage,"duplicate Hunter lifecycle stage evidence")
            seen_stage.add(stage)
            expected_index=STAGES.index(current_stage)+1
            req(expected_index<len(STAGES) and stage==STAGES[expected_index],"Hunter lifecycle stage skipping/out-of-order evidence")
            req(record["source_stage_evidence_hash"]==current_hash,"Hunter lifecycle predecessor evidence conflict")
            current_stage=stage
            current_hash=record["evidence_hash"]
            stage_evidence_ids.append(record["evidence_id"])

        core={
            "proposal_id":pid,
            "finding_id":finding["finding_id"],
            "project_ids":proposal["project_ids"],
            "repository_full_name":finding["repository_full_name"],
            "revision":finding["revision"],
            "current_stage":current_stage,
            "source_proposal_hash":proposal_hash,
            "source_finding_hash":finding_hash,
            "review_id":review_id,
            "review_hash":review_hash,
            "stage_evidence_ids":stage_evidence_ids,
            "current_stage_evidence_hash":current_hash,
            "implementation_complete":STAGES.index(current_stage)>=STAGES.index("IMPLEMENTED"),
            "technical_verified":STAGES.index(current_stage)>=STAGES.index("TECHNICALLY_VERIFIED"),
            "market_verified":STAGES.index(current_stage)>=STAGES.index("MARKET_VERIFIED"),
            "revenue_verified":current_stage=="REVENUE_VERIFIED",
            "authority_granted":False,
        }
        rows.append({**core,"lifecycle_hash":digest(core)})

    counts={stage:sum(1 for row in rows if row["current_stage"]==stage) for stage in STAGES}
    core={
        "schema_version":"1.0.0",
        "projection_id":PROJECTION_ID,
        "proposal_state_sequence":proposal_state["sequence"],
        "review_state_sequence":review_state["sequence"],
        "evidence_record_count":len(ledger["records"]),
        "stage_counts":counts,
        "rows":rows,
        "authority_granted":False,
    }
    return {**core,"projection_hash":digest(core)}
