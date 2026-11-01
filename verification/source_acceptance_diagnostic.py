"""Read-only forensic replay of ORIGINAL protected-source receipt prerequisites.

This intentionally does not import or call GitHubWrite, request an App token,
issue a receipt, or grant acceptance. It labels the exact stage at which the
old source producer would be unable to proceed and exposes no provider details.
Useful when the old producer only emits SOURCE_ACCEPTANCE_NOT_READY.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re

from soak_v3.remote_probe import GitHubReadOnly
from verification.reliability_day import CORE, Snapshot, inventory, window
from verification.source_acceptance_verifier import (
    collect_original_runs, verify_terminal_repair_follow_through,
)
from verification.source_acceptance_producer import _foundation_run
from soak_v3.current_state_probe import verify_source_state

SHA = re.compile(r"[0-9a-f]{40}\Z")
STAGES = (
    "MAIN_EXACT_SOURCE",
    "SOURCE_CORE_INVENTORY",
    "ORIGINAL_CORE_ARTIFACTS",
    "ORIGINAL_TWELVE_HOUR_SPAN",
    "TERMINAL_REPAIR_FOLLOW_THROUGH",
    "TERMINAL_SQLITE_REPORT_REPLAY",
    "ORIGINAL_MAIN_FOUNDATION",
    "READONLY_DIAGNOSTIC_COMPLETE",
)
SAFE_ERRORS = frozenset({
    "API_CALL_BUDGET", "GITHUB_API_UNAVAILABLE", "GITHUB_API_QUOTA_OR_FORBIDDEN",
    "GITHUB_API_RATE_LIMITED", "GITHUB_API_HTTP_REJECTED",
    "original terminal repair follow-through incomplete",
    "terminal 30-minute repair follow-through interval not complete",
    "12-hour automatic window not complete", "source runs absent",
    "original scheduled repair failed or retried", "incomplete run inventory",
    "RUN_INVENTORY_CAPACITY_EXCEEDED",
})


def error_code(exc):
    """Strict finite public vocabulary; never echo arbitrary provider text."""
    value = str(exc)
    return value if value in SAFE_ERRORS else "ORIGINAL_PROOF_NOT_VERIFIED"


def run_probe(api, source):
    """Read-only original-source assessment, not owner-started acceptance."""
    stage = STAGES[0]
    out = {"status": "BLOCKED", "stage": stage, "source_sha": source,
           "read_only": True, "independent_release_authority": False,
           "owner_aborted_observation_is_not_accepted": True}
    try:
        if api.json("/branches/main").get("commit", {}).get("sha") != source:
            raise ValueError("SOURCE_CHANGED")
        stage = STAGES[1]
        rows = window(inventory(api, CORE + "&head_sha=" + source), source)
        if len(rows) < 3:
            raise ValueError("TOO_FEW_ORIGINAL_CORES")
        stage = STAGES[2]
        summary = collect_original_runs(Snapshot(api, rows), source)
        stage = STAGES[3]
        if summary["span"] < 43200 or summary["maximum_gap"] > 5400:
            raise ValueError("TWELVE_HOUR_ORIGINAL_EVIDENCE_INCOMPLETE")
        stage = STAGES[4]
        verify_terminal_repair_follow_through(api, summary, source)
        stage = STAGES[5]
        terminal = summary["terminal"]
        state = verify_source_state(
            api, state_commit=terminal["state_commit"], source_sha=source,
            expected_parent=terminal["state_parent"],
            expected_sequence=terminal["sequence"],
            expected_chain=terminal["canonical_hash"],
        )
        if state.get("status") != "ORIGINAL_BINARY_AND_PROJECTION_VERIFIED_NOT_SOAK_PASS":
            raise ValueError("TERMINAL_REPLAY_UNVERIFIED")
        stage = STAGES[6]
        foundation_run_id = _foundation_run(api, source)
        if api.json("/branches/main").get("commit", {}).get("sha") != source:
            raise ValueError("SOURCE_CHANGED_DURING_PROOF")
        out.update(status="DIAGNOSTIC_PREREQUISITES_VERIFIED", stage=STAGES[7],
                   qualifying_original_cores=len(summary["automatic"]),
                   source_history_seconds=summary["span"],
                   maximum_gap_seconds=summary["maximum_gap"],
                   terminal_core_run_id=terminal["id"],
                   original_foundation_run_id=foundation_run_id,
                   # Explicitly NOT a certificate or owner-started window.
                   source_acceptance_receipt_issued=False)
    except Exception as exc:
        out.update(stage=stage, error_code=error_code(exc))
    out["read_calls"] = getattr(api, "calls", None)
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description="Original-source read-only diagnostic, NOT acceptance")
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--output", type=Path, default=Path("source-diagnostic-not-acceptance.json"))
    parser.add_argument("--max-calls", type=int, choices=(256, 512), default=256)
    args = parser.parse_args(argv)
    if not isinstance(args.source_sha, str) or not SHA.fullmatch(args.source_sha):
        raise SystemExit("INVALID_DIAGNOSTIC_SOURCE_SHA")
    output = args.output
    if output.is_symlink() or output.exists():
        raise SystemExit("OUTPUT_ALREADY_EXISTS")
    api = GitHubReadOnly(os.environ.get("GITHUB_TOKEN", ""), max_calls=args.max_calls)
    result = run_probe(api, args.source_sha)
    result["read_limit"] = args.max_calls
    output.write_text(json.dumps(result, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    # A diagnostic is not a release check, and returns zero only for recording.
    # Never print "PASS", "RELEASED", or "CERTIFIED" for this command.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
