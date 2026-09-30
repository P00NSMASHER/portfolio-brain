"""Read-only GitHub ingestion with exact artifact/run/job/attempt provenance.

Never trusts PASS strings or names alone. Only a same-repository main-branch
producer whose actual event publication steps succeeded may supply an event.
Artifacts from pull requests and unregistered callers cannot enter the journal.
"""
from __future__ import annotations

import base64
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
MAX_FALLBACK_JOBS = 8
MAX_JOB_LOG_BYTES = 5_242_880
MAX_WORKFLOW_SOURCE_BYTES = 1_048_576


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


def _validate_workflow_publication_contract(event: dict, upload_steps: dict, workflow_source: str) -> None:
    producer = event["producer"]
    require(producer in upload_steps, "Producer upload contract missing")
    require(isinstance(workflow_source, str) and workflow_source, "Source workflow text missing")
    require(f"- name: {EMIT_STEP}" in workflow_source, "Source workflow emitter step missing")
    require(
        f"run: python -m state_journal.emitter --producer {producer}" in workflow_source,
        "Source workflow emitter command changed",
    )
    require(f"- name: {UPLOAD_STEP}" in workflow_source, "Source workflow event upload step missing")
    event_artifact = (
        f"name: portfolio-state-event-v2-${{{{ github.run_id }}}}-{producer}-"
        f"${{{{ github.sha }}}}-${{{{ github.run_attempt }}}}"
    )
    require(event_artifact in workflow_source, "Source workflow event artifact binding changed")
    for domain, step_name in upload_steps[producer].items():
        require(f"- name: {step_name}" in workflow_source,
                f"Source workflow domain upload step missing: {domain}")
        require(
            f"steps.journal_upload_{domain}.outcome == 'success'" in workflow_source,
            f"Source workflow domain publication binding changed: {domain}",
        )


def _job_log_proves_publication(
    log_raw: bytes,
    *,
    event: dict,
    meta: dict,
    upload_steps: dict,
    workflow_source: str,
) -> bool:
    require(isinstance(log_raw, (bytes, bytearray)), "Source job log is not bytes")
    require(len(log_raw) <= MAX_JOB_LOG_BYTES, "Source job log exceeds byte limit")
    try:
        text = bytes(log_raw).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise JournalError("Source job log is not UTF-8") from exc

    emitter_command = f"python -m state_journal.emitter --producer {event['producer']}"
    if emitter_command not in text:
        return False

    _validate_workflow_publication_contract(event, upload_steps, workflow_source)

    published_rows = []
    emitted_rows = []
    for line in text.splitlines():
        if "JOURNAL_PUBLISHED_DOMAINS:" in line:
            payload = line.split("JOURNAL_PUBLISHED_DOMAINS:", 1)[1].strip()
            try:
                published_rows.append(json.loads(payload))
            except json.JSONDecodeError as exc:
                raise JournalError("Source job publication outcomes are malformed") from exc
        marker = line.find('{"emitted"')
        if marker >= 0:
            try:
                emitted_rows.append(json.loads(line[marker:]))
            except json.JSONDecodeError as exc:
                raise JournalError("Source job emitter receipt is malformed") from exc

    require(len(published_rows) == 1, "Source job publication outcomes missing or ambiguous")
    published = published_rows[0]
    expected_domains = set(upload_steps[event["producer"]])
    require(isinstance(published, dict) and set(published) == expected_domains,
            "Source job publication domain set changed")
    require(all(type(value) is bool for value in published.values()),
            "Source job publication outcomes must be booleans")
    changed_domains = {change["domain"] for change in event["changes"]}
    require(changed_domains <= expected_domains, "Event contains unregistered publication domain")
    require(all(published[domain] is True for domain in changed_domains),
            "Event domain was not backed by a successful publication outcome")

    matching_receipts = [
        row for row in emitted_rows
        if row.get("emitted") is True and row.get("event_id") == event["event_id"]
    ]
    require(len(matching_receipts) == 1, "Source emitter receipt missing or ambiguous")

    artifact_name = meta["name"]
    digest_hex = meta["digest"].removeprefix("sha256:")
    require(f"name: {artifact_name}" in text, "Source event upload name missing from job log")
    require(
        f"SHA256 digest of uploaded artifact zip is {digest_hex}" in text,
        "Source event upload digest missing from job log",
    )
    require(
        f"Artifact {artifact_name}.zip successfully finalized. Artifact ID {meta['id']}" in text,
        "Source event upload finalization missing from job log",
    )
    return True


