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
    require(set(snapshot["state_sources"]["sources"]) >= {"runtime","scheduler","hunter","cost","notifications","agents"}, "public live-state provenance incomplete")
    require(snapshot["data_boundary"] == "SANITIZED_CHECKED_IN_AND_DURABLE_ARTIFACT_STATE", "public data boundary widened")

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
