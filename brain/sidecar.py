"""One-shot, opt-in V7 sidecar provenance and sanitized evidence publication.

This code verifies original same-run delivery metadata and publishes an
advisory summary only. It does not authorize further actions or make calls.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import stat
import sys
from pathlib import Path

from .core import BrainError, require

_SHA = re.compile(r"[0-9a-f]{40}\Z")
_RUN = re.compile(r"[1-9][0-9]{0,19}\Z")
_STAGE = frozenset({"success", "failure", "cancelled", "skipped", "unknown"})
_REPORT_STATUSES = frozenset({
    "NO_ELIGIBLE_FAILURES",
    "READ_ONLY_REVALIDATION_COMPLETE",
    "BOUNDED_READ_ONLY_REVALIDATION_COMPLETE_WITH_DEFERRED",
    "INCOMPLETE_READ_ONLY_REVALIDATION",
    "REQUEST_BUDGET_DEFERRED",
    "STOPPED",
})
_OBSERVED = frozenset({
    "STILL_ADVERSE", "SUCCESS_OBSERVED_NOT_RESOLUTION",
    "CHECK_NOT_COMPLETED", "OTHER_CONCLUSION_NOT_RESOLUTION",
    "UNVERIFIED_MISSING_OR_AMBIGUOUS_CHECK",
})
_ROWS = frozenset({
    "OBSERVED_CHECK_STATUS_NOT_ROOT_CAUSE",
    "SOURCE_CHANGED_REQUIRES_NEW_COMPARISON",
    "UNVERIFIED_READ_FAILED",
})
_FOLLOWUP_KINDS = frozenset({
    "INITIAL_ADVERSE_TRANSITION",
    "EVIDENCE_GAP_REVALIDATION",
    "PERSISTENT_ADVERSE_OBSERVED",
    "RECOVERY_OBSERVED_NOT_RESOLUTION",
})


def validate_delivery(document, source_sha, run_id, run_attempt):
    """Bind immutable state checkout only to the completed original core."""
    require(type(document) is dict and set(document) == {
        "schema_version", "source_sha", "state_parent", "state_commit",
        "run_id", "run_attempt", "workflow", "publication_verified",
        "execution_boundary", "soak_completed",
    }, "SIDECAR_DELIVERY_SCHEMA")
    require(type(source_sha) is str and _SHA.fullmatch(source_sha),
            "SIDECAR_SOURCE_SHA")
    require(type(run_id) is str and _RUN.fullmatch(run_id)
            and type(run_attempt) is str and _RUN.fullmatch(run_attempt),
            "SIDECAR_RUN_ID")
    require(type(document["schema_version"]) is int
            and document["schema_version"] == 2,
            "SIDECAR_SCHEMA_VERSION")
    require(document["source_sha"] == source_sha
            and document["run_id"] == run_id
            and document["run_attempt"] == run_attempt
            and document["workflow"] == "brain-cycle-v2"
            and document["execution_boundary"] == "READ_ONLY_PUBLIC_METADATA"
            and document["publication_verified"] is True
            and document["soak_completed"] is False,
            "SIDECAR_DELIVERY_NOT_COMPLETED_OR_SOURCE_CHANGED")
    for key in ("state_parent", "state_commit"):
        require(type(document[key]) is str and _SHA.fullmatch(document[key]),
                "SIDECAR_STATE_IDENTITY_INVALID")
    return document["state_commit"]


def prepare(original_delivery, source_sha, run_id, run_attempt, github_output):
    """Emit only the pinned state commit to the trusted Actions output file."""
    original = Path(original_delivery)
    require(original.is_file() and not original.is_symlink()
            and 0 < original.stat().st_size <= 8192,
            "SIDECAR_ORIGINAL_RECEIPT_UNAVAILABLE")
    data = json.loads(original.read_text(encoding="utf-8"))
    sha = validate_delivery(data, source_sha, run_id, run_attempt)
    target = Path(github_output)
    require(target.is_file() and not target.is_symlink(),
            "SIDECAR_UNTRUSTED_STEP_OUTPUT")
    st = target.stat()
    require(stat.S_ISREG(st.st_mode) and st.st_nlink == 1,
            "SIDECAR_UNTRUSTED_STEP_OUTPUT")
    try:
        handle = os.open(target, os.O_WRONLY | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(handle, "w", encoding="ascii") as file:
            file.write("state_sha=" + sha + "\n")
    except OSError as exc:
        raise BrainError("SIDECAR_STEP_OUTPUT_FAILED") from exc
    return sha


def _blocked(source_sha):
    return {
        "schema_version": 1, "scope": "OPTIONAL_READ_ONLY_V7_ADVISORY",
        "source_sha": source_sha if type(source_sha) is str and _SHA.fullmatch(source_sha) else None,
        "status": "BLOCKED_NO_VERIFIED_INVESTIGATION",
        "checked": 0, "eligible": 0, "deferred": 0, "requests_used": 0,
        "observed_outcomes": {}, "observed_followup_kinds": {},
        "observed_check_evidence_classes": {},
        "root_cause_verified": False, "execution_authority": False,
        "github_mutations": 0, "events_written": 0, "paid_calls": 0,
        "production_accepted": False, "authorization_granted": False,
    }


def summarize(report, source_sha, downloaded, proven, state, investigated):
    """All input data is untrusted; return a fixed-schema, public-safe summary."""
    result = _blocked(source_sha)
    if not all(x in _STAGE for x in (downloaded, proven, state, investigated)):
        return result
    if not isinstance(report, dict) or any(x != "success" for x in (downloaded, proven, state)):
        return result
    if (report.get("schema_version") != 1
            or type(report.get("schema_version")) is not int
            or report.get("scope") != "READ_ONLY_AUTONOMOUS_CHECK_REVALIDATION"
            or report.get("source_sha") != source_sha
            or report.get("status") not in _REPORT_STATUSES
            or report.get("execution_authority") is not False
            or report.get("root_cause_verified") is not False
            or type(report.get("github_mutations")) is not int
            or report["github_mutations"] != 0
            or type(report.get("events_written")) is not int
            or report["events_written"] != 0
            or type(report.get("paid_calls")) is not int
            or report["paid_calls"] != 0
            or type(report.get("state_sequence")) is not int
            or report["state_sequence"] < 0):
        return result
    entries = report.get("investigations")
    eligible = report.get("eligible_count")
    deferred = report.get("deferred_count")
    requests = report.get("requests_used")
    if (type(entries) is not list or len(entries) > 3
            or type(eligible) is not int or eligible < 0 or eligible > 4
            or type(deferred) is not int or deferred < 0
            or eligible != len(entries) + deferred
            or type(requests) is not int or requests < 0 or requests > 24):
        return result
    counts = {}
    kinds = {}
    check_classes = {}
    for entry in entries:
        if type(entry) is not dict or entry.get("outcome") not in _ROWS:
            return result
        kind = entry.get("follow_up_kind", "INITIAL_ADVERSE_TRANSITION")
        if type(kind) is not str or kind not in _FOLLOWUP_KINDS:
            return result
        kinds[kind] = kinds.get(kind, 0) + 1
        checks = entry.get("checks")
        if type(checks) is not list or len(checks) > 500:
            return result
        if entry["outcome"] == "UNVERIFIED_READ_FAILED" and checks:
            return result
        for item in checks:
            if type(item) is not dict or item.get("outcome") not in _OBSERVED:
                return result
            category = item["outcome"]
            counts[category] = counts.get(category, 0) + 1
            original = item.get("original_evidence_class", kind)
            if type(original) is not str or original not in _FOLLOWUP_KINDS:
                return _blocked(source_sha)
            check_classes[original] = check_classes.get(original, 0) + 1
    reported = report["status"]
    # A finished GET does not make a missing or still-pending check complete.
    # Surface unresolved evidence gaps as partial instead of a green summary.
    unresolved = (counts.get("UNVERIFIED_MISSING_OR_AMBIGUOUS_CHECK", 0)
                  + counts.get("CHECK_NOT_COMPLETED", 0))
    if investigated == "success" and reported in {
        "NO_ELIGIBLE_FAILURES", "READ_ONLY_REVALIDATION_COMPLETE"
    } and not deferred and not unresolved and all(
        x.get("outcome") != "UNVERIFIED_READ_FAILED" for x in entries
    ):
        final = "OBSERVED_READ_ONLY"
    elif reported in _REPORT_STATUSES:
        final = "PARTIAL_READ_ONLY"
    else:
        return result
    result.update(
        status=final, checked=len(entries), eligible=eligible, deferred=deferred,
        requests_used=requests, observed_outcomes=dict(sorted(counts.items())),
        observed_followup_kinds=dict(sorted(kinds.items())),
        observed_check_evidence_classes=dict(sorted(check_classes.items())),
    )
    return result


def finalize(receipt_path, output_path, source_sha, downloaded, proven, state, investigated):
    """Emit one safe result even if original investigation ended incomplete."""
    source = None
    original = Path(receipt_path)
    try:
        if (original.is_file() and not original.is_symlink()
                and 0 < original.stat().st_size <= 250000):
            source = json.loads(original.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        source = None
    result = summarize(source, source_sha, downloaded, proven, state, investigated)
    out = Path(output_path)
    require(out.name == "sidecar-status.json", "SIDECAR_OUTPUT_NAME_INVALID")
    require(not out.is_symlink(), "SIDECAR_OUTPUT_SYMLINK_INVALID")
    out.parent.mkdir(parents=True, exist_ok=True)
    require(not out.parent.is_symlink(), "SIDECAR_OUTPUT_PARENT_SYMLINK")
    if out.exists():
        st = out.stat()
        require(stat.S_ISREG(st.st_mode) and st.st_nlink == 1,
                "SIDECAR_OUTPUT_INODE_INVALID")
    temp = out.parent / (".sidecar-" + secrets.token_hex(10))
    try:
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(result, file, sort_keys=True, indent=2)
            file.write("\n")
        os.replace(temp, out)
    finally:
        if temp.exists():
            temp.unlink()
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    pin = commands.add_parser("prepare")
    pin.add_argument("--delivery", required=True)
    pin.add_argument("--source-sha", required=True)
    pin.add_argument("--run-id", required=True)
    pin.add_argument("--run-attempt", required=True)
    pin.add_argument("--github-output", required=True)
    finish = commands.add_parser("finalize")
    finish.add_argument("--receipt", required=True)
    finish.add_argument("--output", required=True)
    finish.add_argument("--source-sha", required=True)
    for stage in ("downloaded", "proven", "state", "investigated"):
        finish.add_argument("--" + stage, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            prepare(args.delivery, args.source_sha, args.run_id, args.run_attempt,
                    args.github_output)
            print("SIDECAR_SOURCE_BOUND")
        else:
            result = finalize(args.receipt, args.output, args.source_sha,
                              args.downloaded, args.proven, args.state, args.investigated)
            print(json.dumps({"status": result["status"], "checked": result["checked"]}))
        return 0
    except (ValueError, OSError, UnicodeError) as exc:
        print("SIDECAR_FAIL_CLOSED:" + type(exc).__name__, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
