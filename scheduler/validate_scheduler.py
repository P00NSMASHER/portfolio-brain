#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path
from hunting.proposal_state import load_seed_state as load_hunter_proposal_seed, validate_state as validate_hunter_proposal_state
from hunting.proposal_review_state import load_seed_state as load_hunter_proposal_review_seed, validate_state as validate_hunter_proposal_review_state
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
    handoff=p["hunter_proposal_handoff"]
    req(handoff["enabled"] is True,"Hunter proposal handoff disabled")
    req(handoff["source_state_id"]=="portfolio-hunter-proposal-state","Hunter proposal handoff source identity drifted")
    req((handoff["work_type"],handoff["agent_id"],handoff["goal_type"],handoff["authority_class"])==("RESEARCH","AGT-RESEARCHER","RESEARCH_EVIDENCE","OBSERVE"),"Hunter proposal handoff widened scheduler authority or role")
    req(handoff["rights_state"]=="NOT_GRANTED_BY_DISCOVERY","Hunter proposal handoff granted reuse rights")
    req(handoff["exact_revision_reinspection_required"] is True and handoff["license_metadata_is_not_reuse_authority"] is True,"Hunter proposal evidence safeguards weakened")
    req(handoff["origin_cycle_required"] is True,"Hunter proposal origin-cycle provenance disabled")
    req(handoff["backlog_priority_mode"]=="RANK_SCORE_DESC_THEN_FIRST_SEEN_FIFO","Hunter proposal backlog priority mode drifted")
    req(handoff["continuation_class"]=="CONTINUATION","Hunter proposal review lost continuation classification")
    req(handoff["continuation_priority_policy"]=="CONTINUATION_BEFORE_NEW_WORK_WITHIN_SAME_GATE","Hunter proposal continuation priority drifted")
    proposal_seed=load_hunter_proposal_seed();validate_hunter_proposal_state(proposal_seed)
    req(proposal_seed.get("origins")=={},"Hunter proposal seed origin map must be empty")
    proposal_review_seed=load_hunter_proposal_review_seed();validate_hunter_proposal_review_state(proposal_review_seed)
    req(proposal_review_seed["reviews"]==[] and proposal_review_seed["applied_execution_ids"]==[],"Hunter proposal review seed invented review evidence")
    context=build_context();state,receipt=schedule_cycle(seed,context,at="2026-09-25T20:40:00Z")
    selected=receipt["selected_work"];types={w["work_type"] for w in selected}
    req(3<=len(selected)<=p["max_new_work_per_cycle"] and {"RESEARCH","HUNT","INTEGRATION"}<=types,"unexpected current selected work")
    req({"AGT-RESEARCHER","AGT-HUNTER","AGT-PRODUCT-ANALYST"}<={w["assigned_agent_id"] for w in selected},"unexpected current agent assignment")
    req(receipt["blocked_work"]==[],"adult-only education validation still appears in blocked work")
    req(not any(w["required_authority"]=="ACT" for w in [*selected,*receipt["blocked_work"]]),"scheduler created ACT work")
    req(not any(w["work_type"] in {"REPAIR","TEST","VERIFICATION"} for w in selected),"scheduler invented gated repair/test/verification work")
    req(any(w["work_type"]=="EXPERIMENT" and w["assigned_agent_id"]=="AGT-COMMERCIAL-ANALYST" for w in selected),"bounded commercial experiment prep not queued")
    req(len(state["work_items"])==len(selected),"scheduler state did not persist queue")
    wf=(ROOT/".github/workflows/portfolio-autonomous-scheduler.yml").read_text().lower()
    for token in ["contents: read","actions: read","23 * * * *","portfolio_scheduler_disabled","actions/upload-artifact@v4","cancel-in-progress: false"]:
        req(token in wf,f"scheduler workflow missing {token}")
    req("push:" not in wf,"scheduler must not fan out on push inside the singleton cost-state concurrency lane")
    req(wf.index("concurrency:")>wf.index("schedule:"),"scheduler cost concurrency must remain job-level so cancelled queued jobs are rerunnable")
    runtime_event=(ROOT/".github/workflows/runtime-event-observe.yml").read_text()
    req('".github/workflows/portfolio-autonomous-scheduler.yml"' in runtime_event,"scheduler workflow changes are not isolated from runtime-event churn")
    for s in ["hunting.proposal_artifact_state","hunting/live/hunter_proposal_state.json","portfolio-hunter-proposal-state"]:
        req(s in wf,f"scheduler Hunter proposal inbox integration missing {s}")
    for token in [
        "hunting.proposal_review_artifact_state",
        "hunting.proposal_review_state",
        "hunter_proposal_review_state.json",
        "portfolio-hunter-proposal-review-state",
    ]:
        req(token in wf,f"scheduler Hunter proposal review persistence missing {token}")
    executor=(ROOT/"scheduler/work_executor.py").read_text()
    for token in [
        "HUNTER_PROPOSAL_PUBLIC_EVIDENCE_REVIEW",
        '"rights_state":"UNKNOWN_REQUIRES_REVIEW"',
        '"reuse_authorized":False',
        '"implementation_authorized":False',
        '"code_execution_performed":False',
        "inspect_revision",
    ]:
        req(token in executor,f"Hunter proposal evidence-review boundary missing {token}")
    scheduler_source=(ROOT/"scheduler/autonomous_scheduler.py").read_text()
    for token in ["hunter-origin-cycle:","hunter-origin-receipt:","hunter-origin-sequence:","hunter-last-seen-sequence:"]:
        req(token in scheduler_source,f"Hunter proposal scheduler provenance missing {token}")
    for token in ['continuation_class="CONTINUATION"','"CONTINUATION":0','THEN_CONTINUATION_CLASS']:
        req(token in scheduler_source,f"Scheduler continuation ordering missing {token}")
    for forbidden in ["contents: write","pull-requests: write","deployments: write","id-token: write","git push","gh pr","openai","anthropic"]:
        req(forbidden not in wf,f"forbidden scheduler workflow capability: {forbidden}")
    req("git push origin head:main" not in (ROOT/"scheduler/SCHEDULER_CONTRACT.md").read_text().lower(),"upstream direct-main behavior adopted")
    return {"work_types":7,"selected_current":len(selected),"blocked_approval":0,"queued_agents":len({w["assigned_agent_id"] for w in selected}),"act_work":0,"max_new_per_cycle":p["max_new_work_per_cycle"],"hunter_proposal_handoff":"OBSERVE_RESEARCH","hunter_proposal_backlog_priority":handoff["backlog_priority_mode"],"hunter_proposal_continuation_priority":handoff["continuation_priority_policy"],"hunter_proposal_seed_sequence":proposal_seed["sequence"],"hunter_proposal_review_seed_sequence":proposal_review_seed["sequence"]}
if __name__=="__main__":print("portfolio-brain Step 19 scheduler: PASS",json.dumps(validate_scheduler(),sort_keys=True))
