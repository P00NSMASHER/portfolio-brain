"""Evidence-only repository changes derived from canonical observations.

No remote reads, external actions, confidence scores or inferred business value.
Only the latest two *semantic observation times* are compared per repository.
"""
from collections import defaultdict

from brain.core import require, timestamp, same_semantic_observation

_ADVERSE = frozenset({"failure", "timed_out", "action_required", "stale", "startup_failure"})


def _unambiguous_checks(checks):
    """Index checks only when their names uniquely identify a run in this sample."""
    indexed = {}
    duplicates = set()
    for check in checks:
        name = check["name"]
        if name in indexed:
            duplicates.add(name)
        else:
            indexed[name] = check
    for name in duplicates:
        del indexed[name]
    return indexed, duplicates


def repository_changes(events, *, now, max_age):
    """Compare two newest distinct observation times without mutating ledger data.

    GitHub's open_issues_count includes pull requests. Missing, duplicated and
    cross-revision checks must never be interpreted as passed or recovered.
    """
    observations = defaultdict(dict)
    for event in events:
        if event["kind"] != "repository":
            continue
        by_time = observations[event["key"]]
        previous = by_time.get(event["observed_at"])
        if previous is None:
            by_time[event["observed_at"]] = event
        else:
            require(
                same_semantic_observation(previous, event),
                "AMBIGUOUS_OBSERVATION: conflicting same-time repository evidence",
            )

    result = []
    for repository, by_time in sorted(observations.items()):
        if len(by_time) < 2:
            continue
        before, after = sorted(
            by_time.values(), key=lambda event: timestamp(event["observed_at"])
        )[-2:]
        old, new = before["payload"], after["payload"]
        revision_changed = old["head_sha"] != new["head_sha"]
        delta = new["open_issues"] - old["open_issues"]
        deteriorations, recoveries = [], []
        comparison, compared = "REVISION_CHANGED", 0

        if not revision_changed:
            old_checks, old_ambiguous = _unambiguous_checks(old["checks"])
            new_checks, new_ambiguous = _unambiguous_checks(new["checks"])
            shared = sorted(old_checks.keys() & new_checks.keys())
            compared = len(shared)
            if old_ambiguous or new_ambiguous:
                comparison = "PARTIAL_AMBIGUOUS_CHECK_NAMES"
            else:
                comparison = "COMPARABLE" if shared else "NO_SHARED_CHECK_NAMES"
            for name in shared:
                prior, current = old_checks[name], new_checks[name]
                # Only explicit completed conclusions, not pending/absent checks.
                if prior["status"] != "completed" or current["status"] != "completed":
                    continue
                transition = {
                    "name": name,
                    "from_conclusion": prior["conclusion"],
                    "to_conclusion": current["conclusion"],
                    "source_ref": current["url"],
                }
                if prior["conclusion"] == "success" and current["conclusion"] in _ADVERSE:
                    deteriorations.append(transition)
                elif prior["conclusion"] in _ADVERSE and current["conclusion"] == "success":
                    recoveries.append(transition)

        quality = "ACTUAL_FRESH"
        age = (timestamp(now) - timestamp(after["observed_at"])).total_seconds()
        require(age >= 0, "FUTURE_SOURCE: change comparison after report time required")
        if after["data_kind"] != "ACTUAL" or before["data_kind"] != "ACTUAL":
            quality = "NON_ACTUAL"
        elif age > max_age:
            quality = "HISTORICAL"

        types = []
        if revision_changed:
            types.append("REVISION_CHANGED")
        if delta:
            types.append("OPEN_TRACKER_TALLY_CHANGED")
        if deteriorations:
            types.append("CHECK_DETERIORATED")
        if recoveries:
            types.append("CHECK_RECOVERED")

        result.append({
            "repository": repository,
            "previous_observed_at": before["observed_at"],
            "current_observed_at": after["observed_at"],
            "previous_revision": old["head_sha"],
            "current_revision": new["head_sha"],
            "revision_changed": revision_changed,
            "open_issue_pr_tally": {
                "previous": old["open_issues"],
                "current": new["open_issues"],
                "net_delta": delta,
                "definition": "GITHUB_OPEN_ISSUES_COUNT_INCLUDES_PULL_REQUESTS",
            },
            "check_comparison": comparison,
            "compared_check_names": compared,
            "check_deteriorations": deteriorations,
            "check_recoveries": recoveries,
            "change_types": types,
            "evidence_quality": quality,
            "source_refs": [old["source_ref"], new["source_ref"]],
            "scope": "OBSERVED_DIFFERENCES_NOT_CAUSATION_OR_VALUE_VERIFICATION",
        })
    return result
