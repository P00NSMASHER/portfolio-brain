#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path
from transfer.cross_project_transfer import build_transfer_state,policy
ROOT=Path(__file__).resolve().parents[1]
class TransferValidationError(ValueError):pass
def req(ok,msg):
    if not ok:raise TransferValidationError(msg)
def load(p):return json.loads((ROOT/p).read_text())
def validate_transfer():
    p=policy();pin=load("transfer/AI_BUSINESS_OS_PEER_TRANSFER_PIN.json");ledger=load("transfer/TRANSFER_LEDGER.json")
    req(pin["source_revision"]=="c6276c80828d2632d5fee37cdaaf65f1d5b36427","transfer source revision mismatch")
    expected={"learning_engine":"6ce4b266e24b9f6d8089e32618fa7a5c95bfe89c","learning_engine_contract":"4baf08ed31bb6727ec316ffd79189650cd938f68","learning_engine_tests":"ada39ebadffd047ab5f2de706887747c9fff2795","knowledge_graph":"d0ed2e015dc4593361d7600e48cb680a0df13245","entity_canonicalization":"29a765be3598f83d20f5747518deb8de8f41ffd2"}
    for k,v in expected.items():req(pin["components"][k]["blob_sha"]==v,f"{k} blob mismatch")
    req(pin["copied_source_code"] is False,"canonical transfer source copied");req(p["automatic_downstream_modify"] is False and p["automatic_generated_value_edges"] is False and p["automatic_rights_assumption"] is False,"transfer authority widened")
    req(ledger["outcomes"]==[],"checked-in transfer ledger fabricated outcomes")
    state=build_transfer_state();req(state["proposal_count"]==44,"unexpected current transfer proposal count");req(state["assessment_ready"]==40 and state["blocked"]==4,"unexpected ready/blocked distribution")
    req(state["checked_in_outcomes"]==0 and state["verified_success_edge_candidates"]==0,"transfer success fabricated")
    req(all(x["source_project_id"]=="PRJ-000" for x in state["proposals"]),"current proposals should originate only from PRJ-000")
    req({x["source_capability_key"] for x in state["proposals"]}=={"portfolio:event-evidence","portfolio:readonly-adapters","portfolio:truth-integration","portfolio:shared-value-memory"},"unexpected source capabilities")
    req(all(x["rights_review_required"] and not x["implementation_allowed"] for x in state["proposals"]),"implementation/rights gate weakened")
    req(sum(1 for x in state["proposals"] if x["target_project_id"]=="PRJ-003" and x["state"]=="BLOCKED")==4,"PermitPlate BLK-001 not preserved")
    build=load("PORTFOLIO_BUILD_STATE.json");req(build["repositories"]["REPO-001"]["last_inspected_sha"]==pin["source_revision"],"transfer source cursor drifted")
    runtime=(ROOT/"runtime/continuous_runtime.py").read_text();req("cross_project_transfer_state.json" in runtime and "build_transfer_state" in runtime,"daily runtime not connected")
    return {"proposals":44,"assessment_ready":40,"blocked":4,"checked_in_outcomes":0,"verified_success_edges":0,"source_capabilities":4}
if __name__=="__main__":print("portfolio-brain Step 18 transfer: PASS",json.dumps(validate_transfer(),sort_keys=True))
