"""One-shot, opt-in V7 sidecar provenance and sanitized evidence publication.

This code verifies original same-run delivery metadata and publishes an
advisory summary only. It does not authorize further actions or make calls.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import stat
import sys
from pathlib import Path

from .core import BrainError, require, timestamp

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
    "UNBASELINED_ADVERSE_OBSERVED",
    "EVIDENCE_GAP_REVALIDATION",
    "PERSISTENT_ADVERSE_OBSERVED",
    "RECOVERY_OBSERVED_NOT_RESOLUTION",
})
_TEMPORAL_SCOPE = "RECENT_TERMINAL_OBSERVATIONS_NOT_REALTIME_OUTAGE"
_TEMPORAL_FIELDS = frozenset({
    "scope", "terminal_samples", "adverse_streak_samples",
    "adverse_streak_first_observed_at", "latest_terminal_observed_at",
    "adverse_success_flips_observed", "capped_at_12_samples",
})


def _valid_temporal_facts(value, checked_at):
    """Never publish fabricated age/confidence values from an untrusted receipt."""
    if type(value) is not dict or set(value) != _TEMPORAL_FIELDS:
        return False
    if value["scope"] != _TEMPORAL_SCOPE:
        return False
    n = value["terminal_samples"]
    streak = value["adverse_streak_samples"]
    changes = value["adverse_success_flips_observed"]
    capped = value["capped_at_12_samples"]
    if (type(n) is not int or not 0 <= n <= 12
            or type(streak) is not int or not 0 <= streak <= n
            or type(changes) is not int or not 0 <= changes <= max(n-1, 0)
            or type(capped) is not bool or (capped and n != 12)):
        return False
    first = value["adverse_streak_first_observed_at"]
    last = value["latest_terminal_observed_at"]
    if (streak == 0 and first is not None) or (n == 0 and last is not None):
        return False
    if (streak > 0 and type(first) is not str) or (n > 0 and type(last) is not str):
        return False
    try:
        observed_at = timestamp(checked_at)
        if last is not None and timestamp(last) > observed_at:
            return False
        if first is not None and (timestamp(first) > timestamp(last)
                                  or timestamp(first) > observed_at):
            return False
    except (BrainError, ValueError, TypeError):
        return False
    return True


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
        "original_delivery_verified": False,
        "original_core_run_id": None,
        "original_core_run_attempt": None,
        "published_state_sha": None,
        "original_delivery_sha256": None,
        "checked": 0, "eligible": 0, "deferred": 0, "requests_used": 0,
        "observed_outcomes": {}, "observed_followup_kinds": {},
        "comparison_coverage_counts": {},
        "unassessed_approved_repositories": None,
        "comparison_coverage_limited": None,
        "observed_check_evidence_classes": {},
        "repository_local_provider_failures": 0,
        "provider_failure_hard_stops": 0,
        "partial_check_coverage_repositories": 0,
        "historical_adverse_streak_bands": {},
        "historical_repeated_terminal_movements": 0,
        "historical_sample_caps": 0,
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
    coverage = None
    if "original_comparison_coverage" in report:
        from .coverage import validate_coverage
        coverage = report["original_comparison_coverage"]
        if not validate_coverage(coverage):
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
    # Reconcile status, counts and work-limit semantics before displaying
    # a result. An apparently green receipt with conflicting completion
    # metadata is unverified rather than an autonomous success.
    status = report["status"]
    if ((status == "NO_ELIGIBLE_FAILURES"
         and (eligible != 0 or entries or deferred != 0 or requests != 0))
        or (status == "READ_ONLY_REVALIDATION_COMPLETE"
            and (not entries or deferred != 0))
        or (status == "BOUNDED_READ_ONLY_REVALIDATION_COMPLETE_WITH_DEFERRED"
            and deferred == 0)
        or (status in {"REQUEST_BUDGET_DEFERRED", "STOPPED"} and deferred == 0)
        or (status == "INCOMPLETE_READ_ONLY_REVALIDATION"
            and not any(type(item) is dict
                        and item.get("outcome") == "UNVERIFIED_READ_FAILED"
                        for item in entries))
        or (type(report.get("max_investigations", 3)) is not int)
        or not 1 <= report.get("max_investigations", 3) <= 3
        or len(entries) > report.get("max_investigations", 3)):
        return result
    counts = {}
    kinds = {}
    check_classes = {}
    repository_local_failures = 0
    provider_hard_stops = 0
    partially_comparable = 0
    streak_bands = {}
    repeated_movements = 0
    sample_caps = 0
    for index, entry in enumerate(entries):
        if type(entry) is not dict or entry.get("outcome") not in _ROWS:
            return result
        failed = entry["outcome"] == "UNVERIFIED_READ_FAILED"
        if "provider_failure_scope" in entry:
            scope = entry["provider_failure_scope"]
            if not failed or type(scope) is not str:
                return result
            if scope == "REPOSITORY_LOCAL_EVIDENCE_UNAVAILABLE":
                repository_local_failures += 1
            elif scope == "GLOBAL_OR_UNCLASSIFIED_STOP":
                if index != len(entries) - 1:
                    # The global circuit breaker must have stopped work.
                    return result
                provider_hard_stops += 1
            else:
                return result
        if failed and report["status"] in {
            "NO_ELIGIBLE_FAILURES", "READ_ONLY_REVALIDATION_COMPLETE",
            "BOUNDED_READ_ONLY_REVALIDATION_COMPLETE_WITH_DEFERRED",
        }:
            return result
        kind = entry.get("follow_up_kind", "INITIAL_ADVERSE_TRANSITION")
        if type(kind) is not str or kind not in _FOLLOWUP_KINDS:
            return result
        kinds[kind] = kinds.get(kind, 0) + 1
        quarantined = entry.get("partial_check_coverage", False)
        if type(quarantined) is not bool:
            return result
        partially_comparable += int(quarantined)
        checks = entry.get("checks")
        if type(checks) is not list or len(checks) > 500:
            return result
        if entry["outcome"] != "OBSERVED_CHECK_STATUS_NOT_ROOT_CAUSE" and checks:
            return result
        original_names = entry.get("check_names")
        if original_names is not None:
            if (type(original_names) is not list
                    or any(type(name) is not str or not name
                           for name in original_names)):
                return result
            if len(original_names) != len(set(original_names)):
                return result
            if entry["outcome"] == "OBSERVED_CHECK_STATUS_NOT_ROOT_CAUSE":
                if any(type(item) is not dict
                       or type(item.get("name")) is not str for item in checks):
                    return result
                if (len(original_names) != len(checks)
                        or set(original_names) != {item["name"] for item in checks}):
                    return result
        history = entry.get("historical_check_patterns")
        if history is not None:
            if (type(history) is not dict or original_names is None
                    or set(history) != set(original_names)):
                return result
            if any(not _valid_temporal_facts(value, report.get("checked_at"))
                   for value in history.values()):
                return result
        expected_classes = entry.get("check_evidence_classes")
        if expected_classes is not None:
            if (type(expected_classes) is not dict
                    or original_names is None
                    or set(expected_classes) != set(original_names)
                    or any(type(key) is not str or type(value) is not str
                           or value not in _FOLLOWUP_KINDS
                           for key, value in expected_classes.items())):
                return result
        for item in checks:
            if type(item) is not dict or item.get("outcome") not in _OBSERVED:
                return result
            category = item["outcome"]
            original = item.get("original_evidence_class", kind)
            if type(original) is not str or original not in _FOLLOWUP_KINDS:
                return result
            if expected_classes is not None:
                if original != expected_classes.get(item.get("name")):
                    return result
            elif original != kind:
                return result
            pattern = item.get("historical_observations")
            if history is None:
                if pattern is not None:
                    return result
            else:
                if type(item.get("name")) is not str:
                    return result
                if pattern != history.get(item["name"]):
                    return result
                samples = pattern["adverse_streak_samples"]
                band = ("NONE" if samples == 0 else "SINGLE" if samples == 1
                        else "TWO" if samples == 2 else "THREE_OR_MORE")
                streak_bands[band] = streak_bands.get(band, 0) + 1
                repeated_movements += pattern["adverse_success_flips_observed"] >= 2
                sample_caps += pattern["capped_at_12_samples"]
            counts[category] = counts.get(category, 0) + 1
            check_classes[original] = check_classes.get(original, 0) + 1
    reported = report["status"]
    # A finished GET does not make a missing or still-pending check complete.
    # Surface unresolved evidence gaps as partial instead of a green summary.
    unresolved = (partially_comparable
                  + counts.get("UNVERIFIED_MISSING_OR_AMBIGUOUS_CHECK", 0)
                  # No historical baseline exists for a new adverse check.
                  # Provider revalidation cannot retroactively create one.
                  + check_classes.get("UNBASELINED_ADVERSE_OBSERVED", 0)
                  + counts.get("CHECK_NOT_COMPLETED", 0)
                  + counts.get("OTHER_CONCLUSION_NOT_RESOLUTION", 0)
                  + sum(row.get("outcome") == "SOURCE_CHANGED_REQUIRES_NEW_COMPARISON"
                        for row in entries))
    if investigated == "success" and reported in {
        "NO_ELIGIBLE_FAILURES", "READ_ONLY_REVALIDATION_COMPLETE"
    } and not deferred and not unresolved and not (
        coverage is not None and coverage["limitations_present"]
    ) and all(
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
        comparison_coverage_counts=(dict(sorted(
            coverage["comparison_classes"].items()
        )) if coverage is not None else {}),
        unassessed_approved_repositories=(
            coverage["unassessed_repositories"] if coverage is not None else None
        ),
        comparison_coverage_limited=(
            coverage["limitations_present"] if coverage is not None else None
        ),
        observed_check_evidence_classes=dict(sorted(check_classes.items())),
        repository_local_provider_failures=repository_local_failures,
        provider_failure_hard_stops=provider_hard_stops,
        partial_check_coverage_repositories=partially_comparable,
        historical_adverse_streak_bands=dict(sorted(streak_bands.items())),
        historical_repeated_terminal_movements=int(repeated_movements),
        historical_sample_caps=int(sample_caps),
    )
    return result


def _original_delivery_binding(original_delivery, source_sha, run_id,
                               run_attempt, published_state_sha):
    """Reverify the immutable core publication at public advisory finalization.

    Never use the original manifest as a state writer or a source of
    instructions; it merely certifies the exact original run + state revision.
    """
    source = Path(original_delivery)
    require(source.is_file() and not source.is_symlink(),
            "SIDECAR_FINAL_DELIVERY_UNAVAILABLE")
    st = source.stat()
    require(stat.S_ISREG(st.st_mode) and st.st_nlink == 1
            and 0 < st.st_size <= 8192,
            "SIDECAR_FINAL_DELIVERY_INODE_INVALID")
    raw = source.read_bytes()
    require(len(raw) == st.st_size and 0 < len(raw) <= 8192,
            "SIDECAR_FINAL_DELIVERY_UNSTABLE")
    parsed = json.loads(raw.decode("utf-8"))
    actual_state = validate_delivery(parsed, source_sha, run_id, run_attempt)
    require(type(published_state_sha) is str and
            _SHA.fullmatch(published_state_sha) and
            published_state_sha == actual_state,
            "SIDECAR_FINAL_PUBLISHED_STATE_MISMATCH")
    return {
        "original_delivery_verified": True,
        "original_core_run_id": run_id,
        "original_core_run_attempt": run_attempt,
        "published_state_sha": actual_state,
        "original_delivery_sha256": hashlib.sha256(raw).hexdigest(),
    }


def finalize(receipt_path, output_path, source_sha, downloaded, proven, state,
             investigated, *, original_delivery=None, original_run_id=None,
             original_run_attempt=None, published_state_sha=None):
    """Emit a safe result, bound to an original core run when requested."""
    source = None
    original = Path(receipt_path)
    try:
        if (original.is_file() and not original.is_symlink()
                and 0 < original.stat().st_size <= 250000):
            source = json.loads(original.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        source = None
    result = summarize(source, source_sha, downloaded, proven, state, investigated)
    originals = (original_delivery, original_run_id, original_run_attempt,
                 published_state_sha)
    if any(item is not None for item in originals):
        # The production path always requests all four fields. A missing,
        # mismatched or altered manifest MUST produce a blocked advisory, not
        # an unbound green status, and still leave a sanitized artifact.
        if any(type(item) is not str or not item for item in originals):
            result = _blocked(source_sha)
        else:
            try:
                result.update(_original_delivery_binding(*(
                    original_delivery, source_sha, original_run_id,
                    original_run_attempt, published_state_sha)))
            except (BrainError, ValueError, OSError, UnicodeError, TypeError):
                result = _blocked(source_sha)
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
    finish.add_argument("--original-delivery")
    finish.add_argument("--original-run-id")
    finish.add_argument("--original-run-attempt")
    finish.add_argument("--published-state-sha")
    for stage in ("downloaded", "proven", "state", "investigated"):
        finish.add_argument("--" + stage, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            prepare(args.delivery, args.source_sha, args.run_id, args.run_attempt,
                    args.github_output)
            print("SIDECAR_SOURCE_BOUND")
        else:
            result = finalize(
                args.receipt, args.output, args.source_sha,
                args.downloaded, args.proven, args.state, args.investigated,
                original_delivery=args.original_delivery,
                original_run_id=args.original_run_id,
                original_run_attempt=args.original_run_attempt,
                published_state_sha=args.published_state_sha,
            )
            print(json.dumps({"status": result["status"], "checked": result["checked"]}))
        return 0
    except (ValueError, OSError, UnicodeError) as exc:
        print("SIDECAR_FAIL_CLOSED:" + type(exc).__name__, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
