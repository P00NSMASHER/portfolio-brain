"""Non-authoritative original GitHub core-run inventory for V7 review.

Cannot verify ZIP artifacts, P-256-signed Cloudflare origins, independent
terminal SQLite, provider completeness, acceptance or release authority.
Accepts caller-supplied provider metadata; never calls an API, trades, spends,
changes any scheduled task, or writes canonical state.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

from .core import BrainError, require, timestamp

_SHA = re.compile(r"[0-9a-f]{40}\Z")
_MAX_ROWS = 250
_SCOPE = "ORIGINAL_PROVIDER_RUN_INVENTORY_NOT_ACCEPTANCE"
_EVENTS = frozenset({"schedule", "workflow_dispatch", "push",
                     "repository_dispatch", "workflow_run",
                     "pull_request", "other"})
_STATES = frozenset({"queued", "in_progress", "completed", "waiting", "pending"})
_CONCLUSIONS = frozenset({"success", "failure", "cancelled", "skipped",
                          "timed_out", "action_required", "neutral", "stale",
                          "startup_failure", None})
_CLASSES = (
    "NATIVE_SCHEDULE_SUCCESS_ARTIFACT_NOT_VERIFIED",
    "DISPATCH_ORIGIN_NOT_AUTHENTICATED",
    "PUSH_SMOKE_NONQUALIFYING",
    "EXACT_SOURCE_FAILED",
    "EXACT_SOURCE_NOT_COMPLETED",
    "OTHER_SOURCE_EXCLUDED",
    "OTHER_ORIGIN_NONQUALIFYING",
)


def _classify(item, expected_sha, checked_at):
    require(type(item) is dict and set(item) == {
        "run_id", "run_attempt", "workflow", "head_sha", "event",
        "status", "conclusion", "created_at", "updated_at",
    }, "INVENTORY_RUN_SCHEMA_INVALID")
    require(type(item["run_id"]) is int and 0 < item["run_id"] < 10**20
            and type(item["run_attempt"]) is int
            and 1 <= item["run_attempt"] <= 1000,
            "INVENTORY_RUN_ID_INVALID")
    require(item["workflow"] == "brain-cycle-v2",
            "INVENTORY_NONCORE_WORKFLOW_INCLUDED")
    sha = item["head_sha"]
    require(type(sha) is str and _SHA.fullmatch(sha),
            "INVENTORY_EXACT_SOURCE_INVALID")
    event = item["event"]
    status = item["status"]
    conclusion = item["conclusion"]
    require(type(event) is str and event in _EVENTS,
            "INVENTORY_ORIGIN_CLASS_INVALID")
    require(type(status) is str and status in _STATES
            and (type(conclusion) is str or conclusion is None)
            and conclusion in _CONCLUSIONS
            and (status == "completed") == (conclusion is not None),
            "INVENTORY_CONCLUSION_STATUS_INVALID")
    created = timestamp(item["created_at"])
    updated = timestamp(item["updated_at"])
    checked = timestamp(checked_at)
    require(created <= updated <= checked, "INVENTORY_RUN_CLOCK_INVALID")
    if sha != expected_sha:
        category = "OTHER_SOURCE_EXCLUDED"
    elif status != "completed":
        category = "EXACT_SOURCE_NOT_COMPLETED"
    elif conclusion != "success":
        category = "EXACT_SOURCE_FAILED"
    elif event == "schedule":
        category = "NATIVE_SCHEDULE_SUCCESS_ARTIFACT_NOT_VERIFIED"
    elif event == "workflow_dispatch":
        category = "DISPATCH_ORIGIN_NOT_AUTHENTICATED"
    elif event == "push":
        category = "PUSH_SMOKE_NONQUALIFYING"
    else:
        category = "OTHER_ORIGIN_NONQUALIFYING"
    return {
        "run_id": item["run_id"],
        "run_attempt": item["run_attempt"],
        "classification": category,
        "provider_event": event,
        "provider_status": status,
        "provider_conclusion": conclusion,
        "exact_protected_source": sha == expected_sha,
        # Provider last update time is not certified job completion.
        "provider_last_updated_at": item["updated_at"],
        "provider_run_url": (
            "https://github.com/P00NSMASHER/portfolio-brain/actions/runs/"
            + str(item["run_id"])
        ),
    }


def audit_run_inventory(rows, *, expected_sha, checked_at,
                        provider_pagination_complete=False):
    """Review current provider listing without ever producing acceptance."""
    require(type(expected_sha) is str and _SHA.fullmatch(expected_sha),
            "INVENTORY_PROTECTED_SOURCE_REQUIRED")
    require(type(checked_at) is str, "INVENTORY_EXPLICIT_UTC_TIME_REQUIRED")
    timestamp(checked_at)
    require(type(rows) is list and len(rows) <= _MAX_ROWS,
            "INVENTORY_PROVIDER_ROWS_BOUND")
    require(type(provider_pagination_complete) is bool,
            "INVENTORY_PAGINATION_CLAIM_INVALID")
    entries = [_classify(row, expected_sha, checked_at) for row in rows]
    keys = [(entry["run_id"], entry["run_attempt"]) for entry in entries]
    require(len(set(keys)) == len(keys),
            "INVENTORY_DUPLICATE_PROVIDER_RUN_ATTEMPT")
    # Normalize UTC instants: lexical sort misorders Z and fractional-Z
    # timestamps with different precision, even on the same second.
    entries.sort(key=lambda entry: (
        timestamp(entry["provider_last_updated_at"]),
        entry["run_id"], entry["run_attempt"],
    ))
    counts = {name: 0 for name in _CLASSES}
    for entry in entries:
        counts[entry["classification"]] += 1
    native = [entry for entry in entries if entry["classification"]
              == "NATIVE_SCHEDULE_SUCCESS_ARTIFACT_NOT_VERIFIED"]
    observed_span = None
    observed_gap = None
    if len(native) >= 2:
        observed = [timestamp(entry["provider_last_updated_at"])
                    for entry in native]
        observed_span = int((observed[-1] - observed[0]).total_seconds())
        observed_gap = max(
            int((right - left).total_seconds())
            for left, right in zip(observed, observed[1:])
        )
    failed = counts["EXACT_SOURCE_FAILED"]
    return {
        "schema_version": 1,
        "scope": _SCOPE,
        "expected_protected_source_sha": expected_sha,
        "checked_at": checked_at,
        "observed_run_attempts": len(entries),
        "category_counts": {k: n for k, n in counts.items() if n},
        "run_rows": entries,
        "native_schedule_success_candidates": len(native),
        "provider_update_span_seconds_NOT_COMPLETION_PROOF": observed_span,
        "provider_update_max_gap_seconds_NOT_COMPLETION_PROOF": observed_gap,
        "exact_source_failures_observed": failed,
        "exact_source_nonterminal_observed": counts["EXACT_SOURCE_NOT_COMPLETED"],
        "caller_claims_pagination_complete_NOT_AUTHENTICATED":
            provider_pagination_complete,
        "original_github_zip_verified_here": False,
        "original_signed_cloudflare_origin_verified_here": False,
        "original_mandatory_jobs_verified_here": False,
        "independent_sqlite_replay_verified_here": False,
        "all_provider_runs_authenticated": False,
        "six_hour_source_window_verified": False,
        "production_accepted": False,
        "release_authority": False,
        "github_mutations": 0,
        "provider_calls_added": 0,
        "status": ("EXACT_SOURCE_FAILURES_REVIEW_REQUIRED" if failed
                   else "ORIGINAL_SIGNED_AND_BINARY_EVIDENCE_REQUIRED"),
    }


def project_native_actions_page(payload):
    """Reduce one bounded, raw GitHub Actions API page to fixed, safe fields.

    This projection does not certify the URL it came from, enumerate
    unseen pages, authenticate Cloudflare, or prove job completion. The
    optional audit remains advisory even if the provider count matches.
    """
    require(type(payload) is dict
            and type(payload.get("total_count")) is int
            and payload["total_count"] >= 0
            and type(payload.get("workflow_runs")) is list
            and len(payload["workflow_runs"]) <= _MAX_ROWS
            and payload["total_count"] >= len(payload["workflow_runs"]),
            "INVENTORY_GITHUB_PAGE_INVALID")
    selected = []
    for run in payload["workflow_runs"]:
        require(type(run) is dict and type(run.get("name")) is str,
                "INVENTORY_GITHUB_RUN_INVALID")
        if run["name"] != "brain-cycle-v2":
            continue
        repository = run.get("repository")
        require(type(repository) is dict
                and repository.get("full_name") == "P00NSMASHER/portfolio-brain",
                "INVENTORY_GITHUB_REPOSITORY_SCOPE_CHANGED")
        # In particular, never copy actor details, branch tokens, commit
        # messages, URLs, permission headers, logs, or arbitrary response data.
        selected.append({
            "run_id": run.get("id"),
            "run_attempt": run.get("run_attempt"),
            "workflow": run["name"],
            "head_sha": run.get("head_sha"),
            "event": run.get("event"),
            "status": run.get("status"),
            "conclusion": run.get("conclusion"),
            "created_at": run.get("created_at"),
            "updated_at": run.get("updated_at"),
        })
    return selected


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--checked-at", required=True)
    args = parser.parse_args(argv)
    try:
        source, target = args.input, args.output
        require(source.is_file() and not source.is_symlink()
                and 0 < source.stat().st_size <= 2000000,
                "INVENTORY_INPUT_INVALID")
        require(source.resolve() != target.resolve(), "INVENTORY_ALIASED_OUTPUT")
        raw = source.read_bytes()
        require(len(raw) == source.stat().st_size and len(raw) <= 2000000,
                "INVENTORY_INPUT_UNSTABLE")
        data = json.loads(raw.decode("utf-8"))
        require(type(data) is dict, "INVENTORY_INPUT_SCHEMA_INVALID")
        if set(data) == {"workflow_runs", "provider_pagination_complete"}:
            entries = data["workflow_runs"]
            completeness = data["provider_pagination_complete"]
        else:
            # Raw single GitHub Actions API page. Never mistake one page
            # for an authenticated complete provider-run inventory.
            entries = project_native_actions_page(data)
            completeness = False
        result = audit_run_inventory(
            entries, expected_sha=args.expected_sha,
            checked_at=args.checked_at,
            provider_pagination_complete=completeness,
        )
        require(target.name == "soak-inventory-advisory.json"
                and target.parent.is_dir() and not target.parent.is_symlink()
                and not target.exists(),
                "INVENTORY_NEW_PRIVATE_OUTPUT_REQUIRED")
        fd = os.open(
            target, os.O_WRONLY | os.O_CREAT | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0), 0o600,
        )
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(result, file, sort_keys=True, indent=2)
            file.write("\n")
        print(json.dumps({"status": result["status"],
                          "reviewed": result["observed_run_attempts"],
                          "production_accepted": False}))
        return 0
    except (BrainError, OSError, UnicodeError, ValueError, TypeError):
        print("INVENTORY_UNVERIFIED: no release decision", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
