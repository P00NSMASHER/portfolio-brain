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
from state_journal.contracts import (DOMAINS, MAX_BYTES, PRODUCERS, REPOSITORY, WORKFLOW_PRODUCERS,
                                    JournalError, canonical, digest, require, strict_load, validate_domain)
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


def extract_domain_state(raw: bytes, domain: str) -> dict:
    """Extract one validated domain state from a same-run durable artifact bundle."""
    require(domain in DOMAINS, "Unknown state-artifact domain")
    require(len(raw) <= MAX_BYTES, "State artifact exceeds byte limit")
    member = Path(DOMAINS[domain][2]).name
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            infos = archive.infolist()
            require(0 < len(infos) <= 100, "State artifact member count invalid")
            for info in infos:
                require(not info.is_dir(), "State artifact contains directory member")
                path = Path(info.filename)
                require(
                    not path.is_absolute() and ".." not in path.parts,
                    "State artifact member path unsafe",
                )
            matches = [info for info in infos if Path(info.filename).name == member]
            require(len(matches) == 1, "State artifact missing or duplicates domain state")
            require(matches[0].file_size <= MAX_BYTES, "Expanded state member exceeds byte limit")
            state = strict_load(archive.read(matches[0]))
    except (zipfile.BadZipFile, RuntimeError, OSError) as exc:
        raise JournalError("Unreadable durable state artifact") from exc
    validate_domain(domain, state)
    return state


