"""Read-only GitHub ingestion with exact artifact/run/job/attempt provenance.

Never trusts PASS strings or names alone. Only a same-repository main-branch
producer whose actual event publication steps succeeded may supply an event.
Artifacts from pull requests and unregistered callers cannot enter the journal.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from datetime import datetime
from pathlib import Path

from runtime.artifact_state import BudgetedHTTP
from state_journal.contracts import (MAX_BYTES, PRODUCERS, REPOSITORY, WORKFLOW_PRODUCERS,
                                    JournalError, canonical, require, strict_load)
from state_journal.events import validate_event

REPO_ID = 1387747549
EVENT_PREFIX = "portfolio-state-event-v2-"
SNAPSHOT_ARTIFACT = "portfolio-canonical-shadow-state"
EMIT_STEP = "Capture immutable state transition event"
UPLOAD_STEP = "Upload immutable state transition event"


def extract_json(raw: bytes, member: str) -> dict:
    require(len(raw) <= MAX_BYTES, "Archive exceeds byte limit")
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            infos = archive.infolist()
            require(len(infos) <= 5, "Unexpected archive members")
            require(all(not i.is_dir() and i.filename in {member, "delivery.json"} for i in infos), "Unexpected archive member/path")
            matches = [i for i in infos if i.filename == member]
            require(len(matches) == 1, "Missing or duplicate archive JSON member")
            require(matches[0].file_size <= MAX_BYTES, "Expanded member exceeds byte limit")
            return strict_load(archive.read(matches[0]))
    except (zipfile.BadZipFile, RuntimeError, OSError) as exc:
        raise JournalError("Unreadable immutable archive") from exc


def artifact_digest(meta: dict, raw: bytes) -> None:
    actual = "sha256:" + hashlib.sha256(raw).hexdigest()
    require(meta.get("digest") == actual, "GitHub artifact digest mismatch or missing")


def source_producer(run: dict) -> str:
    path = run.get("path", "")
    require(isinstance(path, str) and re.fullmatch(r"\.github/workflows/[a-z0-9-]+\.yml", path) is not None,
            "Unrecognized source workflow path")
    stem = Path(path).stem
    require(stem in WORKFLOW_PRODUCERS, "Source workflow caller is not enrolled")
    return WORKFLOW_PRODUCERS[stem]


def validate_provider_event(meta: dict, run: dict, jobs: dict, raw: bytes, upload_steps: dict) -> tuple[dict, dict]:
    artifact_digest(meta, raw)
    event = extract_json(raw, "event.json")
    validate_event(event)
    require(meta.get("expired") is False, "Source artifact expired")
    require(type(meta.get("id")) is int and meta["id"] > 0, "Artifact identity missing")
    attempt = run.get("run_attempt")
    require(type(attempt) is int and attempt > 0, "Source attempt missing")
    expected_name = f"{EVENT_PREFIX}{event['run_id']}-{event['producer']}-{event['source_sha']}-{attempt}"
    require(meta.get("name") == expected_name, "Artifact event identity or attempt mismatch")
    require(run.get("id") == int(event["run_id"]) and run.get("head_sha") == event["source_sha"], "Source run/SHA mismatch")
    require(run.get("head_branch") == "main" and run.get("event") in {"push", "schedule", "workflow_dispatch", "repository_dispatch", "workflow_run"},
            "PR or non-main source denied")
    for key in ("repository", "head_repository"):
        require(run.get(key, {}).get("full_name") == REPOSITORY and run[key].get("id") == REPO_ID, "Source repository/fork mismatch")
    require(run.get("status") == "completed" and run.get("conclusion") in {"success", "failure", "cancelled", "timed_out"},
            "Source run is not terminal")
    require(source_producer(run) == event["producer"], "Workflow is not authorized for event producer")
    source = meta.get("workflow_run", {})
    require(source.get("id") == run["id"] and source.get("head_sha") == event["source_sha"] and source.get("head_branch") == "main",
            "Artifact is not bound to the source run")
    require(source.get("repository_id") == REPO_ID and source.get("head_repository_id") == REPO_ID, "Artifact repository identity mismatch")
    require(type(run.get("workflow_id")) is int and run["workflow_id"] > 0, "Workflow identity absent")
    require(jobs.get("total_count") == len(jobs.get("jobs", [])), "Incomplete source job listing")
    candidates = []
    for job in jobs["jobs"]:
        steps = job.get("steps", [])
        if any(s.get("name") == EMIT_STEP for s in steps):
            candidates.append(job)
    require(len(candidates) == 1, "Source emitter job missing or ambiguous")
    job = candidates[0]
    require(job.get("run_id") == run["id"] and job.get("run_attempt") == attempt, "Emitter job belongs to another attempt")
    required = [EMIT_STEP, UPLOAD_STEP] + [upload_steps[event["producer"]][c["domain"]] for c in event["changes"]]
    for name in required:
        matches = [s for s in job.get("steps", []) if s.get("name") == name]
        require(len(matches) == 1 and matches[0].get("status") == "completed" and matches[0].get("conclusion") == "success",
                f"Actual state/event publication step did not succeed: {name}")
    # A failed overall run may have durably finalized cost or other state. That
    # transition is retained, but failure can NEVER be relabeled as useful work.
    evidence = {"kind": "GITHUB_ACTIONS", "repository": REPOSITORY, "artifact_id": meta["id"],
                "archive_digest": meta["digest"], "source_run_id": run["id"], "source_run_attempt": attempt,
                "source_sha": event["source_sha"], "workflow_id": run["workflow_id"], "workflow_path": run["path"],
                "source_conclusion": run["conclusion"], "event_hash": event["event_hash"], "job_id": job["id"]}
    return event, evidence


class GitHubReader:
    def __init__(self, token: str, *, max_requests: int = 100):
        self.http = BudgetedHTTP(token, max_requests=max_requests, retries=1, backoff=1)
        self.base = f"https://api.github.com/repos/{REPOSITORY}"

    def get(self, suffix: str) -> dict:
        require(suffix.startswith("/") and ".." not in suffix and "://" not in suffix, "Unsafe API suffix")
        return self.http.json(self.base + suffix)

    def archive(self, artifact_id: int) -> bytes:
        require(type(artifact_id) is int and artifact_id > 0, "Invalid artifact ID")
        # Existing transport strips authorization on cross-host artifact redirects.
        return self.http.bytes(f"{self.base}/actions/artifacts/{artifact_id}/zip")

    def list_recent_artifacts(self, since: str, *, max_pages: int = 20) -> list[dict]:
        boundary = datetime.fromisoformat(since.replace("Z", "+00:00"))
        require(boundary.tzinfo is not None, "Artifact boundary requires timezone")
        result = {}
        for page in range(1, max_pages + 1):
            response = self.get(f"/actions/artifacts?per_page=100&page={page}")
            rows = response.get("artifacts")
            require(isinstance(rows, list), "Artifact listing malformed")
            for row in rows:
                artifact_id = row.get("id")
                require(type(artifact_id) is int and artifact_id > 0, "Artifact listing identity missing")
                created = row.get("created_at")
                require(isinstance(created, str), "Artifact created_at missing")
                at = datetime.fromisoformat(created.replace("Z", "+00:00"))
                require(at.tzinfo is not None, "Artifact created_at requires timezone")
                previous = result.get(artifact_id)
                if previous is not None:
                    require(previous == row, "Artifact metadata changed during bounded scan")
                else:
                    result[artifact_id] = row
            if len(rows) < 100:
                selected = [
                    row for row in result.values()
                    if datetime.fromisoformat(row["created_at"].replace("Z", "+00:00")) >= boundary
                ]
                return sorted(selected, key=lambda row: (row["created_at"], row["id"]), reverse=True)
        raise JournalError("Artifact scan incomplete at page bound; checkpoint/archive required")

    def event(self, meta: dict, upload_steps: dict) -> tuple[dict, dict]:
        match = re.fullmatch(r"portfolio-state-event-v2-([1-9][0-9]*)-([a-z0-9-]+)-([a-f0-9]{40})-([1-9][0-9]*)", meta.get("name", ""))
        require(match is not None, "Malformed event archive name")
        run_id, _, _, attempt = match.groups()
        run = self.get(f"/actions/runs/{run_id}/attempts/{attempt}")
        jobs = self.get(f"/actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100")
        raw = self.archive(meta["id"])
        return validate_provider_event(meta, run, jobs, raw, upload_steps)
