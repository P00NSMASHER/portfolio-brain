#!/usr/bin/env python3
"""Independently attest an exact source-specific production acceptance receipt.

The verifier reads original GitHub runs, artifacts, Git state, and the terminal
SQLite image before the separately credentialed verifier App publishes a check.
Candidate code never receives the App token.
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone, timedelta
import hashlib
import io
import json
import os
from pathlib import Path
from types import MappingProxyType
import re
import tempfile
import time
import urllib.parse
import urllib.request
import zipfile

from soak_v3.audit import EvidenceError, REQUIRED_STEPS, require, sha40, sha64, verify_artifact
from soak_v3.current_state_probe import verify_source_state
from soak_v3.remote_probe import GitHubReadOnly
from brain.watchdog import ClockError, verify_parent

REPOSITORY = "P00NSMASHER/portfolio-brain"
VERIFIER_APP_ID = 5121826
CHECK_NAME = "portfolio-source-acceptance"
BRANCH = re.compile(r"auto-repair/pb-01-acceptance-receipt-([0-9a-f]{8})-([0-9]{8})\Z")
SCOPE = "SOURCE_SPECIFIC_UNATTENDED_PRODUCTION_CORE_RELIABILITY_ONLY"
APPROVAL_BASIS = (
    "Trusted-main producer independently verified original GitHub runs, signed-origin "
    "artifacts, state ancestry and terminal SQLite replay. Separate App attestation required."
)
REQUIRED_CRITERIA = {
    "minimum_completed_span_seconds": 43200,
    "requires_original_successful_owner_activation_observer": True,
    "requires_terminal_30_minute_repair_follow_through": True,
    "maximum_intercore_gap_seconds": 5400,
    "required_original_first_attempt_success": True,
    "excludes_push_triggered_completions": True,
    "requires_source_pinned_original_git_and_crc": True,
    "requires_pristine_raw_sqlite_ledger_report_replay": True,
    "requires_external_origin_corroboration": True,
}
REQUIRED_AUTHORITY_LIMITS = {
    "source_specific_current_main_reliability_only": True,
    "source_change_invalidates_this_acceptance": True,
    "no_new_source_acceptance_preissued": True,
    "no_current_or_future_merge_directly_authorized_by_this_receipt": True,
    "no_relaxation_of_repository_branch_rules": True,
    "no_new_secrets_credentials_schedules_or_paid_spending": True,
    "no_customer_contact_or_cross_repo_mutations": True,
    "no_claim_of_independent_third_party_human_review": True,
    "no_claim_of_real_customer_outcome": True,
}
# Immutable, shared contract: a receipt hash must not certify extra claims.
RECEIPT_FIELDS = frozenset({
    "schema_version",
    "decision_date_utc",
    "decision",
    "status",
    "scope",
    "source_sha",
    "approval_basis",
    "criteria",
    "original_run_evidence",
    "terminal_state_replay",
    "external_cloudflare_provider",
    "proof",
    "authority_limits",
})
RECEIPT_NESTED_FIELDS = MappingProxyType({
    "original_run_evidence": frozenset({
        "original_qualifying_cores",
        "original_signed_cloudflare_dispatched_cores",
        "original_github_native_schedule_cores",
        "first_original_run_id",
        "first_original_monitor_completed_utc",
        "terminal_original_run_id",
        "terminal_original_monitor_completed_utc",
        "completed_span_seconds",
        "maximum_gap_seconds",
        "all_success_attempt_one",
        "all_original_core_state_parent_child_links_contiguous",
        "all_required_original_job_steps_success",
        "source_run_census_count",
        "original_artifacts_sha256_size_crc_verified",
        "historical_adverse_automatic_cores_for_this_source",
        "prior_source_acceptance_is_not_transferable",
        "original_proof_status",
        "owner_activation_observer_run_id",
        "owner_activation_observer_created_utc",
        "post_activation_qualifying_cores",
        "post_activation_first_run_id",
        "post_activation_first_completed_utc",
        "post_activation_terminal_run_id",
        "post_activation_terminal_completed_utc",
        "post_activation_completed_span_seconds",
        "post_activation_maximum_gap_seconds",
    }),
    "terminal_state_replay": frozenset({
        "source_sha",
        "last_state_commit",
        "direct_parent",
        "raw_sqlite_sha256",
        "last_original_state_raw_sha256",
        "raw_sqlite_bytes",
        "compressed_sha256",
        "compressed_bytes",
        "state_chunks",
        "canonical_sequence",
        "canonical_hash",
        "attempts",
        "events",
        "ledger_rows",
        "pending_events",
        "sqlite_integrity",
        "foreign_keys",
        "strict_event_ledger_replay",
        "deterministic_report_reproduction",
        "terminal_replay_status",
    }),
    "external_cloudflare_provider": frozenset({
        "source",
        "worker_script_name",
        "signed_dispatch_timestamps_utc",
        "signed_dispatch_count",
        "all_signed_origin_records_source_bound",
        "all_origin_verification_steps_success",
        "only_signed_origin_with_successful_original_github_monitor_counted",
        "standalone_worker_invocation_never_counts_as_completed_cycle",
    }),
    "proof": frozenset({
        "technical_workflow_run_id",
        "technical_workflow_run_attempt",
        "technical_workflow_conclusion",
        "technical_audit_url",
        "hosted_review_result_source_bound",
    }),
})

MAX_RUNS = 100


class SourceAcceptanceError(RuntimeError):
    pass


def req(ok: bool, message: str) -> None:
    if not ok:
        raise SourceAcceptanceError(message)


def strict_json(raw: bytes) -> dict:
    def pairs(rows):
        out = {}
        for key, value in rows:
            req(key not in out, "duplicate JSON key")
            out[key] = value
        return out

    try:
        value = json.loads(
            raw.decode("utf-8"), object_pairs_hook=pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
        )
    except (UnicodeError, ValueError) as exc:
        raise SourceAcceptanceError("receipt JSON invalid") from exc
    req(type(value) is dict, "receipt must be an object")
    return value


def utc(value: str) -> datetime:
    req(type(value) is str and value.endswith("Z"), "UTC timestamp invalid")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise SourceAcceptanceError("UTC timestamp invalid") from exc
    req(parsed.tzinfo == timezone.utc, "UTC timestamp invalid")
    return parsed


def _decode_content(doc: dict) -> bytes:
    req(doc.get("encoding") == "base64" and type(doc.get("content")) is str,
        "GitHub content response invalid")
    try:
        raw = base64.b64decode("".join(doc["content"].split()), validate=True)
    except ValueError as exc:
        raise SourceAcceptanceError("GitHub content base64 invalid") from exc
    req(type(doc.get("size")) is int and len(raw) == doc["size"],
        "GitHub content size mismatch")
    return raw


def _zip_json(raw: bytes, name: str) -> dict:
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            names = archive.namelist()
            req(len(names) <= 100 and len(names) == len(set(names)),
                "artifact ZIP inventory invalid")
            req(all(not n.startswith("/") and ".." not in Path(n).parts for n in names),
                "artifact ZIP path invalid")
            return strict_json(archive.read(name))
    except (KeyError, OSError, zipfile.BadZipFile) as exc:
        raise SourceAcceptanceError("artifact ZIP invalid") from exc


def _one_job(api: GitHubReadOnly, run_id: int, *, source=None, sleep=time.sleep) -> dict:
    """Replay the original monitor with bounded fail-closed GitHub readbacks.

    A successful workflow_run may momentarily expose a partial job-step list.
    Explicit failed steps, adverse jobs, inconsistent identities, and exhausted
    transport or incomplete reads cannot be converted into acceptance.
    """
    path = f"/actions/runs/{run_id}/jobs?filter=all&per_page=100"
    original_job_id = None
    for attempt in range(3):
        try:
            jobs = api.json(path)
        except EvidenceError as exc:
            if str(exc) != "GITHUB_API_UNAVAILABLE" or attempt == 2:
                raise
            sleep(attempt + 1)
            continue
        rows = jobs.get("jobs") if type(jobs) is dict else None
        req(type(jobs) is dict and jobs.get("total_count") == 1
            and type(rows) is list and len(rows) == 1 and type(rows[0]) is dict,
            "run job census incomplete")
        job = rows[0]
        job_id = job.get("id")
        req(type(job_id) is int and job_id > 0, "original monitor ID invalid")
        if original_job_id is None:
            original_job_id = job_id
        req(job_id == original_job_id, "original monitor ID changed")
        req(type(job.get("run_id")) is int and job["run_id"] == run_id
            and job.get("run_attempt") == 1,
            "original monitor run identity mismatch")
        if source is not None:
            req(type(source) is str and re.fullmatch(r"[0-9a-f]{40}", source)
                and job.get("head_sha") == source,
                "original monitor source mismatch")
        req(job.get("name") == "monitor"
            and job.get("status") == "completed"
            and job.get("conclusion") == "success",
            "monitor job failed")
        rows = job.get("steps")
        req(type(rows) is list and all(type(row) is dict for row in rows),
            "original job steps invalid")
        steps = {}
        for row in rows:
            name = row.get("name")
            if name not in REQUIRED_STEPS:
                continue
            req(type(name) is str and name not in steps,
                "duplicate original required step")
            result = row.get("conclusion")
            req(result in (None, "success", "skipped", "failure", "cancelled",
                           "timed_out", "neutral"), "original step result invalid")
            steps[name] = result
        req(all(steps.get(name) in (None, "success") for name in REQUIRED_STEPS),
            "required production step failed")
        if all(steps.get(name) == "success" for name in REQUIRED_STEPS):
            return job
        if attempt == 2:
            raise SourceAcceptanceError(
                "required production step still incomplete after bounded rereads")
        sleep(attempt + 1)
    raise SourceAcceptanceError("original monitor job readback unavailable")


def _one_artifact(api: GitHubReadOnly, run: dict, source: str) -> tuple[dict, bytes, dict]:
    run_id = run["id"]
    doc = api.json(f"/actions/runs/{run_id}/artifacts?per_page=100")
    rows = doc.get("artifacts")
    req(doc.get("total_count") == 1 and type(rows) is list and len(rows) == 1,
        "run artifact census incomplete")
    item = rows[0]
    req(item.get("expired") is False
        and item.get("name") == f"brain-v2-cycle-{source}-{run_id}-1"
        and item.get("workflow_run", {}).get("id") == run_id
        and item.get("workflow_run", {}).get("head_sha") == source,
        "run artifact identity invalid")
    digest = item.get("digest")
    req(type(digest) is str and digest.startswith("sha256:"),
        "run artifact digest missing")
    sha64(digest[7:])
    raw = api.get(f"/actions/artifacts/{item['id']}/zip", limit=20_000_000)
    req(hashlib.sha256(raw).hexdigest() == digest[7:], "run artifact digest mismatch")
    delivery = _zip_json(raw, "delivery.json")
    req(delivery.get("source_sha") == source
        and delivery.get("run_id") == str(run_id)
        and delivery.get("run_attempt") == "1", "delivery identity invalid")
    return item, raw, delivery


def _validated_automatic_origin(api, run: dict, raw: bytes, source: str) -> tuple[str | None, str]:
    """Replay the actual origin: external signed Cron or authenticated GitHub watchdog.

    A workflow_dispatch is never an automatic source merely because its job succeeded.
    GitHub schedule times continue in brain-clock.yml; direct core schedules cannot
    bypass the shared liveness admission after the coordination release.
    """
    event = run["event"]
    if event == "push":
        return None, "push"
    req(event == "workflow_dispatch", "uncoordinated direct core schedule forbidden")
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            names = set(archive.namelist())
    except (OSError, zipfile.BadZipFile) as exc:
        raise SourceAcceptanceError("automatic origin artifact ZIP invalid") from exc
    external = "cloudflare-origin.json" in names
    native = "watchdog-origin.json" in names
    req(external != native, "automatic scheduler origin absent or ambiguous")
    if external:
        origin = _zip_json(raw, "cloudflare-origin.json")
        req(origin.get("kind") == "cloudflare_cron_v1"
            and origin.get("status") == "CLOUDFLARE_SIGNED_ORIGIN_VERIFIED"
            and origin.get("signed_origin") is True
            and origin.get("source_sha") == source
            and origin.get("soak_pass") is False,
            "signed Cloudflare origin invalid")
        scheduled = origin.get("scheduled_at")
        utc(scheduled)
        return scheduled, "cloudflare_cron_v1"

    receipt = _zip_json(raw, "watchdog-origin.json")
    clock_id = receipt.get("clock_run_id")
    req(type(clock_id) is int and clock_id > 0
        and receipt.get("kind") == "github_schedule"
        and receipt.get("core_actor") == "github-actions[bot]"
        and run.get("actor", {}).get("login") == "github-actions[bot]",
        "GitHub watchdog origin identity invalid")
    parent = api.json(f"/actions/runs/{clock_id}")
    try:
        verified = verify_parent(
            parent, source, clock_id, "github-actions[bot]",
            now=utc(run.get("created_at")),
        )
    except (ClockError, ValueError, TypeError, KeyError) as exc:
        raise SourceAcceptanceError("GitHub watchdog provider origin invalid") from exc
    req(receipt == verified, "GitHub watchdog origin receipt mismatch")
    jobs = api.json(f"/actions/runs/{clock_id}/jobs?filter=all&per_page=100")
    job_rows = jobs.get("jobs")
    req(jobs.get("total_count") == 2 and type(job_rows) is list
        and len(job_rows) == 2,
        "GitHub watchdog original job census incomplete")
    by_name = {job.get("name"): job for job in job_rows if type(job) is dict}
    req(len(by_name) == 2 and set(by_name) == {"dispatch", "scheduled-watchdog"}
        and by_name["dispatch"].get("conclusion") == "skipped"
        and by_name["scheduled-watchdog"].get("status") == "completed"
        and by_name["scheduled-watchdog"].get("conclusion") == "success",
        "GitHub watchdog original job verification failed")
    steps = {step.get("name"): step.get("conclusion")
             for step in by_name["scheduled-watchdog"].get("steps", []) if type(step) is dict}
    req(steps.get("Check independent GitHub scheduling liveness") == "success"
        and steps.get("Dispatch one overdue core without inventing a PASS") == "success",
        "GitHub watchdog actual dispatch not verified")
    return None, "github_schedule"


def _require_nonoverlapping_scheduler_origins(rows: list[dict]) -> None:
    """Deny overlapping invocations from distinct automatic schedulers."""
    for previous, current in zip(rows, rows[1:]):
        if previous.get("origin_kind", previous["event"]) != current.get("origin_kind", current["event"]):
            req(current["created"] >= previous["completed"],
                "competing scheduler origins overlapped")


def collect_original_runs(api: GitHubReadOnly, source: str, evidence: dict | None = None) -> dict:
    if evidence is not None:
        req(type(evidence) is dict, "run evidence missing")
        terminal_done = utc(evidence.get("terminal_original_monitor_completed_utc"))
    else:
        terminal_done = None
    inventory = api.json(
        "/actions/workflows/brain-cycle.yml/runs?branch=main&per_page=100"
    )
    rows = inventory.get("workflow_runs")
    req(type(rows) is list and type(inventory.get("total_count")) is int
        and 0 < len(rows) <= MAX_RUNS, "workflow run census incomplete")
    selected = []
    for run in rows:
        if type(run) is not dict or run.get("head_sha") != source:
            continue
        created = utc(run.get("created_at"))
        if terminal_done is None or created <= terminal_done:
            selected.append(run)
    if evidence is not None:
        req(len(selected) == evidence.get("source_run_census_count"),
            "source run census mismatch")

    proven = []
    with tempfile.TemporaryDirectory(prefix="source-acceptance-runs-") as folder:
        for run in selected:
            run_id = run.get("id")
            req(type(run_id) is int and run_id > 0
                and run.get("path") == ".github/workflows/brain-cycle.yml"
                and run.get("head_branch") == "main"
                and run.get("event") in {"push", "schedule", "workflow_dispatch"}
                and run.get("status") == "completed"
                and run.get("conclusion") == "success"
                and run.get("run_attempt") == 1, "source run failed, retried, or invalid")
            job = _one_job(api, run_id, source=source)
            item, raw, delivery = _one_artifact(api, run, source)
            state_parent = sha40(delivery.get("state_parent"))
            state_commit = sha40(delivery.get("state_commit"))
            state = api.json(f"/git/commits/{state_commit}")
            req(state.get("sha") == state_commit
                and [row.get("sha") for row in state.get("parents", [])] == [state_parent],
                "published state ancestry invalid")
            archive_path = Path(folder) / f"{run_id}.zip"
            archive_path.write_bytes(raw)
            proof = verify_artifact(
                archive_path, item["digest"], run_id=run_id, source_sha=source,
                state_parent=state_parent, state_commit=state_commit,
            )
            scheduled, origin_kind = _validated_automatic_origin(api, run, raw, source)
            proven.append({
                "id": run_id, "event": run["event"], "origin_kind": origin_kind,
                "created": utc(run.get("created_at")),
                "completed": utc(job.get("completed_at")),
                "state_parent": state_parent, "state_commit": state_commit,
                "sequence": proof["state_sequence"], "canonical_hash": proof["canonical_hash"],
                "scheduled_at": scheduled,
            })

    proven.sort(key=lambda row: row["completed"])
    req(len(proven) >= 2 and sum(row["event"] == "push" for row in proven) == 1,
        "deployment run census invalid")
    for previous, current in zip(proven, proven[1:]):
        req(current["state_parent"] == previous["state_commit"],
            "source state publication chain is not contiguous")
    automatic = [row for row in proven if row["event"] != "push"]
    req(len(automatic) >= 2, "automatic run census too small")
    _require_nonoverlapping_scheduler_origins(automatic)
    span = int((automatic[-1]["completed"] - automatic[0]["completed"]).total_seconds())
    gaps = [int((right["completed"] - left["completed"]).total_seconds())
            for left, right in zip(automatic, automatic[1:])]
    signed = [row["scheduled_at"] for row in automatic if row["origin_kind"] == "cloudflare_cron_v1"]
    if evidence is not None:
        req(len(automatic) == evidence.get("original_qualifying_cores")
            and sum(row["origin_kind"] == "cloudflare_cron_v1" for row in automatic)
                == evidence.get("original_signed_cloudflare_dispatched_cores")
            and sum(row["origin_kind"] == "github_schedule" for row in automatic)
                == evidence.get("original_github_native_schedule_cores"),
            "automatic origin census mismatch")
        req(automatic[0]["id"] == evidence.get("first_original_run_id")
            and automatic[-1]["id"] == evidence.get("terminal_original_run_id"),
            "acceptance endpoints mismatch")
        req(span == evidence.get("completed_span_seconds")
            and span >= REQUIRED_CRITERIA["minimum_completed_span_seconds"]
            and max(gaps) == evidence.get("maximum_gap_seconds") and max(gaps) <= 5400,
            "acceptance timing mismatch")
        req(automatic[0]["completed"] == utc(evidence["first_original_monitor_completed_utc"])
            and automatic[-1]["completed"] == terminal_done,
            "monitor completion timestamp mismatch")
    return {
        "runs": proven, "automatic": automatic, "terminal": automatic[-1],
        "span": span, "maximum_gap": max(gaps), "signed_timestamps": signed,
    }


def verify_terminal_repair_follow_through(
    api: GitHubReadOnly, summary: dict, source: str, *, now=None,
) -> None:
    """Require the full 30-minute terminal interval and replay original repairs.

    The observer's source-bounded window and repair verifier are reused here,
    but the producer and independent App must each perform their own reads.
    """
    from verification.reliability_day import inventory, verify_repairs
    cutoff = summary["terminal"]["completed"] + timedelta(minutes=30)
    instant = datetime.now(timezone.utc) if now is None else now
    req(isinstance(instant, datetime) and instant.tzinfo is not None
        and instant >= cutoff,
        "terminal 30-minute repair follow-through interval not complete")
    repairs = inventory(
        api, "/actions/workflows/v8-scoped-repair.yml/runs?branch=main&per_page=100&head_sha=" + source,
    )
    req(verify_repairs(
        api, repairs, source, {row["id"] for row in summary["automatic"]},
        cutoff=cutoff,
    ), "original terminal repair follow-through incomplete")


def _verify_receipt_contract(receipt: dict) -> None:
    req(type(receipt) is dict and set(receipt) == RECEIPT_FIELDS,
        "acceptance receipt schema fields invalid")
    for field, required_fields in RECEIPT_NESTED_FIELDS.items():
        value = receipt.get(field)
        req(type(value) is dict and set(value) == required_fields,
            "acceptance receipt nested schema fields invalid")
    req(receipt.get("schema_version") == 2
        and receipt.get("approval_basis") == APPROVAL_BASIS
        and receipt.get("criteria") == REQUIRED_CRITERIA
        and receipt.get("authority_limits") == REQUIRED_AUTHORITY_LIMITS,
        "acceptance receipt contract invalid")
    evidence = receipt.get("original_run_evidence")
    req(type(evidence) is dict
        and (type(evidence.get("owner_activation_observer_run_id")) is int
             or evidence.get("owner_activation_observer_run_id") is None)
        and evidence.get("historical_adverse_automatic_cores_for_this_source") == []
        and evidence.get("prior_source_acceptance_is_not_transferable") is True
        and evidence.get("original_proof_status")
            == "TWELVE_HOUR_ORIGINAL_GITHUB_EVIDENCE_VERIFIED",
        "acceptance original-run contract invalid")
    external = receipt.get("external_cloudflare_provider")
    req(type(external) is dict
        and external.get("source")
            == "Original source-bound signed Cloudflare origin records retained in GitHub artifacts"
        and external.get("worker_script_name") == "portfolio-brain-recovery"
        and external.get("only_signed_origin_with_successful_original_github_monitor_counted")
            is True
        and external.get("standalone_worker_invocation_never_counts_as_completed_cycle")
            is True,
        "acceptance external-origin contract invalid")


def _verify_original_runs(api: GitHubReadOnly, receipt: dict, source: str) -> dict:
    evidence = receipt.get("original_run_evidence")
    summary = collect_original_runs(api, source, evidence)
    from verification.owner_observation_window import (verify_post_activation, OwnerWindowError)
    try:
        owner_window = verify_post_activation(api, source, summary, evidence)
    except OwnerWindowError as exc:
        raise SourceAcceptanceError(str(exc)) from exc
    req(owner_window["terminal"]["id"] == summary["terminal"]["id"],
        "owner-activated terminal is not exact receipt terminal")
    external = receipt.get("external_cloudflare_provider")
    signed = summary["signed_timestamps"]
    req(type(external) is dict and signed == external.get("signed_dispatch_timestamps_utc")
        and len(signed) == external.get("signed_dispatch_count")
        and external.get("all_signed_origin_records_source_bound") is True
        and external.get("all_origin_verification_steps_success") is True
        and external.get("only_signed_origin_with_successful_original_github_monitor_counted")
            is True
        and external.get("standalone_worker_invocation_never_counts_as_completed_cycle")
            is True,
        "external origin evidence mismatch")
    verify_terminal_repair_follow_through(api, summary, source)
    return summary["terminal"]


def _verify_terminal(api: GitHubReadOnly, receipt: dict, source: str, terminal: dict) -> None:
    state = receipt.get("terminal_state_replay")
    req(type(state) is dict and state.get("source_sha") == source
        and state.get("last_state_commit") == terminal["state_commit"]
        and state.get("direct_parent") == terminal["state_parent"]
        and state.get("canonical_sequence") == terminal["sequence"]
        and state.get("canonical_hash") == terminal["canonical_hash"],
        "terminal receipt does not match original run")
    replay = verify_source_state(
        api, state_commit=terminal["state_commit"], source_sha=source,
        expected_parent=terminal["state_parent"], expected_sequence=terminal["sequence"],
        expected_chain=terminal["canonical_hash"],
    )
    req(replay.get("state_bytes_sha256") == state.get("raw_sqlite_sha256")
        and replay.get("state_bytes") == state.get("raw_sqlite_bytes")
        and replay.get("state_chunks") == state.get("state_chunks")
        and replay.get("real_provider_attempt_count") == state.get("attempts")
        and state.get("events") == terminal["sequence"]
        and state.get("ledger_rows") == terminal["sequence"]
        and state.get("pending_events") == 0
        and state.get("sqlite_integrity") == "PASS"
        and state.get("foreign_keys") == "PASS"
        and state.get("strict_event_ledger_replay") == "PASS"
        and state.get("deterministic_report_reproduction") == "PASS"
        and state.get("last_original_state_raw_sha256") == state.get("raw_sqlite_sha256")
        and state.get("terminal_replay_status")
            == "ORIGINAL_TERMINAL_RAW_SQLITE_REPLAY_VERIFIED",
        "terminal SQLite replay mismatch")
    manifest = _decode_content(api.json(
        f"/contents/state-manifest.json?ref={terminal['state_commit']}"
    ))
    manifest_doc = strict_json(manifest)
    req(manifest_doc.get("raw_sha256") == state.get("raw_sqlite_sha256")
        and manifest_doc.get("raw_size") == state.get("raw_sqlite_bytes")
        and manifest_doc.get("compressed_sha256") == state.get("compressed_sha256")
        and manifest_doc.get("compressed_size") == state.get("compressed_bytes")
        and len(manifest_doc.get("chunks", [])) == state.get("state_chunks"),
        "terminal state manifest mismatch")


def _verify_technical_proof(api: GitHubReadOnly, receipt: dict, source: str) -> None:
    proof = receipt.get("proof")
    req(type(proof) is dict, "technical proof missing")
    run_id = proof.get("technical_workflow_run_id")
    run = api.json(f"/actions/runs/{run_id}")
    req(run.get("id") == run_id and run.get("run_attempt") == 1
        and run.get("status") == "completed" and run.get("conclusion") == "success"
        and run.get("head_sha") == source
        and run.get("path") == ".github/workflows/foundation-ci.yml"
        and proof.get("technical_workflow_run_attempt") == 1
        and proof.get("technical_workflow_conclusion") == "success"
        and proof.get("technical_audit_url")
            == f"https://github.com/{REPOSITORY}/actions/runs/{run_id}"
        and proof.get("hosted_review_result_source_bound") is True,
        "technical review run invalid")


def verify_acceptance(api: GitHubReadOnly, *, pr_number: int, head_sha: str) -> tuple[str, str]:
    sha40(head_sha)
    req(type(pr_number) is int and pr_number > 0, "PR number invalid")
    pr = api.json(f"/pulls/{pr_number}")
    branch = pr.get("head", {}).get("ref")
    match = BRANCH.fullmatch(branch or "")
    req(match is not None and pr.get("state") == "open" and pr.get("draft") is False
        and pr.get("head", {}).get("sha") == head_sha
        and pr.get("head", {}).get("repo", {}).get("full_name") == REPOSITORY
        and pr.get("base", {}).get("ref") == "main"
        and pr.get("base", {}).get("repo", {}).get("full_name") == REPOSITORY,
        "acceptance PR identity invalid")
    main = api.json("/branches/main").get("commit", {}).get("sha")
    source = sha40(main)
    req(match.group(1) == source[:8], "acceptance branch source mismatch")
    commit = api.json(f"/git/commits/{head_sha}")
    req(commit.get("sha") == head_sha
        and [row.get("sha") for row in commit.get("parents", [])] == [source],
        "acceptance commit is not one child of current main")
    path = f"acceptance/finish-soak-{source[:8]}-{match.group(2)}.json"
    compare = api.json(f"/compare/{source}...{head_sha}")
    files = compare.get("files")
    req(compare.get("ahead_by") == 1 and compare.get("behind_by") == 0
        and compare.get("merge_base_commit", {}).get("sha") == source
        and type(files) is list and len(files) == 1
        and files[0].get("filename") == path and files[0].get("status") == "added",
        "acceptance branch scope invalid")
    content = api.json(f"/contents/{urllib.parse.quote(path, safe='/')}?ref={head_sha}")
    raw = _decode_content(content)
    receipt = strict_json(raw)
    req(receipt.get("source_sha") == source and receipt.get("decision") == "RELEASED"
        and receipt.get("status") == "PASS" and receipt.get("scope") == SCOPE,
        "acceptance receipt status invalid")
    evidence = receipt.get("original_run_evidence", {})
    req(evidence.get("all_success_attempt_one") is True
        and evidence.get("all_original_core_state_parent_child_links_contiguous") is True
        and evidence.get("all_required_original_job_steps_success") is True
        and evidence.get("original_artifacts_sha256_size_crc_verified") is True,
        "acceptance receipt run assertions incomplete")
    req(match.group(2) == utc(
        evidence.get("first_original_monitor_completed_utc")
    ).strftime("%Y%m%d"), "acceptance branch date mismatch")
    _verify_receipt_contract(receipt)
    _verify_technical_proof(api, receipt, source)
    terminal = _verify_original_runs(api, receipt, source)
    req(receipt.get("decision_date_utc") == terminal["completed"].strftime("%Y-%m-%d"),
        "acceptance decision date mismatch")
    _verify_terminal(api, receipt, source, terminal)
    after = api.json("/branches/main").get("commit", {}).get("sha")
    req(after == source, "main changed during source acceptance verification")
    external_id = "source-acceptance:" + source + ":" + hashlib.sha256(raw).hexdigest()
    return source, external_id


def _app_api(token: str, payload: dict) -> dict:
    req(type(token) is str and token, "verifier App token missing")
    data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.github.com/repos/{REPOSITORY}/check-runs", data=data,
        headers={
            "Accept": "application/vnd.github+json", "Authorization": "Bearer " + token,
            "X-GitHub-Api-Version": "2022-11-28", "Content-Type": "application/json",
            "User-Agent": "portfolio-source-acceptance-verifier/1.0",
        }, method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def publish_check(*, token: str, head_sha: str, external_id: str, success: bool,
                  summary: str) -> dict:
    sha40(head_sha)
    req(type(external_id) is str and len(external_id) == 123,
        "source acceptance binding invalid")
    result = _app_api(token, {
        "name": CHECK_NAME, "head_sha": head_sha, "external_id": external_id,
        "status": "completed", "conclusion": "success" if success else "failure",
        "output": {"title": "Portfolio source acceptance", "summary": summary[:60000]},
    })
    req(result.get("name") == CHECK_NAME and result.get("head_sha") == head_sha
        and result.get("external_id") == external_id
        and result.get("app", {}).get("id") == VERIFIER_APP_ID,
        "source acceptance check publication identity invalid")
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pr-number", type=int, required=True)
    parser.add_argument("--head-sha", required=True)
    args = parser.parse_args(argv)
    read_token = os.environ.get("GITHUB_TOKEN", "")
    app_token = os.environ.get("PORTFOLIO_VERIFIER_TOKEN", "")
    external_id = ""
    try:
        source, external_id = verify_acceptance(
            GitHubReadOnly(read_token, max_calls=256),
            pr_number=args.pr_number, head_sha=args.head_sha,
        )
        check = publish_check(
            token=app_token, head_sha=args.head_sha, external_id=external_id,
            success=True,
            summary=("Independent original GitHub run, signed-origin artifact, state ancestry, "
                     "terminal SQLite/ledger/report, and technical-review evidence all passed "
                     f"for protected source {source}."),
        )
        print(json.dumps({"check_run_id": check.get("id"), "source_sha": source,
                          "head_sha": args.head_sha, "external_id": external_id}, sort_keys=True))
        return 0
    except Exception:
        # Do not emit untrusted exception/provider text or an unbound red check.
        print(json.dumps({
            "status": "BLOCKED",
            "reason_code": "SOURCE_ACCEPTANCE_VERIFICATION_BLOCKED",
        }, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
