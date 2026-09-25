#!/usr/bin/env python3
"""Static/cross-file Step 9 Autonomous Hunter validator."""
from __future__ import annotations
import json
from pathlib import Path
from hunting.autonomous_hunter import detect_gaps, load_policy, load_seed_state, load_strategies, select_objectives, validate_state
ROOT=Path(__file__).resolve().parents[1]
class HunterValidationError(ValueError): pass
def req(ok,msg):
    if not ok: raise HunterValidationError(msg)
def load(p):return json.loads((ROOT/p).read_text())
def validate_hunter():
    state=load("PORTFOLIO_BUILD_STATE.json"); pin=load("hunting/AI_BUSINESS_OS_HUNTER_PIN.json")
    policy=load_policy(); seed=load_seed_state(); validate_state(seed); strategies=load_strategies()
    req(state["repositories"]["REPO-001"]["last_inspected_sha"]==pin["source_revision"],"Hunter source cursor drifted")
    req(pin["copied_source_code"] is False,"canonical Hunter source must not be copied")
    req(pin["source_revision"]=="9533769a669429d2553302df6068b4b1f8099e89","unexpected Hunter source revision")
    expected={
      "business_os_bridge":"185866871c1e3eaa9d8d3aadc700c11c05babc0c",
      "seed_compiler":"6ab65a4f5593601d21d58e9d3a2d771fb070e3bb",
      "allocator":"7832c10f16925d35b6446c24a999b9cef5e212b5",
      "adaptive_policy":"fcb7193202e7a5ac68ff5c205653db4a73631c81",
      "learning_report":"562ec2cc880924a366e3ec45c5e053c555c22a36",
      "run_ingest":"844337f7f87991282d20b6862e4d82553bc6d14e"
    }
    for k,v in expected.items():req(pin["components"][k]["blob_sha"]==v,f"{k} blob mismatch")
    req(policy["authority_class"]=="OBSERVE","Hunter authority changed")
    req(policy["model_calls_allowed"]==0 and policy["downstream_writes_allowed"]==0 and policy["external_actions_allowed"]==0,"Hunter authority widened")
    req(policy["source_allowlist"]==["PUBLIC_GITHUB"],"Hunter source allowlist widened")
    req(policy["repository_count_reward"]==0,"repository count must not be rewarded")
    req(policy["learning"]["verified_outcomes_only_for_value_credit"] is True,"Hunter value training must require verified outcomes")
    req(policy["learning"]["exploration_floor_fraction"]>=0.20,"exploration floor weakened")
    req(len(strategies)==4 and any(x["family"]=="EXPLORATION" for x in strategies),"strategy set/exploration missing")
    gaps=detect_gaps(); objectives=select_objectives(seed)
    req(len(gaps)>=1,"no structural portfolio gaps detected")
    req(1<=len(objectives)<=policy["budgets"]["max_objectives_per_cycle"],"objective generation out of bounds")
    req(any(x["exploration"] for x in objectives),"exploration objective missing")
    req(all(x["authority_class"]=="OBSERVE" for x in objectives),"objective authority widened")
    wf=(ROOT/".github/workflows/hunter-autonomous-cycle.yml").read_text()
    for s in ["contents: read","actions: read","timeout-minutes: 5","PORTFOLIO_HUNTER_DISABLED","47 */6 * * *","cancel-in-progress: false","actions/upload-artifact@v4"]:
        req(s in wf,f"Hunter workflow missing {s}")
    low=wf.lower()
    for forbidden in ["contents: write","pull-requests: write","issues: write","id-token: write","git push","gh pr","openai","anthropic"]:
        req(forbidden not in low,f"forbidden Hunter workflow capability: {forbidden}")
    return {"pinned_components":len(expected),"strategies":len(strategies),"detected_gaps":len(gaps),"selected_objectives":len(objectives),"exploration_objectives":sum(1 for x in objectives if x["exploration"]),"model_calls":0,"downstream_writes":0,"external_actions":0}
if __name__=="__main__":print("portfolio-brain Step 9 Hunter: PASS",json.dumps(validate_hunter(),sort_keys=True))
