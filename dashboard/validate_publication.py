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
    require(publication["mode"] == "AUTO_ON_RELEVANT_MAIN_PUSH_PLUS_HOURLY_REFRESH", "public publication mode drifted")
    if publication["source_commit"] is not None:
        require(len(publication["source_commit"]) == 40, "public source commit is not a full SHA")
    require(snapshot["history"]["history_id"] == "portfolio-command-center-public-history-v1", "public history missing")

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
    require("Stamp publication provenance" in workflow, "Pages publication provenance stamp missing")
    require('if [[ "$GITHUB_EVENT_NAME" == "push" ]]' in workflow, "source-change publication override missing")
    require("Verify deployed source commit" in workflow and "source-commit.txt" in workflow, "end-to-end Pages deployment proof missing")
    require("Operational Telemetry" in html_text and "History & Trends" in html_text, "public telemetry/trends panels missing")
    require("Hunter Proposal Inbox" in html_text, "public Hunter proposal inbox panel missing")
    require(snapshot["hunter_proposals"]["authority_class"]=="OBSERVE","public Hunter proposal inbox widened authority")
    require(snapshot["hunter_proposals"]["rights_state"]=="NOT_GRANTED_BY_DISCOVERY","public Hunter proposal inbox granted reuse rights")
    require(snapshot["hunter_proposals"]["evidence_reviewed_count"]<=snapshot["hunter_proposals"]["proposal_count"],"public Hunter proposal review count invalid")
    require("Verified Model Value" in html_text, "public verified model value panel missing")
    require("project-mobile-card" in html_text and "project-desktop" in html_text, "public responsive portfolio view missing")
    require('data-design="apple-inspired-v4-1"' in html_text, "public v4.1 design marker missing")
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
