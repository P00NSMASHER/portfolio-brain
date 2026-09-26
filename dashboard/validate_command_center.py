#!/usr/bin/env python3
"""Validation for the additive read-only Portfolio Brain command center."""
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

    require(snapshot["command_center_id"] == "portfolio-brain-command-center-v1", "unexpected command-center id")
    require(snapshot["authority_class"] == "OBSERVE", "command center widened authority")
    require(snapshot["mutation_capability"] == "NONE", "command center gained mutation capability")
    require(snapshot["network_capability"] == "NONE", "command center gained outbound network capability")
    require(snapshot["data_boundary"] == "SANITIZED_CHECKED_IN_STATE_ONLY", "data boundary widened")

    require(snapshot["system"]["project_count"] == 12, "project coverage drifted")
    require(len(snapshot["projects"]) == 12, "project rows incomplete")
    require(snapshot["system"]["agent_count"] == 10, "agent registry coverage drifted")
    require(snapshot["system"]["active_agent_count"] == 10, "agent seed state drifted")
    require(all(a["human_act_allowed"] is False for a in snapshot["agents"]), "human ACT authority surfaced")
    require(snapshot["system"]["workflow_count"] >= 10, "workflow surface unexpectedly incomplete")

    ceiling = snapshot["cost_governor"]["portfolio_ceiling"]
    require(ceiling["cost_usd"] == 0, "paid cost ceiling changed")
    require(ceiling["model_calls"] == 0, "paid model-call ceiling changed")
    require(ceiling["api_calls"] == 0, "API-call ceiling changed")
    require(snapshot["commercial_validation"]["followup_to_existing_contacts_allowed"] is False, "outreach boundary changed")

    require(snapshot["validation_sprint"]["architecture_change_policy"] == "VERIFIED_BREAK_FIX_ONLY", "validation freeze policy missing")
    require(snapshot["snapshot_hash"].startswith("sha256:"), "snapshot hash missing")

    require("Portfolio Brain Command Center" in page, "command-center title missing")
    require("OBSERVE ONLY" in page, "read-only authority label missing")
    require("Next admissible action" in page, "operator queue missing")
    require("Kill Switches" in page, "kill-switch panel missing")
    require("Agent Fleet" in page, "agent panel missing")
    require("Portfolio Grid" in page, "portfolio panel missing")

    prohibited_network_or_mutation_tokens = (
        "<form",
        "fetch(",
        "xmlhttprequest",
        "websocket(",
        "eventsource(",
        'method="post"',
        "https://api.",
        "github_token",
    )
    for token in prohibited_network_or_mutation_tokens:
        require(token not in lower, f"unsafe browser capability introduced: {token}")

    return {
        "authority": snapshot["authority_class"],
        "mutation_capability": snapshot["mutation_capability"],
        "projects": snapshot["system"]["project_count"],
        "agents": snapshot["system"]["agent_count"],
        "workflows": snapshot["system"]["workflow_count"],
        "kill_switches": len(snapshot["kill_switches"]),
        "paid_model_budget_usd": ceiling["cost_usd"],
        "snapshot_hash": snapshot["snapshot_hash"],
    }


if __name__ == "__main__":
    print(
        "portfolio-brain command center: PASS",
        json.dumps(validate_command_center(), sort_keys=True),
    )
