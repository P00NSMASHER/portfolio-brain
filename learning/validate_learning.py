#!/usr/bin/env python3
"""Cross-file Step 10 continuous-learning validator."""
from __future__ import annotations
import json
from pathlib import Path
from learning.continuous_learning import policy, rebuild_from_ledger

ROOT=Path(__file__).resolve().parents[1]
class LearningValidationError(ValueError): pass
def req(ok,msg):
    if not ok:raise LearningValidationError(msg)
def load(p):return json.loads((ROOT/p).read_text())

def validate_learning():
    state=load("PORTFOLIO_BUILD_STATE.json");pin=load("learning/AI_BUSINESS_OS_LEARNING_ENGINE_PIN.json")
    p=policy();schema=load("schemas/LEARNING_OBSERVATION_SCHEMA.json");ledger=load("learning/LEARNING_OBSERVATION_LEDGER.json")
    req(state["repositories"]["REPO-001"]["last_inspected_sha"]==pin["source_revision"],"learning source cursor drifted")
    req(pin["source_revision"]=="c6276c80828d2632d5fee37cdaaf65f1d5b36427","unexpected learning source revision")
    expected={
      "learning_engine":"6ce4b266e24b9f6d8089e32618fa7a5c95bfe89c",
      "learning_engine_contract":"4baf08ed31bb6727ec316ffd79189650cd938f68",
      "learning_state_compiler":"03b49f8097430a874d4ae61947e4d9411e815150",
      "search_move_learning":"89f9b38fb18484bc6c00ac20fd451f29e09f2aa8",
      "repair_queue":"eca81c795a130cd467812de5867c26dec1044ef2",
      "learning_tests":"ada39ebadffd047ab5f2de706887747c9fff2795"
    }
    for k,v in expected.items():req(pin["components"][k]["blob_sha"]==v,f"{k} blob mismatch")
    req(pin["copied_source_code"] is False,"canonical learning source must not be copied")
    req(schema["additionalProperties"] is False,"learning observation schema must be closed")
    req(set(p["domains"])=={"SEARCH","ENGINEERING","TEST","REGRESSION","PRODUCT","CUSTOMER","EXPERIMENT","MODEL","RESOURCE"},"learning domain set mismatch")
    req(p["reward_weights"]["VERIFIED_EXTERNAL_VALUE"]>p["reward_weights"]["VERIFIED_TECHNICAL"]>p["reward_weights"]["INTERNAL_ACTIVITY"],"reward evidence ordering weakened")
    req(p["reward_weights"]["INTERNAL_ACTIVITY"]==0.0,"internal activity cannot receive value credit")
    req(p["automatic_policy_promotion"] is False and p["policy_effect"]=="NONE","learning became self-promoting")
    req(p["promotion_gate"]["minimum_train_observations"]>=5 and p["promotion_gate"]["minimum_train_sample_size"]>=20,"train evidence gate weakened")
    req(p["promotion_gate"]["minimum_confirm_observations"]>=2 and p["promotion_gate"]["minimum_confirm_sample_size"]>=6,"confirm evidence gate weakened")
    rebuilt=rebuild_from_ledger()
    req(ledger["observations"]==[],"Step 10 production ledger must not fabricate historical observations")
    req(rebuilt["source_observation_count"]==0 and rebuilt["eligible_record_count"]==0,"empty production ledger produced learned policy")
    runtime=(ROOT/"runtime/continuous_runtime.py").read_text()
    req("portfolio_learning_state.json" in runtime,"daily runtime does not emit portfolio learning state")
    req("rebuild_from_ledger" in runtime,"daily runtime not connected to Step 10 learner")
    return {"pinned_components":len(expected),"domains":len(p["domains"]),"source_observations":0,"eligible_records":0,"policy_effect":"NONE"}

if __name__=="__main__":print("portfolio-brain Step 10 learning: PASS",json.dumps(validate_learning(),sort_keys=True))
