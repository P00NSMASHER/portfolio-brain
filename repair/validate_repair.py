#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path
from repair.repair_engine import build_repair_state,policy
ROOT=Path(__file__).resolve().parents[1]
class RepairValidationError(ValueError):pass
def req(ok,msg):
    if not ok:raise RepairValidationError(msg)
def load(p):return json.loads((ROOT/p).read_text())
def validate_repair():
    p=policy();pin=load("repair/AI_BUSINESS_OS_REPAIR_PIN.json");ledger=load("repair/REPAIR_LEDGER.json")
    req(pin["source_revision"]=="c6276c80828d2632d5fee37cdaaf65f1d5b36427","repair source revision mismatch")
    expected={"repair_queue":"eca81c795a130cd467812de5867c26dec1044ef2","repair_intake":"21b513b5347b0ef3b7e027498f437dfb84f699d6","learning_engine":"6ce4b266e24b9f6d8089e32618fa7a5c95bfe89c","skill_eval_intake":"501f5c201588b57f83928461d1aedf0bddb589db","skill_promotion_intake":"417c387bdc9e6b2a77b860964b4f01d364235a59","skill_eval_tool":"adbcc1875ab42aec245cc08994b81735c5eee424","skill_promotion_tool":"78c6526f7980e57ee0012bfa888eb6572a9d89e0","repair_candidate_contract":"de8ebb24706b225c8cacbd2b60889174bcdfb636","repair_queue_tests":"8779c9c8dbc08bb505816cc56f255c97e2d58588"}
    for k,v in expected.items():req(pin["components"][k]["blob_sha"]==v,f"{k} blob mismatch")
    req(pin["copied_source_code"] is False,"canonical repair source copied")
    req(p["automatic_mutation"] is False and p["automatic_canary"] is False and p["automatic_promotion"] is False,"repair automation authority widened")
    req(p["repair_repository_id"]=="REPO-008","repair repo widened");req(p["builder_agent_id"]=="AGT-ENGINEER","repair builder changed")
    req(ledger["failures"]==[] and ledger["tasks"]==[],"checked-in repair ledger fabricated failures/tasks")
    learning=__import__("learning.continuous_learning",fromlist=["rebuild_from_ledger"]).rebuild_from_ledger()
    state=build_repair_state(learning);req(state["failure_count"]==0 and state["task_count"]==0 and state["promotion_eligible"]==0,"empty production evidence created repairs")
    factory=load("software_factory/FACTORY_POLICY.json");req(factory["mode"]=="ISOLATED_BRANCH_PR_ONLY","repair lost isolated factory gate")
    req(factory["candidate_write_repositories"] if "candidate_write_repositories" in factory else True,"noop")
    source=load("PORTFOLIO_BUILD_STATE.json")["repositories"]["REPO-001"]["last_inspected_sha"];req(source==pin["source_revision"],"repair source cursor drifted")
    src=(ROOT/"repair/repair_engine.py").read_text()
    req("def promote(" not in src and "MERGE_PR" not in src and "DEPLOY" not in src,"repair engine contains direct promotion/deploy surface")
    runtime=(ROOT/"runtime/continuous_runtime.py").read_text();req("repair_state.json" in runtime and "build_repair_state" in runtime,"daily runtime not connected to repair detection")
    return {"pinned_components":len(expected),"seed_failures":0,"seed_tasks":0,"promotion_eligible":0,"automatic_mutation":False,"automatic_promotion":False}
if __name__=="__main__":print("portfolio-brain Step 17 repair: PASS",json.dumps(validate_repair(),sort_keys=True))
