#!/usr/bin/env python3
"""Deterministic architecture/status projection from authoritative machine policy."""
from __future__ import annotations
import argparse, json
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parents[1]

class ArchitectureStatusError(ValueError):
    pass

def load(path:str)->dict[str,Any]:
    return json.loads((ROOT/path).read_text(encoding="utf-8"))

def build_status()->dict[str,Any]:
    boundaries=load("governance/boundaries.json")
    projects=load("registry/projects.json")["projects"]
    adapters=load("adapters/ADAPTER_REGISTRY.json")["adapters"]
    runtime=load("runtime/RUNTIME_POLICY.json")
    notifications=load("notifications/NOTIFICATION_POLICY.json")
    operating=load("operations/OPERATING_MODE_POLICY.json")
    matrix=boundaries["authority_matrix"]
    abvm=next(row for row in boundaries["project_capabilities"] if row["project_id"]=="PRJ-006")
    return {
      "schema_version":"1.0.0",
      "status_id":"portfolio-brain-config-status-v1",
      "claim_scope":"CONFIGURATION_FACTS_ONLY_NOT_LIVE_ACCEPTANCE",
      "remediation_tracker":"github-issue:210",
      "authoritative_sources":[
        "governance/boundaries.json",
        "registry/projects.json",
        "adapters/ADAPTER_REGISTRY.json",
        "runtime/RUNTIME_POLICY.json",
        "notifications/NOTIFICATION_POLICY.json",
        "operations/OPERATING_MODE_POLICY.json"
      ],
      "core_autonomy":{
        "interactive_chatgpt_required":boundaries["core_autonomy_dependencies"]["interactive_chatgpt_required"],
        "gmail_required":boundaries["core_autonomy_dependencies"]["gmail_required"],
        "operational_mode_declares_interactive_chatgpt_dependency":operating["interactive_chatgpt_runtime_dependency"],
        "runtime_authority_class":runtime["authority_class"],
        "runtime_downstream_writes_allowed":runtime["downstream_writes_allowed"],
        "runtime_external_actions_allowed":runtime["external_actions_allowed"],
        "notification_authority_class":notifications["authority_class"]
      },
      "project_forwarding":{
        "registered_project_count":len(projects),
        "enabled_adapter_count":sum(1 for adapter in adapters if adapter.get("enabled")),
        "default_decision":boundaries["default_decision"],
        "authority_inherited":False,
        "capability_fields":["READ_OBSERVE","CANDIDATE_PR","DEPLOY","EXTERNAL_ACTION"]
      },
      "abvm_integration":{
        "project_id":"PRJ-006",
        "repository_id":abvm["repository_id"],
        "evidence_allowlist":abvm["observation_evidence_allowlist"],
        "child_facing_mutation":abvm["child_facing_mutation"],
        "school_content_publication":abvm["school_content_publication"],
        "deployment":abvm["capabilities"]["DEPLOY"],
        "external_action":abvm["capabilities"]["EXTERNAL_ACTION"]
      },
      "evidence_semantics":boundaries["semantics"],
      "authority_boundaries":{
        name:matrix[name]["decision"]
        for name in (
          "OBSERVATION","REPOSITORY_CANDIDATE_WRITE","PR_CREATION",
          "PROTECTED_BOT_REPAIR_INTEGRATION","PRODUCTION_DEPLOYMENT",
          "CUSTOMER_EMAIL_GMAIL","FINANCIAL_ACTION","DESTRUCTIVE_ACTION",
          "CHILD_FACING_ACTION","LIVE_TRADING","PAGES_PUBLIC_PUBLICATION"
        )
      }
    }

def validate_status_file()->dict[str,Any]:
    expected=build_status()
    actual=load("operations/ARCHITECTURE_STATUS.json")
    if actual!=expected:
        raise ArchitectureStatusError("operations/ARCHITECTURE_STATUS.json drifted from authoritative config")
    return expected

def main()->None:
    parser=argparse.ArgumentParser()
    parser.add_argument("--check",action="store_true")
    args=parser.parse_args()
    status=validate_status_file() if args.check else build_status()
    print(json.dumps(status,sort_keys=True))

if __name__=="__main__":
    main()
