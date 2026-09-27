#!/usr/bin/env python3
"""Read-only Portfolio Brain command center.

The command center is an operator-facing projection of already-authorized,
sanitized Portfolio Brain state. It never grants authority, mutates portfolio
state, contacts customers, spends money, deploys, merges, or invokes external
services.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from dashboard.executive_dashboard import build_dashboard_snapshot
from dashboard.history_state import load_state as load_history_state, public_history
from dashboard.operational_telemetry import build_operational_telemetry
from cost_governor.sentinel import build_sentinel_snapshot
from learning.integrity import build_learning_integrity

ROOT = Path(__file__).resolve().parents[1]


LIVE_ROOT = ROOT / "dashboard" / "live"


def load_json(path: str) -> dict[str, Any]:
    return json.loads((ROOT / path).read_text())


def load_live_json(filename: str, fallback_path: str) -> dict[str, Any]:
    live = LIVE_ROOT / filename
    if live.exists():
        return json.loads(live.read_text(encoding="utf-8"))
    return load_json(fallback_path)


def load_state_sources() -> dict[str, Any]:
    receipt = LIVE_ROOT / "state_sources.json"
    if receipt.exists():
        data = json.loads(receipt.read_text(encoding="utf-8"))
    else:
        data = {
            "schema_version":"1.0.0",
            "bridge_id":"portfolio-command-center-live-state-v1",
            "authority_class":"OBSERVE",
            "mutation_capability":"NONE",
            "generated_at":None,
            "bridge_status":"FALLBACK",
            "sources":{},
        }
    seeds = {
        "runtime":"adapters/cursors/repositories.json",
        "scheduler":"scheduler/SCHEDULER_STATE_SEED.json",
        "hunter":"hunting/HUNTER_STATE_SEED.json",
        "cost":"cost_governor/COST_STATE_SEED.json",
        "notifications":"notifications/NOTIFICATION_STATE_SEED.json",
        "agents":"agents/AGENT_HEARTBEAT_STATE_SEED.json",
        "provider":"runtime/PROVIDER_HEALTH_SEED.json",
        "model_feedback":"model_router/MODEL_FEEDBACK_STATE_SEED.json",
        "learning":"learning/LIVE_OBSERVATION_STATE_SEED.json",
        "hunter_proposals":"hunting/HUNTER_PROPOSAL_STATE_SEED.json",
        "hunter_proposal_reviews":"hunting/HUNTER_PROPOSAL_REVIEW_STATE_SEED.json",
    }
    for name, ref in seeds.items():
        data["sources"].setdefault(name, {
            "status":"FALLBACK",
            "source_kind":"CHECKED_IN_SEED",
            "source_ref":ref,
            "restore_status":"NOT_RESTORED",
            "source_run_id":None,
            "source_head_sha":None,
            "artifact_id":None,
            "artifact_created_at":None,
            "artifact_expires_at":None,
            "age_minutes":None,
            "stale_after_minutes":None,
            "state_sequence":None,
            "state_updated_at":None,
            "error_class":None,
        })
    return data


def canon(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def hash_value(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canon(value).encode("utf-8")).hexdigest()


def _kill_switch(name: str, path: str, field: str = "disabled") -> dict[str, Any]:
    state = load_json(path)
    return {
        "name": name,
        "path": path,
        "engaged": bool(state.get(field, False)),
        "reason": state.get("reason"),
        "changed_at": state.get("changed_at"),
    }


def build_command_center_snapshot() -> dict[str, Any]:
    executive = build_dashboard_snapshot()
    operating = load_json("operations/OPERATING_MODE_STATUS.json")
    sprint = load_json("operations/VALIDATION_SPRINT_STATE.json")
    agent_registry = load_json("agents/AGENT_REGISTRY.json")
    agent_state = load_live_json("agent_heartbeat_state.json","agents/AGENT_HEARTBEAT_STATE_SEED.json")
    state_sources = load_state_sources()
    hunter_state = load_live_json("hunter_state.json","hunting/HUNTER_STATE_SEED.json")
    hunter_proposal_state = load_live_json("hunter_proposal_state.json","hunting/HUNTER_PROPOSAL_STATE_SEED.json")
    hunter_proposal_review_state = load_live_json("hunter_proposal_review_state.json","hunting/HUNTER_PROPOSAL_REVIEW_STATE_SEED.json")
    scheduler_state = load_live_json("scheduler_state.json","scheduler/SCHEDULER_STATE_SEED.json")
    cost_policy = load_json("cost_governor/COST_GOVERNOR_POLICY.json")
    cost_state = load_live_json("cost_state.json","cost_governor/COST_STATE_SEED.json")
    notification_policy = load_json("notifications/NOTIFICATION_POLICY.json")
    notification_state = load_live_json("notification_state.json","notifications/NOTIFICATION_STATE_SEED.json")
    runtime_state_path = LIVE_ROOT / "runtime_state.json"
    runtime_state = json.loads(runtime_state_path.read_text(encoding="utf-8")) if runtime_state_path.exists() else None
    optimization = load_json("operations/POST_RESTRICTION_OPTIMIZATION_STATUS.json")
    action_policy = load_json("action_engine/ACTION_POLICY.json")
    action_ledger = load_json("action_engine/GMAIL_GATEWAY_LEDGER.json")
    model_registry = load_json("model_router/PROVIDER_REGISTRY.json")
    model_feedback_state = load_live_json("model_feedback_state.json", "model_router/MODEL_FEEDBACK_STATE_SEED.json")
    learning_observation_state = load_live_json("learning_observation_state.json", "learning/LIVE_OBSERVATION_STATE_SEED.json")
    learning_integrity = build_learning_integrity(hunter_state, model_feedback_state, learning_observation_state)
    provider_health = load_live_json("provider_health.json", "runtime/PROVIDER_HEALTH_SEED.json")
    sentinel = build_sentinel_snapshot(
        cost_policy=cost_policy,
        cost_state=cost_state,
        provider_registry=model_registry,
        model_feedback_state=model_feedback_state,
        action_policy=action_policy,
        action_ledger=action_ledger,
        provider_health=provider_health,
    )
    telemetry = build_operational_telemetry()
    history_public_path = ROOT / "dashboard" / "out" / "history.json"
    if history_public_path.exists():
        history = json.loads(history_public_path.read_text(encoding="utf-8"))
    else:
        history_state_path = ROOT / "dashboard" / "live" / "history_state.json"
        history = public_history(load_history_state(history_state_path if history_state_path.exists() else None))
    heartbeat_by_agent = {row["agent_id"]: row for row in telemetry["agents"]["agents"]}

    state_by_agent = agent_state["agents"]
    agents = []
    for role in agent_registry["roles"]:
        state = state_by_agent.get(role["agent_id"], {})
        heartbeat = heartbeat_by_agent.get(role["agent_id"], {})
        productive_age = heartbeat.get("productive_age_minutes")
        probe_age = heartbeat.get("heartbeat_age_minutes")
        agents.append(
            {
                "agent_id": role["agent_id"],
                "name": role["display_name"],
                "role_key": role["role_key"],
                "status": state.get("status", role.get("status", "UNKNOWN")),
                "generation": 1,
                "last_heartbeat_at": heartbeat.get("last_heartbeat_at", state.get("last_heartbeat_at")),
                "last_productive_at": heartbeat.get("last_productive_at"),
                "last_activity_kind": heartbeat.get("last_activity_kind", state.get("last_activity_kind")),
                "source_workflow": heartbeat.get("source_workflow", state.get("source_workflow")),
                "source_run_id": heartbeat.get("source_run_id", state.get("source_run_id")),
                "recent_work_ids": heartbeat.get("recent_work_ids", state.get("recent_work_ids", [])),
                "heartbeat_health": heartbeat.get("heartbeat_health", "NEVER"),
                "heartbeat_age_minutes": probe_age,
                "productive_age_minutes": productive_age,
                "activity_age_minutes": productive_age if productive_age is not None else probe_age,
                "open_work_count": heartbeat.get("open_work_count", 0),
                "oldest_open_work_age_minutes": heartbeat.get("oldest_open_work_age_minutes"),
                "max_autonomy": role["max_autonomy"],
                "builder_eligible": role["builder_eligible"],
                "verifier_eligible": role["verifier_eligible"],
                "max_model_tier": role["max_model_tier"],
                "human_act_allowed": role["human_act_allowed"],
            }
        )

    workflows = sorted(p.name for p in (ROOT / ".github" / "workflows").glob("*.yml") if p.name != "operator-console.yml")
    kill_switches = [
        _kill_switch("Runtime", "runtime/KILL_SWITCH.json"),
        _kill_switch("Scheduler", "scheduler/KILL_SWITCH.json"),
        _kill_switch("Hunter", "hunting/KILL_SWITCH.json"),
        _kill_switch("Notifications", "notifications/KILL_SWITCH.json"),
        _kill_switch("Spend", "cost_governor/COST_KILL_SWITCH.json", "spend_disabled"),
        _kill_switch("Action Engine", "action_engine/KILL_SWITCH.json"),
    ]

    portfolio_ceiling = cost_policy["portfolio_ceiling"]
    scorecard = sprint["scorecard"]
    commercial = sprint["commercial_baseline"]
    active_agents = sum(1 for a in agents if a["status"] == "ACTIVE")
    engaged_switches = sum(1 for k in kill_switches if k["engaged"])
    hotfixes = operating.get("operational_hotfixes", [])
    verified_hotfixes = sum(1 for h in hotfixes if h.get("status") == "VERIFIED_FIXED")
    enabled_model_routes = [
        {"provider_id": provider["provider_id"], "model_id": model["model_id"], "tier": model["tier"]}
        for provider in model_registry["providers"]
        if provider.get("enabled")
        for model in provider.get("models", [])
        if model.get("enabled") and model.get("tier", 0) > 0
    ]
    action_executions = action_ledger.get("executions", [])
    sent_actions = [x for x in action_executions if x.get("status") == "SENT"]
    proposal_findings = {
        row["proposal_id"]: row for row in hunter_proposal_state.get("findings", [])
    }
    proposal_reviews = {}
    for review in hunter_proposal_review_state.get("reviews", []):
        proposal_id = review.get("proposal_id")
        if isinstance(proposal_id, str):
            current = proposal_reviews.get(proposal_id)
            if current is None or (review.get("reviewed_at") or "") >= (current.get("reviewed_at") or ""):
                proposal_reviews[proposal_id] = review
    scheduler_by_source = {}
    for work in scheduler_state.get("work_items", []):
        source_ref = work.get("source_ref")
        if isinstance(source_ref, str):
            scheduler_by_source.setdefault(source_ref, []).append(work)
    hunter_proposals = []
    for proposal in hunter_proposal_state.get("proposals", []):
        finding = proposal_findings.get(proposal["proposal_id"], {})
        review_work = scheduler_by_source.get(proposal["proposal_id"], [])
        review_work.sort(key=lambda row: (row.get("created_at") or "", row.get("scheduler_work_id") or ""), reverse=True)
        current = review_work[0] if review_work else None
        durable_review = proposal_reviews.get(proposal["proposal_id"])
        review_status = "AWAITING_SCHEDULER"
        if durable_review is not None:
            review_status = "EVIDENCE_REVIEWED"
        elif current is not None:
            review_status = {
                "QUEUED":"REVIEW_QUEUED",
                "ACTIVE":"REVIEW_ACTIVE",
                "COMPLETE":"REVIEW_COMPLETE",
                "CANCELLED":"REVIEW_CANCELLED",
            }.get(current.get("state"), "REVIEW_UNKNOWN")
        hunter_proposals.append({
            "proposal_id": proposal["proposal_id"],
            "finding_id": proposal["finding_id"],
            "project_ids": proposal["project_ids"],
            "repository_full_name": finding.get("repository_full_name"),
            "revision": finding.get("revision"),
            "rank_score": proposal["candidate_rank_score"],
            "rank_band": proposal["candidate_rank_band"],
            "soft_signals": proposal["candidate_soft_signals"],
            "capability_key": finding.get("capability_key"),
            "strategy_id": finding.get("strategy_id"),
            "rights_state": hunter_proposal_state.get("rights_state"),
            "review_status": review_status,
            "scheduler_work_id": None if current is None else current.get("scheduler_work_id"),
            "scheduler_work_state": None if current is None else current.get("state"),
            "license_spdx_id": None if durable_review is None else durable_review.get("license_spdx_id"),
            "license_name": None if durable_review is None else durable_review.get("license_name"),
            "license_state": None if durable_review is None else durable_review.get("license_state"),
            "reviewed_at": None if durable_review is None else durable_review.get("reviewed_at"),
            "review_hash": None if durable_review is None else durable_review.get("review_hash"),
        })
    healthy_agents = telemetry["agents"].get("live", 0) + telemetry["agents"].get("idle_healthy", 0)
    stalled_agents = telemetry["agents"].get("stalled", 0)
    warming_agents = telemetry["agents"].get("warming_up", 0)
    stalled_work = telemetry["queue"].get("stalled_open_count", 0)
    functional_reasons = []
    if state_sources["bridge_status"] != "LIVE":
        functional_reasons.append(f"live-state bridge is {state_sources['bridge_status']}")
    if engaged_switches:
        functional_reasons.append(f"{engaged_switches} kill switch(es) engaged")
    if stalled_agents:
        functional_reasons.append(f"{stalled_agents} agent(s) have stale queued work without productive activity")
    if telemetry["failures"]["count"]:
        functional_reasons.append(f"{telemetry['failures']['count']} durable failure/stall signal(s)")
    if enabled_model_routes and provider_health["status"] != "READY":
        functional_reasons.append(f"enabled model route provider is {provider_health['status']}")
    if learning_integrity["status"]=="DEGRADED":
        functional_reasons.append("verified value has not reconciled across all durable learning layers")
    functional_status = "OPERATIONAL" if not functional_reasons else "DEGRADED"

    alerts = []
    if stalled_work or stalled_agents:
        alerts.append(
            {
                "severity": "HIGH",
                "title": "Queued work is not producing agent activity",
                "detail": f"{stalled_work} scheduler item(s) exceed the {90}-minute stall boundary; {stalled_agents} assigned agent(s) lack recent productive execution evidence.",
                "evidence_ref": "dashboard/operational_telemetry.py",
            }
        )
    if executive["portfolio"]["blocked_action_count"]:
        alerts.append(
            {
                "severity": "HIGH",
                "title": "Human-gated work is waiting",
                "detail": f'{executive["portfolio"]["blocked_action_count"]} scheduler items are blocked behind approval or hard boundaries.',
                "evidence_ref": "dashboard/executive_dashboard.py",
            }
        )
    if sprint["status"] not in {"RETIRED","SUPERSEDED_BY_POST_RESTRICTION_OPTIMIZATION"} and scorecard["verified_external_outcomes_since_start"] == 0:
        alerts.append(
            {
                "severity": "MEDIUM",
                "title": "Active validation cycle still needs an external outcome",
                "detail": sprint["exit_gate"],
                "evidence_ref": "operations/VALIDATION_SPRINT_STATE.json",
            }
        )
    if learning_integrity["status"]=="DEGRADED":
        alerts.append(
            {
                "severity":"HIGH",
                "title":"Verified learning propagation is incomplete",
                "detail":f'{learning_integrity["verified_value_event_count"]} verified value event(s) exist, but {len(learning_integrity["missing_continuous_learning_event_ids"])} have not reached durable continuous learning or another integrity check failed.',
                "evidence_ref":"learning/integrity.py",
            }
        )
    if portfolio_ceiling["cost_usd"] > 0:
        alerts.append(
            {
                "severity": "INFO",
                "title": "Finite paid model/API budget is enabled",
                "detail": f'Portfolio ceiling is USD {portfolio_ceiling["cost_usd"]}/day with {portfolio_ceiling["model_calls"]} model calls and {len(enabled_model_routes)} enabled non-Tier-0 model routes.',
                "evidence_ref": "cost_governor/COST_GOVERNOR_POLICY.json",
            }
        )
    if provider_health["status"] not in {"READY", "UNKNOWN"}:
        alerts.append(
            {
                "severity": "HIGH" if provider_health["status"] in {"MISSING_CREDENTIAL", "BILLING_NOT_ACTIVE", "QUOTA_EXHAUSTED"} else "MEDIUM",
                "title": "Model provider is not ready",
                "detail": f'{provider_health["status"]}: internal cost status is {provider_health.get("cost_gate_status") or "not blocked"}.',
                "evidence_ref": "runtime/provider_health.py",
            }
        )
    if sent_actions:
        alerts.append(
            {
                "severity": "INFO",
                "title": "Bounded external action gateway has live proof",
                "detail": f'{len(sent_actions)} sanitized Gmail action receipt(s) are recorded; the command center itself remains read-only.',
                "evidence_ref": "action_engine/GMAIL_GATEWAY_LEDGER.json",
            }
        )

    snapshot = {
        "schema_version": "1.0.0",
        "command_center_id": "portfolio-brain-command-center-v4",
        "authority_class": "OBSERVE",
        "mutation_capability": "NONE",
        "network_capability": "NONE",
        "data_boundary": "SANITIZED_CHECKED_IN_AND_DURABLE_ARTIFACT_STATE",
        "source_dashboard_hash": executive["snapshot_hash"],
        "system": {
            "status": operating["status"],
            "functional_status": functional_status,
            "functional_reasons": functional_reasons,
            "operational_without_interactive_chatgpt": operating["operational_without_interactive_chatgpt"],
            "main_promotion_sha": operating["promoted_main_sha"],
            "hotfix_count": len(hotfixes),
            "verified_hotfix_count": verified_hotfixes,
            "project_count": executive["project_count"],
            "agent_count": len(agents),
            "active_agent_count": active_agents,
            "healthy_agent_count": healthy_agents,
            "stalled_agent_count": stalled_agents,
            "warming_agent_count": warming_agents,
            "workflow_count": len(workflows),
            "engaged_kill_switch_count": engaged_switches,
            "live_state_bridge_status": state_sources["bridge_status"],
        },
        "validation_sprint": {
            "sprint_id": sprint["sprint_id"],
            "status": sprint["status"],
            "purpose": sprint["purpose"],
            "started_at": sprint["started_at"],
            "target_end_at": sprint["target_end_at"],
            "architecture_freeze_until": sprint["architecture_freeze_until"],
            "architecture_change_policy": sprint["architecture_change_policy"],
            "primary_commercial_track": sprint["primary_commercial_track"],
            "secondary_commercial_track": sprint["secondary_commercial_track"],
            "exit_gate": sprint["exit_gate"],
            "next_admissible_action": sprint["primary_uncertainty"]["next_admissible_action"],
            "scorecard": scorecard,
            "guardrails": sprint["guardrails"],
        },
        "optimization": {
            "optimization_id": optimization["optimization_id"],
            "status": optimization["status"],
            "validation_architecture_freeze": optimization["after"]["validation_architecture_freeze"],
            "project_runtimes_enabled": optimization["after"]["project_runtimes_enabled"],
            "scheduler_max_new_per_cycle": optimization["after"]["scheduler_max_new_per_cycle"],
            "scheduler_max_open_per_agent": optimization["after"]["scheduler_max_open_per_agent"],
            "paid_model_api_budget_usd_per_day": optimization["after"]["paid_model_api_budget_usd_per_day"],
            "paid_model_calls_per_day": optimization["after"]["paid_model_calls_per_day"],
            "controls_retained": optimization["controls_retained"],
        },
        "commercial_validation": {
            "freightrecovery_first_contact_threads_sent": commercial["freightrecovery_first_contact_threads_sent"],
            "freightrecovery_human_replies": commercial["freightrecovery_human_replies"],
            "freightrecovery_related_auto_replies_observed": commercial[
                "freightrecovery_related_auto_replies_observed"
            ],
            "freightrecovery_live_checkout_sessions": commercial["freightrecovery_live_checkout_sessions"],
            "freightrecovery_live_payment_intents": commercial["freightrecovery_live_payment_intents"],
            "followup_to_existing_contacts_allowed": commercial["followup_to_existing_contacts_allowed"],
            "outbound_state": commercial["outbound_state"],
        },
        "portfolio": executive["portfolio"],
        "projects": executive["projects"],
        "agents": agents,
        "workflows": workflows,
        "state_sources": state_sources,
        "telemetry": telemetry,
        "history": history,
        "runtime": {
            "sequence": None if runtime_state is None else runtime_state.get("sequence"),
            "updated_at": None if runtime_state is None else runtime_state.get("updated_at"),
            "last_cycle_id": None if runtime_state is None else runtime_state.get("last_cycle_id"),
            "recent_cycle_count": 0 if runtime_state is None else len(runtime_state.get("recent_cycles", [])),
            "repository_count": 0 if runtime_state is None else len(runtime_state.get("repositories", {})),
        },
        "hunter": {
            "sequence": hunter_state["sequence"],
            "updated_at": hunter_state["updated_at"],
            "strategy_stats": hunter_state["strategy_stats"],
            "recent_cycle_count": len(hunter_state["recent_cycles"]),
            "seen_candidate_count": len(hunter_state["seen_candidate_fingerprints"]),
            "negative_knowledge_count": len(hunter_state["negative_knowledge"]),
        },
        "hunter_proposals": {
            "sequence": hunter_proposal_state.get("sequence", 0),
            "updated_at": hunter_proposal_state.get("updated_at"),
            "cycle_id": hunter_proposal_state.get("cycle_id"),
            "cycle_receipt_hash": hunter_proposal_state.get("cycle_receipt_hash"),
            "authority_class": hunter_proposal_state.get("authority_class", "OBSERVE"),
            "rights_state": hunter_proposal_state.get("rights_state", "NOT_GRANTED_BY_DISCOVERY"),
            "proposal_count": len(hunter_proposals),
            "awaiting_scheduler_count": sum(1 for row in hunter_proposals if row["review_status"]=="AWAITING_SCHEDULER"),
            "queued_review_count": sum(1 for row in hunter_proposals if row["review_status"]=="REVIEW_QUEUED"),
            "active_review_count": sum(1 for row in hunter_proposals if row["review_status"]=="REVIEW_ACTIVE"),
            "completed_review_count": sum(1 for row in hunter_proposals if row["review_status"]=="REVIEW_COMPLETE"),
            "evidence_reviewed_count": sum(1 for row in hunter_proposals if row["review_status"]=="EVIDENCE_REVIEWED"),
            "review_state_sequence": hunter_proposal_review_state.get("sequence",0),
            "review_state_updated_at": hunter_proposal_review_state.get("updated_at"),
            "proposals": hunter_proposals,
        },
        "learning_loop": {
            "integrity": learning_integrity,
            "state_sequence": learning_observation_state.get("sequence",0),
            "updated_at": learning_observation_state.get("updated_at"),
            "observation_count": len(learning_observation_state.get("observations",[])),
            "applied_value_outcome_count": len(learning_observation_state.get("applied_source_keys",[])),
            "policy_effect":"NONE",
        },
        "cost_governor": {
            "mode": cost_policy["mode"],
            "portfolio_ceiling": portfolio_ceiling,
            "reservation_count": len(cost_state["reservations"]),
            "recent_decision_count": len(cost_state["recent_decisions"]),
            "managed_workflow_names": cost_policy["managed_workflow_names"],
            "sentinel": sentinel,
        },
        "notifications": {
            "mode": notification_policy["mode"],
            "channels": notification_policy["delivery_channels"],
            "alert_record_count": len(notification_state["alert_records"]),
            "recent_delivery_count": len(notification_state["recent_deliveries"]),
            "max_emitted_per_cycle": notification_policy["max_emitted_per_cycle"],
        },
        "model_router": {
            "enabled_non_tier0_routes": enabled_model_routes,
            "enabled_non_tier0_route_count": len(enabled_model_routes),
            "provider_readiness": provider_health,
            "model_efficiency": sentinel["model_efficiency"],
            "feedback_state": {
                "sequence": model_feedback_state.get("sequence", 0),
                "updated_at": model_feedback_state.get("updated_at"),
                "verified_feedback_records": sentinel["model_efficiency"]["verified_feedback_records"],
                "verified_value_events": sentinel["model_efficiency"]["verified_value_events"],
                "task_kind_count": len(sentinel["model_efficiency"]["task_summaries"]),
            },
        },
        "action_engine": {
            "enabled": action_policy["enabled"],
            "authority_class": action_policy["authority_class"],
            "mode": action_policy["mode"],
            "allowed_project_ids": action_policy["allowed_project_ids"],
            "allowed_action_types": sorted(action_policy["allowed_actions"].keys()),
            "customer_email_max_per_utc_day": action_policy["allowed_actions"]["CUSTOMER_EMAIL"]["max_per_utc_day"],
            "execution_count": len(action_executions),
            "sent_count": len(sent_actions),
            "prohibited_action_types": action_policy["prohibited_action_types"],
            "execution_provider": action_policy["execution_provider"],
            "gmail_account_ref": action_policy["gmail_account_ref"],
            "gateway_health": sentinel["gmail_gateway"],
        },
        "kill_switches": kill_switches,
        "alerts": alerts,
        "operator_boundary": {
            "mode": "READ_ONLY_COMMAND_CENTER",
            "allowed": [
                "Inspect sanitized checked-in portfolio state.",
                "Review evidence-backed project, scheduler, cost, agent, Hunter, action-gateway, model-route, and optimization status.",
                "Identify human-gated decisions and the next admissible action.",
            ],
            "not_allowed": [
                "Execute ACT authority.",
                "Send or draft customer communications.",
                "Move money or place trades.",
                "Deploy, merge, change secrets, or widen autonomous authority.",
                "Store private customer payloads in this public repository.",
            ],
        },
        "evidence_refs": sorted(
            set(
                executive["evidence_refs"]
                + [
                    "operations/OPERATING_MODE_STATUS.json",
                    "operations/VALIDATION_SPRINT_STATE.json",
                    "agents/AGENT_REGISTRY.json",
                    "agents/AGENT_HEARTBEAT_STATE_SEED.json",
                    "hunting/HUNTER_STATE_SEED.json",
                    "hunting/HUNTER_PROPOSAL_STATE_SEED.json",
                    "hunting/proposal_state.py",
                    "hunting/HUNTER_PROPOSAL_REVIEW_STATE_SEED.json",
                    "hunting/proposal_review_state.py",
                    "cost_governor/COST_GOVERNOR_POLICY.json",
                    "cost_governor/COST_STATE_SEED.json",
                    "notifications/NOTIFICATION_POLICY.json",
                    "notifications/NOTIFICATION_STATE_SEED.json",
                    "operations/POST_RESTRICTION_OPTIMIZATION_STATUS.json",
                    "action_engine/ACTION_POLICY.json",
                    "action_engine/GMAIL_GATEWAY_LEDGER.json",
                    "model_router/PROVIDER_REGISTRY.json",
                    "model_router/MODEL_FEEDBACK_STATE_SEED.json",
                    "model_router/feedback_state.py",
                    "learning/LIVE_OBSERVATION_STATE_SEED.json",
                    "learning/live_observations.py",
                    "learning/integrity.py",
                    "runtime/PROVIDER_HEALTH_SEED.json",
                    "runtime/provider_health.py",
                    "dashboard/live/state_sources.json",
                ]
            )
        ),
    }
    snapshot["snapshot_hash"] = hash_value(snapshot)
    return snapshot


def _e(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _badge(text: str, tone: str = "neutral") -> str:
    return f'<span class="badge {tone}">{_e(text)}</span>'


def _status_tone(value: str) -> str:
    upper = value.upper()
    if upper in {"OPERATIONAL", "ACTIVE", "VERIFIED_FIXED", "RUNNING", "LIVE", "READY", "IDLE_HEALTHY", "HEALTHY"}:
        return "good"
    if upper in {"BLOCKED", "CRITICAL", "HIGH", "ENGAGED", "DISABLED", "MISSING_CREDENTIAL", "BILLING_NOT_ACTIVE", "QUOTA_EXHAUSTED", "BUDGET_BLOCKED", "PROVIDER_ERROR", "STALLED"}:
        return "bad"
    if upper in {"EVIDENCE_GAPS", "MEDIUM", "ACTIVE_RESEARCH_ONLY", "IN_DEVELOPMENT", "STALE", "FALLBACK", "DEGRADED", "RATE_LIMITED", "UNKNOWN", "NO_VERIFIED_VALUE"}:
        return "warn"
    if upper in {"NOT TESTED", "WARMING UP"}:
        return "neutral"
    return "neutral"


def render_html(snapshot: dict[str, Any]) -> str:
    system = snapshot["system"]
    sprint = snapshot["validation_sprint"]
    commercial = snapshot["commercial_validation"]
    cost = snapshot["cost_governor"]
    portfolio = snapshot["portfolio"]
    optimization = snapshot["optimization"]
    action_engine = snapshot["action_engine"]
    model_router = snapshot["model_router"]
    learning_loop = snapshot["learning_loop"]
    learning_integrity = learning_loop["integrity"]
    provider_readiness = model_router["provider_readiness"]
    sentinel = cost["sentinel"]
    gateway_health = action_engine["gateway_health"]
    source_bundle = snapshot["state_sources"]
    sources = source_bundle["sources"]
    telemetry = snapshot["telemetry"]
    history = snapshot["history"]
    project_names = {p["project_id"]: p["name"] for p in snapshot["projects"]}

    def compact_timestamp(value: str | None) -> str:
        if not value:
            return "not observed"
        return value.replace("T"," ")[:16] + " UTC"

    def source_status_label(name: str) -> str:
        src = sources[name]
        status = src["status"]
        if status == "FALLBACK" and name == "provider" and provider_readiness["status"] == "UNKNOWN":
            return "NOT TESTED"
        if status == "FALLBACK" and name == "agents" and src.get("state_sequence") in {None,0}:
            return "WARMING UP"
        return status

    def source_badge(name: str) -> str:
        label = source_status_label(name)
        return _badge(label, _status_tone(label))

    def source_detail(name: str) -> str:
        src = sources[name]
        age = src.get("age_minutes")
        age_text = "—" if age is None else f"{age} min"
        return f"{source_status_label(name).lower()} · {compact_timestamp(src.get('artifact_created_at'))} · age {age_text}"


    alert_rows = "".join(
        f"""
        <div class="alert-row">
          <div>{_badge(a["severity"], _status_tone(a["severity"]))}</div>
          <div><strong>{_e(a["title"])}</strong><span>{_e(a["detail"])}</span></div>
          <code>{_e(a["evidence_ref"])}</code>
        </div>
        """
        for a in snapshot["alerts"]
    ) or '<div class="empty">No derived command-center alerts.</div>'

    project_rows = []
    project_cards = []
    for p in snapshot["projects"]:
        bottleneck = (p["highest_value_uncertainty"] or {}).get("question") or "No ranked uncertainty"
        search_text = _e((p["project_id"] + " " + p["name"] + " " + p["project_type"] + " " + p["lifecycle_status"] + " " + p["health"]).lower())
        project_rows.append(
            f"""
            <tr data-project="{search_text}">
              <td><strong>{_e(p["project_id"])}</strong><span class="sub">{_e(p["name"])}</span></td>
              <td>{_badge(p["lifecycle_status"], _status_tone(p["lifecycle_status"]))}</td>
              <td>{_badge(p["health"], _status_tone(p["health"]))}</td>
              <td class="wrap">{_e(bottleneck)}</td>
              <td class="num">{len(p["pending_autonomous_work"])}</td>
              <td class="num">{len(p["blocked_actions"])}</td>
              <td class="num">{p["evidence_coverage"]["uncertainty_candidates"]}</td>
            </tr>
            """
        )
        project_cards.append(
            f"""
            <article class="project-mobile-card" data-project="{search_text}">
              <div class="project-mobile-top">
                <div class="project-mobile-title">
                  <strong>{_e(p["project_id"])}</strong>
                  <span>{_e(p["name"])}</span>
                </div>
                <div class="project-mobile-badges">
                  {_badge(p["lifecycle_status"], _status_tone(p["lifecycle_status"]))}
                  {_badge(p["health"], _status_tone(p["health"]))}
                </div>
              </div>
              <div class="project-mobile-stats">
                <div><span>Open work</span><strong>{len(p["pending_autonomous_work"])}</strong></div>
                <div><span>Blocked</span><strong>{len(p["blocked_actions"])}</strong></div>
                <div><span>Uncertainties</span><strong>{p["evidence_coverage"]["uncertainty_candidates"]}</strong></div>
              </div>
              <details class="project-bottleneck">
                <summary>Current bottleneck</summary>
                <p>{_e(bottleneck)}</p>
              </details>
            </article>
            """
        )

    agent_rows = "".join(
        f"""
        <tr>
          <td><strong>{_e(a["name"])}</strong><span class="sub">{_e(a["agent_id"])}</span></td>
          <td>{_badge(a["heartbeat_health"], _status_tone(a["heartbeat_health"]))}</td>
          <td class="num">{_e(a["activity_age_minutes"] if a["activity_age_minutes"] is not None else "—")}</td>
          <td class="num">{_e(a["open_work_count"])}</td>
          <td>{_e(a["last_activity_kind"] or "—")}</td>
          <td>{_e(a["source_workflow"] or "—")}<span class="sub">run {_e(a["source_run_id"] or "—")}</span></td>
          <td>{_badge(a["max_autonomy"], "neutral")}</td>
          <td class="num">{_e(a["max_model_tier"])}</td>
        </tr>
        """
        for a in snapshot["agents"]
    )

    kill_rows = "".join(
        f"""
        <div class="switch-card">
          <div class="switch-dot {'off' if k["engaged"] else 'on'}"></div>
          <div><strong>{_e(k["name"])}</strong><span>{_e("ENGAGED" if k["engaged"] else "clear")}</span></div>
          <code>{_e(k["path"])}</code>
        </div>
        """
        for k in snapshot["kill_switches"]
    )

    workflow_rows = "".join(f"<li><code>{_e(name)}</code></li>" for name in snapshot["workflows"])
    guardrails = "".join(f"<li>{_e(x)}</li>" for x in sprint["guardrails"])
    allowed = "".join(f"<li>{_e(x)}</li>" for x in snapshot["operator_boundary"]["allowed"])
    blocked = "".join(f"<li>{_e(x)}</li>" for x in snapshot["operator_boundary"]["not_allowed"])

    strategy_rows = "".join(
        f"""
        <tr>
          <td class="wrap">{_e(name)}</td>
          <td class="num">{stats["cycles"]}</td>
          <td class="num">{stats["queries"]}</td>
          <td class="num">{stats["candidates"]}</td>
          <td class="num">{stats["retained"]}</td>
          <td class="num">{stats["verified_value_outcomes"]}</td>
        </tr>
        """
        for name, stats in snapshot["hunter"]["strategy_stats"].items()
    )

    def proposal_status_tone(status: str) -> str:
        if status in {"REVIEW_COMPLETE","EVIDENCE_REVIEWED"}:
            return "good"
        if status == "REVIEW_CANCELLED":
            return "bad"
        if status in {"REVIEW_ACTIVE","REVIEW_QUEUED","AWAITING_SCHEDULER"}:
            return "warn"
        return "neutral"

    proposal_rows = "".join(
        f"""
        <tr>
          <td><strong>{_e(p["proposal_id"])}</strong><span class="sub">{_e(", ".join(p["project_ids"]))}</span></td>
          <td class="wrap"><strong>{_e(p["repository_full_name"] or "—")}</strong><code class="sub">{_e((p["revision"] or "—")[:12])}</code></td>
          <td class="num">{_e(p["rank_score"])}</td>
          <td>{_badge(p["rank_band"], "good" if p["rank_band"]=="HIGH" else "warn")}</td>
          <td>{_badge(p["review_status"].replace("_"," "), proposal_status_tone(p["review_status"]))}</td>
          <td class="wrap">{_e(p["capability_key"] or "—")}</td>
          <td>{_e(p["license_spdx_id"] or ("none" if p["license_state"] else "—"))}<span class="sub">{_e(p["license_state"] or "not reviewed")}</span></td>
          <td>{_e(p["rights_state"] or "—")}</td>
        </tr>
        """
        for p in snapshot["hunter_proposals"]["proposals"]
    ) or '<tr><td colspan="8" class="empty">No quality-gated Hunter proposals in the durable inbox.</td></tr>'

    proposal_cards = "".join(
        f"""
        <article class="mobile-record">
          <div class="mobile-record-head">
            <div class="mobile-title">
              <strong>{_e(p["repository_full_name"] or p["proposal_id"])}</strong>
              <code>{_e(p["proposal_id"])} · {_e((p["revision"] or "—")[:12])}</code>
            </div>
            {_badge(p["review_status"].replace("_"," "), proposal_status_tone(p["review_status"]))}
          </div>
          <div class="mobile-stats mobile-stats-2">
            <div><span>Rank</span><strong>{_e(p["rank_band"])} · {_e(p["rank_score"])}/10</strong></div>
            <div><span>Projects</span><strong>{_e(", ".join(p["project_ids"]))}</strong></div>
            <div><span>License metadata</span><strong>{_e(p["license_spdx_id"] or ("none" if p["license_state"] else "not reviewed"))}</strong></div>
            <div><span>Rights</span><strong>{_e(p["rights_state"] or "—")}</strong></div>
            <div><span>Capability</span><strong>{_e((p["capability_key"] or "—").replace("capability-coverage:",""))}</strong></div>
            <div><span>Reviewed</span><strong>{_e(compact_timestamp(p["reviewed_at"]))}</strong></div>
          </div>
          <div class="mobile-meta">
            <span>Strategy</span><strong>{_e((p["strategy_id"] or "—").replace("STRAT:",""))}</strong>
            <span>Work</span><code>{_e(p["scheduler_work_id"] or "not queued")}</code>
          </div>
        </article>
        """
        for p in snapshot["hunter_proposals"]["proposals"]
    ) or '<div class="empty mobile-record">No quality-gated Hunter proposals in the durable inbox.</div>'

    model_value_rows = "".join(
        f"""
        <tr>
          <td><strong>{_e(row["model_id"])}</strong><span class="sub">{_e(row["provider_id"])}</span></td>
          <td class="num">T{_e(row["tier"])}</td>
          <td class="num">{_e(row["successful_calls"])}</td>
          <td class="num">{_e("$"+str(round(row["committed_spend_usd"],6)))}</td>
          <td class="num">{_e(row["verified_outcomes_recorded"])}</td>
          <td class="num">{_e(row["verified_value_events"])}</td>
          <td class="num">{_e("—" if row["mean_verified_outcome_value"] is None else row["mean_verified_outcome_value"])}</td>
          <td class="num">{_e("—" if row["spend_per_verified_outcome_usd"] is None else "$"+str(round(row["spend_per_verified_outcome_usd"],6)))}</td>
          <td>{_badge(row["value_signal"].replace("_"," "), "good" if row["value_signal"]=="VERIFIED_VALUE_EVIDENCE" else "neutral")}</td>
        </tr>
        """
        for row in sentinel["model_efficiency"]["models"]
    )

    model_value_cards = "".join(
        f"""
        <article class="mobile-record">
          <div class="mobile-record-head">
            <div class="mobile-title">
              <strong>{_e(row["model_id"])}</strong>
              <code>{_e(row["provider_id"])} · T{_e(row["tier"])}</code>
            </div>
            {_badge(row["value_signal"].replace("_"," "), "good" if row["value_signal"]=="VERIFIED_VALUE_EVIDENCE" else "neutral")}
          </div>
          <div class="mobile-stats mobile-stats-2">
            <div><span>Verified feedback</span><strong>{_e(row["verified_outcomes_recorded"])}</strong></div>
            <div><span>Value events</span><strong>{_e(row["verified_value_events"])}</strong></div>
            <div><span>Mean verified value</span><strong>{_e("—" if row["mean_verified_outcome_value"] is None else row["mean_verified_outcome_value"])}</strong></div>
            <div><span>Cost / verified</span><strong>{_e("—" if row["spend_per_verified_outcome_usd"] is None else "$"+str(round(row["spend_per_verified_outcome_usd"],6)))}</strong></div>
            <div><span>Calls today</span><strong>{_e(row["successful_calls"])}</strong></div>
            <div><span>Spend today</span><strong>{_e("$"+str(round(row["committed_spend_usd"],6)))}</strong></div>
          </div>
        </article>
        """
        for row in sentinel["model_efficiency"]["models"]
    )

    source_labels = {
        "runtime":"Runtime",
        "scheduler":"Scheduler",
        "hunter":"Hunter",
        "cost":"Cost Governor",
        "notifications":"Notifications",
        "agents":"Agent Fleet",
        "provider":"Model Provider",
        "model_feedback":"Verified Model Value",
        "learning":"Continuous Learning",
        "hunter_proposals":"Hunter Proposal Inbox",
        "hunter_proposal_reviews":"Hunter Proposal Reviews",
    }
    source_rows = "".join(
        f"""
        <tr>
          <td><strong>{_e(source_labels[name])}</strong><span class="sub">{_e(src.get("source_kind"))}</span></td>
          <td>{source_badge(name)}</td>
          <td class="num">{_e(src.get("state_sequence") if src.get("state_sequence") is not None else "—")}</td>
          <td>{_e(src.get("artifact_created_at") or "—")}</td>
          <td>{_e(src.get("source_run_id") or "—")}</td>
          <td class="num">{_e(src.get("age_minutes") if src.get("age_minutes") is not None else "—")}</td>
          <td class="wrap"><code>{_e(src.get("source_ref") or "—")}</code></td>
        </tr>
        """
        for name, src in sources.items()
        if name in source_labels
    )

    source_cards = "".join(
        f"""
        <div class="source-mobile-card">
          <div class="source-mobile-head">
            <div><strong>{_e(source_labels[name])}</strong><span class="sub">{_e(src.get("source_kind"))}</span></div>
            {source_badge(name)}
          </div>
          <div class="source-mobile-specs">
            <div><span>Sequence</span><strong>{_e(src.get("state_sequence") if src.get("state_sequence") is not None else "—")}</strong></div>
            <div><span>Age</span><strong>{_e(str(src.get("age_minutes")) + " min" if src.get("age_minutes") is not None else "—")}</strong></div>
            <div><span>Source run</span><strong>{_e(src.get("source_run_id") or "—")}</strong></div>
          </div>
          <div class="source-mobile-time">{_e(compact_timestamp(src.get("artifact_created_at")))}</div>
        </div>
        """
        for name, src in sources.items()
        if name in source_labels
    )

    queue_rows = "".join(
        f"""
        <tr>
          <td><strong>{_e(w["work_id"])}</strong><span class="sub">{_e(w.get("source_ref") or "")}</span></td>
          <td>{_badge(w["state"], _status_tone(w["state"]))}</td>
          <td>{_e(w["work_type"])}</td>
          <td>{_e(w["assigned_agent_id"])}</td>
          <td>{_e(", ".join(w["project_ids"]))}</td>
          <td>{_e(w.get("created_at") or "—")}</td>
        </tr>
        """
        for w in telemetry["queue"]["items"]
    ) or '<tr><td colspan="6" class="empty">No durable scheduler work items.</td></tr>'

    action_rows = "".join(
        f"""
        <tr>
          <td><strong>{_e(a["action_id"])}</strong></td>
          <td>{_e(project_names.get(a["project_id"], a["project_id"]))}</td>
          <td>{_e(a["action_type"])}</td>
          <td>{_badge(a["status"], _status_tone(a["status"]))}</td>
          <td>{_e(a["sent_at"])}</td>
        </tr>
        """
        for a in telemetry["actions"]["recent"][:10]
    ) or '<tr><td colspan="5" class="empty">No sanitized action receipts.</td></tr>'

    failure_rows = "".join(
        f"""
        <tr>
          <td>{_badge(f["kind"], "bad")}</td>
          <td>{_e(f.get("ref") or "—")}</td>
          <td>{_e(", ".join(f.get("project_ids") or []))}</td>
          <td>{_e(f.get("at") or "—")}</td>
        </tr>
        """
        for f in telemetry["failures"]["recent"][:10]
    ) or '<tr><td colspan="4" class="empty">No current failure records in durable telemetry.</td></tr>'

    usage_order = [
        ("cost_usd","USD"),("model_calls","Model calls"),("api_calls","API calls"),
        ("github_job_starts","GitHub jobs"),("github_runner_minutes","Runner minutes"),
    ]
    usage_rows = "".join(
        f"""
        <tr>
          <td>{_e(label)}</td>
          <td class="num">{_e(telemetry["cost"]["utilization"][key]["actual"])}</td>
          <td class="num">{_e(telemetry["cost"]["utilization"][key]["used"])}</td>
          <td class="num">{_e(telemetry["cost"]["utilization"][key]["ceiling"])}</td>
          <td class="num">{_e(round(100*telemetry["cost"]["utilization"][key]["fraction"],1))}%</td>
        </tr>
        """ for key,label in usage_order
    )

    daily_rows = "".join(
        f"""
        <tr>
          <td>{_e(d["day"])}</td>
          <td class="num">{d["completed_work"]}</td>
          <td class="num">{_e(d["cost_usd"])}</td>
          <td class="num">{d["model_calls"]}</td>
          <td class="num">{d["hunter_candidates"]}</td>
          <td class="num">{d["action_executions"]}</td>
          <td class="num">{d["new_failures"]}</td>
          <td class="num">{d["verified_external_outcomes"]}</td>
        </tr>
        """ for d in history["daily"]
    ) or '<tr><td colspan="8" class="empty">History begins with this deployment; daily trends will accumulate automatically.</td></tr>'

    momentum_sorted = sorted(
        history["project_momentum"],
        key=lambda x:(
            -x["verified_outcomes_delta"],-x["completed_work_delta"],-x["sent_actions_delta"],
            -x["open_work"],x["project_id"]
        ),
    )
    momentum_rows = "".join(
        f"""
        <tr>
          <td><strong>{_e(m["project_id"])}</strong><span class="sub">{_e(project_names.get(m["project_id"],""))}</span></td>
          <td class="num">{m["open_work"]}</td>
          <td class="num">{m["completed_work_delta"]}</td>
          <td class="num">{m["sent_actions_delta"]}</td>
          <td class="num">{m["verified_outcomes_delta"]}</td>
          <td class="num">{m["cancelled_work_delta"]}</td>
        </tr>
        """ for m in momentum_sorted
    )

    queue_cards = "".join(
        f"""
        <article class="mobile-record">
          <div class="mobile-record-head">
            <div class="mobile-title">
              <strong>{_e(w["work_type"].replace("_", " ").title())}</strong>
              <code>{_e(w["work_id"])}</code>
            </div>
            {_badge(w["state"], _status_tone(w["state"]))}
          </div>
          <div class="mobile-stats mobile-stats-2">
            <div><span>Agent</span><strong>{_e(w["assigned_agent_id"])}</strong></div>
            <div><span>Projects</span><strong>{_e(", ".join(w["project_ids"]) or "—")}</strong></div>
            <div><span>Created</span><strong>{_e(compact_timestamp(w.get("created_at")))}</strong></div>
            <div><span>Source</span><code>{_e(w.get("source_ref") or "—")}</code></div>
          </div>
        </article>
        """
        for w in telemetry["queue"]["items"]
    ) or '<div class="empty mobile-record">No durable scheduler work items.</div>'

    agent_cards = "".join(
        f"""
        <article class="mobile-record">
          <div class="mobile-record-head">
            <div class="mobile-title"><strong>{_e(a["name"])}</strong><code>{_e(a["agent_id"])}</code></div>
            {_badge(a["heartbeat_health"], _status_tone(a["heartbeat_health"]))}
          </div>
          <div class="mobile-stats mobile-stats-2">
            <div><span>Evidence age</span><strong>{_e(str(a["activity_age_minutes"]) + " min" if a["activity_age_minutes"] is not None else "—")}</strong></div>
            <div><span>Open work</span><strong>{_e(a["open_work_count"])}</strong></div>
            <div><span>Last activity</span><strong>{_e((a["last_activity_kind"] or "—").replace("_"," "))}</strong></div>
            <div><span>Autonomy / tier</span><strong>{_e(a["max_autonomy"])} · T{_e(a["max_model_tier"])}</strong></div>
          </div>
          <div class="mobile-meta"><span>Source</span><strong>{_e(a["source_workflow"] or "—")}</strong><code>run {_e(a["source_run_id"] or "—")}</code></div>
        </article>
        """
        for a in snapshot["agents"]
    )

    strategy_cards = "".join(
        f"""
        <article class="mobile-record">
          <div class="mobile-record-head">
            <div class="mobile-title mobile-title-wide"><strong>{_e(name.replace("STRAT:","").replace("-"," "))}</strong><code>{_e(name)}</code></div>
          </div>
          <div class="mobile-stats mobile-stats-3">
            <div><span>Cycles</span><strong>{stats["cycles"]}</strong></div>
            <div><span>Queries</span><strong>{stats["queries"]}</strong></div>
            <div><span>Candidates</span><strong>{stats["candidates"]}</strong></div>
            <div><span>Retained</span><strong>{stats["retained"]}</strong></div>
            <div><span>Verified value</span><strong>{stats["verified_value_outcomes"]}</strong></div>
          </div>
        </article>
        """
        for name, stats in snapshot["hunter"]["strategy_stats"].items()
    )

    usage_cards = "".join(
        f"""
        <article class="mobile-record compact">
          <div class="mobile-record-head">
            <div class="mobile-title"><strong>{_e(label)}</strong></div>
            {_badge(f'{round(100*telemetry["cost"]["utilization"][key]["fraction"],1)}% used',"neutral")}
          </div>
          <div class="mobile-stats mobile-stats-3">
            <div><span>Actual</span><strong>{_e(telemetry["cost"]["utilization"][key]["actual"])}</strong></div>
            <div><span>Accounted</span><strong>{_e(telemetry["cost"]["utilization"][key]["used"])}</strong></div>
            <div><span>Ceiling</span><strong>{_e(telemetry["cost"]["utilization"][key]["ceiling"])}</strong></div>
          </div>
        </article>
        """
        for key,label in usage_order
    )

    action_cards = "".join(
        f"""
        <article class="mobile-record">
          <div class="mobile-record-head">
            <div class="mobile-title"><strong>{_e(project_names.get(a["project_id"], a["project_id"]))}</strong><code>{_e(a["action_id"])}</code></div>
            {_badge(a["status"], _status_tone(a["status"]))}
          </div>
          <div class="mobile-stats mobile-stats-2">
            <div><span>Type</span><strong>{_e(a["action_type"].replace("_"," "))}</strong></div>
            <div><span>Sent</span><strong>{_e(compact_timestamp(a["sent_at"]))}</strong></div>
          </div>
        </article>
        """
        for a in telemetry["actions"]["recent"][:10]
    ) or '<div class="empty mobile-record">No sanitized action receipts.</div>'

    failure_cards = "".join(
        f"""
        <article class="mobile-record">
          <div class="mobile-record-head">
            <div class="mobile-title"><strong>{_e(f["kind"].replace("_"," "))}</strong><code>{_e(f.get("ref") or "—")}</code></div>
            {_badge("FAILURE","bad")}
          </div>
          <div class="mobile-stats mobile-stats-2">
            <div><span>Projects</span><strong>{_e(", ".join(f.get("project_ids") or []) or "—")}</strong></div>
            <div><span>Observed</span><strong>{_e(compact_timestamp(f.get("at")))}</strong></div>
          </div>
        </article>
        """
        for f in telemetry["failures"]["recent"][:10]
    ) or '<div class="empty mobile-record">No current failure records in durable telemetry.</div>'

    daily_cards = "".join(
        f"""
        <article class="mobile-record">
          <div class="mobile-record-head">
            <div class="mobile-title"><strong>{_e(d["day"])}</strong></div>
            {_badge(f'USD {_e(d["cost_usd"])}',"neutral")}
          </div>
          <div class="mobile-stats mobile-stats-3">
            <div><span>Completed</span><strong>{d["completed_work"]}</strong></div>
            <div><span>Model calls</span><strong>{d["model_calls"]}</strong></div>
            <div><span>Hunter</span><strong>{d["hunter_candidates"]}</strong></div>
            <div><span>Actions</span><strong>{d["action_executions"]}</strong></div>
            <div><span>Failures</span><strong>{d["new_failures"]}</strong></div>
            <div><span>Outcomes</span><strong>{d["verified_external_outcomes"]}</strong></div>
          </div>
        </article>
        """
        for d in history["daily"]
    ) or '<div class="empty mobile-record">History will accumulate automatically.</div>'

    momentum_cards = "".join(
        f"""
        <article class="mobile-record compact">
          <div class="mobile-record-head">
            <div class="mobile-title"><strong>{_e(project_names.get(m["project_id"], m["project_id"]))}</strong><code>{_e(m["project_id"])}</code></div>
            {_badge(f'{m["open_work"]} open',"neutral")}
          </div>
          <div class="mobile-stats mobile-stats-2">
            <div><span>Completed Δ</span><strong>{m["completed_work_delta"]}</strong></div>
            <div><span>Actions Δ</span><strong>{m["sent_actions_delta"]}</strong></div>
            <div><span>Verified Δ</span><strong>{m["verified_outcomes_delta"]}</strong></div>
            <div><span>Cancelled Δ</span><strong>{m["cancelled_work_delta"]}</strong></div>
          </div>
        </article>
        """
        for m in momentum_sorted
    )

    last_cycle = telemetry["cycles"]["latest_overall"]
    if last_cycle is None:
        last_cycle_title = "No successful cycle yet"
        last_cycle_meta = "Waiting for durable runtime evidence."
        last_cycle_id = ""
    else:
        last_cycle_title = str(last_cycle["subsystem"]).replace("_"," ").title()
        last_cycle_meta = "Successful · " + compact_timestamp(last_cycle["finished_at"])
        raw_cycle_id = str(last_cycle["cycle_id"])
        last_cycle_id = raw_cycle_id if len(raw_cycle_id) <= 22 else raw_cycle_id[:19] + "…"

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#f5f5f7" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#000000" media="(prefers-color-scheme: dark)">
<title>Portfolio Brain Command Center</title>
<style>
:root {{
  color-scheme: light dark;
  --page:#f5f5f7;
  --page-2:#ffffff;
  --surface:rgba(255,255,255,.82);
  --surface-solid:#ffffff;
  --surface-soft:rgba(248,248,250,.86);
  --glass:rgba(250,250,252,.76);
  --line:rgba(0,0,0,.08);
  --line-strong:rgba(0,0,0,.13);
  --text:#1d1d1f;
  --muted:#6e6e73;
  --faint:#a1a1a6;
  --blue:#0071e3;
  --blue-2:#2997ff;
  --green:#16893e;
  --amber:#ad6a00;
  --red:#d70015;
  --cyan:#007c91;
  --shadow:0 22px 70px rgba(0,0,0,.08);
  --shadow-soft:0 8px 30px rgba(0,0,0,.055);
  --radius-xl:32px;
  --radius-lg:24px;
  --radius-md:18px;
  --nav-h:58px;
}}
@media (prefers-color-scheme:dark){{
  :root{{
    --page:#000000;
    --page-2:#0a0a0a;
    --surface:rgba(28,28,30,.78);
    --surface-solid:#1c1c1e;
    --surface-soft:rgba(44,44,46,.64);
    --glass:rgba(20,20,22,.72);
    --line:rgba(255,255,255,.10);
    --line-strong:rgba(255,255,255,.16);
    --text:#f5f5f7;
    --muted:#a1a1a6;
    --faint:#6e6e73;
    --blue:#2997ff;
    --blue-2:#64d2ff;
    --green:#30d158;
    --amber:#ffd60a;
    --red:#ff453a;
    --cyan:#64d2ff;
    --shadow:0 28px 90px rgba(0,0,0,.35);
    --shadow-soft:0 10px 36px rgba(0,0,0,.26);
  }}
}}
*{{box-sizing:border-box}}
html{{scroll-behavior:smooth;background:var(--page)}}
body{{
  margin:0;
  min-height:100vh;
  color:var(--text);
  background:
    radial-gradient(900px 540px at 14% -10%,rgba(0,113,227,.10),transparent 64%),
    radial-gradient(760px 520px at 88% 8%,rgba(100,210,255,.09),transparent 62%),
    linear-gradient(180deg,var(--page-2) 0,var(--page) 22rem,var(--page) 100%);
  font-family:-apple-system,BlinkMacSystemFont,"SF Pro Display","SF Pro Text","Helvetica Neue",Arial,sans-serif;
  -webkit-font-smoothing:antialiased;
  text-rendering:optimizeLegibility;
  letter-spacing:-.012em;
}}
::selection{{background:rgba(0,113,227,.18)}}
a{{color:inherit}}
code{{
  font-family:"SFMono-Regular",ui-monospace,Menlo,Monaco,Consolas,monospace;
  color:var(--muted);
  font-size:.74rem;
  overflow-wrap:anywhere;
}}
.shell{{display:block;min-height:100vh}}
aside{{
  position:sticky;
  top:0;
  z-index:100;
  height:var(--nav-h);
  display:flex;
  align-items:center;
  gap:22px;
  padding:0 max(22px,calc((100vw - 1480px)/2));
  border-bottom:1px solid var(--line);
  background:var(--glass);
  -webkit-backdrop-filter:saturate(180%) blur(24px);
  backdrop-filter:saturate(180%) blur(24px);
}}
.brand{{
  display:flex;
  align-items:center;
  gap:10px;
  min-width:max-content;
  font-size:.82rem;
  font-weight:650;
  letter-spacing:-.01em;
}}
.logo{{
  width:28px;height:28px;border-radius:9px;
  display:grid;place-items:center;
  background:linear-gradient(145deg,#0a84ff,#64d2ff);
  box-shadow:inset 0 1px 0 rgba(255,255,255,.35),0 6px 18px rgba(0,113,227,.22);
}}
.logo::after{{content:"PB";color:#fff;font-size:.57rem;font-weight:800;letter-spacing:-.04em}}
.brand small{{display:none}}
nav{{
  flex:1;
  display:flex;
  align-items:center;
  justify-content:center;
  gap:4px;
  min-width:0;
  overflow-x:auto;
  scrollbar-width:none;
  scroll-snap-type:x proximity;
  -webkit-overflow-scrolling:touch;
}}
nav::-webkit-scrollbar{{display:none}}
nav a{{
  text-decoration:none;
  color:var(--muted);
  padding:7px 10px;
  border-radius:999px;
  font-size:.73rem;
  font-weight:520;
  white-space:nowrap;
  transition:color .2s ease,background .2s ease,transform .2s ease;
  scroll-snap-align:start;
}}
nav a:hover{{color:var(--text);background:var(--surface-soft);transform:translateY(-1px)}}
.readonly{{
  min-width:max-content;
  display:flex;
  align-items:center;
  gap:7px;
  padding:6px 10px;
  border:1px solid var(--line);
  border-radius:999px;
  color:var(--muted);
  background:var(--surface-soft);
  font-size:.68rem;
  font-weight:560;
}}
.readonly strong{{color:var(--green);font-weight:700}}
.readonly strong::before{{content:"";display:inline-block;width:6px;height:6px;border-radius:50%;background:currentColor;margin-right:6px;box-shadow:0 0 0 3px color-mix(in srgb,currentColor 12%,transparent)}}
main{{
  width:min(1480px,calc(100% - 48px));
  margin:0 auto;
  padding:0 0 72px;
}}
.topbar{{
  position:relative;
  min-height:460px;
  display:grid;
  grid-template-columns:minmax(0,1fr) auto;
  align-items:end;
  gap:40px;
  padding:94px 22px 54px;
  margin-bottom:18px;
  overflow:hidden;
}}
.topbar::before{{
  content:"";
  position:absolute;
  width:520px;height:520px;
  right:-130px;top:-170px;
  border-radius:50%;
  background:radial-gradient(circle at 35% 35%,rgba(41,151,255,.23),rgba(100,210,255,.09) 38%,transparent 70%);
  filter:blur(4px);
  pointer-events:none;
}}
.topbar::after{{
  content:"";
  position:absolute;
  width:430px;height:220px;
  left:12%;bottom:-130px;
  border-radius:50%;
  background:radial-gradient(ellipse,rgba(94,92,230,.11),transparent 67%);
  filter:blur(18px);
  pointer-events:none;
}}
.hero-copy{{position:relative;z-index:1;max-width:980px}}
.eyebrow{{
  display:flex;align-items:center;gap:9px;
  margin-bottom:18px;
  color:var(--muted);
  font-size:.78rem;font-weight:650;
  letter-spacing:.08em;text-transform:uppercase;
}}
.signal-dot{{width:8px;height:8px;border-radius:50%;background:var(--green);box-shadow:0 0 0 5px color-mix(in srgb,var(--green) 12%,transparent)}}
h1{{
  max-width:1050px;
  margin:0;
  font-size:clamp(3.6rem,7vw,7.2rem);
  line-height:.91;
  letter-spacing:-.065em;
  font-weight:720;
}}
h2{{
  margin:0;
  font-size:clamp(1.35rem,2vw,2rem);
  line-height:1.05;
  letter-spacing:-.035em;
  font-weight:650;
}}
p{{color:var(--muted);margin:.45rem 0;line-height:1.48}}
.hero-lede{{
  max-width:760px;
  margin-top:24px;
  font-size:clamp(1.08rem,1.6vw,1.42rem);
  line-height:1.42;
  letter-spacing:-.025em;
}}
.hero-badges{{display:flex;flex-wrap:wrap;gap:7px;margin-top:24px}}
.actions{{
  position:relative;z-index:1;
  display:flex;gap:8px;flex-wrap:wrap;
  justify-content:flex-end;
  align-self:end;
  padding-bottom:6px;
}}
button{{
  appearance:none;
  border:0;
  background:var(--text);
  color:var(--page);
  padding:11px 17px;
  border-radius:999px;
  font:inherit;
  font-size:.82rem;
  font-weight:620;
  cursor:pointer;
  box-shadow:var(--shadow-soft);
  transition:transform .22s ease,opacity .22s ease,box-shadow .22s ease;
}}
button+button{{background:var(--surface-solid);color:var(--text);border:1px solid var(--line)}}
button:hover{{transform:translateY(-2px);box-shadow:0 12px 34px rgba(0,0,0,.12)}}
button:active{{transform:translateY(0) scale(.985)}}
.grid{{display:grid;gap:18px}}
.kpis{{
  grid-template-columns:repeat(12,minmax(0,1fr));
  margin-bottom:22px;
}}
.kpi{{grid-column:span 2;min-height:188px;display:flex;flex-direction:column;justify-content:space-between}}
.kpi:nth-child(1),.kpi:nth-child(2){{grid-column:span 3}}
.kpi:nth-child(5),.kpi:nth-child(6){{grid-column:span 3}}
.card{{
  position:relative;
  overflow:hidden;
  background:var(--surface);
  border:1px solid var(--line);
  border-radius:var(--radius-xl);
  padding:28px;
  box-shadow:var(--shadow-soft);
  -webkit-backdrop-filter:blur(24px) saturate(135%);
  backdrop-filter:blur(24px) saturate(135%);
  transition:transform .28s cubic-bezier(.2,.8,.2,1),box-shadow .28s ease,border-color .28s ease;
}}
.card::before{{
  content:"";
  position:absolute;inset:0 0 auto 0;height:1px;
  background:linear-gradient(90deg,transparent,rgba(255,255,255,.7),transparent);
  opacity:.72;pointer-events:none;
}}
.card:hover{{transform:translateY(-2px);box-shadow:var(--shadow);border-color:var(--line-strong)}}
.kpi::after{{
  content:"";
  position:absolute;
  width:150px;height:150px;
  right:-58px;bottom:-72px;border-radius:50%;
  background:radial-gradient(circle,rgba(41,151,255,.11),transparent 68%);
  pointer-events:none;
}}
.kpi:nth-child(4)::after{{background:radial-gradient(circle,rgba(215,0,21,.09),transparent 68%)}}
.kpi:nth-child(5)::after{{background:radial-gradient(circle,rgba(48,209,88,.10),transparent 68%)}}
.kpi .label{{
  font-size:.72rem;
  text-transform:uppercase;
  letter-spacing:.085em;
  color:var(--muted);
  font-weight:650;
}}
.kpi .value{{
  margin-top:18px;
  font-size:clamp(2.25rem,3.3vw,4.2rem);
  line-height:.92;
  letter-spacing:-.06em;
  font-weight:680;
}}
.kpi .hint{{font-size:.78rem;color:var(--muted);margin-top:14px}}
.two{{grid-template-columns:minmax(0,1.35fr) minmax(360px,.85fr)}}
.three{{grid-template-columns:repeat(3,minmax(0,1fr))}}
.section-head{{
  display:flex;
  justify-content:space-between;
  align-items:flex-start;
  gap:18px;
  margin-bottom:22px;
}}
.section-head p{{font-size:.86rem;max-width:760px;margin-top:7px}}
.badge{{
  display:inline-flex;align-items:center;
  white-space:nowrap;
  border:0;
  border-radius:999px;
  padding:6px 10px;
  font-size:.66rem;
  font-weight:690;
  letter-spacing:.035em;
  background:var(--surface-soft);
  color:var(--muted);
  box-shadow:inset 0 0 0 1px var(--line);
}}
.badge.good{{color:var(--green);background:color-mix(in srgb,var(--green) 9%,var(--surface-solid))}}
.badge.warn{{color:var(--amber);background:color-mix(in srgb,var(--amber) 9%,var(--surface-solid))}}
.badge.bad{{color:var(--red);background:color-mix(in srgb,var(--red) 9%,var(--surface-solid))}}
.badge.neutral{{color:var(--muted)}}
.table-wrap{{
  width:100%;
  overflow:auto;
  -webkit-overflow-scrolling:touch;
  border:1px solid var(--line);
  border-radius:20px;
  background:color-mix(in srgb,var(--surface-solid) 76%,transparent);
}}
table{{width:100%;border-collapse:separate;border-spacing:0;font-size:.82rem}}
th{{
  position:sticky;top:0;
  z-index:2;
  text-align:left;
  color:var(--muted);
  background:color-mix(in srgb,var(--surface-solid) 94%,transparent);
  -webkit-backdrop-filter:blur(16px);
  backdrop-filter:blur(16px);
  font-size:.65rem;
  font-weight:690;
  text-transform:uppercase;
  letter-spacing:.07em;
  padding:12px 14px;
  border-bottom:1px solid var(--line);
}}
td{{padding:14px;border-bottom:1px solid var(--line);vertical-align:top}}
tbody tr:last-child td{{border-bottom:0}}
tbody tr{{transition:background .18s ease}}
tbody tr:hover{{background:color-mix(in srgb,var(--blue) 4%,transparent)}}
.sub{{display:block;color:var(--muted);font-size:.7rem;margin-top:4px}}
.num{{text-align:right;font-variant-numeric:tabular-nums}}
.wrap{{max-width:520px;line-height:1.38}}
.search{{
  width:270px;max-width:100%;
  appearance:none;
  background:var(--surface-soft);
  border:1px solid var(--line);
  color:var(--text);
  padding:10px 14px;
  border-radius:999px;
  outline:none;
  font:inherit;font-size:.8rem;
  transition:border .2s ease,box-shadow .2s ease,background .2s ease;
}}
.search:focus{{border-color:var(--blue);box-shadow:0 0 0 4px color-mix(in srgb,var(--blue) 12%,transparent);background:var(--surface-solid)}}
.alert-row{{
  display:grid;grid-template-columns:70px minmax(0,1fr) auto;
  gap:16px;align-items:start;
  padding:16px 0;border-bottom:1px solid var(--line);
}}
.alert-row:last-child{{border-bottom:0}}
.alert-row span:not(.badge){{display:block;color:var(--muted);font-size:.82rem;margin-top:5px;line-height:1.45}}
.switches{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}}
.switch-card{{
  min-width:0;
  border:1px solid var(--line);
  background:var(--surface-soft);
  padding:14px;
  border-radius:17px;
}}
.switch-card strong,.switch-card span{{display:block}}
.switch-card span{{color:var(--muted);font-size:.7rem;margin:3px 0 7px}}
.switch-dot{{width:9px;height:9px;border-radius:50%;float:right;margin-top:4px}}
.switch-dot.on{{background:var(--green);box-shadow:0 0 0 4px color-mix(in srgb,var(--green) 12%,transparent)}}
.switch-dot.off{{background:var(--red);box-shadow:0 0 0 4px color-mix(in srgb,var(--red) 12%,transparent)}}
.callout{{
  min-height:124px;
  border:1px solid var(--line);
  background:linear-gradient(145deg,var(--surface-soft),color-mix(in srgb,var(--blue) 3%,var(--surface-solid)));
  border-radius:22px;
  padding:20px;
}}
.callout strong{{color:var(--text);font-size:.88rem}}
.callout p{{font-size:.86rem;margin-top:8px}}
.callout-value{{display:block;margin-top:16px;font-size:1.3rem;font-weight:660;letter-spacing:-.035em}}
.callout-meta{{display:block;margin-top:7px;color:var(--muted);font-size:.8rem;line-height:1.4}}
.cycle-id{{display:block;margin-top:8px;max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.break-anywhere{{overflow-wrap:anywhere;word-break:break-word;white-space:normal}}
.spec-grid{{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:16px}}
.spec-item{{min-width:0;padding:14px 15px;border:1px solid var(--line);border-radius:17px;background:var(--surface-soft)}}
.spec-item>span{{display:block;color:var(--muted);font-size:.66rem;font-weight:670;text-transform:uppercase;letter-spacing:.055em;margin-bottom:6px}}
.spec-item>strong,.spec-item>code{{display:block;font-size:.82rem;line-height:1.4}}
.source-mobile{{display:none}}
.source-mobile-card{{border:1px solid var(--line);border-radius:20px;background:var(--surface-soft);padding:16px}}
.source-mobile-head{{display:flex;align-items:flex-start;justify-content:space-between;gap:12px}}
.source-mobile-specs{{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:14px}}
.source-mobile-specs>div{{min-width:0}}
.source-mobile-specs span{{display:block;color:var(--muted);font-size:.62rem;text-transform:uppercase;letter-spacing:.05em}}
.source-mobile-specs strong{{display:block;margin-top:4px;font-size:.8rem;overflow-wrap:anywhere}}
.source-mobile-time{{margin-top:12px;color:var(--muted);font-size:.72rem}}
.mobile-records{{display:none}}
.mobile-record{{
  min-width:0;
  border:1px solid var(--line);
  border-radius:20px;
  background:var(--surface-soft);
  padding:16px;
}}
.mobile-record.compact{{padding:14px 16px}}
.mobile-record-head{{display:flex;align-items:flex-start;justify-content:space-between;gap:12px}}
.mobile-title{{min-width:0;display:grid;gap:5px}}
.mobile-title strong{{font-size:.98rem;line-height:1.22;letter-spacing:-.02em;overflow-wrap:anywhere}}
.mobile-title code{{display:block;max-width:100%;font-size:.66rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.mobile-title-wide strong{{text-transform:capitalize}}
.mobile-stats{{display:grid;gap:8px;margin-top:14px}}
.mobile-stats-2{{grid-template-columns:repeat(2,minmax(0,1fr))}}
.mobile-stats-3{{grid-template-columns:repeat(3,minmax(0,1fr))}}
.mobile-stats>div{{
  min-width:0;
  padding:10px 11px;
  border:1px solid var(--line);
  border-radius:14px;
  background:color-mix(in srgb,var(--surface-solid) 70%,transparent);
}}
.mobile-stats span,.mobile-meta span{{
  display:block;
  color:var(--muted);
  font-size:.59rem;
  font-weight:680;
  text-transform:uppercase;
  letter-spacing:.055em;
}}
.mobile-stats strong{{
  display:block;
  margin-top:5px;
  font-size:.82rem;
  line-height:1.3;
  overflow-wrap:anywhere;
  font-variant-numeric:tabular-nums;
}}
.mobile-stats code{{display:block;margin-top:5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.mobile-meta{{
  display:grid;
  grid-template-columns:auto minmax(0,1fr);
  gap:5px 10px;
  align-items:baseline;
  margin-top:12px;
  padding-top:12px;
  border-top:1px solid var(--line);
}}
.mobile-meta strong{{font-size:.8rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.mobile-meta code{{grid-column:2;font-size:.64rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.project-mobile{{display:none}}
.project-mobile-card{{border:1px solid var(--line);border-radius:22px;background:var(--surface-soft);padding:18px}}
.project-mobile-top{{display:flex;justify-content:space-between;align-items:flex-start;gap:14px}}
.project-mobile-title{{min-width:0}}
.project-mobile-title strong{{display:block;font-size:1rem;letter-spacing:-.025em}}
.project-mobile-title span{{display:block;margin-top:4px;color:var(--muted);font-size:.86rem;line-height:1.3}}
.project-mobile-badges{{display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end;max-width:58%}}
.project-mobile-badges .badge{{max-width:100%;overflow:hidden;text-overflow:ellipsis}}
.project-mobile-stats{{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:16px}}
.project-mobile-stats>div{{min-width:0;border:1px solid var(--line);background:color-mix(in srgb,var(--surface-solid) 72%,transparent);border-radius:15px;padding:11px}}
.project-mobile-stats span{{display:block;color:var(--muted);font-size:.6rem;text-transform:uppercase;letter-spacing:.05em}}
.project-mobile-stats strong{{display:block;margin-top:5px;font-size:1rem;font-variant-numeric:tabular-nums}}
.project-bottleneck{{margin-top:14px;border-top:1px solid var(--line);padding-top:12px}}
.project-bottleneck summary{{cursor:pointer;list-style:none;color:var(--blue);font-size:.78rem;font-weight:620}}
.project-bottleneck summary::-webkit-details-marker{{display:none}}
.project-bottleneck summary::after{{content:"+";float:right;font-size:1rem;line-height:.9;color:var(--muted)}}
.project-bottleneck[open] summary::after{{content:"–"}}
.project-bottleneck p{{margin:10px 0 0;font-size:.82rem;line-height:1.45}}
ul{{margin:.7rem 0 0;padding-left:19px;color:var(--muted)}}
li{{margin:.45rem 0;line-height:1.42}}
.progress{{height:7px;border-radius:999px;background:var(--surface-soft);overflow:hidden;border:1px solid var(--line);margin:11px 0}}
.progress span{{display:block;height:100%;background:linear-gradient(90deg,var(--blue),var(--blue-2));width:0%}}
.mono{{font-family:"SFMono-Regular",ui-monospace,Menlo,monospace}}
.footer{{color:var(--muted);font-size:.7rem;text-align:center;padding:52px 0 10px}}
.empty{{color:var(--muted);padding:20px 14px}}
section{{scroll-margin-top:calc(var(--nav-h) + 18px);margin-top:18px!important}}
#live-state{{background:linear-gradient(145deg,var(--surface),color-mix(in srgb,var(--blue) 4%,var(--surface-solid)))}}
#operations{{background:linear-gradient(145deg,var(--surface),color-mix(in srgb,var(--cyan) 3%,var(--surface-solid)))}}
#trends{{background:linear-gradient(145deg,var(--surface),color-mix(in srgb,#af52de 4%,var(--surface-solid)))}}
#boundary .card:first-child{{background:linear-gradient(145deg,var(--surface),color-mix(in srgb,var(--green) 4%,var(--surface-solid)))}}
#boundary .card:last-child{{background:linear-gradient(145deg,var(--surface),color-mix(in srgb,var(--red) 3%,var(--surface-solid)))}}
@keyframes rise{{from{{opacity:0;transform:translateY(14px)}}to{{opacity:1;transform:none}}}}
.topbar,.kpis,.card{{animation:rise .62s cubic-bezier(.2,.8,.2,1) both}}
.kpis{{animation-delay:.04s}}
.card:nth-of-type(2){{animation-delay:.07s}}
@media(prefers-reduced-motion:reduce){{
  html{{scroll-behavior:auto}}
  *,*::before,*::after{{animation:none!important;transition:none!important}}
}}
@media(max-width:1220px){{
  aside{{padding:0 18px;gap:12px}}
  nav{{justify-content:flex-start;overflow-x:auto;scrollbar-width:none}}
  nav::-webkit-scrollbar{{display:none}}
  nav a{{font-size:.7rem}}
  .readonly{{display:none}}
  .kpi{{grid-column:span 4}}
  .kpi:nth-child(1),.kpi:nth-child(2),.kpi:nth-child(5),.kpi:nth-child(6){{grid-column:span 4}}
  .two{{grid-template-columns:1fr}}
}}
@media(max-width:820px){{
  :root{{--nav-h:96px;--radius-xl:22px}}
  body{{overflow-x:hidden}}
  aside{{
    min-height:var(--nav-h);
    height:auto;
    align-content:center;
    flex-wrap:wrap;
    gap:7px 10px;
    padding:8px max(12px,env(safe-area-inset-left)) 8px max(12px,env(safe-area-inset-right));
  }}
  .brand{{font-size:.75rem;min-height:30px}}
  .logo{{width:28px;height:28px;border-radius:9px}}
  nav{{
    order:3;
    flex:0 0 100%;
    justify-content:flex-start;
    gap:6px;
    margin:0;
    padding:0 8px 1px 0;
    scroll-padding-inline:2px 22px;
  }}
  nav a{{
    min-height:34px;
    display:flex;
    align-items:center;
    padding:7px 11px;
    border:1px solid var(--line);
    background:color-mix(in srgb,var(--surface-solid) 70%,transparent);
    font-size:.69rem;
    scroll-snap-align:start;
  }}
  main{{
    width:100%;
    padding:0 max(12px,env(safe-area-inset-right)) calc(46px + env(safe-area-inset-bottom)) max(12px,env(safe-area-inset-left));
  }}
  .topbar{{min-height:340px;display:block;padding:52px 6px 30px}}
  h1{{font-size:clamp(3.25rem,16vw,5.6rem)}}
  .hero-lede{{font-size:1.05rem;max-width:92%}}
  .actions{{justify-content:flex-start;margin-top:28px}}
  .kpis{{grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}}
  .kpi,.kpi:nth-child(n){{grid-column:span 1;min-height:158px;padding:20px}}
  .kpi .value{{font-size:2.5rem}}
  .card{{padding:18px;border-radius:22px;box-shadow:0 6px 24px rgba(0,0,0,.045)}}
  .card:hover{{transform:none}}
  .three{{grid-template-columns:1fr}}
  .switches{{grid-template-columns:repeat(2,minmax(0,1fr))}}
  .section-head{{display:block}}
  .section-head>.badge{{margin-top:12px}}
  .table-wrap{{margin-left:0;margin-right:0;width:100%;border-radius:17px}}
  .mobile-hide{{display:none!important}}
  .mobile-records{{display:grid;gap:10px}}
  .source-desktop{{display:none}}
  .source-mobile{{display:grid;gap:10px}}
  .project-desktop{{display:none}}
  .project-mobile{{display:grid;gap:10px}}
  .callout{{min-height:0;padding:18px}}
  .cycle-callout{{min-height:0}}
  .spec-grid{{grid-template-columns:1fr}}
  .spec-item{{padding:13px 14px}}
  th,td{{padding:12px 11px}}
  .alert-row{{grid-template-columns:1fr;gap:7px}}
  .search{{margin-top:12px;width:100%;font-size:16px;min-height:44px}}
  button{{min-height:44px;padding:10px 16px}}
  .section-head{{margin-bottom:16px}}
  .section-head p{{font-size:.82rem;line-height:1.42}}
  h2{{font-size:1.62rem;line-height:1.08}}
  .badge{{font-size:.62rem;padding:6px 9px}}
  .source-mobile-specs{{grid-template-columns:repeat(2,minmax(0,1fr))}}
  .project-mobile-badges{{max-width:52%}}
  .mobile-stats-3{{grid-template-columns:repeat(3,minmax(0,1fr))}}
}}

@media(max-width:520px){{
  :root{{--nav-h:94px}}
  nav{{gap:6px;padding-right:24px}}
  nav a{{padding:7px 10px;font-size:.68rem}}
  .brand div:last-child{{font-size:0}}
  .brand div:last-child::after{{content:"Brain";font-size:.76rem}}
  .topbar{{min-height:320px;padding-top:46px}}
  .eyebrow{{font-size:.66rem}}
  h1{{font-size:clamp(2.9rem,17vw,4.5rem)}}
  .hero-lede{{font-size:.98rem}}
  .kpis{{grid-template-columns:1fr 1fr}}
  .kpi{{min-height:145px}}
  .kpi .label{{font-size:.65rem}}
  .kpi .value{{font-size:2.15rem}}
  .switches{{grid-template-columns:1fr}}
  .mobile-stats-3{{grid-template-columns:repeat(2,minmax(0,1fr))}}
  .mobile-record{{padding:14px}}
  .mobile-record-head{{gap:9px}}
  .mobile-title strong{{font-size:.94rem}}
  .mobile-stats{{gap:7px;margin-top:12px}}
  .mobile-stats>div{{padding:9px 10px}}
  .project-mobile-stats{{gap:6px}}
}}

</style>
</head>
<body data-design="apple-inspired-v4-1" data-mobile-optimized="true">
<div class="shell">
<aside>
  <div class="brand"><div class="logo"></div><div>PORTFOLIO BRAIN<small>Command Center v4.1</small></div></div>
  <nav>
    <a href="#overview">Overview</a><a href="#live-state">Live</a><a href="#operations">Ops</a><a href="#trends">Trends</a><a href="#alerts">Alerts</a><a href="#projects">Portfolio</a>
    <a href="#agents">Agents</a><a href="#actions">Actions</a><a href="#hunter">Hunter</a>
    <a href="#cost">Cost</a><a href="#workflows">Workflows</a><a href="#boundary">Boundaries</a>
  </nav>
  <div class="readonly"><strong>OBSERVE ONLY</strong><span>Public command center</span></div>
</aside>
<main>
  <header class="topbar" id="overview">
    <div class="hero-copy">
      <div class="eyebrow"><span class="signal-dot"></span>Portfolio Intelligence System</div>
      <h1>Portfolio Brain Command Center</h1>
      <p class="hero-lede">A live, evidence-backed view of your autonomous portfolio — work, agents, spend, outcomes, and operating boundaries in one place.</p>
      <div class="hero-badges">{_badge(system["functional_status"], _status_tone(system["functional_status"]))} {_badge("EVIDENCE-DRIVEN", "neutral")} {_badge("READ ONLY", "neutral")}</div>
    </div>
    <div class="actions">
      <button type="button" onclick="location.reload()">Refresh</button>
      <button type="button" onclick="navigator.clipboard && navigator.clipboard.writeText(document.getElementById('snapshotHash').textContent)">Copy hash</button>
    </div>
  </header>

  <section class="grid kpis">
    <div class="card kpi"><div class="label">Projects</div><div class="value">{system["project_count"]}</div><div class="hint">{len([p for p in snapshot["projects"] if p["lifecycle_status"] == "ACTIVE"])} active</div></div>
    <div class="card kpi"><div class="label">Agents healthy</div><div class="value">{system["healthy_agent_count"]}/{system["agent_count"]}</div><div class="hint">{system["stalled_agent_count"]} stalled · {system["warming_agent_count"]} warming</div></div>
    <div class="card kpi"><div class="label">Open work</div><div class="value">{telemetry["queue"]["open_total"]}</div><div class="hint">{telemetry["queue"].get("stalled_open_count",0)} stalled · {_e(sources["scheduler"]["status"].lower())}</div></div>
    <div class="card kpi"><div class="label">Blocked work</div><div class="value">{portfolio["blocked_action_count"]}</div><div class="hint">human/authority gated</div></div>
    <div class="card kpi"><div class="label">Verified outcomes</div><div class="value">{telemetry["verified_external_outcomes"]}</div><div class="hint">verified durable evidence</div></div>
    <div class="card kpi"><div class="label">Paid model spend</div><div class="value">USD {_e(round(telemetry["cost"]["actual_usage_today"]["cost_usd"],2))}</div><div class="hint">of USD {cost["portfolio_ceiling"]["cost_usd"]:.2f} today</div></div>
  </section>

  <section class="card" id="live-state" style="margin-bottom:14px">
    <div class="section-head">
      <div><h2>Live State Bridge</h2><p>Newest validated durable state is restored before publication; seeds are explicit fallback only.</p></div>
      {_badge(source_bundle["bridge_status"], _status_tone(source_bundle["bridge_status"]))}
    </div>
    <p>Bridge generated: {_e(source_bundle.get("generated_at") or "local fallback mode")}</p>
    <div class="table-wrap source-desktop"><table>
      <thead><tr><th>Subsystem</th><th>Status</th><th class="num">Seq</th><th>Artifact time</th><th>Source run</th><th class="num">Age min</th><th>Source</th></tr></thead>
      <tbody>{source_rows}</tbody>
    </table></div>
    <div class="source-mobile">{source_cards}</div>
  </section>

  <section class="card" id="operations" style="margin-bottom:14px">
    <div class="section-head">
      <div><h2>Operational Telemetry</h2><p>Durable queue, governed usage, actions, failures, agent heartbeats, and successful-cycle evidence.</p></div>
      {_badge("LIVE DATA" if source_bundle["bridge_status"]=="LIVE" else source_bundle["bridge_status"], _status_tone(source_bundle["bridge_status"]))}
    </div>
    <div class="grid three">
      <div class="callout"><strong>Queue</strong><p>Queued {telemetry["queue"]["counts"]["QUEUED"]} · Active {telemetry["queue"]["counts"]["ACTIVE"]} · Complete {telemetry["queue"]["counts"]["COMPLETE"]} · Cancelled {telemetry["queue"]["counts"]["CANCELLED"]}</p></div>
      <div class="callout cycle-callout"><strong>Last successful autonomous cycle</strong><span class="callout-value">{_e(last_cycle_title)}</span><span class="callout-meta">{_e(last_cycle_meta)}</span>{('<code class="cycle-id">'+_e(last_cycle_id)+'</code>') if last_cycle_id else ''}</div>
      <div class="callout"><strong>Failures</strong><p>{telemetry["failures"]["count"]} durable failure signal(s) currently represented.</p></div>
    </div>
    <div class="section-head" style="margin-top:16px"><div><h2>Durable Work Queue</h2><p>Newest 32 scheduler work records.</p></div>{source_badge("scheduler")}</div>
    <div class="table-wrap mobile-hide"><table>
      <thead><tr><th>Work</th><th>State</th><th>Type</th><th>Agent</th><th>Projects</th><th>Created</th></tr></thead>
      <tbody>{queue_rows}</tbody>
    </table></div>
    <div class="mobile-records">{queue_cards}</div>
  </section>

  <section class="grid two" style="margin-bottom:14px">
    <div class="card">
      <div class="section-head"><div><h2>Actual Cost / Capacity Today</h2><p>Actual committed usage is separate from conservative governor accounting.</p></div>{source_badge("cost")}</div>
      <table class="mobile-hide"><thead><tr><th>Resource</th><th class="num">Actual</th><th class="num">Accounted</th><th class="num">Ceiling</th><th class="num">Utilization</th></tr></thead><tbody>{usage_rows}</tbody></table>
      <div class="mobile-records">{usage_cards}</div>
    </div>
    <div class="card">
      <div class="section-head"><div><h2>Recent External Actions</h2><p>Sanitized action receipts only.</p></div>{_badge(f'{telemetry["actions"]["total_sent"]} total',"neutral")}</div>
      <div class="table-wrap mobile-hide"><table><thead><tr><th>Action</th><th>Project</th><th>Type</th><th>Status</th><th>Sent</th></tr></thead><tbody>{action_rows}</tbody></table></div>
      <div class="mobile-records">{action_cards}</div>
    </div>
  </section>

  <section class="card" style="margin-bottom:14px">
    <div class="section-head"><div><h2>Failure Stream</h2><p>Cancelled scheduler work, cost overages, and active failure-class alerts.</p></div>{_badge(str(telemetry["failures"]["count"]), "bad" if telemetry["failures"]["count"] else "good")}</div>
    <div class="table-wrap mobile-hide"><table><thead><tr><th>Kind</th><th>Reference</th><th>Projects</th><th>Observed</th></tr></thead><tbody>{failure_rows}</tbody></table></div>
    <div class="mobile-records">{failure_cards}</div>
  </section>

  <section class="card" id="trends" style="margin-bottom:14px">
    <div class="section-head">
      <div><h2>History & Trends</h2><p>{history["point_count"]} hourly snapshot point(s). Project momentum is evidence-backed signals, not an opaque score.</p></div>
      {_badge(f'seq {history["sequence"]}',"neutral")}
    </div>
    <div class="table-wrap mobile-hide"><table>
      <thead><tr><th>Day</th><th class="num">Completed</th><th class="num">Cost USD</th><th class="num">Model calls</th><th class="num">Hunter candidates</th><th class="num">Actions</th><th class="num">Failures</th><th class="num">Verified outcomes</th></tr></thead>
      <tbody>{daily_rows}</tbody>
    </table></div>
    <div class="mobile-records">{daily_cards}</div>
    <div class="section-head" style="margin-top:16px"><div><h2>24h Project Momentum Signals</h2><p>{_e(history["momentum_definition"])}</p></div></div>
    <div class="table-wrap mobile-hide"><table>
      <thead><tr><th>Project</th><th class="num">Open work</th><th class="num">Completed Δ</th><th class="num">Actions Δ</th><th class="num">Verified Δ</th><th class="num">Cancelled Δ</th></tr></thead>
      <tbody>{momentum_rows}</tbody>
    </table></div>
    <div class="mobile-records">{momentum_cards}</div>
  </section>

  <section class="grid two">
    <div class="card" id="alerts">
      <div class="section-head"><div><h2>Attention Queue</h2><p>Derived from evidence plus {_e(sources["notifications"]["status"].lower())} notification state.</p></div>{source_badge("notifications")}</div>
      {alert_rows}
    </div>
    <div class="card">
      <div class="section-head"><div><h2>Operating Mode</h2><p>{_e(optimization["optimization_id"])} · {_e(source_detail("runtime"))}</p></div>{source_badge("runtime")}</div>
      <p>Continuous optimization is active. The former validation sprint is {_e(sprint["status"].lower())} and carries no active freeze or stop date.</p>
      <div class="callout"><strong>Next admissible action</strong><p>{_e(sprint["next_admissible_action"])}</p></div>
      <div class="spec-grid">
        <div class="spec-item"><span>Architecture freeze</span><strong>{_e("ACTIVE" if optimization["validation_architecture_freeze"] else "LIFTED")}</strong></div>
        <div class="spec-item"><span>Policy</span><code class="break-anywhere">{_e(sprint["architecture_change_policy"])}</code></div>
        <div class="spec-item"><span>Runtime</span><strong>{_e(optimization["project_runtimes_enabled"])} projects enabled</strong></div>
        <div class="spec-item"><span>Scheduler</span><strong>{_e(optimization["scheduler_max_new_per_cycle"])} new/cycle · {_e(optimization["scheduler_max_open_per_agent"])} open/agent</strong></div>
      </div>
    </div>
  </section>

  <section class="card" id="projects" style="margin-top:14px">
    <div class="section-head">
      <div><h2>Portfolio Grid</h2><p>Lifecycle, evidence health, uncertainty, and scheduler state · {_e(source_detail("scheduler"))}</p></div>
      <div>{source_badge("scheduler")} <input class="search" id="projectSearch" placeholder="Filter projects…" oninput="filterProjects(this.value)"></div>
    </div>
    <div class="table-wrap project-desktop"><table>
      <thead><tr><th>Project</th><th>Lifecycle</th><th>Evidence health</th><th>Current bottleneck</th><th class="num">Pending</th><th class="num">Blocked</th><th class="num">Uncertainties</th></tr></thead>
      <tbody id="projectRows">{''.join(project_rows)}</tbody>
    </table></div>
    <div id="projectCards" class="project-mobile">{''.join(project_cards)}</div>
  </section>

  <section class="grid two" style="margin-top:14px">
    <div class="card" id="agents">
      <div class="section-head"><div><h2>Agent Fleet</h2><p>Persistent roles and maximum authorized autonomy · {_e(source_detail("agents"))}</p></div>{source_badge("agents")}</div>
      <div class="table-wrap mobile-hide"><table>
        <thead><tr><th>Agent</th><th>Functional health</th><th class="num">Evidence age</th><th class="num">Open work</th><th>Last real activity</th><th>Source</th><th>Max autonomy</th><th class="num">Tier</th></tr></thead>
        <tbody>{agent_rows}</tbody>
      </table></div>
      <div class="mobile-records">{agent_cards}</div>
    </div>
    <div class="card">
      <div class="section-head"><div><h2>Commercial Validation</h2><p>Sanitized evidence counts only.</p></div>{_badge("NO PRIVATE PAYLOADS","neutral")}</div>
      <table>
        <tbody>
          <tr><td>FreightRecovery first-contact threads</td><td class="num">{commercial["freightrecovery_first_contact_threads_sent"]}</td></tr>
          <tr><td>Genuine human replies</td><td class="num">{commercial["freightrecovery_human_replies"]}</td></tr>
          <tr><td>Related auto replies</td><td class="num">{commercial["freightrecovery_related_auto_replies_observed"]}</td></tr>
          <tr><td>Live checkout sessions</td><td class="num">{commercial["freightrecovery_live_checkout_sessions"]}</td></tr>
          <tr><td>Live payment intents</td><td class="num">{commercial["freightrecovery_live_payment_intents"]}</td></tr>
        </tbody>
      </table>
      <p><strong>Outbound:</strong> {_e(commercial["outbound_state"])}</p>
    </div>
  </section>

  <section class="grid two" style="margin-top:14px">
    <div class="card" id="hunter">
      <div class="section-head"><div><h2>Hunter Intelligence Loop</h2><p>{_e(source_detail("hunter"))}</p></div>{source_badge("hunter")}</div>
      <div class="table-wrap mobile-hide"><table>
        <thead><tr><th>Strategy</th><th class="num">Cycles</th><th class="num">Queries</th><th class="num">Candidates</th><th class="num">Retained</th><th class="num">Verified value</th></tr></thead>
        <tbody>{strategy_rows}</tbody>
      </table></div>
      <div class="mobile-records">{strategy_cards}</div>
    </div>
    <div class="card" id="cost">
      <div class="section-head"><div><h2>Cost Governor</h2><p>{_e(cost["mode"])} · {_e(source_detail("cost"))}</p></div>{source_badge("cost")}</div>
      <table><tbody>
        <tr><td>Actual cost today</td><td class="num">USD {_e(round(telemetry["cost"]["actual_usage_today"]["cost_usd"],4))}</td></tr>
        <tr><td>Actual model calls today</td><td class="num">{telemetry["cost"]["actual_usage_today"]["model_calls"]}</td></tr>
        <tr><td>Actual API calls today</td><td class="num">{telemetry["cost"]["actual_usage_today"]["api_calls"]}</td></tr>
        <tr><td>Accounted runner minutes today</td><td class="num">{telemetry["cost"]["budget_accounted_usage_today"]["github_runner_minutes"]}</td></tr>
        <tr><td>Daily GitHub job starts</td><td class="num">{cost["portfolio_ceiling"]["github_job_starts"]}</td></tr>
        <tr><td>Daily runner minutes</td><td class="num">{cost["portfolio_ceiling"]["github_runner_minutes"]}</td></tr>
        <tr><td>Paid model calls</td><td class="num">{cost["portfolio_ceiling"]["model_calls"]}</td></tr>
        <tr><td>API calls</td><td class="num">{cost["portfolio_ceiling"]["api_calls"]}</td></tr>
        <tr><td>Active durable reservations</td><td class="num">{cost["reservation_count"]}</td></tr>
        <tr><td>Committed model/API spend</td><td class="num">${sentinel["budget"]["committed_usage"]["cost_usd"]:.4f}</td></tr>
        <tr><td>Fail-closed expired reservation spend</td><td class="num">${sentinel["budget"]["fail_closed_expired_usage"]["cost_usd"]:.4f}</td></tr>
        <tr><td>Effective budget-accounted spend</td><td class="num">${sentinel["budget"]["effective_budget_usage"]["cost_usd"]:.4f}</td></tr>
        <tr><td>Governed runner minutes committed</td><td class="num">{int(sentinel["github"]["governed_job_usage"]["committed_runner_minutes"])}</td></tr>
        <tr><td>Watchdog max control-plane minutes/day</td><td class="num">{_e(sentinel["github"]["watchdog_control_plane_overhead"]["nominal_max_runner_minutes_per_day"])}</td></tr>
      </tbody></table>
      <div class="section-head" style="margin-top:16px"><h2>Kill Switches</h2>{_badge(f'{system["engaged_kill_switch_count"]} engaged', "bad" if system["engaged_kill_switch_count"] else "good")}</div>
      <div class="switches">{kill_rows}</div>
      <div class="section-head" style="margin-top:16px"><h2>Enabled Model Routes</h2>{_badge(f'{model_router["enabled_non_tier0_route_count"]} non-Tier-0',"good")}</div>
      <ul>{''.join(f'<li><code>{_e(m["provider_id"])}::{_e(m["model_id"])}</code> — Tier {_e(m["tier"])}</li>' for m in model_router["enabled_non_tier0_routes"])}</ul>
      <div class="section-head" style="margin-top:16px"><h2>Provider Readiness</h2>{_badge(provider_readiness["status"],_status_tone(provider_readiness["status"]))}</div>
      <table><tbody>
        <tr><td>Provider/model</td><td class="num">{_e((provider_readiness.get("provider_id") or "—") + "::" + (provider_readiness.get("model_id") or "—"))}</td></tr>
        <tr><td>Latest governed analysis</td><td class="num">{_e(provider_readiness["source_analysis_status"])}</td></tr>
        <tr><td>Internal cost gate</td><td class="num">{_e(provider_readiness.get("cost_gate_status") or "not blocked")}</td></tr>
        <tr><td>Retryable</td><td class="num">{_e(provider_readiness["retryable"])}</td></tr>
      </tbody></table>
    </div>
  </section>

  <section class="card" id="hunter-proposals" style="margin-top:14px">
    <div class="section-head">
      <div>
        <h2>Hunter Proposal Inbox</h2>
        <p>{_e(source_detail("hunter_proposals"))} · exact-revision public candidates that passed the bounded proposal quality gate.</p>
      </div>
      {_badge(str(snapshot["hunter_proposals"]["proposal_count"]) + " proposal(s)", "good" if snapshot["hunter_proposals"]["proposal_count"] else "neutral")}
    </div>
    <div class="spec-grid" style="margin-bottom:18px">
      <div class="spec-item"><span>Inbox sequence</span><strong>{_e(snapshot["hunter_proposals"]["sequence"])}</strong></div>
      <div class="spec-item"><span>Awaiting scheduler</span><strong>{_e(snapshot["hunter_proposals"]["awaiting_scheduler_count"])}</strong></div>
      <div class="spec-item"><span>Queued / active review</span><strong>{_e(snapshot["hunter_proposals"]["queued_review_count"] + snapshot["hunter_proposals"]["active_review_count"])}</strong></div>
      <div class="spec-item"><span>Completed scheduler work</span><strong>{_e(snapshot["hunter_proposals"]["completed_review_count"])}</strong></div>
      <div class="spec-item"><span>Durable evidence reviewed</span><strong>{_e(snapshot["hunter_proposals"]["evidence_reviewed_count"])}</strong></div>
      <div class="spec-item"><span>Review state sequence</span><strong>{_e(snapshot["hunter_proposals"]["review_state_sequence"])}</strong></div>
    </div>
    <div class="table-wrap mobile-hide"><table>
      <thead><tr><th>Proposal</th><th>Repository @ revision</th><th class="num">Score</th><th>Rank</th><th>Review</th><th>Capability</th><th>License metadata</th><th>Rights</th></tr></thead>
      <tbody>{proposal_rows}</tbody>
    </table></div>
    <div class="mobile-records">{proposal_cards}</div>
    <p>Discovery never grants reuse rights. Scheduler review is OBSERVE-only and re-inspects the exact public revision before recording license metadata; implementation remains independently gated.</p>
  </section>

  <section class="card" id="model-value" style="margin-top:14px">
    <div class="section-head">
      <div>
        <h2>Verified Model Value</h2>
        <p>{_e(source_detail("model_feedback"))} · {_e(sentinel["model_efficiency"]["feedback_source"])}</p>
      </div>
      {_badge(str(sentinel["model_efficiency"]["verified_value_events"]) + " verified value event(s)", "good" if sentinel["model_efficiency"]["verified_value_events"] else "neutral")}
    </div>
    <div class="spec-grid" style="margin-bottom:18px">
      <div class="spec-item"><span>Feedback state sequence</span><strong>{_e(model_router["feedback_state"]["sequence"])}</strong></div>
      <div class="spec-item"><span>Verified model feedback</span><strong>{_e(model_router["feedback_state"]["verified_feedback_records"])}</strong></div>
      <div class="spec-item"><span>Unique value events</span><strong>{_e(model_router["feedback_state"]["verified_value_events"])}</strong></div>
      <div class="spec-item"><span>Task kinds with evidence</span><strong>{_e(model_router["feedback_state"]["task_kind_count"])}</strong></div>
    </div>
    <div class="table-wrap mobile-hide"><table>
      <thead><tr><th>Model</th><th class="num">Tier</th><th class="num">Calls today</th><th class="num">Spend today</th><th class="num">Verified feedback</th><th class="num">Value events</th><th class="num">Mean value</th><th class="num">Cost / verified</th><th>Evidence signal</th></tr></thead>
      <tbody>{model_value_rows}</tbody>
    </table></div>
    <div class="mobile-records">{model_value_cards}</div>
    <p>Value evidence is credited only from durable VERIFIED feedback. This panel does not convert model output into authority, reuse rights, capability verification, deployment permission, or customer-value claims.</p>
  </section>

  <section class="card" id="learning-integrity" style="margin-top:14px">
    <div class="section-head">
      <div>
        <h2>Verified Learning Integrity</h2>
        <p>{_e(source_detail("learning"))} · cross-checks Hunter, model feedback, and continuous learning.</p>
      </div>
      {_badge(learning_integrity["status"], _status_tone(learning_integrity["status"]))}
    </div>
    <div class="spec-grid" style="margin-bottom:18px">
      <div class="spec-item"><span>Verified value events</span><strong>{_e(learning_integrity["verified_value_event_count"])}</strong></div>
      <div class="spec-item"><span>Independent builder/verifier events</span><strong>{_e(learning_integrity["independently_verified_event_count"])}</strong></div>
      <div class="spec-item"><span>Reached continuous learning</span><strong>{_e(learning_integrity["continuous_learning_event_count"])}</strong></div>
      <div class="spec-item"><span>Hunter verified value credit</span><strong>{_e(learning_integrity["hunter_verified_value_outcomes"])}</strong></div>
      <div class="spec-item"><span>Learning observations</span><strong>{_e(learning_loop["observation_count"])}</strong></div>
      <div class="spec-item"><span>Learning state sequence</span><strong>{_e(learning_loop["state_sequence"])}</strong></div>
    </div>
    <div class="table-wrap mobile-hide"><table>
      <thead><tr><th>Integrity check</th><th>Status</th></tr></thead>
      <tbody>{''.join(f'<tr><td>{_e(key.replace("_"," ").title())}</td><td>{_badge("PASS" if value else "FAIL","good" if value else "bad")}</td></tr>' for key,value in learning_integrity["checks"].items())}</tbody>
    </table></div>
    <div class="mobile-records">
      {''.join(f'<article class="mobile-record"><div class="mobile-record-head"><div class="mobile-title"><strong>{_e(key.replace("_"," ").title())}</strong></div>{_badge("PASS" if value else "FAIL","good" if value else "bad")}</div></article>' for key,value in learning_integrity["checks"].items())}
    </div>
    <p>Green here means the same VERIFIED value evidence has reconciled across the durable model-feedback, Hunter-value, and continuous-learning layers. It does not mean policy is automatically promoted; policy effect remains {_e(learning_loop["policy_effect"])}.</p>
  </section>

  <section class="grid two" id="actions" style="margin-top:14px">
    <div class="card">
      <div class="section-head"><div><h2>Bounded Action Engine</h2><p>{_e(action_engine["mode"])}</p></div>{_badge(action_engine["authority_class"],"warn")}</div>
      <table><tbody>
        <tr><td>Gateway enabled</td><td class="num">{_e(action_engine["enabled"])}</td></tr>
        <tr><td>Allowed projects</td><td class="num">{len(action_engine["allowed_project_ids"])}</td></tr>
        <tr><td>Email max / UTC day</td><td class="num">{action_engine["customer_email_max_per_utc_day"]}</td></tr>
        <tr><td>Sanitized executions</td><td class="num">{action_engine["execution_count"]}</td></tr>
        <tr><td>Sent receipts</td><td class="num">{action_engine["sent_count"]}</td></tr>
        <tr><td>Today headroom</td><td class="num">{gateway_health["daily_headroom"]}</td></tr>
        <tr><td>Duplicate receipt issues</td><td class="num">{gateway_health["duplicate_receipt_count"]}</td></tr>
      </tbody></table>
      <p><strong>Execution provider:</strong> {_e(action_engine["execution_provider"])} via {_e(action_engine["gmail_account_ref"])}</p>
      <p><strong>Accounting:</strong> {_e(gateway_health["accounting_domain"])} · excluded from model/GitHub spend.</p>
      <p>This panel is observational. The command center cannot invoke the ACT gateway.</p>
    </div>
    <div class="card">
      <div class="section-head"><div><h2>Action Boundaries</h2><p>Explicitly prohibited action classes.</p></div>{_badge(f'{len(action_engine["prohibited_action_types"])} prohibited',"neutral")}</div>
      <ul>{''.join(f'<li>{_e(x)}</li>' for x in action_engine["prohibited_action_types"])}</ul>
    </div>
  </section>

  <section class="grid two" style="margin-top:14px">
    <div class="card" id="workflows">
      <div class="section-head"><div><h2>Autonomous Workflow Surface</h2><p>{system["workflow_count"]} checked-in workflows visible to the command center.</p></div></div>
      <ul>{workflow_rows}</ul>
    </div>
    <div class="card">
      <div class="section-head"><div><h2>Controls Retained</h2><p>Post-restriction optimization safety and evidence controls.</p></div></div>
      <ul>{''.join(f'<li>{_e(x)}</li>' for x in optimization["controls_retained"])}</ul>
    </div>
  </section>

  <section class="grid two" id="boundary" style="margin-top:14px">
    <div class="card"><div class="section-head"><h2>What this screen may do</h2>{_badge("OBSERVE","good")}</div><ul>{allowed}</ul></div>
    <div class="card"><div class="section-head"><h2>What this screen may not do</h2>{_badge("NO ACT","bad")}</div><ul>{blocked}</ul></div>
  </section>

  <div class="footer">
    Snapshot <code id="snapshotHash">{_e(snapshot["snapshot_hash"])}</code><br>
    Source executive dashboard <code>{_e(snapshot["source_dashboard_hash"])}</code>
  </div>
</main>
</div>
<script>
function filterProjects(q) {{
  q = (q || "").toLowerCase().trim();
  document.querySelectorAll("#projectRows tr, #projectCards .project-mobile-card").forEach(function(item) {{
    item.style.display = item.dataset.project.indexOf(q) >= 0 ? "" : "none";
  }});
}}
</script>
</body>
</html>
"""


