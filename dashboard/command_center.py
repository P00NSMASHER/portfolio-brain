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
        "agents":"agents/AGENT_STATE_SEED.json",
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
    agent_state = load_json("agents/AGENT_STATE_SEED.json")
    state_sources = load_state_sources()
    hunter_state = load_live_json("hunter_state.json","hunting/HUNTER_STATE_SEED.json")
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

    state_by_agent = {a["agent_id"]: a for a in agent_state["agents"]}
    agents = []
    for role in agent_registry["roles"]:
        state = state_by_agent.get(role["agent_id"], {})
        agents.append(
            {
                "agent_id": role["agent_id"],
                "name": role["display_name"],
                "role_key": role["role_key"],
                "status": state.get("status", role.get("status", "UNKNOWN")),
                "generation": state.get("generation"),
                "last_heartbeat_at": state.get("last_heartbeat_at"),
                "max_autonomy": role["max_autonomy"],
                "builder_eligible": role["builder_eligible"],
                "verifier_eligible": role["verifier_eligible"],
                "max_model_tier": role["max_model_tier"],
                "human_act_allowed": role["human_act_allowed"],
            }
        )

    workflows = sorted(p.name for p in (ROOT / ".github" / "workflows").glob("*.yml"))
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

    alerts = []
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
    if portfolio_ceiling["cost_usd"] > 0:
        alerts.append(
            {
                "severity": "INFO",
                "title": "Finite paid model/API budget is enabled",
                "detail": f'Portfolio ceiling is USD {portfolio_ceiling["cost_usd"]}/day with {portfolio_ceiling["model_calls"]} model calls and {len(enabled_model_routes)} enabled non-Tier-0 model routes.',
                "evidence_ref": "cost_governor/COST_GOVERNOR_POLICY.json",
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
        "command_center_id": "portfolio-brain-command-center-v3",
        "authority_class": "OBSERVE",
        "mutation_capability": "NONE",
        "network_capability": "NONE",
        "data_boundary": "SANITIZED_CHECKED_IN_AND_DURABLE_ARTIFACT_STATE",
        "source_dashboard_hash": executive["snapshot_hash"],
        "system": {
            "status": operating["status"],
            "operational_without_interactive_chatgpt": operating["operational_without_interactive_chatgpt"],
            "main_promotion_sha": operating["promoted_main_sha"],
            "hotfix_count": len(hotfixes),
            "verified_hotfix_count": verified_hotfixes,
            "project_count": executive["project_count"],
            "agent_count": len(agents),
            "active_agent_count": active_agents,
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
        "cost_governor": {
            "mode": cost_policy["mode"],
            "portfolio_ceiling": portfolio_ceiling,
            "reservation_count": len(cost_state["reservations"]),
            "recent_decision_count": len(cost_state["recent_decisions"]),
            "managed_workflow_names": cost_policy["managed_workflow_names"],
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
                    "agents/AGENT_STATE_SEED.json",
                    "hunting/HUNTER_STATE_SEED.json",
                    "cost_governor/COST_GOVERNOR_POLICY.json",
                    "cost_governor/COST_STATE_SEED.json",
                    "notifications/NOTIFICATION_POLICY.json",
                    "notifications/NOTIFICATION_STATE_SEED.json",
                    "operations/POST_RESTRICTION_OPTIMIZATION_STATUS.json",
                    "action_engine/ACTION_POLICY.json",
                    "action_engine/GMAIL_GATEWAY_LEDGER.json",
                    "model_router/PROVIDER_REGISTRY.json",
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
    if upper in {"OPERATIONAL", "ACTIVE", "VERIFIED_FIXED", "RUNNING", "LIVE"}:
        return "good"
    if upper in {"BLOCKED", "CRITICAL", "HIGH", "ENGAGED", "DISABLED"}:
        return "bad"
    if upper in {"EVIDENCE_GAPS", "MEDIUM", "ACTIVE_RESEARCH_ONLY", "IN_DEVELOPMENT", "STALE", "FALLBACK", "DEGRADED"}:
        return "warn"
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
    source_bundle = snapshot["state_sources"]
    sources = source_bundle["sources"]

    def source_badge(name: str) -> str:
        status = sources[name]["status"]
        return _badge(status, _status_tone(status))

    def source_detail(name: str) -> str:
        src = sources[name]
        created = src.get("artifact_created_at") or "seed/no artifact"
        run = src.get("source_run_id")
        run_text = "—" if run is None else str(run)
        age = src.get("age_minutes")
        age_text = "—" if age is None else f"{age} min"
        return f"artifact {created} · run {run_text} · age {age_text}"


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
    for p in snapshot["projects"]:
        bottleneck = (p["highest_value_uncertainty"] or {}).get("question") or "No ranked uncertainty"
        project_rows.append(
            f"""
            <tr data-project="{_e((p["project_id"] + " " + p["name"] + " " + p["project_type"]).lower())}">
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

    agent_rows = "".join(
        f"""
        <tr>
          <td><strong>{_e(a["name"])}</strong><span class="sub">{_e(a["agent_id"])}</span></td>
          <td>{_badge(a["status"], _status_tone(a["status"]))}</td>
          <td>{_badge(a["max_autonomy"], "neutral")}</td>
          <td>{_e("yes" if a["builder_eligible"] else "no")}</td>
          <td>{_e("yes" if a["verifier_eligible"] else "no")}</td>
          <td>{_e(a["max_model_tier"])}</td>
          <td>{_e(a["last_heartbeat_at"] or "seed / artifact-backed runtime")}</td>
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

    source_labels = {
        "runtime":"Runtime",
        "scheduler":"Scheduler",
        "hunter":"Hunter",
        "cost":"Cost Governor",
        "notifications":"Notifications",
        "agents":"Agent Fleet",
    }
    source_rows = "".join(
        f"""
        <tr>
          <td><strong>{_e(source_labels[name])}</strong><span class="sub">{_e(src.get("source_kind"))}</span></td>
          <td>{_badge(src["status"], _status_tone(src["status"]))}</td>
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

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Portfolio Brain Command Center</title>
<style>
:root {{
  color-scheme: dark;
  --bg:#071018;--panel:#0d1823;--panel2:#111f2c;--line:#203345;--text:#e8f0f7;
  --muted:#8da0b3;--cyan:#67e8f9;--green:#5ee6a8;--amber:#f7c76d;--red:#ff7f8f;
  --blue:#82aaff;--shadow:0 16px 42px rgba(0,0,0,.26);
}}
*{{box-sizing:border-box}}
body{{margin:0;background:radial-gradient(circle at 20% 0%,#10263a 0,#071018 36rem);font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:var(--text)}}
a{{color:inherit}} code{{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;color:#b8c8d8;font-size:.78rem}}
.shell{{display:grid;grid-template-columns:230px minmax(0,1fr);min-height:100vh}}
aside{{position:sticky;top:0;height:100vh;padding:24px 18px;border-right:1px solid var(--line);background:rgba(5,14,22,.9);backdrop-filter:blur(14px)}}
.brand{{display:flex;align-items:center;gap:10px;font-weight:800;letter-spacing:.04em}}
.logo{{width:34px;height:34px;border-radius:11px;background:linear-gradient(145deg,var(--cyan),var(--blue));box-shadow:0 0 26px rgba(103,232,249,.28)}}
.brand small{{display:block;color:var(--muted);font-weight:600;letter-spacing:0;margin-top:2px}}
nav{{display:grid;gap:6px;margin-top:30px}}
nav a{{text-decoration:none;color:var(--muted);padding:9px 10px;border-radius:9px;font-size:.9rem}}
nav a:hover{{color:var(--text);background:#102233}}
.readonly{{position:absolute;bottom:22px;left:18px;right:18px;border:1px solid #214358;background:#0b1c29;padding:12px;border-radius:12px;color:var(--muted);font-size:.78rem}}
.readonly strong{{display:block;color:var(--cyan);margin-bottom:4px}}
main{{padding:28px;max-width:1600px;width:100%;margin:0 auto}}
.topbar{{display:flex;justify-content:space-between;gap:20px;align-items:flex-start;margin-bottom:22px}}
h1{{font-size:1.8rem;margin:0 0 6px}} h2{{font-size:1rem;margin:0}} p{{color:var(--muted);margin:.35rem 0;line-height:1.5}}
.actions{{display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end}}
button{{border:1px solid var(--line);background:#0c1b28;color:var(--text);padding:9px 12px;border-radius:9px;cursor:pointer}}
button:hover{{border-color:#3e6680}}
.grid{{display:grid;gap:14px}} .kpis{{grid-template-columns:repeat(6,minmax(0,1fr));margin-bottom:14px}}
.card{{background:linear-gradient(180deg,rgba(17,31,44,.96),rgba(12,24,35,.96));border:1px solid var(--line);border-radius:15px;padding:16px;box-shadow:var(--shadow)}}
.kpi .label{{font-size:.76rem;text-transform:uppercase;letter-spacing:.08em;color:var(--muted)}} .kpi .value{{font-size:1.75rem;font-weight:800;margin-top:7px}} .kpi .hint{{font-size:.76rem;color:var(--muted);margin-top:5px}}
.two{{grid-template-columns:minmax(0,1.7fr) minmax(320px,.8fr)}} .three{{grid-template-columns:repeat(3,minmax(0,1fr))}}
.section-head{{display:flex;justify-content:space-between;gap:14px;align-items:center;margin-bottom:12px}}
.section-head p{{font-size:.8rem}}
.badge{{display:inline-flex;align-items:center;white-space:nowrap;border:1px solid #314557;border-radius:999px;padding:3px 8px;font-size:.7rem;font-weight:750;letter-spacing:.04em}}
.badge.good{{color:var(--green);border-color:#225944;background:#0d2b21}} .badge.warn{{color:var(--amber);border-color:#5a4927;background:#2a2110}} .badge.bad{{color:var(--red);border-color:#60303a;background:#2b141a}} .badge.neutral{{color:#aebed0;background:#121e29}}
table{{width:100%;border-collapse:collapse;font-size:.82rem}} th{{text-align:left;color:var(--muted);font-size:.7rem;text-transform:uppercase;letter-spacing:.07em;padding:9px 8px;border-bottom:1px solid var(--line)}} td{{padding:10px 8px;border-bottom:1px solid rgba(32,51,69,.65);vertical-align:top}} tr:last-child td{{border-bottom:0}} .sub{{display:block;color:var(--muted);font-size:.72rem;margin-top:3px}} .num{{text-align:right;font-variant-numeric:tabular-nums}} .wrap{{max-width:460px;line-height:1.35}}
.search{{width:260px;max-width:100%;background:#091620;border:1px solid var(--line);color:var(--text);padding:8px 10px;border-radius:9px}}
.alert-row{{display:grid;grid-template-columns:70px minmax(0,1fr) auto;gap:12px;align-items:start;padding:11px 0;border-bottom:1px solid var(--line)}} .alert-row:last-child{{border-bottom:0}} .alert-row span:not(.badge){{display:block;color:var(--muted);font-size:.8rem;margin-top:3px}}
.switches{{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:9px}} .switch-card{{border:1px solid var(--line);padding:11px;border-radius:11px;min-width:0}} .switch-card strong,.switch-card span{{display:block}} .switch-card span{{color:var(--muted);font-size:.72rem;margin:2px 0 6px}} .switch-dot{{width:9px;height:9px;border-radius:50%;float:right;margin-top:4px}} .switch-dot.on{{background:var(--green);box-shadow:0 0 14px rgba(94,230,168,.55)}} .switch-dot.off{{background:var(--red);box-shadow:0 0 14px rgba(255,127,143,.5)}}
.callout{{border:1px solid #2e5268;background:#0b202d;border-radius:12px;padding:14px}} .callout strong{{color:var(--cyan)}} ul{{margin:.6rem 0 0;padding-left:18px;color:var(--muted)}} li{{margin:.38rem 0;line-height:1.35}}
.progress{{height:8px;border-radius:999px;background:#08121b;overflow:hidden;border:1px solid #1f3445;margin:11px 0}} .progress span{{display:block;height:100%;background:linear-gradient(90deg,var(--cyan),var(--blue));width:0%}}
.mono{{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}} .footer{{color:var(--muted);font-size:.72rem;text-align:center;padding:28px 0 8px}}
.empty{{color:var(--muted);padding:12px 0}}
@media(max-width:1100px){{.kpis{{grid-template-columns:repeat(3,1fr)}}.two,.three{{grid-template-columns:1fr}}.switches{{grid-template-columns:repeat(2,1fr)}}}}
@media(max-width:760px){{.shell{{display:block}}aside{{position:relative;height:auto;border-right:0;border-bottom:1px solid var(--line)}}nav,.readonly{{display:none}}main{{padding:18px}}.topbar{{display:block}}.actions{{justify-content:flex-start;margin-top:12px}}.kpis{{grid-template-columns:repeat(2,1fr)}}.switches{{grid-template-columns:1fr}}.table-wrap{{overflow:auto}}.alert-row{{grid-template-columns:1fr}}}}
</style>
</head>
<body>
<div class="shell">
<aside>
  <div class="brand"><div class="logo"></div><div>PORTFOLIO BRAIN<small>Command Center v3</small></div></div>
  <nav>
    <a href="#overview">Overview</a><a href="#live-state">Live State</a><a href="#alerts">Attention</a><a href="#projects">Portfolio</a>
    <a href="#agents">Agent Fleet</a><a href="#actions">Action Engine</a><a href="#hunter">Hunter</a>
    <a href="#cost">Cost & Models</a><a href="#workflows">Workflows</a><a href="#boundary">Authority Boundary</a>
  </nav>
  <div class="readonly"><strong>OBSERVE ONLY</strong>No control on this screen can widen authority or mutate Portfolio Brain state.</div>
</aside>
<main>
  <header class="topbar" id="overview">
    <div>
      <h1>Portfolio Brain Command Center</h1>
      <p>Evidence-backed operational view of the autonomous portfolio control plane.</p>
      <div>{_badge(system["status"], _status_tone(system["status"]))} {_badge("READ ONLY", "neutral")} {_badge(snapshot["data_boundary"], "neutral")}</div>
    </div>
    <div class="actions">
      <button type="button" onclick="location.reload()">Refresh view</button>
      <button type="button" onclick="navigator.clipboard && navigator.clipboard.writeText(document.getElementById('snapshotHash').textContent)">Copy snapshot hash</button>
    </div>
  </header>

  <section class="grid kpis">
    <div class="card kpi"><div class="label">Projects</div><div class="value">{system["project_count"]}</div><div class="hint">{len([p for p in snapshot["projects"] if p["lifecycle_status"] == "ACTIVE"])} active</div></div>
    <div class="card kpi"><div class="label">Agents</div><div class="value">{system["active_agent_count"]}/{system["agent_count"]}</div><div class="hint">active registry roles</div></div>
    <div class="card kpi"><div class="label">Open work</div><div class="value">{portfolio["pending_autonomous_work_count"]}</div><div class="hint">{_e(sources["scheduler"]["status"].lower())} scheduler queue</div></div>
    <div class="card kpi"><div class="label">Blocked work</div><div class="value">{portfolio["blocked_action_count"]}</div><div class="hint">human/authority gated</div></div>
    <div class="card kpi"><div class="label">Verified outcomes</div><div class="value">{sprint["scorecard"]["verified_external_outcomes_since_start"]}</div><div class="hint">historical baseline</div></div>
    <div class="card kpi"><div class="label">Paid model budget</div><div class="value">USD {cost["portfolio_ceiling"]["cost_usd"]:.2f}</div><div class="hint">{cost["portfolio_ceiling"]["model_calls"]} model calls authorized</div></div>
  </section>

  <section class="card" id="live-state" style="margin-bottom:14px">
    <div class="section-head">
      <div><h2>Live State Bridge</h2><p>Newest validated durable state is restored before publication; seeds are explicit fallback only.</p></div>
      {_badge(source_bundle["bridge_status"], _status_tone(source_bundle["bridge_status"]))}
    </div>
    <p>Bridge generated: {_e(source_bundle.get("generated_at") or "local fallback mode")}</p>
    <div class="table-wrap"><table>
      <thead><tr><th>Subsystem</th><th>Status</th><th class="num">Seq</th><th>Artifact time</th><th>Source run</th><th class="num">Age min</th><th>Source</th></tr></thead>
      <tbody>{source_rows}</tbody>
    </table></div>
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
      <p><strong>Architecture freeze:</strong> {_e("ACTIVE" if optimization["validation_architecture_freeze"] else "LIFTED")} &nbsp; <strong>Policy:</strong> {_e(sprint["architecture_change_policy"])}</p>
      <p><strong>Runtime:</strong> {_e(optimization["project_runtimes_enabled"])} projects enabled &nbsp; <strong>Scheduler:</strong> {_e(optimization["scheduler_max_new_per_cycle"])} new/cycle, {_e(optimization["scheduler_max_open_per_agent"])} open/agent</p>
    </div>
  </section>

  <section class="card" id="projects" style="margin-top:14px">
    <div class="section-head">
      <div><h2>Portfolio Grid</h2><p>Lifecycle, evidence health, uncertainty, and scheduler state · {_e(source_detail("scheduler"))}</p></div>
      <div>{source_badge("scheduler")} <input class="search" id="projectSearch" placeholder="Filter projects…" oninput="filterProjects(this.value)"></div>
    </div>
    <div class="table-wrap"><table>
      <thead><tr><th>Project</th><th>Lifecycle</th><th>Evidence health</th><th>Current bottleneck</th><th class="num">Pending</th><th class="num">Blocked</th><th class="num">Uncertainties</th></tr></thead>
      <tbody id="projectRows">{''.join(project_rows)}</tbody>
    </table></div>
  </section>

  <section class="grid two" style="margin-top:14px">
    <div class="card" id="agents">
      <div class="section-head"><div><h2>Agent Fleet</h2><p>Persistent roles and maximum authorized autonomy · {_e(source_detail("agents"))}</p></div>{source_badge("agents")}</div>
      <div class="table-wrap"><table>
        <thead><tr><th>Agent</th><th>Status</th><th>Max autonomy</th><th>Builder</th><th>Verifier</th><th>Tier</th><th>Heartbeat basis</th></tr></thead>
        <tbody>{agent_rows}</tbody>
      </table></div>
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
      <div class="table-wrap"><table>
        <thead><tr><th>Strategy</th><th class="num">Cycles</th><th class="num">Queries</th><th class="num">Candidates</th><th class="num">Retained</th><th class="num">Verified value</th></tr></thead>
        <tbody>{strategy_rows}</tbody>
      </table></div>
    </div>
    <div class="card" id="cost">
      <div class="section-head"><div><h2>Cost Governor</h2><p>{_e(cost["mode"])} · {_e(source_detail("cost"))}</p></div>{source_badge("cost")}</div>
      <table><tbody>
        <tr><td>Daily GitHub job starts</td><td class="num">{cost["portfolio_ceiling"]["github_job_starts"]}</td></tr>
        <tr><td>Daily runner minutes</td><td class="num">{cost["portfolio_ceiling"]["github_runner_minutes"]}</td></tr>
        <tr><td>Paid model calls</td><td class="num">{cost["portfolio_ceiling"]["model_calls"]}</td></tr>
        <tr><td>API calls</td><td class="num">{cost["portfolio_ceiling"]["api_calls"]}</td></tr>
        <tr><td>Active durable reservations</td><td class="num">{cost["reservation_count"]}</td></tr>
      </tbody></table>
      <div class="section-head" style="margin-top:16px"><h2>Kill Switches</h2>{_badge(f'{system["engaged_kill_switch_count"]} engaged', "bad" if system["engaged_kill_switch_count"] else "good")}</div>
      <div class="switches">{kill_rows}</div>
      <div class="section-head" style="margin-top:16px"><h2>Enabled Model Routes</h2>{_badge(f'{model_router["enabled_non_tier0_route_count"]} non-Tier-0',"good")}</div>
      <ul>{''.join(f'<li><code>{_e(m["provider_id"])}::{_e(m["model_id"])}</code> — Tier {_e(m["tier"])}</li>' for m in model_router["enabled_non_tier0_routes"])}</ul>
    </div>
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
      </tbody></table>
      <p><strong>Execution provider:</strong> {_e(action_engine["execution_provider"])} via {_e(action_engine["gmail_account_ref"])}</p>
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
  document.querySelectorAll("#projectRows tr").forEach(function(row) {{
    row.style.display = row.dataset.project.indexOf(q) >= 0 ? "" : "none";
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