def validate_provider_event(
    meta: dict,
    run: dict,
    jobs: dict,
    raw: bytes,
    upload_steps: dict,
    *,
    job_logs: dict[int, bytes] | None = None,
    workflow_source: str | None = None,
) -> tuple[dict, dict]:
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
    job_rows = jobs.get("jobs")
    require(isinstance(job_rows, list) and jobs.get("total_count") == len(job_rows),
            "Incomplete source job listing")
    require(job_rows, "Source job listing is empty")
    for candidate_job in job_rows:
        require(isinstance(candidate_job.get("steps"), list), "Source job steps field malformed")

    candidates = []
    for candidate_job in job_rows:
        steps = candidate_job["steps"]
        if any(s.get("name") == EMIT_STEP for s in steps):
            candidates.append(candidate_job)

    fallback_used = False
    if not candidates and all(candidate_job["steps"] == [] for candidate_job in job_rows):
        require(len(job_rows) <= MAX_FALLBACK_JOBS, "Empty-step fallback job bound exceeded")
        require(isinstance(job_logs, dict), "Source job steps unavailable and job logs were not supplied")
        require(isinstance(workflow_source, str) and workflow_source,
                "Source job steps unavailable and workflow source was not supplied")
        for candidate_job in job_rows:
            job_id = candidate_job.get("id")
            require(type(job_id) is int and job_id > 0, "Source job identity missing")
            log_raw = job_logs.get(job_id)
            require(log_raw is not None, "Source job log missing from bounded fallback")
            if _job_log_proves_publication(
                log_raw,
                event=event,
                meta=meta,
                upload_steps=upload_steps,
                workflow_source=workflow_source,
            ):
                candidates.append(candidate_job)
        fallback_used = True

    require(len(candidates) == 1, "Source emitter job missing or ambiguous")
    job = candidates[0]
    require(job.get("run_id") == run["id"] and job.get("run_attempt") == attempt, "Emitter job belongs to another attempt")
    required = [EMIT_STEP, UPLOAD_STEP] + [upload_steps[event["producer"]][c["domain"]] for c in event["changes"]]
    if job["steps"]:
        for name in required:
            matches = [s for s in job["steps"] if s.get("name") == name]
            require(len(matches) == 1 and matches[0].get("status") == "completed" and matches[0].get("conclusion") == "success",
                    f"Actual state/event publication step did not succeed: {name}")
    else:
        require(fallback_used, "Empty source steps were not independently proven")
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
        self._workflow_source_cache: dict[tuple[str, str], str] = {}
        self._job_log_cache: dict[int, bytes] = {}

    def get(self, suffix: str) -> dict:
        require(suffix.startswith("/") and ".." not in suffix and "://" not in suffix, "Unsafe API suffix")
        return self.http.json(self.base + suffix)

    def archive(self, artifact_id: int) -> bytes:
        require(type(artifact_id) is int and artifact_id > 0, "Invalid artifact ID")
        # Existing transport strips authorization on cross-host artifact redirects.
        return self.http.bytes(f"{self.base}/actions/artifacts/{artifact_id}/zip")

    def job_log(self, job_id: int) -> bytes:
        require(type(job_id) is int and job_id > 0, "Invalid workflow job ID")
        if job_id not in self._job_log_cache:
            raw = self.http.bytes(f"{self.base}/actions/jobs/{job_id}/logs")
            require(len(raw) <= MAX_JOB_LOG_BYTES, "Source job log exceeds byte limit")
            self._job_log_cache[job_id] = raw
        return self._job_log_cache[job_id]

    def workflow_source(self, workflow_path: str, source_sha: str) -> str:
        require(
            isinstance(workflow_path, str)
            and re.fullmatch(r"\.github/workflows/[a-z0-9-]+\.yml", workflow_path) is not None,
            "Unsafe source workflow path",
        )
        require(isinstance(source_sha, str) and re.fullmatch(r"[a-f0-9]{40}", source_sha) is not None,
                "Unsafe source workflow SHA")
        key = (workflow_path, source_sha)
        if key not in self._workflow_source_cache:
            encoded_path = quote(workflow_path, safe="/")
            encoded_sha = quote(source_sha, safe="")
            doc = self.get(f"/contents/{encoded_path}?ref={encoded_sha}")
            require(doc.get("type") == "file" and doc.get("encoding") == "base64",
                    "Source workflow contents response malformed")
            payload = doc.get("content")
            require(isinstance(payload, str), "Source workflow contents missing")
            try:
                raw = base64.b64decode("".join(payload.split()), validate=True)
                source = raw.decode("utf-8")
            except (ValueError, UnicodeDecodeError) as exc:
                raise JournalError("Source workflow contents are unreadable") from exc
            require(len(raw) <= MAX_WORKFLOW_SOURCE_BYTES, "Source workflow exceeds byte limit")
            self._workflow_source_cache[key] = source
        return self._workflow_source_cache[key]

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

        event_since = since
        if len(snapshot_runs) == 2:
            # Recent producer discovery may advance to the predecessor reducer
            # start only because every reducer triggered by workflow_run also
            # supplies that exact producer run explicitly below. This prevents
            # in-flight/queued producers from falling through the overlap gap.
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

        job_rows = jobs.get("jobs")
        fallback = (
            isinstance(job_rows, list)
            and bool(job_rows)
            and all(isinstance(job.get("steps"), list) and job["steps"] == [] for job in job_rows)
        )
        job_logs = None
        workflow_source = None
        if fallback:
            require(len(job_rows) <= MAX_FALLBACK_JOBS, "Empty-step fallback job bound exceeded")
            job_logs = {}
            for job in job_rows:
                job_id = job.get("id")
                require(type(job_id) is int and job_id > 0, "Source job identity missing")
                job_logs[job_id] = self.job_log(job_id)
            workflow_source = self.workflow_source(run.get("path", ""), run.get("head_sha", ""))

        return validate_provider_event(
            meta,
            run,
            jobs,
            raw,
            upload_steps,
            job_logs=job_logs,
            workflow_source=workflow_source,
        )
