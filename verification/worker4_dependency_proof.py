#!/usr/bin/env python3
"""Deterministic controlled proof for audit-remediation Steps 13, 15, 16 and 17."""
from __future__ import annotations
import argparse,json
from pathlib import Path

from dashboard.live_state_bridge import EVIDENCE_SEMANTICS
from governance.validate_boundaries import validate_boundaries
from adapters.abvm_health import build_evidence as build_abvm_evidence, HEALTH_WORKFLOW_PATH
from runtime.project_forwarding import ProjectForwardingError,build_project_delivery,forward_observations,seed_state

def observation(repo_id,adapter_id,full_name,revision):
    return {
      "schema_version":"1.0.0","adapter_id":adapter_id,"repository_id":repo_id,
      "repository_full_name":full_name,"source_ref":"main","observed_at":"2026-09-30T14:00:00Z",
      "status":"CHANGED","blocked_by":None,"prior_sha":"0"*40,"current_sha":revision,
      "compare":None,"network_reads":1,"receipt_hash":"sha256:"+"f"*64
    }

def build_proof():
    validate_boundaries()
    repo1=observation("REPO-001","ADP-001","P00NSMASHER/github-value-hunt-ledger","1"*40)
    abvm=observation("REPO-003","ADP-003","P00NSMASHER/abvmschoolstarworld","3"*40)
    state,first=forward_observations(seed_state(),[repo1,abvm,abvm],at="2026-09-30T14:00:01Z",cycle_id="PROOF-1",cycle_receipt_hash="sha256:"+"a"*64)
    state2,second=forward_observations(state,[repo1,abvm],at="2026-09-30T14:01:01Z",cycle_id="PROOF-2",cycle_receipt_hash="sha256:"+"b"*64)
    expected_repo1={"PRJ-001","PRJ-002","PRJ-008","PRJ-009","PRJ-010","PRJ-011"}
    repo1_projects={x["project_id"] for x in first["deliveries"] if x["repository_id"]=="REPO-001"}
    abvm_rows=[x for x in first["deliveries"] if x["project_id"]=="PRJ-006"]
    if repo1_projects!=expected_repo1 or len(abvm_rows)!=1: raise SystemExit("project forwarding proof routing mismatch")
    if second["deliveries"]: raise SystemExit("project forwarding repeat was not suppressed")
    if len(second["duplicate_delivery_keys"])!=7: raise SystemExit("project forwarding duplicate ledger mismatch")
    try:
        build_project_delivery(abvm,"PRJ-005",at="2026-09-30T14:00:01Z")
    except ProjectForwardingError:
        wrong_project_rejected=True
    else:
        raise SystemExit("wrong-project forwarding did not fail closed")
    row=abvm_rows[0]
    if row["evidence_scope"]!=["REPOSITORY_OBSERVATION"]: raise SystemExit("ABVM repository observation was mislabeled")
    if any(row[k] for k in ("authority_granted","mutation_performed","deploy_authority","external_action_authority","child_facing_mutation_authority","school_content_publication_authority")):
        raise SystemExit("ABVM delivery gained authority")
    abvm_health=build_abvm_evidence("3"*40,[{
      "id":301,"run_number":17,"run_attempt":1,"name":"ABVM Operational Health Dashboard",
      "path":HEALTH_WORKFLOW_PATH,"head_branch":"main","head_sha":"3"*40,
      "status":"completed","conclusion":"success","created_at":"2026-09-30T14:00:00Z","updated_at":"2026-09-30T14:00:10Z"
    }],observed_at="2026-09-30T14:00:11Z")
    if abvm_health["source_run_head_sha"]!=abvm_health["source_revision"] or abvm_health["automation_health"]!="HEALTHY":
        raise SystemExit("ABVM health proof is not source-bound")
    if any(EVIDENCE_SEMANTICS[k] for k in ("technical_verification_credit","market_verification_credit","revenue_verification_credit")):
        raise SystemExit("telemetry/publication created verification credit")
    return {
      "schema_version":"1.0.0","status":"PASS",
      "step13":{"repo001_project_deliveries":len(repo1_projects),"exact_once_repeat_deliveries":len(second["deliveries"]),"duplicate_keys_suppressed":len(second["duplicate_delivery_keys"]),"wrong_project_rejected":wrong_project_rejected},
      "step15":{"abvm_deliveries":len(abvm_rows),"repository_evidence_scope":row["evidence_scope"],
                "automation_evidence_scope":abvm_health["evidence_scope"],"source_run_id":abvm_health["source_run_id"],
                "source_run_head_sha":abvm_health["source_run_head_sha"],"automation_health":abvm_health["automation_health"],
                "child_facing_mutation_authority":row["child_facing_mutation_authority"],
                "school_content_publication_authority":row["school_content_publication_authority"],
                "deploy_authority":row["deploy_authority"]},
      "step16":{"semantics":EVIDENCE_SEMANTICS},
      "step17":{"authority_model":validate_boundaries()["authority_model"]},
      "authority_granted":False,"mutation_performed":False
    }

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--output",default="verification/out/worker4_dependency_proof.json");a=ap.parse_args()
    proof=build_proof();p=Path(a.output);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(proof,indent=2,sort_keys=True)+"\n")
    print(json.dumps(proof,sort_keys=True))
if __name__=="__main__":main()
