#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path
from notifications.notification_engine import load_state,notification_cycle,policy,validate_policy
ROOT=Path(__file__).resolve().parents[1]
class NotificationValidationError(ValueError):pass
def req(ok,msg):
    if not ok:raise NotificationValidationError(msg)
def load(p):return json.loads((ROOT/p).read_text())
def validate_notifications():
    p=policy();validate_policy(p)
    req(p["authority_class"]=="NONE","notification authority widened")
    req(p["delivery_channels"]==["GITHUB_ACTIONS_ANNOTATION","GITHUB_STEP_SUMMARY"],"delivery channels widened")
    state,first=notification_cycle(load_state(),at="2026-09-25T22:40:00Z")
    kinds={x["kind"] for x in first["emitted_alerts"]}
    req(kinds=={"OPEN_HUMAN_BLOCKERS"},"unexpected current alert set")
    req(len(first["emitted_alerts"])==1 and first["active_alert_count"]==1,"current alert aggregation drifted")
    req(all(x["severity"]=="HIGH" and x["authority_granted"] is False for x in first["emitted_alerts"]),"current alert severity/authority invalid")
    state,second=notification_cycle(state,at="2026-09-25T23:40:00Z")
    req(second["emitted_alerts"]==[] and len(second["suppressed_fingerprints"])==1,"duplicate/cooldown suppression failed")
    req(all(r["status"]=="ACTIVE" for r in state["alert_records"]),"current alerts unexpectedly resolved")
    wf=(ROOT/".github/workflows/portfolio-notification-cycle.yml").read_text().lower()
    for text in ["7 */6 * * *","portfolio-cost-governed-autonomy","cost_governor.workflow_gate preflight","notifications.artifact_state","notifications.notification_engine","notifications.github_sink","portfolio_notification_disabled"]:
        req(text in wf,f"notification workflow missing {text}")
    for forbidden in ["contents: write","issues: write","pull-requests: write","deployments: write","id-token: write","curl ","webhook","slack","sms","smtp"]:
        req(forbidden not in wf,f"notification workflow widened capability: {forbidden}")
    cp=load("cost_governor/COST_GOVERNOR_POLICY.json")
    req("portfolio-notification-cycle" in cp["managed_workflow_names"],"notification workflow missing from cost managed list")
    req("portfolio-notification-cycle::notify" in cp["workflow_job_ceilings"],"notification workflow lacks cost ceiling")
    return {"current_signals":first["signal_count"],"current_emitted":1,"current_active":1,"dedup_suppressed_next_cycle":1,"delivery_channels":2,"authority":"NONE"}
if __name__=="__main__":print("portfolio-brain Step 22 notifications: PASS",json.dumps(validate_notifications(),sort_keys=True))
