"""Read-only, source-specific CI comparison coverage advisory.

This is not a CI health grade, outage detector, incident fix, or acceptance
gate. Absence of eligible rechecks may reflect missing, stale, ambiguous or
unobserved original evidence. Uses only the existing canonical report and
policy repository allowlist; no provider reads, durable state or new tasks.
"""
from __future__ import annotations

from .core import BrainError, require, timestamp

_SCOPE = "ORIGINAL_COMPARISON_COVERAGE_NOT_HEALTH_CERTIFICATION"
_FIXED_CLASSES = frozenset({
    "COMPARABLE_FRESH",
    "DUPLICATE_NAME_QUARANTINE",
    "NO_SHARED_CHECK_NAMES",
    "REVISION_CHANGED",
    "STALE_SOURCE_EVIDENCE",
    "NON_ACTUAL_SOURCE",
    "UNVERIFIED_OTHER_COMPARISON",
})


def original_coverage(report, *, now, limits):
    """Count exactly four-or-fewer original allowlisted comparison categories.

    This projection deliberately excludes unapproved repositories and any
    unverified source-code discovery. Missing original comparison pairs are
    explicitly counted as unassessed, never reported as healthy.
    """
    approved = limits["repositories"]
    require(type(approved) is list and 1 <= len(approved) <= 4
            and len(approved) == len(set(approved))
            and all(type(repo) is str for repo in approved),
            "COVERAGE_POLICY_REPOSITORIES_INVALID")
    require(type(limits.get("max_source_age_seconds")) is int
            and 1 <= limits["max_source_age_seconds"] <= 172800,
            "COVERAGE_POLICY_FRESHNESS_INVALID")
    require(type(report) is dict
            and type(report.get("repository_changes")) is list,
            "COVERAGE_CANONICAL_CHANGES_REQUIRED")
    actual_now = timestamp(now)
    compared = {}
    classes = {}
    for row in report["repository_changes"]:
        require(type(row) is dict, "COVERAGE_COMPARISON_OBJECT_INVALID")
        repo = row.get("repository")
        if repo not in approved:
            continue
        require(repo not in compared, "COVERAGE_DUPLICATED_APPROVED_REPOSITORY")
        quality = row.get("evidence_quality")
        match = row.get("check_comparison")
        revision_changed = row.get("revision_changed")
        if quality == "NON_ACTUAL":
            label = "NON_ACTUAL_SOURCE"
        elif quality in {"HISTORICAL", "ACTUAL_STALE_BASELINE"}:
            label = "STALE_SOURCE_EVIDENCE"
        elif quality != "ACTUAL_FRESH":
            label = "UNVERIFIED_OTHER_COMPARISON"
        else:
            try:
                old = timestamp(row["previous_observed_at"])
                new = timestamp(row["current_observed_at"])
                fresh = (old <= new <= actual_now
                         and 0 <= (actual_now - old).total_seconds()
                         <= limits["max_source_age_seconds"])
            except (BrainError, ValueError, TypeError, KeyError):
                fresh = False
            if not fresh:
                label = "STALE_SOURCE_EVIDENCE"
            elif revision_changed is True:
                label = "REVISION_CHANGED"
            elif revision_changed is not False:
                label = "UNVERIFIED_OTHER_COMPARISON"
            elif match == "COMPARABLE":
                label = "COMPARABLE_FRESH"
            elif match == "PARTIAL_AMBIGUOUS_CHECK_NAMES":
                label = "DUPLICATE_NAME_QUARANTINE"
            elif match == "NO_SHARED_CHECK_NAMES":
                label = "NO_SHARED_CHECK_NAMES"
            else:
                label = "UNVERIFIED_OTHER_COMPARISON"
        compared[repo] = label
        classes[label] = classes.get(label, 0) + 1
    unassessed = len(approved) - len(compared)
    limited = (unassessed > 0
               or classes.get("COMPARABLE_FRESH", 0) != len(compared))
    return {
        "scope": _SCOPE,
        "approved_repositories": len(approved),
        "compared_repositories": len(compared),
        "unassessed_repositories": unassessed,
        "comparison_classes": dict(sorted(classes.items())),
        "limitations_present": limited,
        "healthy_ci_verified": False,
        "root_cause_verified": False,
        "execution_authority": False,
        "provider_reads_added": 0,
    }


def validate_coverage(value):
    """Allowlist public-safe fixed categories; fail closed on forged counts."""
    if type(value) is not dict or set(value) != {
        "scope", "approved_repositories", "compared_repositories",
        "unassessed_repositories", "comparison_classes",
        "limitations_present", "healthy_ci_verified",
        "root_cause_verified", "execution_authority", "provider_reads_added",
    }:
        return False
    n = value["approved_repositories"]
    compared = value["compared_repositories"]
    unassessed = value["unassessed_repositories"]
    labels = value["comparison_classes"]
    if (value["scope"] != _SCOPE
            or type(n) is not int or not 1 <= n <= 4
            or type(compared) is not int or not 0 <= compared <= n
            or type(unassessed) is not int or unassessed != n - compared
            or type(labels) is not dict
            or any(type(label) is not str or label not in _FIXED_CLASSES
                   or type(count) is not int or not 1 <= count <= n
                   for label, count in labels.items())
            or sum(labels.values()) != compared
            or type(value["limitations_present"]) is not bool
            or value["limitations_present"] is not (
                unassessed > 0 or labels.get("COMPARABLE_FRESH", 0) != compared
            )
            or value["healthy_ci_verified"] is not False
            or value["root_cause_verified"] is not False
            or value["execution_authority"] is not False
            or type(value["provider_reads_added"]) is not int
            or value["provider_reads_added"] != 0):
        return False
    return True
