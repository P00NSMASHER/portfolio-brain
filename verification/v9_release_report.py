"""Deterministic, offline release-evidence digest. NEVER an acceptance authority.

Consumes original source-pinned GitHub reviewer evidence; does not fetch a
provider, authenticate Cloudflare, issue source acceptance, or merge anything.
Untrusted JSON cannot assert release. All output keeps release_authorized false.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

SHA = re.compile(r"[0-9a-f]{40}\Z")
HEX256 = re.compile(r"[0-9a-f]{64}\Z")
MINIMUM_SECONDS = 21600
MAX_GAP_SECONDS = 5400
MAX_CORES = 80
MAX_DOCUMENT = 1024 * 1024


class EvidenceError(ValueError):
    pass


def require(allowed, reason):
    if not allowed:
        raise EvidenceError(reason)


def _sha(value):
    return type(value) is str and SHA.fullmatch(value) is not None


def _hex(value):
    return type(value) is str and HEX256.fullmatch(value) is not None


def _int(value, lower=0):
    return type(value) is int and value >= lower


def _strict_pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def read_json(path):
    source = Path(path)
    require(source.is_file() and source.stat().st_size <= MAX_DOCUMENT,
            "SOURCE_ARTIFACT_MISSING_OR_OVERSIZED")
    try:
        return json.loads(source.read_bytes(), object_pairs_hook=_strict_pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, UnicodeError) as exc:
        raise EvidenceError("MALFORMED_JSON") from exc


def fingerprint(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=True, allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def compile_report(census, replay=None, *, source_sha):
    """Classify technical evidence, always require external provider + governance.

    This digest is read-only and does NOT elevate caller-provided JSON into
    authenticated originals. Only the independent reviewer may verify original
    run/artifact ancestry; Cloudflare originals require separate provider access.
    """
    require(_sha(source_sha), "TARGET_SOURCE_SHA_INVALID")
    require(type(census) is dict and census.get("production_source") == source_sha,
            "CENSUS_SOURCE_MISMATCH")
    require(census.get("acceptance_pass") is False
            and census.get("release_or_merge_authorized") is False
            and census.get("external_cloudflare_provider_accepted") is False,
            "TECHNICAL_REPORT_MUST_NOT_SELF_APPROVE")
    status = census.get("status")
    require(status in ("WINDOW_RUNNING_NOT_ACCEPTED",
                       "SIX_HOUR_ORIGINAL_GITHUB_EVIDENCE_VERIFIED"),
            "CENSUS_STATUS_UNTRUSTED")
    count = census.get("verified_original_cores")
    span = census.get("completion_span_seconds")
    gap = census.get("maximum_gap_seconds")
    require(_int(count, 1) and count <= MAX_CORES
            and _int(span) and _int(gap) and gap <= MAX_GAP_SECONDS
            and (count > 1 or (span == 0 and gap == 0)),
            "CORE_COUNTS_OR_GAPS_INVALID")
    require((span < MINIMUM_SECONDS) == (status == "WINDOW_RUNNING_NOT_ACCEPTED"),
            "WINDOW_STATUS_CONTRADICTION")
    if status == "WINDOW_RUNNING_NOT_ACCEPTED":
        require(census.get("seconds_remaining_minimum") == MINIMUM_SECONDS-span,
                "REMAINING_WINDOW_INCONSISTENT")
    require(_int(census.get("anchor_run"), 1)
            and _int(census.get("latest_run"), 1)
            and _int(census.get("last_sequence"), 1)
            and _sha(census.get("last_state_commit"))
            and _hex(census.get("last_raw_sha256"))
            and _hex(census.get("last_canonical_hash")),
            "STATE_OR_RUN_PROVENANCE_INCOMPLETE")
    require(type(census.get("historical_adverse_automatic_cores")) is list
            and type(census.get("superseded_earlier_successful_cores")) is int,
            "ADVERSE_OR_SUPERSEDED_CENSUS_INCOMPLETE")
    require(type(census.get("anchor_completion_utc")) is str
            and type(census.get("latest_completion_utc")) is str,
            "ORIGINAL_COMPLETION_TIMES_MISSING")

    state_replay_pass = False
    replay_kind = "NOT_SUPPLIED"
    if replay is not None:
        require(type(replay) is dict, "REPLAY_NOT_OBJECT")
        require(replay.get("source_released") is False
                and replay.get("merge_authorized") is False
                and replay.get("external_provider_complete") is False,
                "REPLAY_CANNOT_CLAIM_EXTERNAL_APPROVAL")
        require(replay.get("reviewed_source") == source_sha
                and replay.get("state_commit") == census["last_state_commit"]
                and replay.get("sequence") == census["last_sequence"]
                and _hex(replay.get("raw_sqlite_sha256"))
                and replay.get("pending_events") == 0,
                "REPLAY_STATE_DISAGREES_WITH_CENSUS")
        replay_kind = replay.get("status")
        require(replay_kind == "PRELIMINARY_RAW_SQLITE_REPLAY_PASSED_NOT_ACCEPTANCE",
                "UNEXPECTED_PRELIMINARY_REPLAY_STATUS")
        state_replay_pass = True

    terminal = census.get("terminal_replay")
    if status == "SIX_HOUR_ORIGINAL_GITHUB_EVIDENCE_VERIFIED":
        require(type(terminal) is dict
                and terminal.get("status") == "ORIGINAL_TERMINAL_RAW_SQLITE_REPLAY_VERIFIED"
                and terminal.get("terminal_source_sha") == source_sha
                and terminal.get("terminal_state_commit") == census["last_state_commit"]
                and terminal.get("sequence") == census["last_sequence"]
                and terminal.get("pending_events") == 0
                and _hex(terminal.get("restored_sqlite_sha256"))
                and terminal.get("authorizes_production_release") is False,
                "AUTHENTIC_TERMINAL_REPLAY_STILL_REQUIRED")
        state_replay_pass = True
        replay_kind = terminal["status"]

    ready_for_separate_provider_review = (
        status == "SIX_HOUR_ORIGINAL_GITHUB_EVIDENCE_VERIFIED"
        and state_replay_pass
    )
    return {
        "schema_version": 1,
        "kind": "REVIEW_ONLY_UNAUTHENTICATED_SUMMARY_OF_SOURCE_PINNED_EVIDENCE",
        "source_sha": source_sha,
        "technical_window": status,
        "first_original_run": census["anchor_run"],
        "latest_original_run": census["latest_run"],
        "original_automatic_core_count": count,
        "completed_span_seconds": span,
        "maximum_gap_seconds": gap,
        "seconds_remaining_minimum": max(0, MINIMUM_SECONDS-span),
        "last_state_commit": census["last_state_commit"],
        "last_sequence": census["last_sequence"],
        "state_replay_result": replay_kind,
        "original_replay_report_consistent": state_replay_pass,
        "retained_adverse_automatic_cores": len(census["historical_adverse_automatic_cores"]),
        "census_sha256": fingerprint(census),
        "replay_sha256": fingerprint(replay) if replay is not None else None,
        "review_queue": (
            ["INDEPENDENT_CLOUDFLARE_ORIGINAL_PROVIDER_CORRELATION",
             "SEPARATE_GOVERNED_SOURCE_SPECIFIC_RELEASE_DECISION",
             "FRESH_EXACT_HEAD_PROTECTION_CHECKS_FOR_EACH_RELEASE"]
            if ready_for_separate_provider_review else
            ["COMPLETE_SIX_HOURS_OF_ORIGINAL_SUCCESSFUL_AUTOMATIC_CORES",
             "INDEPENDENT_FINAL_RAW_SQLITE_LEDGER_REPORT_REPLAY",
             "INDEPENDENT_CLOUDFLARE_ORIGINAL_PROVIDER_CORRELATION",
             "SEPARATE_GOVERNED_SOURCE_SPECIFIC_RELEASE_DECISION"]
        ),
        "external_provider_authenticated_by_this_module": False,
        "owner_governance_approved_by_this_module": False,
        "production_accepted": False,
        "merge_authorized": False,
        "auto_merge_enrollment_authorized": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--census", type=Path, required=True)
    parser.add_argument("--replay", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    report = compile_report(read_json(args.census),
                            read_json(args.replay) if args.replay else None,
                            source_sha=args.source)
    args.output.write_text(json.dumps(report, sort_keys=True, indent=2)+"\n")
    print(json.dumps({"source": args.source,
                      "technical_window": report["technical_window"],
                      "production_accepted": False,
                      "merge_authorized": False}, sort_keys=True))


if __name__ == "__main__":
    main()
