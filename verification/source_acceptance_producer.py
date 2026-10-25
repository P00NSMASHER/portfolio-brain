#!/usr/bin/env python3
"""Create one source-bound acceptance receipt PR after original evidence passes.

This producer cannot attest its receipt. The separately credentialed verifier
App independently replays the evidence before publishing the required check.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import urllib.parse
import urllib.request

from soak_v3.audit import require, sha40
from soak_v3.current_state_probe import verify_source_state
from soak_v3.remote_probe import GitHubReadOnly
from verification.source_acceptance_verifier import (
    REPOSITORY, SCOPE, _decode_content, collect_original_runs, req, strict_json,
)


class GitHubWrite:
    def __init__(self, token: str):
        req(type(token) is str and token, "GitHub write token missing")
        self.token = token
        self.writes = 0

    def post(self, path: str, payload: dict) -> dict:
        req(path.startswith("/") and "://" not in path and ".." not in path.split("/"),
            "unsafe GitHub write path")
        self.writes += 1
        req(self.writes <= 5, "GitHub write budget exceeded")
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        request = urllib.request.Request(
            "https://api.github.com/repos/" + REPOSITORY + path, data=data,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": "Bearer " + self.token,
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
                "User-Agent": "portfolio-source-acceptance-producer/1.0",
            }, method="POST",
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
        value = json.loads(raw.decode("utf-8")) if raw else {}
        req(type(value) is dict, "GitHub write response invalid")
        return value


def _iso(value) -> str:
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def _foundation_run(api: GitHubReadOnly, source: str) -> int:
    doc = api.json("/actions/workflows/foundation-ci.yml/runs?branch=main&per_page=100")
    matches = [row for row in doc.get("workflow_runs", [])
               if row.get("head_sha") == source and row.get("event") == "push"
               and row.get("status") == "completed" and row.get("conclusion") == "success"
               and row.get("run_attempt") == 1]
    req(len(matches) == 1, "exact-source Foundation push proof missing or ambiguous")
    return matches[0]["id"]


def build_receipt(api: GitHubReadOnly, source: str) -> tuple[dict, str]:
    main = api.json("/branches/main").get("commit", {}).get("sha")
    req(main == source, "current main changed before acceptance collection")
    summary = collect_original_runs(api, source)
    automatic = summary["automatic"]
    terminal = summary["terminal"]
    req(summary["span"] >= 21600 and summary["maximum_gap"] <= 5400,
        "six-hour automatic window not complete")
    state = verify_source_state(
        api, state_commit=terminal["state_commit"], source_sha=source,
        expected_parent=terminal["state_parent"], expected_sequence=terminal["sequence"],
        expected_chain=terminal["canonical_hash"],
    )
    manifest = json.loads(_decode_content(api.json(
        f"/contents/state-manifest.json?ref={terminal['state_commit']}"
    )))
    foundation_run = _foundation_run(api, source)
    signed = summary["signed_timestamps"]
    date = terminal["completed"].strftime("%Y%m%d")
    receipt = {
        "schema_version": 2,
        "decision_date_utc": terminal["completed"].strftime("%Y-%m-%d"),
        "decision": "RELEASED",
        "status": "PASS",
        "scope": SCOPE,
        "source_sha": source,
        "approval_basis": (
            "Trusted-main producer independently verified original GitHub runs, signed-origin "
            "artifacts, state ancestry and terminal SQLite replay. Separate App attestation required."
        ),
        "criteria": {
            "minimum_completed_span_seconds": 21600,
            "maximum_intercore_gap_seconds": 5400,
            "required_original_first_attempt_success": True,
            "excludes_push_triggered_completions": True,
            "requires_source_pinned_original_git_and_crc": True,
            "requires_pristine_raw_sqlite_ledger_report_replay": True,
            "requires_external_origin_corroboration": True,
        },
        "original_run_evidence": {
            "original_qualifying_cores": len(automatic),
            "original_signed_cloudflare_dispatched_cores": sum(
                row["event"] == "workflow_dispatch" for row in automatic),
            "original_github_native_schedule_cores": sum(
                row["event"] == "schedule" for row in automatic),
            "first_original_run_id": automatic[0]["id"],
            "first_original_monitor_completed_utc": _iso(automatic[0]["completed"]),
            "terminal_original_run_id": terminal["id"],
            "terminal_original_monitor_completed_utc": _iso(terminal["completed"]),
            "completed_span_seconds": summary["span"],
            "maximum_gap_seconds": summary["maximum_gap"],
            "all_success_attempt_one": True,
            "all_original_core_state_parent_child_links_contiguous": True,
            "all_required_original_job_steps_success": True,
            "source_run_census_count": len(summary["runs"]),
            "original_artifacts_sha256_size_crc_verified": True,
            "historical_adverse_automatic_cores_for_this_source": [],
            "prior_source_acceptance_is_not_transferable": True,
            "original_proof_status": "SIX_HOUR_ORIGINAL_GITHUB_EVIDENCE_VERIFIED",
        },
        "terminal_state_replay": {
            "source_sha": source,
            "last_state_commit": terminal["state_commit"],
            "direct_parent": terminal["state_parent"],
            "raw_sqlite_sha256": state["state_bytes_sha256"],
            "last_original_state_raw_sha256": state["state_bytes_sha256"],
            "raw_sqlite_bytes": state["state_bytes"],
            "compressed_sha256": manifest["compressed_sha256"],
            "compressed_bytes": manifest["compressed_size"],
            "state_chunks": state["state_chunks"],
            "canonical_sequence": terminal["sequence"],
            "canonical_hash": terminal["canonical_hash"],
            "attempts": state["real_provider_attempt_count"],
            "events": terminal["sequence"],
            "ledger_rows": terminal["sequence"],
            "pending_events": 0,
            "sqlite_integrity": "PASS",
            "foreign_keys": "PASS",
            "strict_event_ledger_replay": "PASS",
            "deterministic_report_reproduction": "PASS",
            "terminal_replay_status": "ORIGINAL_TERMINAL_RAW_SQLITE_REPLAY_VERIFIED",
        },
        "external_cloudflare_provider": {
            "source": "Original source-bound signed Cloudflare origin records retained in GitHub artifacts",
            "worker_script_name": "portfolio-brain-recovery",
            "signed_dispatch_timestamps_utc": signed,
            "signed_dispatch_count": len(signed),
            "all_signed_origin_records_source_bound": True,
            "all_origin_verification_steps_success": True,
            "only_signed_origin_with_successful_original_github_monitor_counted": True,
            "standalone_worker_invocation_never_counts_as_completed_cycle": True,
        },
        "proof": {
            "technical_workflow_run_id": foundation_run,
            "technical_workflow_run_attempt": 1,
            "technical_workflow_conclusion": "success",
            "technical_audit_url": (
                f"https://github.com/{REPOSITORY}/actions/runs/{foundation_run}"
            ),
            "hosted_review_result_source_bound": True,
        },
        "authority_limits": {
            "source_specific_current_main_reliability_only": True,
            "source_change_invalidates_this_acceptance": True,
            "no_new_source_acceptance_preissued": True,
            "no_current_or_future_merge_directly_authorized_by_this_receipt": True,
            "no_relaxation_of_repository_branch_rules": True,
            "no_new_secrets_credentials_schedules_or_paid_spending": True,
            "no_customer_contact_or_cross_repo_mutations": True,
            "no_claim_of_independent_third_party_human_review": True,
            "no_claim_of_real_customer_outcome": True,
        },
    }
    return receipt, date



_ACCEPTANCE_BRANCH = re.compile(r"^brain-acceptance-([0-9a-f]{8})-(\d{8})$")


def _existing_source_receipt(api: GitHubReadOnly, *, source: str) -> dict | None:
    """Return one structurally valid open receipt for source, regardless of date."""
    rows = json.loads(api.get("/pulls?state=open&base=main&per_page=100"))
    req(type(rows) is list and len(rows) <= 100, "acceptance PR census invalid")
    matches = []
    for row in rows:
        head_ref = row.get("head", {}).get("ref")
        match = _ACCEPTANCE_BRANCH.fullmatch(head_ref) if type(head_ref) is str else None
        if match is None or match.group(1) != source[:8]:
            continue
        number = row.get("number")
        req(type(number) is int and number > 0, "acceptance PR number invalid")
        pr = api.json(f"/pulls/{number}")
        head = pr.get("head", {})
        base = pr.get("base", {})
        date = match.group(2)
        path = f"acceptance/finish-soak-{source[:8]}-{date}.json"
        req(pr.get("state") == "open" and pr.get("draft") is False,
            "matching acceptance PR state invalid")
        req(pr.get("user", {}).get("login") == "portfolio-brain-v8-runtime[bot]",
            "matching acceptance PR actor invalid")
        req(base.get("ref") == "main" and base.get("sha") == source,
            "matching acceptance PR base invalid")
        req(head.get("ref") == head_ref
            and head.get("repo", {}).get("full_name") == REPOSITORY,
            "matching acceptance PR head repository invalid")
        head_sha = sha40(head.get("sha"))
        commit = api.json(f"/git/commits/{head_sha}")
        parents = commit.get("parents")
        req(type(parents) is list and len(parents) == 1
            and parents[0].get("sha") == source,
            "matching acceptance receipt is not a direct source child")
        comparison = api.json(f"/compare/{source}...{head_sha}")
        files = comparison.get("files")
        req(comparison.get("status") == "ahead"
            and comparison.get("ahead_by") == 1
            and comparison.get("behind_by") == 0
            and comparison.get("total_commits") == 1
            and comparison.get("merge_base_commit", {}).get("sha") == source,
            "matching acceptance receipt topology invalid")
        req(type(files) is list and len(files) == 1
            and files[0].get("filename") == path
            and files[0].get("status") == "added",
            "matching acceptance receipt file set invalid")
        raw = _decode_content(api.json(
            f"/contents/{urllib.parse.quote(path, safe='/')}?ref={head_sha}"
        ))
        receipt = strict_json(raw)
        req(receipt.get("source_sha") == source
            and receipt.get("decision") == "RELEASED"
            and receipt.get("status") == "PASS"
            and receipt.get("scope") == SCOPE
            and receipt.get("decision_date_utc")
                == f"{date[:4]}-{date[4:6]}-{date[6:]}",
            "matching acceptance receipt body invalid")
        matches.append({
            "branch": head_ref, "head_sha": head_sha, "path": path,
            "pr_number": number, "provider_writes": 0,
        })
    req(len(matches) <= 1, "multiple open acceptance receipts for exact source")
    return matches[0] if matches else None


def publish_receipt(api: GitHubReadOnly, writer: GitHubWrite, *, source: str,
                    receipt: dict, date: str) -> dict:
    existing = _existing_source_receipt(api, source=source)
    if existing is not None:
        req(writer.writes == 0, "existing receipt discovery must precede writes")
        return existing
    branch = f"brain-acceptance-{source[:8]}-{date}"
    path = f"acceptance/finish-soak-{source[:8]}-{date}.json"
    raw = (json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    prefix = f"/git/matching-refs/heads/{branch}"
    # matching-refs returns an array, while GitHubReadOnly.json intentionally
    # accepts objects only; use its bounded raw reader here.
    matches = json.loads(api.get(prefix))
    req(type(matches) is list and len(matches) <= 1, "acceptance branch ambiguous")
    if matches:
        head = matches[0].get("object", {}).get("sha")
        sha40(head)
        existing = _decode_content(api.json(
            f"/contents/{urllib.parse.quote(path, safe='/')}?ref={head}"
        ))
        req(existing == raw, "existing acceptance receipt differs")
    else:
        base = api.json(f"/git/commits/{source}")
        tree_sha = sha40(base.get("tree", {}).get("sha"))
        blob = writer.post("/git/blobs", {
            "content": base64.b64encode(raw).decode("ascii"), "encoding": "base64",
        })
        blob_sha = sha40(blob.get("sha"))
        tree = writer.post("/git/trees", {
            "base_tree": tree_sha,
            "tree": [{"path": path, "mode": "100644", "type": "blob", "sha": blob_sha}],
        })
        new_tree = sha40(tree.get("sha"))
        commit = writer.post("/git/commits", {
            "message": f"Accept source reliability {source[:8]} ({date})",
            "tree": new_tree, "parents": [source],
        })
        head = sha40(commit.get("sha"))
        created = writer.post("/git/refs", {
            "ref": "refs/heads/" + branch, "sha": head,
        })
        req(created.get("ref") == "refs/heads/" + branch
            and created.get("object", {}).get("sha") == head,
            "acceptance ref creation readback invalid")
    # As above, the pulls endpoint is an array.
    rows = json.loads(api.get(
        "/pulls?state=open&base=main&head="
        + urllib.parse.quote("P00NSMASHER:" + branch, safe="") + "&per_page=100"
    ))
    req(type(rows) is list and len(rows) <= 1, "acceptance PR ambiguous")
    if rows:
        number = rows[0].get("number")
    else:
        pr = writer.post("/pulls", {
            "title": f"accept: source reliability {source[:8]} ({date})",
            "head": branch, "base": "main", "draft": False,
            "body": (
                "Source-specific reliability receipt. App 5121826 must independently replay "
                "the original evidence and publish the exact source-bound attestation. Do not merge."
            ),
        })
        number = pr.get("number")
    req(type(number) is int and number > 0, "acceptance PR creation failed")
    return {"branch": branch, "head_sha": head, "path": path, "pr_number": number,
            "provider_writes": writer.writes}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-sha", required=True)
    args = parser.parse_args(argv)
    source = sha40(args.source_sha)
    read_token = os.environ.get("GITHUB_TOKEN", "")
    write_token = os.environ.get("PORTFOLIO_RUNTIME_TOKEN", "")
    try:
        api = GitHubReadOnly(read_token, max_calls=256)
        receipt, date = build_receipt(api, source)
        result = publish_receipt(
            api, GitHubWrite(write_token), source=source, receipt=receipt, date=date,
        )
        print(json.dumps({"status": "RECEIPT_PR_READY", **result}, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "NOT_READY", "reason": type(exc).__name__ + ":" + str(exc)[:500]},
                         sort_keys=True))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
