#!/usr/bin/env python3
"""Exact, evidence-bound quarantine for known durable-artifact fork incidents."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from runtime.artifact_restore import InvalidStateArtifact

ROOT = Path(__file__).resolve().parents[1]
QUARANTINE_PATH = ROOT / "runtime" / "ARTIFACT_QUARANTINE.json"


def load_quarantine(path: Path = QUARANTINE_PATH) -> dict[str, Any]:
    data = json.loads(path.read_text())
    if data.get("schema_version") != "1.0.0" or data.get("policy") != "EXACT_METADATA_QUARANTINE_ONLY":
        raise InvalidStateArtifact("artifact quarantine policy invalid")
    entries = data.get("artifacts")
    if not isinstance(entries, list):
        raise InvalidStateArtifact("artifact quarantine entries invalid")
    for entry in entries:
        for key in (
            "artifact_id", "artifact_name", "source_run_id", "source_head_sha",
            "superseded_by_artifact_id", "superseded_by_run_id",
        ):
            if key not in entry:
                raise InvalidStateArtifact("artifact quarantine entry incomplete")
        if type(entry["artifact_id"]) is not int or type(entry["superseded_by_artifact_id"]) is not int:
            raise InvalidStateArtifact("artifact quarantine id invalid")
        if type(entry["source_run_id"]) is not int or type(entry["superseded_by_run_id"]) is not int:
            raise InvalidStateArtifact("artifact quarantine run id invalid")
        if not isinstance(entry["artifact_name"], str) or not entry["artifact_name"]:
            raise InvalidStateArtifact("artifact quarantine name invalid")
        if not isinstance(entry["source_head_sha"], str) or len(entry["source_head_sha"]) != 40:
            raise InvalidStateArtifact("artifact quarantine head sha invalid")
    return data


def _verify(item: dict[str, Any], *, artifact_id: int, artifact_name: str, run_id: int, head_sha: str) -> None:
    workflow_run = item.get("workflow_run") or {}
    if (
        item.get("id") != artifact_id
        or item.get("name") != artifact_name
        or workflow_run.get("id") != run_id
        or workflow_run.get("head_sha") != head_sha
        or workflow_run.get("head_branch") != "main"
    ):
        raise InvalidStateArtifact("artifact quarantine metadata mismatch")


def apply_artifact_quarantine(
    data: dict[str, Any],
    *,
    expected_artifact_name: str,
    quarantine: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Remove only an exact known fork sibling when its exact superseder is also present.

    The generic highest-sequence conflict detector remains unchanged. A quarantined
    artifact is ignored only when both sides of the incident match immutable GitHub
    artifact/run metadata; otherwise restoration still fails closed.
    """
    quarantine = quarantine or load_quarantine()
    artifacts = list(data.get("artifacts", []))
    by_id = {item.get("id"): item for item in artifacts}

    remove_ids: set[int] = set()
    for entry in quarantine.get("artifacts", []):
        if entry.get("artifact_name") != expected_artifact_name:
            continue
        bad = by_id.get(entry["artifact_id"])
        if bad is None:
            continue
        good = by_id.get(entry["superseded_by_artifact_id"])
        if good is None:
            raise InvalidStateArtifact("quarantined artifact present without its verified superseder")

        _verify(
            bad,
            artifact_id=entry["artifact_id"],
            artifact_name=entry["artifact_name"],
            run_id=entry["source_run_id"],
            head_sha=entry["source_head_sha"],
        )
        _verify(
            good,
            artifact_id=entry["superseded_by_artifact_id"],
            artifact_name=entry["artifact_name"],
            run_id=entry["superseded_by_run_id"],
            head_sha=entry["source_head_sha"],
        )
        remove_ids.add(entry["artifact_id"])

    filtered = dict(data)
    filtered["artifacts"] = [item for item in artifacts if item.get("id") not in remove_ids]
    return filtered
