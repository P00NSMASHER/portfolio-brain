"""Repeat-adverse and recovery follow-ups derived from an unchanged verified ledger.

Never stores state, calls a provider, authorizes a repair, or equates a green
check with root-cause resolution. Canonical event sequence and chain identity
must match the same verified report before any caller may make provider reads.
"""
from __future__ import annotations

import re

from .changes import repository_changes, _unambiguous_checks
from .core import BrainError, digest, require, timestamp

_SHA = re.compile(r"[0-9a-f]{40}\Z")
_CHAIN = re.compile(r"[0-9a-f]{64}\Z")
_ADVERSE = frozenset({"failure", "timed_out", "action_required", "stale", "startup_failure"})
_MAX_EVENTS = 100000


def _validate_history(report, history, limits):
    require(type(history) is list and len(history) <= _MAX_EVENTS,
            "CONTINUATION_HISTORY_BOUND")
    count = report.get("state_sequence")
    require(type(count) is int and len(history) == count,
            "CONTINUATION_EVENT_SEQUENCE_MISMATCH")
    require(type(report.get("canonical_hash")) is str
            and _CHAIN.fullmatch(report["canonical_hash"]),
            "CONTINUATION_CANONICAL_HASH_REQUIRED")
    require(type(report.get("generated_at")) is str,
            "CONTINUATION_ORIGINAL_REPORT_TIME_REQUIRED")
    previous = "0" * 64
    snapshots = {}
    for sequence, item in enumerate(history, 1):
        require(type(item) is dict and type(item.get("kind")) is str
                and type(item.get("id")) is str
                and item["id"] == item["kind"] + ":" + digest({**item, "id": ""}),
                "CONTINUATION_EVENT_IDENTITY_INVALID")
        event_hash = digest(item)
        previous = digest({"seq": sequence, "event_hash": event_hash,
                           "previous": previous})
        if item["kind"] == "repository":
            repo = item.get("key")
            data = item.get("payload")
            require(type(repo) is str and type(data) is dict
                    and data.get("repository") == repo,
                    "CONTINUATION_REPOSITORY_KEY_MISMATCH")
            if repo in limits["repositories"]:
                instant = timestamp(item["observed_at"])
                per_repo = snapshots.setdefault(repo, {})
                prior = per_repo.get(instant)
                if prior is None:
                    per_repo[instant] = item
                else:
                    require(prior["payload"] == item["payload"]
                            and prior["visibility"] == item["visibility"]
                            and prior["data_kind"] == item["data_kind"],
                            "CONTINUATION_SAME_TIME_CONFLICT")
    require(previous == report["canonical_hash"],
            "CONTINUATION_LEDGER_HASH_MISMATCH")
    derived = repository_changes(
        history, now=report["generated_at"],
        max_age=limits["max_source_age_seconds"],
    )
    require(derived == report.get("repository_changes"),
            "CONTINUATION_REPORT_REPLAY_MISMATCH")
    return snapshots


def _source_url(value, repo):
    return (type(value) is str and len(value) <= 1200
            and value.startswith(f"https://github.com/{repo}/")
            and all(32 <= ord(char) < 127 for char in value))


def _eligible(row, now, limits):
    repo = row["repository"]
    if (repo not in limits["repositories"]
            or row.get("evidence_quality") != "ACTUAL_FRESH"
            or row.get("check_comparison") not in {
                "COMPARABLE", "NO_SHARED_CHECK_NAMES",
                "PARTIAL_AMBIGUOUS_CHECK_NAMES",
            }
            or row.get("revision_changed") is not False):
        return False
    revision = row.get("current_revision")
    require(type(revision) is str and _SHA.fullmatch(revision)
            and revision == row.get("previous_revision"),
            "CONTINUATION_REVISION_MISMATCH")
    expected = f"https://github.com/{repo}/commit/{revision}"
    require(row.get("source_refs") == [expected, expected],
            "CONTINUATION_SOURCE_UNBOUND")
    before = timestamp(row.get("previous_observed_at"))
    after = timestamp(row.get("current_observed_at"))
    now = timestamp(now)
    require(before < after <= now
            and (now - before).total_seconds() <= limits["max_source_age_seconds"],
            "CONTINUATION_STALE_OR_NONMONOTONIC")
    return True


