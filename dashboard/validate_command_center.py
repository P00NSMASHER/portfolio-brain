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

    require(snapshot["command_center_id"] == "portfolio-brain-command-center-v3", "unexpected command-center id")
    require(snapshot["authority_class"] == "OBSERVE", "command center widened authority")
    require(snapshot["mutation_capability"] == "NONE", "command center gained mutation capability")
    require(snapshot["network_capability"] == "NONE", "command center gained outbound network capability")
    require(snapshot["data_boundary"] == "SANITIZED_CHECKED_IN_AND_DURABLE_ARTIFACT_STATE", "data boundary widened")

    require(snapshot["system"]["project_count"] == len(snapshot["projects"]), "project coverage mismatch")
    require(snapshot["system"]["project_count"] == 12, "registered project coverage drifted")
    require(snapshot["system"]["agent_count"] == len(snapshot["agents"]), "agent coverage mismatch")
    require(snapshot["system"]["agent_count"] == 10, "persistent agent registry drifted")
    require(set(snapshot["state_sources"]["sources"]) >= {"runtime","scheduler","hunter","cost","notifications","agents"}, "live-state source coverage incomplete")
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
    require("OBSERVE ONLY" in page, "read-only label missing")
    require("Bounded Action Engine" in page, "action-engine panel missing")
    require("Enabled Model Routes" in page, "model-route panel missing")
    require("Architecture freeze:" in page, "optimization-state panel missing")
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
        "action_receipts": action["execution_count"],
        "snapshot_hash": snapshot["snapshot_hash"],
    }


if __name__ == "__main__":
    print("portfolio-brain command center v3: PASS", json.dumps(validate_command_center(), sort_keys=True))