def write_outputs(html_path: Path | None, json_path: Path | None) -> dict[str, Any]:
    snapshot = build_command_center_snapshot()
    if html_path is not None:
        html_path.parent.mkdir(parents=True, exist_ok=True)
        html_path.write_text(render_html(snapshot), encoding="utf-8")
    if json_path is not None:
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return snapshot


class CommandCenterHandler(BaseHTTPRequestHandler):
    def _send(self, body: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path in {"/", "/index.html"}:
            body = render_html(build_command_center_snapshot()).encode("utf-8")
            self._send(body, "text/html; charset=utf-8")
            return
        if self.path == "/snapshot.json":
            body = (json.dumps(build_command_center_snapshot(), indent=2, sort_keys=True) + "\n").encode("utf-8")
            self._send(body, "application/json; charset=utf-8")
            return
        if self.path == "/healthz":
            self._send(b'{"status":"ok","authority":"OBSERVE"}\n', "application/json; charset=utf-8")
            return
        self._send(b"not found\n", "text/plain; charset=utf-8", 404)

    def do_POST(self) -> None:  # noqa: N802
        self._send(b"read-only command center\n", "text/plain; charset=utf-8", 405)

    def log_message(self, fmt: str, *args: Any) -> None:
        return


def main() -> None:
    parser = argparse.ArgumentParser(description="Portfolio Brain read-only command center")
    parser.add_argument("--write-html", type=Path)
    parser.add_argument("--write-json", type=Path)
    parser.add_argument("--json", action="store_true", help="print snapshot JSON")
    parser.add_argument("--serve", action="store_true", help="serve a local read-only command center")
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    snapshot = write_outputs(args.write_html, args.write_json)
    if args.json:
        print(json.dumps(snapshot, indent=2, sort_keys=True))
    if args.serve:
        server = ThreadingHTTPServer((args.bind, args.port), CommandCenterHandler)
        print(f"Portfolio Brain Command Center: http://{args.bind}:{args.port}")
        print("Authority: OBSERVE | Mutations: NONE | Network calls from UI: NONE")
        server.serve_forever()
    if not args.serve and not args.json and args.write_html is None and args.write_json is None:
        print(render_html(snapshot))


if __name__ == "__main__":
    main()
