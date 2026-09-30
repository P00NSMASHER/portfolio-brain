#!/usr/bin/env python3
from __future__ import annotations
import argparse,json
from pathlib import Path
from governance.authority import load_boundaries,validate_boundaries
ROOT=Path(__file__).resolve().parents[1];STATUS=ROOT/"governance"/"STATUS.json"
def _load(p):return json.loads((ROOT/p).read_text())
def snapshot():
 b=load_boundaries();c=validate_boundaries(b);a=_load("adapters/ADAPTER_REGISTRY.json");n=_load("notifications/NOTIFICATION_POLICY.json")
 return {"schema_version":"1.0.0","status_id":"portfolio-governance-config-status-v1","source_of_truth":["governance/boundaries.json","adapters/ADAPTER_REGISTRY.json","notifications/NOTIFICATION_POLICY.json"],"registered_project_boundaries":c["projects"],"registered_repository_adapters":len(a["adapters"]),"adapter_authority_classes":sorted(set(x["authority_class"] for x in a["adapters"])),"core_autonomy_dependencies":b["core_autonomy_dependencies"],"gmail_customer_communication":b["action_matrix"]["customer_email_gmail"]["decision"],"production_deployment":b["action_matrix"]["production_deployment"]["decision"],"live_trading":b["action_matrix"]["live_trading"]["decision"],"pages_publication":b["action_matrix"]["pages_publication"]["decision"],"notification_authority_class":n["authority_class"],"acceptance_proof_status":"TRACKED_SEPARATELY_IN_GITHUB_ISSUE_210"}
def main():
 p=argparse.ArgumentParser();p.add_argument("--check",action="store_true");p.add_argument("--write",action="store_true");a=p.parse_args();e=snapshot()
 if a.write:STATUS.write_text(json.dumps(e,indent=2,sort_keys=True)+"\n")
 if a.check and json.loads(STATUS.read_text())!=e:raise SystemExit("governance status drift: run python -m governance.status --write")
 print(json.dumps(e,sort_keys=True))
if __name__=="__main__":main()
