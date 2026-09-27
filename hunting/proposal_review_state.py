#!/usr/bin/env python3
"""Durable sanitized evidence-review state for quality-gated Hunter proposals."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parents[1]
SEED=ROOT/"hunting"/"HUNTER_PROPOSAL_REVIEW_STATE_SEED.json"
STATE_ID="portfolio-hunter-proposal-review-state"
ARTIFACT_NAME="portfolio-hunter-proposal-review-state"
MAX_REVIEWS=100

class HunterProposalReviewError(ValueError):
    pass

def req(ok:bool,msg:str)->None:
    if not ok:
        raise HunterProposalReviewError(msg)

def canon(v:Any)->str:
    return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False)

def digest(v:Any)->str:
    return "sha256:"+hashlib.sha256(canon(v).encode()).hexdigest()

def now_iso()->str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00","Z")

def load_seed_state()->dict[str,Any]:
    return json.loads(SEED.read_text(encoding="utf-8"))

def validate_state(state:dict[str,Any])->None:
    req(isinstance(state,dict),"proposal review state must be object")
    req(set(state)=={"schema_version","state_id","sequence","updated_at","applied_execution_ids","reviews"},"proposal review state fields changed")
    req(state["schema_version"]=="1.0.0" and state["state_id"]==STATE_ID,"proposal review state identity mismatch")
    req(type(state["sequence"]) is int and state["sequence"]>=0,"proposal review sequence invalid")
    req(state["updated_at"] is None or isinstance(state["updated_at"],str),"proposal review updated_at invalid")
    req(isinstance(state["applied_execution_ids"],list),"proposal review applied ids invalid")
    req(len(state["applied_execution_ids"])==len(set(state["applied_execution_ids"])),"duplicate proposal review execution id")
    req(isinstance(state["reviews"],list) and len(state["reviews"])<=MAX_REVIEWS,"proposal review history invalid")
    review_ids=set()
    execution_ids=set()
    for row in state["reviews"]:
        expected={
          "review_id","proposal_id","finding_id","project_ids","repository_full_name","repository_id",
          "revision","tree_sha","rank_score","rank_band","capability_key","license_spdx_id","license_name",
          "license_state","rights_state","reuse_authorized","implementation_authorized",
          "code_execution_performed","downstream_mutation_performed","source_execution_id",
          "source_execution_receipt_hash","reviewed_at","evidence_refs","review_hash"
        }
        req(isinstance(row,dict) and set(row)==expected,"proposal review fields changed")
        req(isinstance(row["review_id"],str) and row["review_id"].startswith("HREV-"),"proposal review id invalid")
        req(row["review_id"] not in review_ids,"duplicate proposal review id");review_ids.add(row["review_id"])
        req(isinstance(row["proposal_id"],str) and row["proposal_id"].startswith("HEXP-"),"proposal review proposal id invalid")
        req(isinstance(row["finding_id"],str) and row["finding_id"],"proposal review finding id invalid")
        req(isinstance(row["project_ids"],list) and row["project_ids"],"proposal review projects missing")
        req(isinstance(row["repository_full_name"],str) and "/" in row["repository_full_name"],"proposal review repository invalid")
        req(type(row["repository_id"]) is int and row["repository_id"]>0,"proposal review repository id invalid")
        for field in ("revision","tree_sha"):
            req(isinstance(row[field],str) and len(row[field])==40 and all(c in "0123456789abcdef" for c in row[field]),f"proposal review {field} invalid")
        req(type(row["rank_score"]) is int and 0<=row["rank_score"]<=10,"proposal review rank score invalid")
        req(row["rank_band"] in {"MEDIUM","HIGH"},"proposal review rank band invalid")
        req(isinstance(row["capability_key"],str) and row["capability_key"].startswith("capability-coverage:"),"proposal review capability invalid")
        req(row["license_spdx_id"] is None or isinstance(row["license_spdx_id"],str),"proposal review SPDX id invalid")
        req(row["license_name"] is None or isinstance(row["license_name"],str),"proposal review license name invalid")
        req(row["license_state"] in {"LICENSE_METADATA_PRESENT_REQUIRES_REVIEW","NO_LICENSE_METADATA_REQUIRES_REVIEW"},"proposal review license state invalid")
        req(row["rights_state"]=="UNKNOWN_REQUIRES_REVIEW","proposal review improperly resolved rights")
        req(row["reuse_authorized"] is False,"proposal review improperly authorized reuse")
        req(row["implementation_authorized"] is False,"proposal review improperly authorized implementation")
        req(row["code_execution_performed"] is False,"proposal review executed discovered code")
        req(row["downstream_mutation_performed"] is False,"proposal review performed downstream mutation")
        req(isinstance(row["source_execution_id"],str) and row["source_execution_id"],"proposal review source execution id missing")
        req(row["source_execution_id"] not in execution_ids,"duplicate proposal review source execution");execution_ids.add(row["source_execution_id"])
        req(isinstance(row["source_execution_receipt_hash"],str) and row["source_execution_receipt_hash"].startswith("sha256:"),"proposal review source receipt hash invalid")
        req(isinstance(row["reviewed_at"],str) and row["reviewed_at"],"proposal review timestamp missing")
        req(isinstance(row["evidence_refs"],list) and row["evidence_refs"],"proposal review evidence missing")
        body=dict(row);given=body.pop("review_hash")
        req(given==digest(body),"proposal review hash mismatch")
    req(execution_ids.issubset(set(state["applied_execution_ids"])),"proposal reviews missing applied execution ids")

def _review_id(execution_id:str,proposal_id:str)->str:
    return "HREV-"+hashlib.sha256((execution_id+"\0"+proposal_id).encode()).hexdigest()[:20].upper()

def apply_execution_receipts(
    state:dict[str,Any],
    receipts:list[dict[str,Any]],
    *,
    at:str|None=None,
)->tuple[dict[str,Any],dict[str,Any]]:
    validate_state(state)
    req(isinstance(receipts,list),"scheduler execution receipts must be list")
    out=json.loads(json.dumps(state))
    added=[]
    for receipt in receipts:
        if not isinstance(receipt,dict):
            continue
        if receipt.get("status")!="SUCCESS" or receipt.get("result_kind")!="HUNTER_PROPOSAL_PUBLIC_EVIDENCE_REVIEW":
            continue
        execution_id=receipt.get("execution_id")
        if not isinstance(execution_id,str) or not execution_id:
            raise HunterProposalReviewError("proposal review execution id missing")
        if execution_id in out["applied_execution_ids"]:
            continue
        receipt_body=dict(receipt)
        receipt_hash=receipt_body.pop("receipt_hash",None)
        req(isinstance(receipt_hash,str) and receipt_hash==digest(receipt_body),"proposal review source execution receipt hash mismatch")
        result=receipt.get("result")
        req(isinstance(result,dict),"proposal review execution result missing")
        required={
          "proposal_id","finding_id","repository_full_name","repository_id","revision","tree_sha",
          "rank_score","rank_band","capability_key","license_spdx_id","license_name","license_state",
          "rights_state","reuse_authorized","implementation_authorized","code_execution_performed",
          "downstream_mutation_performed"
        }
        req(set(result)==required,"proposal review execution result fields changed")
        reviewed_at=receipt.get("finished_at") or at or now_iso()
        core={
          "review_id":_review_id(execution_id,result["proposal_id"]),
          "proposal_id":result["proposal_id"],
          "finding_id":result["finding_id"],
          "project_ids":list(receipt.get("project_ids") or []),
          "repository_full_name":result["repository_full_name"],
          "repository_id":result["repository_id"],
          "revision":result["revision"],
          "tree_sha":result["tree_sha"],
          "rank_score":result["rank_score"],
          "rank_band":result["rank_band"],
          "capability_key":result["capability_key"],
          "license_spdx_id":result["license_spdx_id"],
          "license_name":result["license_name"],
          "license_state":result["license_state"],
          "rights_state":result["rights_state"],
          "reuse_authorized":result["reuse_authorized"],
          "implementation_authorized":result["implementation_authorized"],
          "code_execution_performed":result["code_execution_performed"],
          "downstream_mutation_performed":result["downstream_mutation_performed"],
          "source_execution_id":execution_id,
          "source_execution_receipt_hash":receipt["receipt_hash"],
          "reviewed_at":reviewed_at,
          "evidence_refs":list(dict.fromkeys(receipt.get("evidence_refs") or [])),
        }
        row={**core,"review_hash":digest(core)}
        out["reviews"].append(row)
        out["reviews"]=out["reviews"][-MAX_REVIEWS:]
        out["applied_execution_ids"].append(execution_id)
        out["applied_execution_ids"]=out["applied_execution_ids"][-MAX_REVIEWS:]
        out["sequence"]+=1
        out["updated_at"]=reviewed_at
        added.append(row["review_id"])
    validate_state(out)
    report={
      "schema_version":"1.0.0",
      "status":"UPDATED" if added else "NO_NEW_REVIEWS",
      "added_review_ids":added,
      "review_count":len(out["reviews"]),
      "sequence":out["sequence"],
      "authority_granted":False,
      "rights_resolved":False,
    }
    return out,report

def main()->None:
    ap=argparse.ArgumentParser()
    ap.add_argument("--state",type=Path,required=True)
    ap.add_argument("--execution-receipts",type=Path,required=True)
    ap.add_argument("--output",type=Path,required=True)
    ap.add_argument("--report",type=Path,required=True)
    args=ap.parse_args()
    state=json.loads(args.state.read_text(encoding="utf-8")) if args.state.exists() else load_seed_state()
    receipts=json.loads(args.execution_receipts.read_text(encoding="utf-8"))
    updated,report=apply_execution_receipts(state,receipts)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(updated,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps(report,sort_keys=True))

if __name__=="__main__":
    main()
