"""Current-source six-hour evidence window: review-only, never terminal PASS."""
from dataclasses import asdict
from soak_v3.audit import (EvidenceError, evaluate_window, require,
                           sha40)

SIX_HOURS = 21600
NINETY_MINUTES = 5400


def inspect_current_window(records, *, source_sha, current_main,
                           first_state_parent, started_at, deadline_at,
                           now, original_run_inventory_complete=False):
    """Inspect collected ORIGINAL run records without asserting their provenance.

    The caller must separately authenticate GitHub run/job/artifact and signed
    Cloudflare provider events. A clear window is only PRE_POSTVALIDATION:
    complete ZIPs, Git state and terminal SQLite replay remain mandatory.
    """
    sha40(source_sha)
    sha40(current_main)
    sha40(first_state_parent)
    require(type(original_run_inventory_complete) is bool,
            "ORIGINAL_PROVIDER_CENSUS_FLAG_INVALID")
    if not original_run_inventory_complete:
        return {
            "status": "BLOCKED",
            "reason": "ORIGINAL_PROVIDER_INVENTORY_NOT_COMPLETE",
            "six_hour_soak_accepted": False,
        }
    require(type(records) is list, "ORIGINAL_RUN_RECORDS_INVALID")
    if any(type(row) is not dict for row in records):
        raise EvidenceError("ORIGINAL_RUN_RECORD_INVALID")
    # A retried GitHub Actions run can conceal a prior FAILED attempt in a
    # latest-only run listing. Do not count it without a separate full attempt
    # inventory. This conservative audit does not silently promote retries.
    if any(type(row.get("attempt")) is not int or row["attempt"] != 1
           for row in records):
        return {
            "status": "BLOCKED",
            "reason": "UNVERIFIED_RUN_ATTEMPT_CENSUS",
            "six_hour_soak_accepted": False,
        }
    result = evaluate_window(
        records,
        source_sha=source_sha, current_main=current_main,
        first_state_parent=first_state_parent,
        started_at=started_at, deadline_at=deadline_at, now=now,
        minimum_span_seconds=SIX_HOURS,
    )
    evidence = asdict(result)
    evidence.update(
        source_sha=source_sha,
        evaluated_minimum_span_seconds=SIX_HOURS,
        maximum_automatic_completion_gap_seconds=NINETY_MINUTES,
        interpretation="PURE_EVIDENCE_WINDOW_ONLY_NOT_INDEPENDENT_PROVIDER_PROOF",
        original_run_inventory_claim_only=True,
        terminal_binary_replay_verified=False,
        independent_provider_origin_verified=False,
        six_hour_soak_accepted=False,
    )
    return evidence
