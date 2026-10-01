#!/usr/bin/env python3
"""Collect and validate live Step 23 sustained-production-soak evidence from GitHub."""
from __future__ import annotations

import argparse
import io
import json
import os
import time
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from acceptance.final_acceptance import _load_policy
from acceptance.step23_finalize import build_receipt


class Step23CollectError(RuntimeError):
    pass


def req(ok: bool, message: str) -> None:
    if not ok:
        raise Step23CollectError(message)


def _ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class GH:
    def __init__(self, repo: str, token: str):
        self.repo = repo
        self.base = "https://api.github.com/repos/" + repo
        self.token = token

    def get(self, path: str) -> Any:
        url = path if path.startswith("https://") else self.base + path
        request = urllib.request.Request(
            url,
            headers={
                "Authorization": "Bearer " + self.token,
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "portfolio-step23-live-collector/1.0",
            },
            method="GET",
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
        return {} if not raw else json.loads(raw)

    def bytes(self, url: str) -> bytes:
        request = urllib.request.Request(
            url,
            headers={
                "Authorization": "Bearer " + self.token,
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "portfolio-step23-live-collector/1.0",
            },
            method="GET",
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read()


def _artifact_rows(gh: GH, run_id: int) -> list[dict[str, Any]]:
    doc = gh.get(f"/actions/runs/{run_id}/artifacts?per_page=100")
    return [
        row for row in doc.get("artifacts", [])
        if row.get("expired") is False
        and isinstance(row.get("digest"), str)
        and row["digest"].startswith("sha256:")
    ]


def _artifact_by_name(rows: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    matches = [row for row in rows if row.get("name") == name]
    req(len(matches) <= 1, f"ambiguous artifact name: {name}")
    return matches[0] if matches else None


def _primary_digest(rows: list[dict[str, Any]], workflow: str) -> str:
    preferred = {
        "portfolio-state-reducer": "portfolio-canonical-shadow-state",
        "runtime-hourly-sync": "portfolio-runtime-state",
        "portfolio-autonomous-scheduler": "portfolio-scheduler-state",
        "hunter-autonomous-cycle": "portfolio-hunter-state",
        "agent-heartbeat-sweep": "portfolio-agent-heartbeat-state",
        "portfolio-notification-cycle": "portfolio-notification-state",
        "command-center-pages": "portfolio-command-center-history",
        "portfolio-cost-watchdog": "portfolio-workflow-liveness",
    }
    target = _artifact_by_name(rows, preferred.get(workflow, "")) if workflow in preferred else None
    if target is not None:
        return target["digest"]
    req(bool(rows), f"{workflow} successful run has no durable artifact digest")
    return sorted(row["digest"] for row in rows)[0]


def _zip_json(gh: GH, artifact: dict[str, Any], member_suffix: str) -> dict[str, Any]:
    url = artifact.get("archive_download_url")
    req(isinstance(url, str) and url, "artifact archive URL missing")
    raw = gh.bytes(url)
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            names = [name for name in archive.namelist() if name == member_suffix or name.endswith("/" + member_suffix)]
            req(len(names) == 1, f"artifact must contain exactly one {member_suffix}")
            payload = archive.read(names[0])
    except zipfile.BadZipFile as exc:
        raise Step23CollectError("artifact archive is not readable") from exc
    try:
        doc = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Step23CollectError(f"{member_suffix} is not valid UTF-8 JSON") from exc
    req(isinstance(doc, dict), f"{member_suffix} must contain a JSON object")
    return doc


def _scheduled_runs(gh: GH, exact_main_sha: str, workflows: list[str]) -> list[dict[str, Any]]:
    doc = gh.get("/actions/runs?event=schedule&branch=main&per_page=100")
    rows = [
        row for row in doc.get("workflow_runs", [])
        if row.get("head_sha") == exact_main_sha and row.get("name") in workflows
    ]
    rows.sort(key=lambda row: (_ts(row["created_at"]), int(row["id"])))
    return rows


def _claim_window(rows: list[dict[str, Any]], workflows: list[str], minimum: int) -> tuple[list[dict[str, Any]], datetime]:
    thirds: list[datetime] = []
    for workflow in workflows:
        successes = [
            row for row in rows
            if row["name"] == workflow
            and row.get("status") == "completed"
            and row.get("conclusion") == "success"
        ]
        req(len(successes) >= minimum, f"WAITING: {workflow} has only {len(successes)} successful scheduled cycles")
        successes.sort(key=lambda row: (_ts(row["created_at"]), int(row["id"])))
        thirds.append(_ts(successes[minimum - 1]["created_at"]))
    cutoff = max(thirds)
    claimed = [row for row in rows if _ts(row["created_at"]) <= cutoff]
    return claimed, cutoff


def _classify_runs(
    gh: GH,
    rows: list[dict[str, Any]],
    exact_main_sha: str,
) -> list[dict[str, Any]]:
    by_workflow: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_workflow.setdefault(row["name"], []).append(row)

    output: list[dict[str, Any]] = []
    artifacts_by_run: dict[int, list[dict[str, Any]]] = {}
    for workflow, workflow_rows in by_workflow.items():
        workflow_rows.sort(key=lambda row: (_ts(row["created_at"]), int(row["id"])))
        for index, row in enumerate(workflow_rows):
            req(row.get("event") == "schedule", f"{workflow} non-scheduled row entered soak")
            req(row.get("head_sha") == exact_main_sha, f"{workflow} row is not on exact soak main")
            req(row.get("status") == "completed", f"WAITING: {workflow} run {row['id']} is not complete")
            conclusion = row.get("conclusion")
            base = {
                "workflow": workflow,
                "event": "schedule",
                "conclusion": conclusion,
                "created_at": row["created_at"],
                "completed_at": row.get("updated_at") or row.get("run_started_at") or row["created_at"],
                "run_id": int(row["id"]),
                "head_sha": exact_main_sha,
            }
            if conclusion == "success":
                artifacts = _artifact_rows(gh, int(row["id"]))
                artifacts_by_run[int(row["id"])] = artifacts
                output.append(base | {
                    "classification": "SUCCESS",
                    "classification_reason": "COMPLETED_SUCCESSFULLY",
                    "superseding_run_id": None,
                    "artifact_hash": _primary_digest(artifacts, workflow),
                })
                continue
            if conclusion == "cancelled":
                successor = next(
                    (
                        later for later in workflow_rows[index + 1:]
                        if later.get("status") == "completed" and later.get("conclusion") == "success"
                    ),
                    None,
                )
                req(successor is not None, f"WAITING: cancelled {workflow} run {row['id']} has no later successful successor")
                output.append(base | {
                    "classification": "CANCELLED_COALESCED",
                    "classification_reason": "SUPERSEDED_BY_LATER_SUCCESSFUL_SCHEDULE",
                    "superseding_run_id": int(successor["id"]),
                })
                continue
            raise Step23CollectError(
                f"Step 23 soak contains failure: {workflow} run {row['id']} conclusion={conclusion}"
            )
    output.sort(key=lambda row: (_ts(row["created_at"]), row["run_id"]))
    return output


def _success_rows(receipt_runs: list[dict[str, Any]], workflow: str) -> list[dict[str, Any]]:
    return [
        row for row in receipt_runs
        if row["workflow"] == workflow and row["classification"] == "SUCCESS"
    ]


def _reducer_samples(gh: GH, runs: list[dict[str, Any]], minimum: int, exact_main_sha: str) -> list[dict[str, Any]]:
    samples = []
    for row in _success_rows(runs, "portfolio-state-reducer")[:minimum]:
        artifact = _artifact_by_name(_artifact_rows(gh, row["run_id"]), "portfolio-canonical-shadow-state")
        req(artifact is not None, f"reducer run {row['run_id']} missing canonical shadow artifact")
        snapshot = _zip_json(gh, artifact, "snapshot.json")
        req(type(snapshot.get("sequence")) is int and snapshot["sequence"] >= 0, "canonical snapshot sequence invalid")
        state_hash = snapshot.get("state_hash")
        req(isinstance(state_hash, str) and state_hash.startswith("sha256:"), "canonical snapshot state_hash invalid")
        samples.append({
            "run_id": row["run_id"],
            "observed_at": row["completed_at"],
            "sequence": snapshot["sequence"],
            "state_hash": state_hash,
            "source_sha": exact_main_sha,
        })
    return samples


def _scheduler_states(gh: GH, runs: list[dict[str, Any]]) -> list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]]:
    result = []
    for row in _success_rows(runs, "portfolio-autonomous-scheduler"):
        artifact = _artifact_by_name(_artifact_rows(gh, row["run_id"]), "portfolio-scheduler-state")
        req(artifact is not None, f"scheduler run {row['run_id']} missing scheduler-state artifact")
        state = _zip_json(gh, artifact, "scheduler_state.json")
        req(state.get("state_id") == "portfolio-scheduler-state", "scheduler state identity mismatch")
        result.append((row, artifact, state))
    return result


def _pending_count(state: dict[str, Any]) -> int:
    work_items = state.get("work_items")
    req(isinstance(work_items, list), "scheduler work_items missing")
    return sum(1 for row in work_items if row.get("state") in {"QUEUED", "ACTIVE"})


def _handler_evidence(gh: GH, runs: list[dict[str, Any]], exact_main_sha: str) -> list[dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for row in _success_rows(runs, "portfolio-autonomous-scheduler"):
        artifacts = _artifact_rows(gh, row["run_id"])
        artifact = _artifact_by_name(artifacts, "portfolio-step23-handler-acceptance")
        if artifact is None:
            continue
        doc = _zip_json(gh, artifact, "step23_handler_acceptance.json")
        req(doc.get("status") == "PASS", "Step 23 handler acceptance artifact is not PASS")
        req(doc.get("main_sha") == exact_main_sha, "Step 23 handler artifact main SHA mismatch")
        for execution in doc.get("handler_executions") or []:
            kind = execution.get("kind")
            if kind not in {"REPAIR", "TEST", "VERIFICATION"} or kind in found:
                continue
            req(execution.get("status") == "SUCCESS", f"Step 23 {kind} handler did not succeed")
            execution_id = execution.get("execution_id")
            req(isinstance(execution_id, str) and execution_id, f"Step 23 {kind} execution id missing")
            found[kind] = {
                "kind": kind,
                "status": "COMPLETED",
                "run_id": row["run_id"],
                "execution_id": execution_id,
                "head_sha": exact_main_sha,
                "artifact_hash": artifact["digest"],
            }
    req(set(found) == {"REPAIR", "TEST", "VERIFICATION"}, "WAITING: complete Step 23 handler evidence not available")
    return [found[kind] for kind in ("REPAIR", "TEST", "VERIFICATION")]


def _hunter_evidence(gh: GH, runs: list[dict[str, Any]], exact_main_sha: str) -> list[dict[str, Any]]:
    evidence = []
    for row in _success_rows(runs, "hunter-autonomous-cycle"):
        artifacts = _artifact_rows(gh, row["run_id"])
        artifact = _artifact_by_name(artifacts, "portfolio-hunter-state")
        if artifact is None:
            continue
        doc = _zip_json(gh, artifact, "hunt_cycle_receipt.json")
        req(doc.get("status") == "PASS", f"Hunter run {row['run_id']} cycle receipt is not PASS")
        substantive = (
            (type(doc.get("inspected_candidates")) is int and doc["inspected_candidates"] > 0)
            or bool(doc.get("findings"))
            or bool(doc.get("experiment_proposals"))
            or any(
                isinstance(q, dict) and str(q.get("status", "")).startswith("EXECUTED")
                for q in (doc.get("query_outcomes") or [])
            )
        )
        if not substantive:
            continue
        work_id = doc.get("cycle_id")
        req(isinstance(work_id, str) and work_id, "Hunter cycle_id missing")
        evidence.append({
            "run_id": row["run_id"],
            "work_id": work_id,
            "substantive": True,
            "heartbeat_only": False,
            "head_sha": exact_main_sha,
            "artifact_hash": artifact["digest"],
        })
        break
    req(bool(evidence), "WAITING: no substantive Hunter work on a successful scheduled cycle")
    return evidence


def _dashboard_evidence(gh: GH, runs: list[dict[str, Any]]) -> dict[str, Any]:
    pages = _success_rows(runs, "command-center-pages")
    req(bool(pages), "WAITING: no successful scheduled command-center cycle")
    latest = pages[-1]
    artifacts = _artifact_rows(gh, latest["run_id"])
    preview = next(
        (row for row in artifacts if str(row.get("name", "")).startswith("portfolio-command-center-preview-")),
        None,
    )
    artifact = preview or _artifact_by_name(artifacts, "portfolio-command-center-history")
    req(artifact is not None, "command-center run lacks hash-traceable artifact")
    completed = _ts(latest["completed_at"])
    age_seconds = (datetime.now(timezone.utc) - completed).total_seconds()
    req(age_seconds <= 3 * 3600, "Step 23 command center evidence is stale")
    return {
        "fresh": True,
        "hash": artifact["digest"],
        "run_id": latest["run_id"],
        "completed_at": latest["completed_at"],
        "artifact_name": artifact["name"],
    }


def collect(gh: GH, exact_main_sha: str) -> dict[str, Any]:
    policy = _load_policy()["step23"]
    workflows = list(policy["required_workflows"])
    minimum = policy["min_successful_scheduled_cycles_per_workflow"]

    current_main = gh.get("/branches/main")["commit"]["sha"]
    req(current_main == exact_main_sha, "protected main moved before Step 23 collection")

    observed = _scheduled_runs(gh, exact_main_sha, workflows)
    claimed, cutoff = _claim_window(observed, workflows, minimum)
    runs = _classify_runs(gh, claimed, exact_main_sha)

    samples = _reducer_samples(gh, runs, minimum, exact_main_sha)
    scheduler_states = _scheduler_states(gh, runs)
    req(len(scheduler_states) >= minimum, "WAITING: insufficient scheduler-state evidence")

    pending_start = _pending_count(scheduler_states[0][2])
    pending_final = _pending_count(scheduler_states[-1][2])
    req(pending_final == 0, f"WAITING: scheduler pending work remains: {pending_final}")

    handler_evidence = _handler_evidence(gh, runs, exact_main_sha)
    hunter_evidence = _hunter_evidence(gh, runs, exact_main_sha)
    dashboard = _dashboard_evidence(gh, runs)

    req(gh.get("/branches/main")["commit"]["sha"] == exact_main_sha,
        "protected main moved during Step 23 collection")

    return {
        "schema_version": "1.0.0",
        "exact_main_sha": exact_main_sha,
        "claim_cutoff": cutoff.isoformat().replace("+00:00", "Z"),
        "runs": runs,
        "canonical_samples": samples,
        "pending_events_start": pending_start,
        "pending_events_final": pending_final,
        "handler_execution_evidence": handler_evidence,
        "hunter_substantive_work_evidence": hunter_evidence,
        "dashboard": dashboard,
        "hash_traceability_pass": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exact-main-sha", required=True)
    parser.add_argument("--output-meta", type=Path, required=True)
    parser.add_argument("--output-receipt", type=Path, required=True)
    args = parser.parse_args()

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("PORTFOLIO_GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    req(bool(token), "GitHub token required")
    req(bool(repo), "GITHUB_REPOSITORY required")

    gh = GH(repo, token)
    meta = collect(gh, args.exact_main_sha)
    receipt = build_receipt(meta)

    args.output_meta.parent.mkdir(parents=True, exist_ok=True)
    args.output_meta.write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.output_receipt.parent.mkdir(parents=True, exist_ok=True)
    args.output_receipt.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(json.dumps({
        "status": receipt["status"],
        "exact_main_sha": receipt["exact_main_sha"],
        "receipt_hash": receipt["receipt_hash"],
        "claimed_runs": len(receipt["runs"]),
        "claim_cutoff": meta["claim_cutoff"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
