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
import urllib.parse
import urllib.request

from soak_v3.audit import require, sha40
from verification.owner_observation_window import activation, post_activation, evidence_fields
from soak_v3.current_state_probe import verify_source_state
from soak_v3.remote_probe import GitHubReadOnly
from verification.source_acceptance_verifier import (
    APPROVAL_BASIS, REPOSITORY, REQUIRED_AUTHORITY_LIMITS, REQUIRED_CRITERIA,
    SCOPE, _decode_content, _verify_receipt_contract, collect_original_runs,
    req, strict_json, verify_acceptance, verify_terminal_repair_follow_through,
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


def _source_receipt_date(automatic: list[dict]) -> str:
    """Use the first qualifying core so one source maps to one receipt key."""
    req(type(automatic) is list and automatic,
        "automatic source evidence missing")
    return automatic[0]["completed"].strftime("%Y%m%d")


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
    # Anchor this source at the first genuine successful source-bound observer,
    # never at the first pre-activation automatic core. Existing source history
    # is replayed for state continuity without earning owner-window time.
    from verification.reliability_day import CORE, Snapshot, inventory, window
    marker = activation(api, source)
    rows = window(inventory(api, CORE + "&head_sha=" + source), source,
                  activation_start=marker["created"])
    summary = collect_original_runs(Snapshot(api, rows), source)
    scoped = post_activation(summary, marker)
    req(scoped["status"] == "PASS", "post-activation 12-hour window not complete")
    # Freeze at the FIRST terminal eligible core so later normal activity
    # never advances the 30-minute follow-through deadline.
    frozen_terminal = scoped["terminal"]
    # Do NOT re-fetch all original artifacts a second time: use only the
    # verified original proofs returned by the single complete replay.
    # The independent App will separately re-read each original source run.
    proven = [row for row in summary["runs"]
              if row["created"] <= frozen_terminal["completed"]]
    automatic = [row for row in proven if row["event"] != "push"]
    req(len(proven) >= 3 and len(automatic) >= 2
        and automatic[-1]["id"] == frozen_terminal["id"]
        and len([row for row in proven if row["event"] == "push"]) == 1,
        "post-activation terminal or source census changed")
    gaps = [int((right["completed"] - left["completed"]).total_seconds())
            for left, right in zip(automatic, automatic[1:])]
    summary = {
        "runs": proven, "automatic": automatic, "terminal": automatic[-1],
        "span": int((automatic[-1]["completed"] - automatic[0]["completed"]).total_seconds()),
        "maximum_gap": max(gaps),
        "signed_timestamps": [row["scheduled_at"] for row in automatic
                              if row["origin_kind"] == "cloudflare_cron_v1"],
    }
    scoped = post_activation(summary, marker)
    req(scoped["status"] == "PASS" and scoped["terminal"]["id"] == summary["terminal"]["id"],
        "frozen owner interval changed during source replay")
    terminal = summary["terminal"]
    req(summary["span"] >= REQUIRED_CRITERIA["minimum_completed_span_seconds"]
        and summary["maximum_gap"] <= REQUIRED_CRITERIA["maximum_intercore_gap_seconds"],
        "full source original-run ancestry or timing invalid")
    verify_terminal_repair_follow_through(api, summary, source)
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
    date = _source_receipt_date(automatic)
    receipt = {
        "schema_version": 2,
        "decision_date_utc": terminal["completed"].strftime("%Y-%m-%d"),
        "decision": "RELEASED",
        "status": "PASS",
        "scope": SCOPE,
        "source_sha": source,
        "approval_basis": APPROVAL_BASIS,
        "criteria": dict(REQUIRED_CRITERIA),
        "original_run_evidence": {
            "original_qualifying_cores": len(automatic),
            "original_signed_cloudflare_dispatched_cores": sum(
                row["origin_kind"] == "cloudflare_cron_v1" for row in automatic),
            "original_github_native_schedule_cores": sum(
                row["origin_kind"] == "github_schedule" for row in automatic),
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
            "original_proof_status": "TWELVE_HOUR_ORIGINAL_GITHUB_EVIDENCE_VERIFIED",
            **evidence_fields(marker, scoped),
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
        "authority_limits": dict(REQUIRED_AUTHORITY_LIMITS),
    }
    _verify_receipt_contract(receipt)
    return receipt, date


def publish_receipt(api: GitHubReadOnly, writer: GitHubWrite, *, source: str,
                    receipt: dict, date: str) -> dict:
    # Reject any undeclared assertion before provider reads or writes.
    _verify_receipt_contract(receipt)
    branch = f"auto-repair/pb-01-acceptance-receipt-{source[:8]}-{date}"
    path = f"acceptance/finish-soak-{source[:8]}-{date}.json"
    raw = (json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    prefix = f"/git/matching-refs/heads/{branch}"
    # matching-refs returns an array, while GitHubReadOnly.json intentionally
    # accepts objects only; use its bounded raw reader here.
    matches = json.loads(api.get(prefix))
    req(type(matches) is list and len(matches) <= 1, "acceptance branch ambiguous")
    reused = bool(matches)
    if matches:
        head = matches[0].get("object", {}).get("sha")
        sha40(head)
        existing = _decode_content(api.json(
            f"/contents/{urllib.parse.quote(path, safe='/')}?ref={head}"
        ))
        accepted = strict_json(existing)
        req(accepted.get("source_sha") == source
            and accepted.get("scope") == SCOPE
            and accepted.get("status") == "PASS"
            and accepted.get("decision") == "RELEASED",
            "existing acceptance receipt identity invalid")
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
        req(not reused, "existing acceptance branch missing open PR")
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
    if reused:
        verified_source, _ = verify_acceptance(
            api, pr_number=number, head_sha=head,
        )
        req(verified_source == source, "existing acceptance source verification mismatch")
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
    except Exception:
        # Public workflow output is a closed interface: provider/exception text
        # must never cross into logs or durable evidence.
        print(json.dumps({
            "status": "NOT_READY",
            "reason_code": "SOURCE_ACCEPTANCE_NOT_READY",
        }, sort_keys=True))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
