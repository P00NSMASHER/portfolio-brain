"""Bounded, one-shot read-only adverse/recovery follow-up; no repair authority.

Library callers supply a canonical replay-verified report. The standalone CLI
verifies that provenance itself on a disposable snapshot of existing state.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from .adapters import GitHub, policy
from .core import BrainError, Store, require, timestamp, utcnow
from .triage import decision_queue

_MAX_INVESTIGATIONS = 3
# Metadata, branch before/after, and at most five check pages; one retry each.
_OBSERVATION_REQUEST_RESERVE = 16
_ADVERSE = frozenset({"failure", "timed_out", "action_required", "startup_failure", "stale"})
_SHA = re.compile(r"[0-9a-f]{40}\Z")

# Only provider failures demonstrably scoped to one repository are isolated.
# Rate limits, authorization/visibility, transport failures, policy or
# malformed unclassified evidence still break the entire investigation.
_LOCAL_REPOSITORY_READ_FAILURES = frozenset({
    "SOURCE_API_404",
    "CHECK_COVERAGE_UNAVAILABLE",
    "CHECK_COVERAGE_TRUNCATED",
    "CHECK_COVERAGE_CHANGED",
    "CHECK_COVERAGE_AMBIGUOUS",
    "SOURCE_REVISION_CHANGED",
    "SOURCE_REVISION_UNAVAILABLE",
    "SOURCE_RESPONSE_TOO_LARGE",
})


def _provider_failure_scope(exc):
    """Fixed-label circuit breaker; never echo upstream diagnostic content."""
    if isinstance(exc, BrainError):
        fixed_code = str(exc).partition(":")[0]
        if fixed_code in _LOCAL_REPOSITORY_READ_FAILURES:
            return "REPOSITORY_LOCAL_EVIDENCE_UNAVAILABLE"
    return "GLOBAL_OR_UNCLASSIFIED_STOP"


def _source_reference(value, repository):
    return (type(value) is str and len(value) <= 1200
            and value.startswith(f"https://github.com/{repository}/")
            and not any(ord(char) < 32 or ord(char) == 127 for char in value))


def _plan(report, now, limits):
    """Validate all eligible evidence before allowing any provider request."""
    require(type(report) is dict, "verified report required")
    require(type(report.get("schema_version")) is int and report["schema_version"] == 2,
            "canonical schema required")
    require(report.get("status") == "PASS", "verified PASS required")
    require(type(report.get("pending_events")) is int and report["pending_events"] == 0,
            "zero backlog required")
    require(type(report.get("state_sequence")) is int and report["state_sequence"] >= 0,
            "state sequence required")
    require(type(report.get("source_sha")) is str and _SHA.fullmatch(report["source_sha"]),
            "exact source required")
    current = timestamp(now)
    age_limit = limits["max_source_age_seconds"]
    if "generated_at" in report:
        require(0 <= (current - timestamp(report["generated_at"])).total_seconds() <= age_limit,
                "canonical report expired")
    changes = report.get("repository_changes")
    require(type(changes) is list, "repository comparisons required")
    selected = {}
    for row in changes:
        require(type(row) is dict, "comparison object required")
        repository = row.get("repository")
        if repository not in limits["repositories"] or row.get("evidence_quality") != "ACTUAL_FRESH":
            continue
        deteriorations = row.get("check_deteriorations")
        require(type(deteriorations) is list, "check evidence required")
        if not deteriorations:
            continue
        require(repository not in selected, "duplicate repository evidence")
        # Quarantine duplicate-named checks, not independent unique checks.
        # The canonical comparison already excludes ambiguous check names.
        require(row.get("check_comparison") in {
            "COMPARABLE", "PARTIAL_AMBIGUOUS_CHECK_NAMES",
        } and row.get("revision_changed") is False,
                "same-revision uniquely identifiable evidence required")
        revision = row.get("current_revision")
        require(type(revision) is str and _SHA.fullmatch(revision)
                and row.get("previous_revision") == revision, "exact comparison revision required")
        previous = timestamp(row.get("previous_observed_at"))
        latest = timestamp(row.get("current_observed_at"))
        require(previous <= latest <= current, "comparison timestamps out of order")
        require((current - previous).total_seconds() <= age_limit, "comparison evidence expired")
        expected_ref = f"https://github.com/{repository}/commit/{revision}"
        require(row.get("source_refs") == [expected_ref, expected_ref], "unbound comparison source")
        require(type(row.get("change_types")) is list and "CHECK_DETERIORATED" in row["change_types"],
                "adverse transition classification required")
        names = set()
        for check in deteriorations:
            require(type(check) is dict, "check evidence object required")
            name = check.get("name")
            require(type(name) is str and 0 < len(name) <= 1000 and name not in names,
                    "unique check name required")
            require(check.get("from_conclusion") == "success"
                    and check.get("to_conclusion") in _ADVERSE, "adverse transition evidence required")
            require(_source_reference(check.get("source_ref"), repository), "unbound check source")
            names.add(name)
        selected[repository] = row

    # The existing queue establishes stable identity. Only validated failure
    # comparisons enter this projection; third-party code proposals never run.
    queue_input = {**report, "repository_changes": list(selected.values()), "reuse_candidates": []}
    queue = decision_queue(queue_input)
    result = []
    for item in queue["items"]:
        if item["category"] != "INVESTIGATE_CHECK_CHANGE":
            continue
        repository = item["metadata"]["repository"]
        row = selected[repository]
        # A repository may show one new adverse check and a different observed
        # recovery in the same exact-source comparison. Recheck both in ONE
        # bounded GET instead of discarding the recovery forever.
        recoveries = row.get("check_recoveries")
        require(type(recoveries) is list, "CONTINUATION_RECOVERY_EVIDENCE_MISSING")
        for change in recoveries:
            require(type(change) is dict
                    and change.get("from_conclusion") in _ADVERSE
                    and change.get("to_conclusion") == "success"
                    and _source_reference(change.get("source_ref"), repository),
                    "CONTINUATION_RECOVERY_EVIDENCE_UNBOUND")
        check_names = [check["name"] for check in row["check_deteriorations"]]
        check_names.extend(change["name"] for change in recoveries)
        require(len(check_names) == len(set(check_names)),
                "CONTINUATION_RECOVERY_CHECK_NAME_AMBIGUOUS")
        original_classes = {
            check["name"]: "INITIAL_ADVERSE_TRANSITION"
            for check in row["check_deteriorations"]
        }
        original_classes.update({
            check["name"]: "RECOVERY_OBSERVED_NOT_RESOLUTION"
            for check in recoveries
        })
        refs = sorted(set(item["source_refs"] + [change["source_ref"]
                                                  for change in recoveries]))
        result.append({
            "repository": repository, "queue_id": item["id"],
            "expected_revision": row["current_revision"],
            "original_observed_at": row["current_observed_at"],
            "source_refs": refs,
            "check_names": sorted(check_names),
            "check_evidence_classes": original_classes,
            "partial_check_coverage": (
                row["check_comparison"] == "PARTIAL_AMBIGUOUS_CHECK_NAMES"
            ),
        })
    require(len(result) == len(selected), "investigation queue unexpectedly truncated")
    return result


def _revalidate(plan, observation):
    repository = plan["repository"]
    revision = observation.get("head_sha")
    require(observation.get("repository") == repository
            and type(revision) is str and _SHA.fullmatch(revision), "provider source mismatch")
    require(observation.get("source_ref") == f"https://github.com/{repository}/commit/{revision}",
            "provider reference mismatch")
    result = {**plan, "observed_revision": revision,
              "observation_ref": observation["source_ref"], "checks": []}
    if revision != plan["expected_revision"]:
        result["outcome"] = "SOURCE_CHANGED_REQUIRES_NEW_COMPARISON"
        return result
    checks = observation.get("checks")
    require(type(checks) is list, "provider checks missing")
    classes = plan.get("check_evidence_classes")
    if classes is not None:
        require(type(classes) is dict
                and set(classes) == set(plan["check_names"])
                and all(type(tag) is str and tag in {
                    "INITIAL_ADVERSE_TRANSITION",
                    "EVIDENCE_GAP_REVALIDATION",
                    "PERSISTENT_ADVERSE_OBSERVED",
                    "RECOVERY_OBSERVED_NOT_RESOLUTION",
                } for tag in classes.values()),
                "CONTINUATION_PER_CHECK_CLASS_INVALID")
    historical = plan.get("historical_check_patterns")
    if historical is not None:
        require(type(historical) is dict
                and set(historical) == set(plan["check_names"]),
                "TEMPORAL_SELECTED_CHECKS_MISMATCH")
    for name in plan["check_names"]:
        matches = [row for row in checks if row.get("name") == name]
        checked = {"name": name}
        if classes is not None:
            checked["original_evidence_class"] = classes[name]
        if historical is not None:
            # Keep private check evidence independent of its source plan.
            # In-memory aliasing must not let a forged check observation
            # silently mutate its companion expected-history record.
            require(type(historical[name]) is dict,
                    "TEMPORAL_CHECK_RECORD_INVALID")
            checked["historical_observations"] = dict(historical[name])
        if len(matches) != 1:
            checked["outcome"] = "UNVERIFIED_MISSING_OR_AMBIGUOUS_CHECK"
        else:
            match = matches[0]
            if match.get("status") != "completed":
                checked["outcome"] = "CHECK_NOT_COMPLETED"
            elif match.get("conclusion") in _ADVERSE:
                checked["outcome"] = "STILL_ADVERSE"
            elif match.get("conclusion") == "success":
                checked["outcome"] = "SUCCESS_OBSERVED_NOT_RESOLUTION"
            else:
                checked["outcome"] = "OTHER_CONCLUSION_NOT_RESOLUTION"
            # A provider URL is never followed, interpreted as an instruction,
            # or rendered as trusted evidence outside the scoped repository.
            if _source_reference(match.get("url"), repository):
                checked["source_ref"] = match["url"]
        result["checks"].append(checked)
    result["outcome"] = "OBSERVED_CHECK_STATUS_NOT_ROOT_CAUSE"
    return result


def investigate(report, *, api=None, now=None, max_investigations=3, stop_requested=None, history=None):
    """Select and revalidate bounded failure evidence without state mutation.

    ``report`` must already have passed canonical ledger replay. This function
    verifies selection/freshness constraints; the CLI also verifies provenance.
    Optional ``history`` must match the report's exact immutable hash chain;
    it only adds repeated-adverse and observed-recovery GET rechecks.
    Provider exceptions are deliberately reduced to fixed, nonsecret labels.
    """
    require(type(max_investigations) is int and 1 <= max_investigations <= _MAX_INVESTIGATIONS,
            "investigation limit outside fixed bound")
    require(stop_requested is None or callable(stop_requested), "stop predicate invalid")
    now = now or utcnow()
    limits = policy()
    plans = _plan(report, now, limits)
    if history is not None:
        from .continuation import continued_plans
        extended = continued_plans(report, history, now=now, limits=limits)
        # Merge current deterioration with other independent check findings
        # from the *same exact immutable observation*. One repository GET
        # must cover all evidence without duplicating request expenditure.
        already_planned = {item["repository"]: item for item in plans}
        remaining = []
        for continuation in extended:
            current = already_planned.get(continuation["repository"])
            if current is None:
                remaining.append(continuation)
                continue
            require(current["expected_revision"] == continuation["expected_revision"]
                    and current["original_observed_at"] == continuation["original_observed_at"],
                    "CONTINUATION_SOURCE_OR_TIME_MISMATCH")
            existing_classes = current["check_evidence_classes"]
            additional_classes = continuation["check_evidence_classes"]
            require(type(additional_classes) is dict,
                    "CONTINUATION_EVIDENCE_MAP_INVALID")
            for check_name, evidence_class in additional_classes.items():
                require(check_name not in existing_classes
                        or existing_classes[check_name] == evidence_class,
                        "CONTINUATION_CONTRADICTORY_CHECK_EVIDENCE")
                existing_classes[check_name] = evidence_class
            current["check_names"] = sorted(existing_classes)
            current["source_refs"] = sorted(set(
                current["source_refs"] + continuation["source_refs"]
            ))
        extended = remaining
        # New regressions stay first. Persistent/recovery work is equally
        # important within its class, so rotate it deterministically each UTC
        # hour; four ongoing failures must not permanently starve the fourth.
        # No cursor, scheduling change, mutable state or extra API reads.
        def rotated(rows):
            rows = sorted(rows, key=lambda item: item["repository"])
            if len(rows) < 2:
                return rows
            offset = (int(timestamp(now).timestamp()) // 3600) % len(rows)
            return rows[offset:] + rows[:offset]

        # Rotate equal-priority fresh regressions as well: when four
        # repositories regress at once, no repository should permanently
        # occupy the fourth (deferred) slot in every bounded follow-up.
        initial = rotated(plans)
        gaps = [item for item in extended
                if item["follow_up_kind"] == "EVIDENCE_GAP_REVALIDATION"]
        persistent = [item for item in extended
                      if item["follow_up_kind"] == "PERSISTENT_ADVERSE_OBSERVED"]
        recovered = [item for item in extended
                     if item["follow_up_kind"] == "RECOVERY_OBSERVED_NOT_RESOLUTION"]
        require(len(gaps) + len(persistent) + len(recovered) == len(extended),
                "CONTINUATION_CLASSIFICATION_INVALID")
        plans = initial + rotated(gaps) + rotated(persistent) + rotated(recovered)
        # A purely local, original-ledger historical pattern projection.
        # It cannot add provider calls, change priority, or write state.
        from .temporal import annotate_verified_plans
        plans = annotate_verified_plans(
            history, plans, now=now,
            max_age=limits["max_source_age_seconds"],
        )
    receipt = {
        "schema_version": 1, "scope": "READ_ONLY_AUTONOMOUS_CHECK_REVALIDATION",
        "source_sha": report["source_sha"],
        "state_sequence": report["state_sequence"], "checked_at": now,
        "status": "NO_ELIGIBLE_FAILURES", "investigations": [],
        "eligible_count": len(plans), "deferred_count": len(plans),
        "requests_used": 0, "max_investigations": max_investigations,
        "execution_authority": False, "root_cause_verified": False,
        "github_mutations": 0, "events_written": 0, "paid_calls": 0,
    }
    if not plans:
        return receipt
    api = api if api is not None else GitHub(private=False)
    require(api.private is False, "public provider scope required")
    require(type(api.requests) is int and 0 <= api.requests <= limits["max_requests_per_operation"],
            "provider request counter invalid")
    started_requests = api.requests
    receipt["status"] = "READ_ONLY_REVALIDATION_COMPLETE"
    for plan in plans[:max_investigations]:
        if stop_requested is not None and stop_requested():
            receipt["status"] = "STOPPED"
            break
        if limits["max_requests_per_operation"] - api.requests < _OBSERVATION_REQUEST_RESERVE:
            receipt["status"] = "REQUEST_BUDGET_DEFERRED"
            break
        must_stop_provider = False
        try:
            observation, private = api.observe(plan["repository"])
            require(private is False, "private provider observation refused")
            result = _revalidate(plan, observation)
        except (BrainError, OSError, KeyError, TypeError, AttributeError) as exc:
            scope = _provider_failure_scope(exc)
            result = {**plan, "observed_revision": None, "checks": [],
                      "outcome": "UNVERIFIED_READ_FAILED",
                      "provider_failure_scope": scope}
            receipt["status"] = "INCOMPLETE_READ_ONLY_REVALIDATION"
            must_stop_provider = scope == "GLOBAL_OR_UNCLASSIFIED_STOP"
        receipt["investigations"].append(result)
        if must_stop_provider:
            # Keep the original circuit breaker for auth/rate-limit/global or
            # unclassified failure. No later provider calls are permissible.
            break
        # Only a fixed, repository-local failure permits checking the next
        # independently prevalidated repository within the existing budget.
    receipt["requests_used"] = api.requests - started_requests
    receipt["deferred_count"] = len(plans) - len(receipt["investigations"])
    if receipt["deferred_count"] and receipt["status"] == "READ_ONLY_REVALIDATION_COMPLETE":
        receipt["status"] = "BOUNDED_READ_ONLY_REVALIDATION_COMPLETE_WITH_DEFERRED"
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--expected-sha")
    parser.add_argument("--max-investigations", type=int, default=_MAX_INVESTIGATIONS)
    args = parser.parse_args(argv)
    try:
        from .__main__ import source_sha
        from .render import write_report
        from .transfer import readonly_authority_snapshot

        require(1 <= args.max_investigations <= _MAX_INVESTIGATIONS,
                "investigation limit outside fixed bound")
        # Never let a receipt replace its original authority, even when that
        # database has an unusual name. Publisher separately rejects aliases.
        for name in ("report.json", "report.md", "report.html"):
            target = args.output / name
            require(target.resolve() != args.db.resolve(), "receipt aliases original state")
            if target.exists() and args.db.exists():
                require(not target.samefile(args.db), "receipt aliases original state")
        sha = source_sha(args.expected_sha)
        with readonly_authority_snapshot(args.db) as snapshot:
            # Snapshot contexts own any Store they yield. Never reopen that
            # object as a filesystem path or construct a Store on authority.
            snapshot_path = snapshot.path if isinstance(snapshot, Store) else Path(snapshot)
            require(snapshot_path.resolve() != args.db.resolve(), "snapshot aliases original state")
            if isinstance(snapshot, Store):
                report = snapshot.read_report(sha)
                history, sequence, ledger_hash = snapshot._verified_events()
            else:
                store = Store(snapshot_path, visibility="PUBLIC")
                try:
                    report = store.read_report(sha)
                    history, sequence, ledger_hash = store._verified_events()
                finally:
                    store.close()
        require(sequence == report["state_sequence"]
                and ledger_hash == report["canonical_hash"],
                "CONTINUATION_SNAPSHOT_CHANGED")
        receipt = investigate(report, history=history,
                              max_investigations=args.max_investigations,
                              stop_requested=lambda: (args.db.parent / "STOP").exists())
        write_report(receipt, args.output)
        print(json.dumps({"status": receipt["status"], "requests_used": receipt["requests_used"]}))
        return 0 if receipt["status"] in {"READ_ONLY_REVALIDATION_COMPLETE", "NO_ELIGIBLE_FAILURES"} else 1
    except (BrainError, OSError, ValueError, KeyError, TypeError):
        print("INVESTIGATION_BLOCKED: source, evidence, state or output verification failed", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
