#!/usr/bin/env python3
"""Independently attest an exact source-specific production acceptance receipt.

The verifier reads original GitHub runs, artifacts, Git state, and the terminal
SQLite image before the separately credentialed verifier App publishes a check.
Candidate code never receives the App token.
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import tempfile
import urllib.parse
import urllib.request
import zipfile

from soak_v3.audit import REQUIRED_STEPS, require, sha40, sha64, verify_artifact
from soak_v3.current_state_probe import verify_source_state
from soak_v3.remote_probe import GitHubReadOnly

REPOSITORY = "P00NSMASHER/portfolio-brain"
VERIFIER_APP_ID = 5121826
CHECK_NAME = "portfolio-source-acceptance"
BRANCH = re.compile(r"brain-acceptance-([0-9a-f]{8})-([0-9]{8})\Z")
SCOPE = "SOURCE_SPECIFIC_UNATTENDED_PRODUCTION_CORE_RELIABILITY_ONLY"
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


def _one_job(api: GitHubReadOnly, run_id: int) -> dict:
    jobs = api.json(f"/actions/runs/{run_id}/jobs?filter=all&per_page=100")
    rows = jobs.get("jobs")
    req(jobs.get("total_count") == 1 and type(rows) is list and len(rows) == 1,
        "run job census incomplete")
    job = rows[0]
    req(job.get("name") == "monitor" and job.get("status") == "completed"
        and job.get("conclusion") == "success", "monitor job failed")
    steps = {row.get("name"): row.get("conclusion") for row in job.get("steps", [])
             if type(row) is dict and type(row.get("name")) is str}
    req(all(steps.get(name) == "success" for name in REQUIRED_STEPS),
        "required production step failed")
    return job


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


def _verify_original_runs(api: GitHubReadOnly, receipt: dict, source: str) -> dict:
    evidence = receipt.get("original_run_evidence")
    req(type(evidence) is dict, "run evidence missing")
    terminal_done = utc(evidence.get("terminal_original_monitor_completed_utc"))
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
        if created <= terminal_done:
            selected.append(run)
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
            job = _one_job(api, run_id)
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
            scheduled = None
            if run["event"] == "workflow_dispatch":
                origin = _zip_json(raw, "cloudflare-origin.json")
                req(origin.get("kind") == "cloudflare_cron_v1"
                    and origin.get("status") == "CLOUDFLARE_SIGNED_ORIGIN_VERIFIED"
                    and origin.get("signed_origin") is True
                    and origin.get("source_sha") == source
                    and origin.get("soak_pass") is False,
                    "signed Cloudflare origin invalid")
                scheduled = origin.get("scheduled_at")
                utc(scheduled)
            proven.append({
                "id": run_id, "event": run["event"], "completed": utc(job.get("completed_at")),
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
    req(len(automatic) == evidence.get("original_qualifying_cores")
        and sum(row["event"] == "workflow_dispatch" for row in automatic)
            == evidence.get("original_signed_cloudflare_dispatched_cores")
        and sum(row["event"] == "schedule" for row in automatic)
            == evidence.get("original_github_native_schedule_cores"),
        "automatic origin census mismatch")
    req(automatic[0]["id"] == evidence.get("first_original_run_id")
        and automatic[-1]["id"] == evidence.get("terminal_original_run_id"),
        "acceptance endpoints mismatch")
    span = int((automatic[-1]["completed"] - automatic[0]["completed"]).total_seconds())
    gaps = [int((right["completed"] - left["completed"]).total_seconds())
            for left, right in zip(automatic, automatic[1:])]
    req(span == evidence.get("completed_span_seconds") and span >= 21600
        and max(gaps) == evidence.get("maximum_gap_seconds") and max(gaps) <= 5400,
        "acceptance timing mismatch")
    req(automatic[0]["completed"] == utc(evidence["first_original_monitor_completed_utc"])
        and automatic[-1]["completed"] == terminal_done,
        "monitor completion timestamp mismatch")
    signed = [row["scheduled_at"] for row in automatic if row["event"] == "workflow_dispatch"]
    external = receipt.get("external_cloudflare_provider")
    req(type(external) is dict and signed == external.get("signed_dispatch_timestamps_utc")
        and len(signed) == external.get("signed_dispatch_count")
        and len(signed) == external.get("authenticated_exact_second_script_matches")
        and external.get("expected_dispatches_without_provider_observation") == 0
        and external.get("matched_dispatches_with_nonzero_reported_errors") == 0
        and external.get("worker_reported_errors_total") == 0,
        "external origin evidence mismatch")
    return automatic[-1]


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
        and state.get("deterministic_report_reproduction") == "PASS",
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
        and proof.get("technical_workflow_conclusion") == "success",
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
    _verify_technical_proof(api, receipt, source)
    terminal = _verify_original_runs(api, receipt, source)
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
    except Exception as exc:
        # Do not emit an unbound red check: the guarded consumer requires an exact
        # immutable source/receipt digest and absence is safely fail-closed.
        print(json.dumps({"status": "BLOCKED", "reason": type(exc).__name__ + ":" + str(exc)[:500]},
                         sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
