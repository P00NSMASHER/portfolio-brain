#!/usr/bin/env python3
"""Constrained ABVM health/progress projection from read-only repository evidence."""
from __future__ import annotations
import argparse, json
from pathlib import Path

from adapters.project_forwarding import ProjectForwardingError, _validate_cycle, digest

class AbvmProjectionError(ProjectForwardingError):
    pass

def req(ok: bool, message: str)->None:
    if not ok:
        raise AbvmProjectionError(message)

def build_abvm_evidence(cycle: dict, forwarding: dict)->dict:
    _validate_cycle(cycle)
    observations=[row for row in cycle["observations"] if row.get("repository_id")=="REPO-003"]
    req(len(observations)==1,"ABVM projection requires exactly one REPO-003 observation")
    obs=observations[0]
    deliveries=[row for row in forwarding.get("deliveries",[]) if row.get("project_id")=="PRJ-006"]
    req(len(deliveries)==1,"ABVM observation must forward to PRJ-006 exactly once")
    delivery=deliveries[0]
    req(delivery["repository_id"]=="REPO-003" and delivery["capability_used"]=="READ_OBSERVE","ABVM forwarding scope invalid")
    req(delivery["downstream_write"] is False and delivery["deployment"] is False and delivery["external_action"] is False,
        "ABVM forwarding gained mutation authority")

    compare=obs.get("compare") if isinstance(obs.get("compare"),dict) else {}
    changed_count=compare.get("changed_file_count")
    if changed_count is None and isinstance(compare.get("files"),list):
        changed_count=len(compare["files"])
    if obs["status"]=="CHANGED":
        progress="CHANGE_OBSERVED"
    elif obs["status"]=="UNCHANGED":
        progress="NO_CHANGE_OBSERVED"
    elif obs["status"]=="INITIALIZED":
        progress="BASELINE_OBSERVED"
    else:
        progress="OBSERVATION_BLOCKED"
    core={
      "schema_version":"1.0.0",
      "evidence_id":"abvm-automation-health-progress-v1",
      "project_id":"PRJ-006",
      "repository_id":"REPO-003",
      "source_cycle_id":cycle["cycle_id"],
      "source_cycle_receipt_hash":cycle["receipt_hash"],
      "source_delivery_id":delivery["delivery_id"],
      "source_revision":obs.get("current_sha"),
      "observation_status":obs["status"],
      "automation_health":"OBSERVABLE" if obs["status"]!="BLOCKED" else "BLOCKED",
      "automation_progress":progress,
      "changed_file_count":changed_count,
      "authority_class":"OBSERVE",
      "evidence_scope":["AUTOMATION_HEALTH","AUTOMATION_PROGRESS"],
      "content_body_included":False,
      "child_data_included":False,
      "child_facing_mutation":False,
      "school_content_publication":False,
      "deployment_authority":False,
      "external_action_authority":False,
      "technical_verification_credit":False,
      "market_verification_credit":False,
      "revenue_verification_credit":False,
    }
    return {**core,"evidence_hash":digest(core)}

def main()->None:
    parser=argparse.ArgumentParser()
    parser.add_argument("--cycle",default="runtime/out/cycle_receipt.json")
    parser.add_argument("--forwarding",default="runtime/out/project_forwarding_receipt.json")
    parser.add_argument("--output",default="runtime/out/abvm_health_progress_evidence.json")
    args=parser.parse_args()
    cycle=json.loads(Path(args.cycle).read_text(encoding="utf-8"))
    forwarding=json.loads(Path(args.forwarding).read_text(encoding="utf-8"))
    evidence=build_abvm_evidence(cycle,forwarding)
    output=Path(args.output); output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(evidence,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps({"project_id":"PRJ-006","health":evidence["automation_health"],"progress":evidence["automation_progress"],
                      "authority_class":evidence["authority_class"]},sort_keys=True))

if __name__=="__main__":
    main()