def _artifact_time(value: object) -> datetime:
    require(isinstance(value, str), "Artifact created_at missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise JournalError("Artifact created_at invalid") from exc
    require(parsed.tzinfo is not None, "Artifact created_at requires timezone")
    return parsed


def validate_artifact_publication_fallback(
    event: dict,
    event_meta: dict,
    run: dict,
    jobs: dict,
    run_artifacts: list[dict],
    artifact_bytes: dict[int, bytes],
    artifact_names: dict[str, dict[str, str]],
    required_steps: list[str] | tuple[str, ...] = (),
) -> int:
    """Prove publication from exact artifacts when GitHub step metadata is absent or stale.

    This fallback never admits failed/cancelled runs or an explicit non-success
    publication step. It is only a provider-metadata recovery path: every
    changed domain must have exactly one exact-run durable state artifact whose
    validated bytes equal the immutable event after-state.
    """
    require(run.get("conclusion") == "success",
            "Step-metadata fallback requires successful source run")
    job_rows = jobs.get("jobs", [])
    require(isinstance(job_rows, list) and jobs.get("total_count") == len(job_rows),
            "Incomplete source job listing")
    require(len(job_rows) == 1, "Step-metadata fallback requires exactly one source job")
    job = job_rows[0]
    require(job.get("run_id") == run["id"] and job.get("run_attempt") == run["run_attempt"],
            "Fallback job belongs to another run attempt")
    require(job.get("status") == "completed" and job.get("conclusion") == "success",
            "Fallback source job did not succeed")
    steps = job.get("steps", [])
    require(isinstance(steps, list), "Fallback source job steps malformed")
    for name in required_steps:
        matches = [step for step in steps if step.get("name") == name]
        require(len(matches) <= 1, f"Ambiguous publication step metadata: {name}")
        if not matches:
            continue
        step = matches[0]
        status = step.get("status")
        conclusion = step.get("conclusion")
        if conclusion is not None:
            require(conclusion == "success", f"Explicit publication step failed: {name}")
        if status == "completed":
            require(conclusion == "success", f"Explicit publication step failed: {name}")
        else:
            require(status in {"in_progress", "pending", "queued"},
                    f"Publication step metadata is not a recognized stale state: {name}")
    producer_artifacts = artifact_names.get(event["producer"])
    require(isinstance(producer_artifacts, dict), "Producer artifact map missing")

    event_created = _artifact_time(event_meta.get("created_at"))
    for change in event["changes"]:
        domain = change["domain"]
        expected_name = producer_artifacts.get(domain)
        require(isinstance(expected_name, str) and expected_name,
                f"Durable artifact mapping missing for {event['producer']}:{domain}")
        matches = [row for row in run_artifacts if row.get("name") == expected_name]
        require(len(matches) == 1,
                f"Durable state artifact missing or ambiguous for {domain}")
        meta = matches[0]
        require(meta.get("expired") is False, f"Durable state artifact expired for {domain}")
        source = meta.get("workflow_run", {})
        require(
            source.get("id") == run["id"]
            and source.get("head_sha") == event["source_sha"]
            and source.get("head_branch") == "main",
            f"Durable state artifact source mismatch for {domain}",
        )
        require(
            source.get("repository_id") == REPO_ID
            and source.get("head_repository_id") == REPO_ID,
            f"Durable state artifact repository mismatch for {domain}",
        )
        require(_artifact_time(meta.get("created_at")) <= event_created,
                f"Durable state artifact was published after event for {domain}")
        artifact_id = meta.get("id")
        require(type(artifact_id) is int and artifact_id > 0,
                f"Durable state artifact identity missing for {domain}")
        raw = artifact_bytes.get(artifact_id)
        require(isinstance(raw, bytes), f"Durable state artifact bytes missing for {domain}")
        artifact_digest(meta, raw)
        state = extract_domain_state(raw, domain)
        require(digest(state) == change["after_hash"],
                f"Durable state artifact hash does not match event for {domain}")
        require(canonical(state) == canonical(change["after"]),
                f"Durable state artifact payload does not match event for {domain}")
    return job["id"]


def source_producer(run: dict) -> str:
    path = run.get("path", "")
    require(isinstance(path, str) and re.fullmatch(r"\.github/workflows/[a-z0-9-]+\.yml", path) is not None,
            "Unrecognized source workflow path")
    stem = Path(path).stem
    require(stem in WORKFLOW_PRODUCERS, "Source workflow caller is not enrolled")
    return WORKFLOW_PRODUCERS[stem]


def validate_provider_event(meta: dict, run: dict, jobs: dict, raw: bytes, upload_steps: dict,
                            *, run_artifacts: list[dict] | None = None,
                            artifact_bytes: dict[int, bytes] | None = None,
                            artifact_names: dict[str, dict[str, str]] | None = None) -> tuple[dict, dict]:
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
    job_rows = jobs.get("jobs", [])
    require(isinstance(job_rows, list) and jobs.get("total_count") == len(job_rows),
            "Incomplete source job listing")
    candidates = []
    any_steps = False
    for job in job_rows:
        steps = job.get("steps", [])
        require(isinstance(steps, list), "Source job steps malformed")
        any_steps = any_steps or bool(steps)
        if any(s.get("name") == EMIT_STEP for s in steps):
            candidates.append(job)
    if len(candidates) == 1:
        job = candidates[0]
        require(job.get("run_id") == run["id"] and job.get("run_attempt") == attempt,
                "Emitter job belongs to another attempt")
        required = [EMIT_STEP, UPLOAD_STEP] + [upload_steps[event["producer"]][c["domain"]] for c in event["changes"]]
        step_proof_complete = True
        for name in required:
            matches = [s for s in job.get("steps", []) if s.get("name") == name]
            if not (
                len(matches) == 1
                and matches[0].get("status") == "completed"
                and matches[0].get("conclusion") == "success"
            ):
                step_proof_complete = False
                break
        if step_proof_complete:
            job_id = job["id"]
        else:
            require(run_artifacts is not None and artifact_bytes is not None and artifact_names is not None,
                    "Source step metadata inconclusive and durable artifact proof missing")
            job_id = validate_artifact_publication_fallback(
                event, meta, run, jobs, run_artifacts, artifact_bytes, artifact_names,
                required_steps=required,
            )
    else:
        require(not any_steps and len(candidates) == 0,
                "Source emitter job missing or ambiguous")
        require(run_artifacts is not None and artifact_bytes is not None and artifact_names is not None,
                "Source step metadata unavailable and durable artifact proof missing")
        job_id = validate_artifact_publication_fallback(
            event, meta, run, jobs, run_artifacts, artifact_bytes, artifact_names
        )
    # A failed overall run may have durably finalized cost or other state. That
    # transition is retained, but failure can NEVER be relabeled as useful work.
    evidence = {"kind": "GITHUB_ACTIONS", "repository": REPOSITORY, "artifact_id": meta["id"],
                "archive_digest": meta["digest"], "source_run_id": run["id"], "source_run_attempt": attempt,
                "source_sha": event["source_sha"], "workflow_id": run["workflow_id"], "workflow_path": run["path"],
                "source_conclusion": run["conclusion"], "event_hash": event["event_hash"], "job_id": job_id}
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

    def list_recent_journal_artifacts(self, since: str, *, max_pages: int = 20,
                                      explicit_run_ids: list[int] | tuple[int, ...] = ()) -> list[dict]:
        """Discover only reducer snapshots and enrolled producer events.

        Repository-wide artifact pagination eventually becomes unbounded because
        receipts, previews, and other unrelated artifacts accumulate. Journal
        restore instead enumerates the closed workflow allowlist, validates each
        run later through the existing provider checks, and scans events only
        from the older of the two newest successful reducer publications.
        """
        boundary = datetime.fromisoformat(since.replace("Z", "+00:00"))
        require(boundary.tzinfo is not None, "Artifact boundary requires timezone")
        require(type(max_pages) is int and max_pages > 0, "Artifact page bound invalid")
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

        # Producer run discovery stays anchored to the reviewed
        # journal/checkpoint boundary so an in-flight run that started before
        # recent reducer snapshots cannot disappear. Artifact retrieval is
        # narrower: once two successful reducer snapshots exist, a terminal
        # producer run that both started and finished before the older reducer
        # started is already covered by that predecessor snapshot and does not
        # need another per-run artifact request. Runs that started earlier but
        # remained active into the overlap window are still inspected.
        event_since = since
        overlap_at = None
        if len(snapshot_runs) == 2:
            overlap = min(snapshot_runs[0][0]["created_at"], snapshot_runs[1][0]["created_at"])
            overlap_at = datetime.fromisoformat(overlap.replace("Z", "+00:00"))
            require(overlap_at.tzinfo is not None, "Reducer overlap boundary requires timezone")

        terminal = {"success", "failure", "cancelled", "timed_out"}
        for workflow in sorted(WORKFLOW_PRODUCERS):
            for run in self._workflow_runs_since(f"{workflow}.yml", event_since, max_pages=max_pages):
                if not (
                    run.get("head_branch") == "main"
                    and run.get("status") == "completed"
                    and run.get("conclusion") in terminal
                ):
                    continue
                if overlap_at is not None:
                    created_at = run.get("created_at")
                    updated_at = run.get("updated_at")
                    require(isinstance(created_at, str), "Workflow run created_at missing")
                    require(isinstance(updated_at, str), "Workflow run updated_at missing")
                    started = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                    finished = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
                    require(started.tzinfo is not None and finished.tzinfo is not None,
                            "Workflow run timestamps require timezone")
                    if started < overlap_at and finished < overlap_at:
                        continue
                for row in self._run_artifacts(run["id"]):
                    if row.get("name", "").startswith(EVENT_PREFIX):
                        retain(row)

        for run_id in explicit_run_ids:
            require(type(run_id) is int and run_id > 0, "Explicit recovery run ID invalid")
            run = self.get(f"/actions/runs/{run_id}")
            require(run.get("id") == run_id, "Explicit recovery run identity mismatch")
            require(run.get("head_branch") == "main", "Explicit recovery run is not on main")
            require(run.get("status") == "completed" and run.get("conclusion") in terminal,
                    "Explicit recovery run is not terminal")
            source_producer(run)
            for row in self._run_artifacts(run_id):
                if row.get("name", "").startswith(EVENT_PREFIX):
                    retain(row)

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
        event = extract_json(raw, "event.json")
        validate_event(event)

        # Most events use exact completed-step metadata and need no extra
        # artifact downloads. Gather the bounded same-run artifact proof only
        # when provider step metadata is absent or stale/inconclusive.
        job_rows = jobs.get("jobs", [])
        require(isinstance(job_rows, list), "Source job listing malformed")
        all_steps_missing = bool(job_rows) and all(job.get("steps") == [] for job in job_rows)
        candidates = [
            job for job in job_rows
            if any(step.get("name") == EMIT_STEP for step in job.get("steps", []))
        ]
        fallback_needed = all_steps_missing
        if len(candidates) == 1:
            required = [
                EMIT_STEP,
                UPLOAD_STEP,
                *[upload_steps[event["producer"]][change["domain"]] for change in event["changes"]],
            ]
            fallback_needed = any(
                len(matches := [step for step in candidates[0].get("steps", []) if step.get("name") == name]) != 1
                or matches[0].get("status") != "completed"
                or matches[0].get("conclusion") != "success"
                for name in required
            )
        if not fallback_needed:
            return validate_provider_event(meta, run, jobs, raw, upload_steps)

        run_artifacts = self._run_artifacts(int(run_id))
        artifact_names = strict_load(
            (Path(__file__).resolve().parent / "UPLOAD_ARTIFACTS.json").read_bytes()
        )
        needed_names = {
            artifact_names.get(event["producer"], {}).get(change["domain"])
            for change in event["changes"]
        }
        require(None not in needed_names, "Durable state artifact mapping incomplete")
        artifacts = [
            row for row in run_artifacts
            if row.get("name") in needed_names
        ]
        artifact_bytes = {row["id"]: self.archive(row["id"]) for row in artifacts}
        return validate_provider_event(
            meta, run, jobs, raw, upload_steps,
            run_artifacts=run_artifacts,
            artifact_bytes=artifact_bytes,
            artifact_names=artifact_names,
        )