def continued_plans(report, history, *, now, limits):
    """Return new bounded read-only work, never an executable recommendation."""
    snapshots = _validate_history(report, history, limits)
    selected = []
    for row in sorted(report["repository_changes"], key=lambda r: r["repository"]):
        if not _eligible(row, now, limits):
            continue
        repo = row["repository"]
        current_revision = row["current_revision"]
        times = sorted(snapshots.get(repo, {}))
        require(len(times) >= 2, "CONTINUATION_MISSING_SOURCE_SAMPLES")
        prior = snapshots[repo][times[-2]]
        current = snapshots[repo][times[-1]]
        require(timestamp(prior["observed_at"]) == timestamp(row["previous_observed_at"])
                and timestamp(current["observed_at"]) == timestamp(row["current_observed_at"]),
                "CONTINUATION_WRONG_OBSERVATIONS")
        commit_url = f"https://github.com/{repo}/commit/{current_revision}"
        for sample in (prior, current):
            data = sample["payload"]
            require(sample["visibility"] == "PUBLIC"
                    and sample["data_kind"] == "ACTUAL"
                    and data["head_sha"] == current_revision
                    and data["source_ref"] == commit_url,
                    "CONTINUATION_NONACTUAL_OR_UNBOUND_SAMPLE")
        old_checks, old_duplicates = _unambiguous_checks(prior["payload"]["checks"])
        new_checks, new_duplicates = _unambiguous_checks(current["payload"]["checks"])
        # The canonical comparison already quarantines duplicate names.
        # Continue only on checks uniquely identifiable in BOTH snapshots.
        # A duplicated current name is ambiguous, not evidence of a missing
        # or recovered check.
        recoveries = row.get("check_recoveries")
        require(type(recoveries) is list, "CONTINUATION_RECOVERY_MISSING")
        recovered_names = []
        for item in recoveries:
            require(type(item) is dict
                    and item.get("from_conclusion") in _ADVERSE
                    and item.get("to_conclusion") == "success"
                    and _source_url(item.get("source_ref"), repo),
                    "CONTINUATION_UNBOUND_RECOVERY")
            recovered_names.append(item["name"])
        require(len(recovered_names) == len(set(recovered_names)),
                "CONTINUATION_AMBIGUOUS_RECOVERY")

        persistent_names = [
            name for name in sorted(old_checks.keys() & new_checks.keys())
            if old_checks[name]["status"] == "completed"
            and new_checks[name]["status"] == "completed"
            and old_checks[name]["conclusion"] in _ADVERSE
            and new_checks[name]["conclusion"] in _ADVERSE
        ]
        # A missing or stalled check is an observability gap, NOT an adverse
        # transition or a recovered incident. Revisit using one bounded GET.
        gaps = [
            name for name, earlier in sorted(old_checks.items())
            if earlier["status"] == "completed"
            and earlier["conclusion"] in (_ADVERSE | {"success"})
            and name not in old_duplicates
            and name not in new_duplicates
            and (name not in new_checks
                 or new_checks[name]["status"] != "completed")
        ]
        # A recovery in one check must never hide another check that is
        # still failing. Reconcile every relevant signal in one bounded GET.
        evidence_classes = {}
        for classification, candidates in (
            ("RECOVERY_OBSERVED_NOT_RESOLUTION", recovered_names),
            ("PERSISTENT_ADVERSE_OBSERVED", persistent_names),
            ("EVIDENCE_GAP_REVALIDATION", gaps),
        ):
            for name in candidates:
                require(name not in evidence_classes,
                        "CONTINUATION_OVERLAPPING_CHECK_EVIDENCE")
                evidence_classes[name] = classification
        names = sorted(evidence_classes)
        if not names:
            continue
        kind = ("EVIDENCE_GAP_REVALIDATION" if gaps else
                "PERSISTENT_ADVERSE_OBSERVED" if persistent_names else
                "RECOVERY_OBSERVED_NOT_RESOLUTION")
        require(len(names) <= 500, "CONTINUATION_CHECK_COUNT_LIMIT")
        checked_refs = []
        for name in names:
            evidence = new_checks.get(name, old_checks.get(name))
            require(evidence is not None
                    and _source_url(evidence["url"], repo),
                    "CONTINUATION_CHECK_REF_UNBOUND")
            checked_refs.append(evidence["url"])
        refs = sorted({commit_url} | set(checked_refs))
        selected.append({
            "repository": repo,
            "queue_id": digest(["CONTINUATION", kind, repo, current_revision,
                                row["current_observed_at"], names])[:20],
            "follow_up_kind": kind, "expected_revision": current_revision,
            "original_observed_at": row["current_observed_at"],
            "source_refs": refs, "check_names": names,
            "check_evidence_classes": evidence_classes,
            "partial_check_coverage": (
                row["check_comparison"] == "PARTIAL_AMBIGUOUS_CHECK_NAMES"
            ),
        })
    return selected
