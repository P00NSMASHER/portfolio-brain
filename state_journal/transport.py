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
from urllib.parse import quote

from runtime.artifact_state import BudgetedHTTP
from state_journal.contracts import (MAX_BYTES, PRODUCERS, REPOSITORY, WORKFLOW_PRODUCERS,
                                    JournalError, canonical, require, strict_load)
from state_journal.events import upgrade_legacy_event_attempt, validate_event

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
    if "run_attempt" in event:
        require(event["run_attempt"] == attempt, "Event payload/provider attempt mismatch")
    elif attempt > 1:
        # Historical v1 emitters did not encode GitHub run_attempt in event_id.
        # Preserve the immutable archive/digest, but normalize the admitted
        # journal event so a legitimate rerun can follow attempt 1 instead of
        # colliding with it.
        event = upgrade_legacy_event_attempt(event, attempt)
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
        previous_created = None
        ordering_proven = True
        for page in range(1, max_pages + 1):
            response = self.get(f"/actions/artifacts?per_page=100&page={page}")
            rows = response.get("artifacts")
            require(isinstance(rows, list), "Artifact listing malformed")
            crossed_boundary = False
            for row in rows:
                artifact_id = row.get("id")
                require(type(artifact_id) is int and artifact_id > 0, "Artifact listing identity missing")
                created = row.get("created_at")
                require(isinstance(created, str), "Artifact created_at missing")
                at = datetime.fromisoformat(created.replace("Z", "+00:00"))
                require(at.tzinfo is not None, "Artifact created_at requires timezone")
                if previous_created is not None and at > previous_created:
                    ordering_proven = False
                previous_created = at
                if at < boundary:
                    crossed_boundary = True
                previous = result.get(artifact_id)
                if previous is not None:
                    require(previous == row, "Artifact metadata changed during bounded scan")
                else:
                    result[artifact_id] = row
            # Repository artifact history can be much larger than the journal
            # window. Stop once the fetched pagination has remained monotonic
            # newest-to-oldest and has crossed the explicit checkpoint boundary.
            # Any observed ordering reversal disables this optimization, so an
            # ambiguous listing still fails closed at max_pages.
            if len(rows) < 100 or (ordering_proven and crossed_boundary):
                selected = [
                    row for row in result.values()
                    if datetime.fromisoformat(row["created_at"].replace("Z", "+00:00")) >= boundary
                ]
                return sorted(selected, key=lambda row: (row["created_at"], row["id"]), reverse=True)
        raise JournalError("Artifact scan incomplete at page bound; checkpoint/archive required")

    def _workflow_runs_since(self, workflow_file: str, since: str, *, max_pages: int) -> list[dict]:
        require(re.fullmatch(r"[a-z0-9-]+\.yml", workflow_file) is not None, "Unsafe workflow file")
        boundary = datetime.fromisoformat(since.replace("Z", "+00:00"))
        require(boundary.tzinfo is not None, "Workflow boundary requires timezone")
        encoded = quote(f">={since}", safe="")
        result = {}
        for page in range(1, max_pages + 1):
            response = self.get(
                f"/actions/workflows/{workflow_file}/runs?branch=main&created={encoded}&per_page=100&page={page}"
            )
            rows = response.get("workflow_runs")
            require(isinstance(rows, list), "Workflow run listing malformed")
            for row in rows:
                run_id = row.get("id")
                require(type(run_id) is int and run_id > 0, "Workflow run identity missing")
                created = row.get("created_at")
                require(isinstance(created, str), "Workflow run created_at missing")
                at = datetime.fromisoformat(created.replace("Z", "+00:00"))
                require(at.tzinfo is not None, "Workflow run created_at requires timezone")
                if at < boundary:
                    continue
                previous = result.get(run_id)
                if previous is not None:
                    require(previous == row, "Workflow run metadata changed during bounded scan")
                else:
                    result[run_id] = row
            if len(rows) < 100:
                return sorted(
                    result.values(),
                    key=lambda row: (row["created_at"], row["id"]),
                    reverse=True,
                )
        raise JournalError("Workflow run scan incomplete at page bound; checkpoint/archive required")

    def _run_artifacts(self, run_id: int) -> list[dict]:
        require(type(run_id) is int and run_id > 0, "Invalid workflow run ID")
        response = self.get(f"/actions/runs/{run_id}/artifacts?per_page=100")
        rows = response.get("artifacts")
        require(isinstance(rows, list), "Run artifact listing malformed")
        total = response.get("total_count")
        require(type(total) is int and total == len(rows) and total <= 100,
                "Run artifact listing incomplete; per-run artifact bound exceeded")
        return rows

    def list_recent_journal_artifacts(
        self,
        since: str,
        *,
        max_pages: int = 20,
        explicit_run_ids: list[int] | tuple[int, ...] = (),
        covered_run_attempts: set[tuple[int, int]] | frozenset[tuple[int, int]] = frozenset(),
    ) -> list[dict]:
        """Discover reducer snapshots and enrolled producer events with bounded replay proof.

        Repository-wide artifact pagination is intentionally avoided. For each
        producer run in the replay window, a missing event artifact is acceptable
        only when that exact run/attempt is already covered by the validated
        durable checkpoint. Otherwise, if the producer's immutable-event upload
        step succeeded but the artifact is gone, recovery fails closed with
        MISSING_REPLAY instead of silently dropping an event.
        """
        boundary = datetime.fromisoformat(since.replace("Z", "+00:00"))
        require(boundary.tzinfo is not None, "Artifact boundary requires timezone")
        require(type(max_pages) is int and max_pages > 0, "Artifact page bound invalid")
        covered = set(covered_run_attempts)
        require(
            all(
                isinstance(item, tuple)
                and len(item) == 2
                and all(type(value) is int and value > 0 for value in item)
                for item in covered
            ),
            "Archived run/attempt coverage invalid",
        )
        result: dict[int, dict] = {}

        def retain(row: dict) -> None:
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

        def retain_run_events(run: dict) -> None:
            run_id = run.get("id")
            attempt = run.get("run_attempt")
            require(type(run_id) is int and run_id > 0, "Producer run identity missing")
            require(type(attempt) is int and attempt > 0, "Producer run attempt missing")
            rows = self._run_artifacts(run_id)
            events = [row for row in rows if row.get("name", "").startswith(EVENT_PREFIX)]
            for row in events:
                retain(row)
            if events or (run_id, attempt) in covered:
                return

            jobs = self.get(f"/actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100")
            job_rows = jobs.get("jobs")
            total = jobs.get("total_count")
            require(
                isinstance(job_rows, list)
                and type(total) is int
                and total == len(job_rows)
                and total <= 100,
                "Replay source job listing incomplete",
            )
            uploaded = [
                step
                for job in job_rows
                for step in job.get("steps", [])
                if step.get("name") == UPLOAD_STEP
                and step.get("status") == "completed"
                and step.get("conclusion") == "success"
            ]
            require(
                not uploaded,
                f"MISSING_REPLAY: run {run_id} attempt {attempt} published an immutable event "
                "but its artifact is unavailable",
            )

        reducer_runs = self._workflow_runs_since(
            "portfolio-state-reducer.yml", since, max_pages=max_pages
        )
        snapshot_runs: list[tuple[dict, dict]] = []
        for run in reducer_runs:
            if not (
                run.get("head_branch") == "main"
                and run.get("status") == "completed"
                and run.get("conclusion") == "success"
            ):
                continue
            snapshots = [
                row for row in self._run_artifacts(run["id"])
                if row.get("name") == SNAPSHOT_ARTIFACT and not row.get("expired")
            ]
            require(len(snapshots) <= 1, "Reducer published multiple canonical snapshots in one run")
            if snapshots:
                retain(snapshots[0])
                snapshot_runs.append((run, snapshots[0]))
                if len(snapshot_runs) == 2:
                    break

        event_since = since
        if len(snapshot_runs) == 2:
            # Scan from the predecessor reducer publication as an additional
            # overlap. The durable checkpoint also carries an explicit replay
            # overlap boundary, so queued/racing producers cannot disappear at
            # the rollover boundary.
            event_since = min(snapshot_runs[0][0]["created_at"], snapshot_runs[1][0]["created_at"])

        terminal = {"success", "failure", "cancelled", "timed_out"}
        for workflow in sorted(WORKFLOW_PRODUCERS):
            for run in self._workflow_runs_since(f"{workflow}.yml", event_since, max_pages=max_pages):
                if not (
                    run.get("head_branch") == "main"
                    and run.get("status") == "completed"
                    and run.get("conclusion") in terminal
                ):
                    continue
                retain_run_events(run)

        for run_id in explicit_run_ids:
            require(type(run_id) is int and run_id > 0, "Explicit recovery run ID invalid")
            run = self.get(f"/actions/runs/{run_id}")
            require(run.get("id") == run_id, "Explicit recovery run identity mismatch")
            require(run.get("head_branch") == "main", "Explicit recovery run is not on main")
            require(run.get("status") == "completed" and run.get("conclusion") in terminal,
                    "Explicit recovery run is not terminal")
            source_producer(run)
            retain_run_events(run)

        return sorted(
            result.values(),
            key=lambda row: (row["created_at"], row["id"]),
            reverse=True,
        )

    def event(self, meta: dict, upload_steps: dict) -> tuple[dict, dict]:
        match = re.fullmatch(r"portfolio-state-event-v2-([1-9][0-9]*)-([a-z0-9-]+)-([a-f0-9]{40})-([1-9][0-9]*)", meta.get("name", ""))
        require(match is not None, "Malformed event archive name")
        run_id, _, _, attempt = match.groups()
        run = self.get(f"/actions/runs/{run_id}/attempts/{attempt}")
        jobs = self.get(f"/actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100")
        raw = self.archive(meta["id"])
        return validate_provider_event(meta, run, jobs, raw, upload_steps)
