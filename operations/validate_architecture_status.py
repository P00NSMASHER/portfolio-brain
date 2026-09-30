#!/usr/bin/env python3
"""Validate the checked-in architecture status against authoritative config."""
from __future__ import annotations
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
STATUS_PATH=ROOT/"operations"/"ARCHITECTURE_STATUS.json"

class ArchitectureStatusError(ValueError):
    pass

def req(ok: bool, message: str)->None:
    if not ok:
        raise ArchitectureStatusError(message)

def load(path: str):
    return json.loads((ROOT/path).read_text(encoding="utf-8"))

def build_status()->dict:
    projects=load("registry/projects.json")["projects"]
    adapters=load("adapters/ADAPTER_REGISTRY.json")["adapters"]
    boundaries=load("governance/boundaries.json")
    runtime=load("runtime/RUNTIME_POLICY.json")
    notifications=load("notifications/NOTIFICATION_POLICY.json")
    operating=load("operations/OPERATING_MODE_STATUS.json")
    build=load("PORTFOLIO_BUILD_STATE.json")
    completed=build["completed_steps"]
    req(completed==list(range(26)),"historical build ledger no longer records exact Steps 0-25")
    for path in ("adapters/project_forwarding.py","hunting/repo001_intake.py","adapters/abvm_constrained.py","governance/evidence_semantics.py"):
        req((ROOT/path).is_file(),f"architecture component missing: {path}")
    return {
      "schema_version":"1.0.0",
      "status_id":"portfolio-architecture-derived-status-v1",
      "operating_mode":operating["status"],
      "historical_build_ledger":"PORTFOLIO_BUILD_STATE.json",
      "historical_build_step_range":"0-25",
      "historical_build_step_count":len(completed),
      "audit_remediation_tracker":"issue:#210",
      "audit_remediation_labels_are_separate_from_historical_build_steps":True,
      "authoritative_config":{
        "project_registry":"registry/projects.json",
        "adapter_registry":"adapters/ADAPTER_REGISTRY.json",
        "authority_matrix":"governance/boundaries.json",
        "runtime_policy":"runtime/RUNTIME_POLICY.json",
        "notification_policy":"notifications/NOTIFICATION_POLICY.json",
      },
      "derived":{
        "project_count":len(projects),
        "adapter_count":len(adapters),
        "enabled_adapter_count":sum(1 for row in adapters if row.get("enabled")),
        "boundary_id":boundaries["boundary_id"],
        "runtime_authority_class":runtime["authority_class"],
        "runtime_downstream_writes_allowed":runtime["downstream_writes_allowed"],
        "runtime_external_actions_allowed":runtime["external_actions_allowed"],
        "notification_authority_class":notifications["authority_class"],
        "interactive_chatgpt_core_dependency":boundaries["core_autonomy_dependencies"]["interactive_chatgpt_required"],
        "gmail_core_dependency":boundaries["core_autonomy_dependencies"]["gmail_required"],
      },
      "current_systems":{
        "project_forwarding":{
          "path":"adapters/project_forwarding.py","authority_class":"OBSERVE",
          "capability_source":"governance/boundaries.json","exact_identity_idempotent":True,
        },
        "repo001_scout_intake":{
          "path":"hunting/repo001_intake.py","destination":"EXISTING_PORTFOLIO_HUNTER_RESEARCH_INTAKE",
          "creates_hunter_engine":False,"promotes_to_hunter_proposal":False,
        },
        "abvm_projection":{
          "path":"adapters/abvm_constrained.py","scope":["AUTOMATION_HEALTH","AUTOMATION_PROGRESS"],
          "child_facing_mutation":False,"deployment_authority":False,
        },
        "evidence_semantics":{
          "path":"governance/evidence_semantics.py","heartbeat":"CONNECTIVITY_LIVENESS_ONLY",
          "notification":"ALERT_ONLY","pages":"PUBLICATION_ONLY",
        },
        "live_dashboard_source":"dashboard/live/state_sources.json",
      },
      "live_acceptance_status":"SEPARATE_EVIDENCE_REQUIRED",
      "live_acceptance_note":"This config-derived status describes code and machine policy. Hosted CI, independent verifier, and controlled/live receipts remain separate acceptance evidence and must not be inferred from this file.",
    }

def validate_status()->dict:
    expected=build_status()
    actual=json.loads(STATUS_PATH.read_text(encoding="utf-8"))
    req(actual==expected,"ARCHITECTURE_STATUS.json drifted from authoritative config")
    return {"status_id":actual["status_id"],"projects":actual["derived"]["project_count"],"adapters":actual["derived"]["adapter_count"]}

def main()->None:
    print(json.dumps(validate_status(),sort_keys=True))

if __name__=="__main__":
    main()
