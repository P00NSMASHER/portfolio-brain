#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path
from scheduler.autonomous_scheduler import build_context,load_state,policy,schedule_cycle
ROOT=Path(__file__).resolve().parents[1]
class SchedulerValidationError(ValueError):pass
def req(ok,msg):
    if not ok:raise SchedulerValidationError(msg)
def load(p):return json.loads((ROOT/p).read_text())
def validate_scheduler():
    p=policy();pin=load("scheduler/AI_BUSINESS_OS_SCHEDULER_PIN.json");seed=load_state()
    req(pin["source_revision"]=="c6276c80828d2632d5fee37cdaaf65f1d5b36427","scheduler source revision mismatch")
    expected={"priority_lease_runtime":"2118648b08ff53a4eb3add2fc77715fe722f0588","priority_lease_contract":"455a9f60ee15a6f390d32acf2cbb9eb87c942474","durable_agent_runtime":"f200573259bcf29c09fbe9e480df4f983dd50903","current_hunter_schedule":"243d11413ab63212af1efc9241b32f8540f5734f","current_hunter_workflow":"15a905bbb99f568661b5b4f0247fbf6efeda0ca7"}
    for k,v in expected.items():req(pin["components"][k]["blob_sha"]==v,f"{k} blob mismatch")
    req(pin["copied_source_code"] is False,"canonical scheduler source copied")
    req(p["authority_class"]=="MODIFY" and p["mode"]=="EVIDENCE_GATED_PERSISTENT_QUEUE","scheduler authority/mode changed")
    req(p["work_types"]==["HUNT","EXPERIMENT","REPAIR","TEST","RESEARCH","INTEGRATION","VERIFICATION"],"scheduler work type set changed")
    req(p["max_new_work_per_cycle"]<=8 and p["max_open_work_per_agent"]==2,"scheduler concurrency ceiling invalid")
    context=build_context();state,receipt=schedule_cycle(seed,context,at="2026-09-25T20:40:00Z")
    selected=receipt["selected_work"];types={w["work_type"] for w in selected}
    req(len(selected)==3 and types=={"RESEARCH","HUNT","INTEGRATION"},"unexpected current selected work")
    req({w["assigned_agent_id"] for w in selected}=={"AGT-RESEARCHER","AGT-HUNTER","AGT-PRODUCT-ANALYST"},"unexpected current agent assignment")
    req(len(receipt["blocked_work"])==6 and all(w["state"]=="BLOCKED_APPROVAL" for w in receipt["blocked_work"]),"human-gated work not preserved as blocked approval")
    req(all("CUSTOMER_COMMUNICATION" in w["approval_requirements"] for w in receipt["blocked_work"]),"blocked external experiments missing customer approval")
    req(not any(w["required_authority"]=="ACT" for w in [*selected,*receipt["blocked_work"]]),"scheduler created ACT work")
    req(not any(w["work_type"] in {"REPAIR","TEST","VERIFICATION","EXPERIMENT"} for w in selected),"scheduler invented gated work")
    req(len(state["work_items"])==3,"scheduler state did not persist queue")
    wf=(ROOT/".github/workflows/portfolio-autonomous-scheduler.yml").read_text().lower()
    for s in ["contents: read","actions: read","23 * * * *","portfolio_scheduler_disabled","actions/upload-artifact@v4","cancel-in-progress: false"]:
        req(s in wf,f"scheduler workflow missing {s}")
    for forbidden in ["contents: write","pull-requests: write","deployments: write","id-token: write","git push","gh pr","openai","anthropic"]:
        req(forbidden not in wf,f"forbidden scheduler workflow capability: {forbidden}")
    req("git push origin head:main" not in (ROOT/"scheduler/SCHEDULER_CONTRACT.md").read_text().lower(),"upstream direct-main behavior adopted")
    return {"work_types":7,"selected_current":3,"blocked_approval":6,"queued_agents":3,"act_work":0,"max_new_per_cycle":p["max_new_work_per_cycle"]}
if __name__=="__main__":print("portfolio-brain Step 19 scheduler: PASS",json.dumps(validate_scheduler(),sort_keys=True))
