#!/usr/bin/env python3
"""Fail-closed checks for public Portfolio Brain command-center publication."""
from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path

from dashboard.command_center import build_command_center_snapshot, render_html, write_outputs

EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
SECRET_MARKERS = (
    "github_pat_",
    "ghp_",
    "gho_",
    "ghu_",
    "ghs_",
    "ghr_",
    "sk-proj-",
    "authorization: bearer",
    "portfolio_model_api_key=",
    "gmail_message_id",
    "gmail_thread_id",
)


ROOT = Path(__file__).resolve().parents[1]


class PublicationValidationError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise PublicationValidationError(message)


def validate_publication() -> dict[str, object]:
    snapshot = build_command_center_snapshot()
    page = render_html(snapshot)

    require(snapshot["authority_class"] == "OBSERVE", "public command center widened authority")
    require(snapshot["mutation_capability"] == "NONE", "public command center gained mutation capability")
    require(snapshot["network_capability"] == "NONE", "public command center gained browser network capability")
    require(set(snapshot["state_sources"]["sources"]) >= {"runtime","scheduler","hunter","cost","notifications","agents","provider","model_feedback","hunter_proposals","hunter_proposal_reviews"}, "public live-state provenance incomplete")
    require(snapshot["data_boundary"] == "SANITIZED_CHECKED_IN_AND_DURABLE_ARTIFACT_STATE", "public data boundary widened")
    require(snapshot["telemetry"]["authority_class"] == "OBSERVE", "public telemetry widened authority")
    require(snapshot["workload_control"]["mode"] == "GITHUB_NATIVE_WORKLOAD_CONTROL", "public workload controls missing")
    require(set(snapshot["execution_truth"]) == {"attempted","blocked","executed","verified","scope_note"}, "public execution truth missing")
    publication=snapshot["publication"]
    require(publication["mode"] == "AUTO_ON_RELEVANT_MAIN_PUSH_PLUS_DURABLE_STATE_EVENTS_AND_HOURLY_REFRESH", "public publication mode drifted")
    if publication["source_commit"] is not None:
        require(len(publication["source_commit"]) == 40, "public source commit is not a full SHA")
    upgrades=snapshot["recommended_upgrades"]
    require(isinstance(upgrades,list) and 1<=len(upgrades)<=5,"public recommended upgrades invalid")
    require(all(row.get("prompt") and row.get("evidence_ref") for row in upgrades),"public recommended upgrade prompt/evidence missing")
    require(snapshot["history"]["history_id"] == "portfolio-command-center-public-history-v1", "public history missing")
    revenue=snapshot["revenue_focus"]
    factory=snapshot["micro_product_factory"]
    require(revenue["objective_id"]=="OBJ-001","public revenue objective missing")
    require(revenue["strategy_name"]=="Roblox micro-product factory","public revenue strategy drifted")
    require(factory["authority_class"]=="PLAN_ONLY","public micro-product factory widened authority")
    require(factory["build_caps"]["max_hours_per_sku"]<=4,"public micro-product time cap widened")
    require(factory["build_caps"]["max_paid_ai_spend_usd_per_sku"]<=10,"public micro-product spend cap widened")

    commercial=snapshot["commercial_validation"]
    require(commercial["evidence_status"] in {"CURRENT_SCOPE_OBSERVED","STALE_OR_UNAVAILABLE"},"public commercial evidence status invalid")
    require(commercial["current_source_kind"]=="CHATGPT_GMAIL_CONNECTOR_SANITIZED_OBSERVATION","public current commercial source kind drifted")
    require(commercial["current_source_ref"]=="commercial_evidence/CURRENT_SANITIZED_OBSERVATION.json","public current commercial provenance missing")
    require(commercial["historical_source_ref"]=="operations/VALIDATION_SPRINT_STATE.json","public historical commercial provenance missing")
    require(commercial["live_external_evidence_feed"] is False,"public snapshot invented autonomous live commercial evidence feed")
    require(commercial["current_external_payment_state"]=="UNKNOWN","public Gmail-only evidence invented payment state")
    require(commercial["definitive_outcome_recorded"] is False,"public OBSERVED evidence invented definitive outcome")
    require(commercial["threads_truncated"]==0,"public commercial observation is truncated")
    if commercial["evidence_status"]=="CURRENT_SCOPE_OBSERVED":
        require(commercial["fresh"] is True,"public current commercial observation is stale")
        require(commercial["current_evidence_state"]=="OBSERVED","public commercial evidence state widened")
        require(commercial["current_external_reply_state"] in {"OBSERVED_NO_HUMAN_REPLY_IN_SCOPE","OBSERVED_HUMAN_REPLY_IN_SCOPE"},"public scoped reply state invalid")
    else:
        require(commercial["fresh"] is False,"public stale commercial observation marked fresh")
        require(commercial["current_external_reply_state"]=="UNKNOWN","public stale commercial reply state did not fail closed")

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        html_path = root / "index.html"
        json_path = root / "snapshot.json"
        written = write_outputs(html_path, json_path)
        require(written["snapshot_hash"] == snapshot["snapshot_hash"], "publication snapshot changed during render")
        html_text = html_path.read_text(encoding="utf-8")
        json_text = json_path.read_text(encoding="utf-8")

    combined = html_text + "\n" + json_text
    lower = combined.lower()

    require(EMAIL.search(combined) is None, "raw email address detected in public artifact")
    for marker in SECRET_MARKERS:
        require(marker not in lower, f"sensitive marker detected in public artifact: {marker}")

    require("<form" not in lower, "public command center introduced form submission")
    require("fetch(" not in lower, "public command center introduced browser fetch")
    require("xmlhttprequest" not in lower, "public command center introduced XHR")
    require("websocket(" not in lower, "public command center introduced websocket")
    require('method="post"' not in lower, "public command center introduced POST form")
    require("Portfolio Brain Command Center" in html_text, "public page title missing")
    require("OBSERVE ONLY" in html_text, "public read-only boundary missing")
    require("Paid Cost Governor" in html_text and "GitHub Workload Controls" in html_text, "public paid/workload separation missing")
    workflow=(ROOT/".github/workflows/command-center-pages.yml").read_text(encoding="utf-8")
    require("\n  push:\n" in workflow and "      - main" in workflow, "Pages is not auto-triggered by relevant main pushes")
    require("\n  workflow_run:\n" in workflow, "Pages durable-state event trigger missing")
    for producer in ("portfolio-autonomous-scheduler","runtime-hourly-sync","agent-heartbeat-sweep","hunter-autonomous-cycle","portfolio-notification-cycle","portfolio-cost-watchdog"):
        require(f'      - "{producer}"' in workflow, f"Pages is not coupled to durable producer {producer}")
    require("Stamp publication provenance" in workflow, "Pages publication provenance stamp missing")
    require('if [[ "$GITHUB_EVENT_NAME" == "push" ]]' in workflow, "source-change publication override missing")
    require("Verify deployed source commit" in workflow and "source-commit.txt" in workflow, "end-to-end Pages deployment proof missing")
    require("Brain improvements worth considering" in html_text and "IMPROVE NEXT · EVIDENCE BACKED" in html_text, "public recommended upgrades board missing")
    require("Run upgrade" in html_text and "Build SKU-001" in html_text and "https://chatgpt.com/?prompt=" in html_text, "public action-button UX missing")
    require("Refresh Brain" in html_text, "public refresh workflow link missing")
    require("Show operations & diagnostics" in html_text and 'id="advanced-content"' in html_text, "public simple-mode disclosure missing")
    require('class="mobile-dock"' in html_text, "public mobile quick-action dock missing")
    require("Verified cash, not activity." in html_text, "public revenue-first operator focus missing")
    require(
        "MICRO-PRODUCT FACTORY · BOUNDED BETS" in html_text
        and "Quiz &amp; Reward Engine" in html_text
        and "House Controls Pack" in html_text
        and "Redeem Code System" in html_text,
        "public current first-launch-batch micro-product factory missing",
    )
    require(html_text.index("Verified cash, not activity.") < html_text.index("FIX FIRST · SYSTEM DIAGNOSTICS") < html_text.index("MICRO-PRODUCT FACTORY · BOUNDED BETS") < html_text.index("IMPROVE NEXT · EVIDENCE BACKED") < html_text.index('class="grid kpis"'), "public revenue-first hierarchy drifted")
    require("Operational Telemetry" in html_text and "History & Trends" in html_text, "public telemetry/trends panels missing")
    require("Commercial Evidence" in html_text and "Retired FreightRecovery Baseline" in html_text, "public commercial provenance UI missing")
    require("Observed gateway threads" in html_text and "Human-reply threads in scope" in html_text, "public scoped commercial evidence UI missing")
    require("GMAIL_SENT_18_FREIGHTRECOVERY_CAMPAIGN_THREADS_THREE_EXACT_SUBJECT_FAMILIES" in html_text, "public commercial coverage scope missing")
    require("Live checkout sessions</td>" not in html_text and "Live payment intents</td>" not in html_text, "retired commercial baseline labeled live")
    require("Hunter Proposal Inbox" in html_text, "public Hunter proposal inbox panel missing")
    require(snapshot["hunter_proposals"]["authority_class"]=="OBSERVE","public Hunter proposal inbox widened authority")
    require(snapshot["hunter_proposals"]["rights_state"]=="OPERATOR_ASSUMED","public Hunter proposal inbox granted reuse rights")
    require(snapshot["hunter_proposals"]["evidence_reviewed_count"]<=snapshot["hunter_proposals"]["proposal_count"],"public Hunter proposal review count invalid")
    require("Verified Model Value" in html_text, "public verified model value panel missing")
    require("project-mobile-card" in html_text and "project-desktop" in html_text, "public responsive portfolio view missing")
    require('data-design="revenue-first-v5"' in html_text, "public v5 design marker missing")
    require("fonts.googleapis.com" not in lower and "<script src=" not in lower, "public redesign introduced external presentation dependency")
    require("operator-console" not in lower and "operator console" not in lower, "private operator console leaked into public command center")

    return {
        "publishable": True,
        "authority": snapshot["authority_class"],
        "projects": snapshot["system"]["project_count"],
        "agents": snapshot["system"]["agent_count"],
        "action_receipts": snapshot["action_engine"]["execution_count"],
        "snapshot_hash": snapshot["snapshot_hash"],
    }


if __name__ == "__main__":
    print("portfolio-brain public command center: PASS", json.dumps(validate_publication(), sort_keys=True))
