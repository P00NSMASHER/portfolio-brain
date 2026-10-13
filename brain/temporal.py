"""Bounded historical check patterns from an independently replayed ledger.

Pure projection; observations never prove incident root cause, real-time
downtime, flaky tests, source rights, or any repair authorization.
Called ONLY after original ledger/report replay by brain.continuation.
"""
from __future__ import annotations

from .core import require, timestamp

_MAX_TERMINAL_SAMPLES = 12
_ADVERSE = frozenset({"failure", "timed_out", "action_required", "stale",
                      "startup_failure"})
_TERMINAL = _ADVERSE | {"success"}
_SCOPE = "RECENT_TERMINAL_OBSERVATIONS_NOT_REALTIME_OUTAGE"


def _one_check(checks, name, sha):
    """Ambiguous/missing/pending checks break continuity: never skip gaps."""
    require(type(checks) is list and len(checks) <= 500,
            "TEMPORAL_CHECK_COVERAGE_INVALID")
    matches = [c for c in checks if type(c) is dict and c.get("name") == name]
    if len(matches) != 1:
        return None
    item = matches[0]
    if (item.get("head_sha") != sha
            or item.get("status") != "completed"
            or item.get("conclusion") not in _TERMINAL):
        return None
    return "SUCCESS" if item["conclusion"] == "success" else "ADVERSE"


def _recent_samples(history, repository, *, latest_at):
    """Deduplicate semantic times: upstream original replay rejects conflict."""
    values = {}
    latest = timestamp(latest_at)
    for record in history:
        if record["kind"] != "repository" or record["key"] != repository:
            continue
        at = timestamp(record["observed_at"])
        if at > latest:
            continue
        previous = values.get(at)
        if previous is None:
            values[at] = record
        else:
            require(previous["payload"] == record["payload"]
                    and previous["data_kind"] == record["data_kind"]
                    and previous["visibility"] == record["visibility"],
                    "TEMPORAL_AMBIGUOUS_SAME_TIME_SOURCE")
    return sorted(values.items(), reverse=True)


def _pattern(samples, name, *, revision, repository, latest_at, now, max_age):
    require(type(name) is str and 0 < len(name) <= 200,
            "TEMPORAL_CHECK_NAME_INVALID")
    now_at = timestamp(now)
    latest = timestamp(latest_at)
    require(latest <= now_at, "TEMPORAL_FUTURE_OBSERVATION")
    cutoff = now_at.timestamp() - max_age
    series = []
    expected_ref = f"https://github.com/{repository}/commit/{revision}"
    for at, sample in samples:
        if at.timestamp() < cutoff or at > latest:
            break
        data = sample["payload"]
        if (sample["visibility"] != "PUBLIC"
                or sample["data_kind"] != "ACTUAL"
                or data["head_sha"] != revision
                or data["source_ref"] != expected_ref):
            break
        conclusion = _one_check(data["checks"], name, revision)
        if conclusion is None:
            break
        series.append((conclusion, sample["observed_at"]))
        if len(series) > _MAX_TERMINAL_SAMPLES:
            break

    capped = len(series) > _MAX_TERMINAL_SAMPLES
    series = series[:_MAX_TERMINAL_SAMPLES]
    adverse = 0
    for state, _ in series:
        if state != "ADVERSE":
            break
        adverse += 1
    flips = sum(series[i][0] != series[i+1][0]
                for i in range(len(series) - 1))
    return {
        "scope": _SCOPE,
        "terminal_samples": len(series),
        "adverse_streak_samples": adverse,
        "adverse_streak_first_observed_at": (
            series[adverse-1][1] if adverse else None
        ),
        "latest_terminal_observed_at": series[0][1] if series else None,
        "adverse_success_flips_observed": flips,
        "capped_at_12_samples": capped,
    }


def annotate_verified_plans(history, plans, *, now, max_age):
    """Add bounded private original-ledger patterns without additional GETs.

    Source history is the unmodified Store._verified_events() stream, after
    the full replay is checked against the report by brain.continuation.
    """
    require(type(history) is list and len(history) <= 100000,
            "TEMPORAL_HISTORY_BOUND")
    require(type(plans) is list and len(plans) <= 4,
            "TEMPORAL_PLAN_BOUND")
    require(type(max_age) is int and 0 < max_age <= 172800,
            "TEMPORAL_FRESHNESS_BOUND")
    result = []
    for plan in plans:
        require(type(plan) is dict, "TEMPORAL_PLAN_OBJECT_REQUIRED")
        repository = plan["repository"]
        revision = plan["expected_revision"]
        names = plan["check_names"]
        require(type(names) is list and len(names) <= 500
                and all(type(item) is str for item in names)
                and len(names) == len(set(names)),
                "TEMPORAL_SELECTED_CHECK_NAMES_INVALID")
        samples = _recent_samples(history, repository,
                                  latest_at=plan["original_observed_at"])
        require(samples and samples[0][1]["observed_at"]
                == plan["original_observed_at"],
                "TEMPORAL_LATEST_ORIGINAL_SNAPSHOT_MISSING")
        pattern = {
            check_name: _pattern(
                samples, check_name, revision=revision, repository=repository,
                latest_at=plan["original_observed_at"], now=now, max_age=max_age,
            )
            for check_name in names
        }
        result.append({**plan, "historical_check_patterns": pattern})
    return result
