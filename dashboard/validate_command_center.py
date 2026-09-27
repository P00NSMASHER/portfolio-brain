#!/usr/bin/env python3
"""Validation for the Portfolio Brain read-only command center v2."""
from __future__ import annotations

import json

from dashboard.command_center import build_command_center_snapshot, render_html


class CommandCenterValidationError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise CommandCenterValidationError(message)


def validate_command_center() -> dict[str, object]:
    snapshot = build_command_center_snapshot()
    page = render_html(snapshot)
    lower = page.lower()

    require(snapshot["command_center_id"] == "portfolio-brain-command-center-v4", "unexpected command-center id")
    require(snapshot["authority_class"] == "OBSERVE", "command center widened authority")
    require(snapshot["mutation_capability"] == "NONE", "command center gained mutation capability")
    require(snapshot["network_capability"] == "NONE", "command center gained outbound network capability")
    require(snapshot["data_boundary"] == "SANITIZED_CHECKED_IN_AND_DURABLE_ARTIFACT_STATE", "data boundary widened")

    require(snapshot["system"]["project_count"] == len(snapshot["projects"]), "project coverage mismatch")
    require(snapshot["system"]["project_count"] == 12, "registered project coverage drifted")
    require(snapshot["system"]["agent_count"] == len(snapshot["agents"]), "agent coverage mismatch")
    require(snapshot["system"]["agent_count"] == 10, "persistent agent registry drifted")
    require(set(snapshot["state_sources"]["sources"]) >= {"runtime","scheduler","hunter","cost","notifications","agents","provider","model_feedback","hunter_proposals","hunter_proposal_reviews"}, "live-state source coverage incomplete")
    require(snapshot["telemetry"]["authority_class"] == "OBSERVE", "telemetry widened authority")
    require(set(snapshot["telemetry"]["queue"]["counts"]) == {"QUEUED","ACTIVE","COMPLETE","CANCELLED"}, "queue telemetry state vector drifted")
    require(snapshot["telemetry"]["cost"]["utilization"]["cost_usd"]["ceiling"] == snapshot["cost_governor"]["portfolio_ceiling"]["cost_usd"], "cost telemetry ceiling mismatch")
    require(snapshot["workload_control"]["mode"] == "GITHUB_NATIVE_WORKLOAD_CONTROL", "workload controls missing")
    require(snapshot["workload_control"]["service_count"] >= 8, "workload service coverage incomplete")
    publication=snapshot["publication"]
    require(publication["mode"] == "AUTO_ON_RELEVANT_MAIN_PUSH_PLUS_HOURLY_REFRESH", "publication mode drifted")
    if publication["source_commit"] is not None:
        require(len(publication["source_commit"]) == 40, "published source commit is not a full SHA")
    truth=snapshot["execution_truth"]
    require(set(truth) == {"attempted","blocked","executed","verified","scope_note"}, "execution truth vector changed")
    require(all(type(truth[k]) is int and truth[k] >= 0 for k in ("attempted","blocked","executed","verified")), "execution truth counts invalid")
    require(snapshot["history"]["history_id"] == "portfolio-command-center-public-history-v1", "history payload missing")
    require("momentum_definition" in snapshot["history"], "project momentum definition missing")
    require(snapshot["state_sources"]["bridge_status"] in {"LIVE","STALE","DEGRADED","FALLBACK"}, "invalid live-state bridge status")
    require(all(src["status"] in {"LIVE","STALE","FALLBACK"} for src in snapshot["state_sources"]["sources"].values()), "invalid subsystem freshness status")
    require(all(a["human_act_allowed"] is False for a in snapshot["agents"]), "agent human-ACT boundary drifted")

    require(snapshot["optimization"]["validation_architecture_freeze"] is False, "unrestricted optimization state unexpectedly refrozen")
    require(snapshot["validation_sprint"]["architecture_freeze_until"] is None, "legacy freeze timestamp returned")
    require(snapshot["validation_sprint"]["status"] == "RETIRED", "legacy validation sprint not retired")
    require(snapshot["validation_sprint"]["target_end_at"] is None, "retired sprint still has a target end date")
    require(snapshot["validation_sprint"]["architecture_change_policy"] == "CONTINUOUS_OPTIMIZATION_NO_SPRINT_FREEZE", "continuous optimization policy drifted")

    ceiling = snapshot["cost_governor"]["portfolio_ceiling"]
    require(ceiling["cost_usd"] >= 0, "invalid portfolio cost ceiling")
    require(ceiling["model_calls"] >= 0, "invalid model-call ceiling")
    require(snapshot["model_router"]["enabled_non_tier0_route_count"] >= 1, "no enabled non-Tier-0 model route visible")
    learning=snapshot["learning_loop"]
    integrity=learning["integrity"]
    require(integrity["status"] in {"HEALTHY","DEGRADED","NO_VERIFIED_VALUE"},"learning integrity status invalid")
    require(integrity["authority_granted"] is False and integrity["policy_promoted"] is False and integrity["evidence_upgraded"] is False,"learning integrity widened authority/policy/evidence")
    require(learning["policy_effect"]=="NONE","command-center learning policy effect widened")
    if integrity["verified_value_event_count"]>0:
        require(integrity["status"]=="HEALTHY" or snapshot["system"]["functional_status"]=="DEGRADED","incomplete verified learning propagation hidden behind operational health")
    readiness=snapshot["model_router"]["provider_readiness"]
    require(readiness["status"] in {"READY","MISSING_CREDENTIAL","BILLING_NOT_ACTIVE","QUOTA_EXHAUSTED","RATE_LIMITED","BUDGET_BLOCKED","PROVIDER_ERROR","UNKNOWN"}, "provider readiness status invalid")
    require(readiness["authority_granted"] is False and readiness["evidence_upgraded"] is False, "provider health widened authority/evidence")

    action = snapshot["action_engine"]
    require(action["enabled"] is True, "bounded action engine not represented as enabled")
    require(action["authority_class"] == "ACT", "action engine authority source drifted")
    require("CUSTOMER_EMAIL" in action["allowed_action_types"], "allowed action type missing")
    require(action["sent_count"] <= action["execution_count"], "action receipt counts inconsistent")
    require(action["customer_email_max_per_utc_day"] > 0, "action rate limit missing")

    action_serialized = json.dumps(action, sort_keys=True).lower()
    require("@" not in action_serialized, "raw recipient-like data leaked into command-center action snapshot")
    require("gmail_message_id" not in action_serialized, "raw Gmail message id leaked")
    require("gmail_thread_id" not in action_serialized, "raw Gmail thread id leaked")

    require(snapshot["snapshot_hash"].startswith("sha256:"), "snapshot hash missing")
    require("Portfolio Brain Command Center" in page, "command-center title missing")
    require("Live State Bridge" in page, "live-state bridge panel missing")
    require("Operational Telemetry" in page, "operational telemetry panel missing")
    require("History & Trends" in page, "history/trends panel missing")
    require("Paid Cost Governor" in page, "paid-only cost governor label missing")
    require("GitHub Workload Controls" in page, "separate workload-control panel missing")
    require("Daily GitHub job-start quota</td><td class=\"num\">None" in page, "retired GitHub daily job quota is not explicit")
    require("Daily runner-minute quota</td><td class=\"num\">None" in page, "retired runner-minute quota is not explicit")
    for retired_label in ("Accounted runner minutes today", "<td>Daily GitHub job starts</td>", "<td>Daily runner minutes</td>", "Governed runner minutes committed"):
        require(retired_label not in page, f"paid-cost UI still conflates GitHub workload: {retired_label}")
    require('data-design="apple-inspired-v4-1"' in page, "v4.1 visual-design marker missing")
    require("font-family:-apple-system" in page, "native system typography stack missing")
    require("-webkit-backdrop-filter" in page and "border-radius:var(--radius-xl)" in page, "premium glass/card design contract missing")
    require("Durable Work Queue" in page, "durable queue panel missing")
    require("project-mobile-card" in page and "project-desktop" in page and "projectCards" in page, "responsive project-card portfolio view missing")
    require("<details class=\"project-bottleneck\">" in page, "mobile project bottleneck disclosure missing")
    require("OBSERVE ONLY" in page, "read-only label missing")
    require("Bounded Action Engine" in page, "action-engine panel missing")
    require("Enabled Model Routes" in page, "model-route panel missing")
    require("Provider Readiness" in page, "provider-readiness panel missing")
    require("Verified Learning Integrity" in page, "verified learning-integrity panel missing")
    require("cross-checks Hunter, model feedback, and continuous learning" in page, "learning-integrity explanation missing")
    require("Hunter Proposal Inbox" in page, "Hunter proposal inbox panel missing")
    require("Discovery never grants reuse rights." in page, "Hunter proposal rights boundary missing")
    proposals=snapshot["hunter_proposals"]
    require(proposals["authority_class"]=="OBSERVE","Hunter proposal inbox widened authority")
    require(proposals["rights_state"]=="NOT_GRANTED_BY_DISCOVERY","Hunter proposal inbox granted reuse rights")
    require(proposals["proposal_count"]==len(proposals["proposals"]),"Hunter proposal inbox count mismatch")
    require(proposals["evidence_reviewed_count"]<=proposals["proposal_count"],"Hunter durable proposal review count exceeds inbox")
    require(proposals["review_state_sequence"]>=0,"Hunter proposal review state sequence invalid")
    require(proposals["awaiting_scheduler_count"]+proposals["queued_review_count"]+proposals["active_review_count"]+proposals["completed_review_count"] <= proposals["proposal_count"],"Hunter proposal review-status counts invalid")
    require("Verified Model Value" in page, "verified model value panel missing")
    require("verified value event(s)" in page, "verified model value evidence badge missing")
    require(snapshot["model_router"]["feedback_state"]["verified_feedback_records"] == snapshot["model_router"]["model_efficiency"]["verified_feedback_records"], "model feedback count mismatch")
    require(snapshot["model_router"]["feedback_state"]["verified_value_events"] == snapshot["model_router"]["model_efficiency"]["verified_value_events"], "model value-event count mismatch")
    require("Architecture freeze" in page and "spec-grid" in page, "mobile-safe optimization-state panel missing")
    require("source-mobile" in page and "source-mobile-card" in page, "mobile live-state cards missing")
    require("Last successful autonomous cycle" in page and "cycle-callout" in page, "mobile cycle summary missing")
    require("Kill Switches" in page, "kill-switch panel missing")

    prohibited_browser_capabilities = (
        "<form",
        "fetch(",
        "xmlhttprequest",
        "websocket(",
        "eventsource(",
        'method="post"',
        "https://api.",
        "github_token",
    )
    for token in prohibited_browser_capabilities:
        require(token not in lower, f"unsafe browser capability introduced: {token}")

    return {
        "authority": snapshot["authority_class"],
        "mutation_capability": snapshot["mutation_capability"],
        "projects": snapshot["system"]["project_count"],
        "agents": snapshot["system"]["agent_count"],
        "workflows": snapshot["system"]["workflow_count"],
        "kill_switches": len(snapshot["kill_switches"]),
        "daily_model_budget_usd": ceiling["cost_usd"],
        "enabled_non_tier0_model_routes": snapshot["model_router"]["enabled_non_tier0_route_count"],
        "learning_integrity_status": integrity["status"],
        "action_receipts": action["execution_count"],
        "history_points": snapshot["history"]["point_count"],
        "queue_open": snapshot["telemetry"]["queue"]["open_total"],
        "snapshot_hash": snapshot["snapshot_hash"],
    }


if __name__ == "__main__":
    print("portfolio-brain command center v4: PASS", json.dumps(validate_command_center(), sort_keys=True))
