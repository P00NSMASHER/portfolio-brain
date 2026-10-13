"""Read-only, bounded operator review routing for a verified V7 investigation.

No API calls, incident closure, source execution, third-party instructions,
notifications, portfolio trades, spending, or writable state. This is an
advisory projection ONLY for the already private investigation report bundle.
"""
from __future__ import annotations

import hashlib
import json
import re

from .evidence_urls import check_run_ref, repo_evidence_ref

_MAX_REVIEWS = 12
_MAX_PER_REPOSITORY = 4
_MAX_COINCIDENCE_GROUPS = 4
_REPO = re.compile(r"[A-Za-z0-9_.-]{1,39}/[A-Za-z0-9_.-]{1,100}\Z")
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_BANDS = {
    "SOURCE_COMPARABILITY_LOST": (0, "Obtain two fresh observations on the new commit before comparing CI outcomes."),
    "PROVIDER_EVIDENCE_UNAVAILABLE": (0, "Verify provider availability and rerun bounded public evidence collection; no diagnosis is established."),
    "NEW_ADVERSE_CHECK": (1, "Inspect the original same-commit transition and fresh completed CI logs; independently test before any repair."),
    "RECOVERY_NOT_REPRODUCED": (1, "Original recovery was NOT reproduced by the current exact-source recheck. Compare separate original and current CI runs; do not infer a new regression or a confirmed root cause."),
    "ORIGINAL_ADVERSE_NOT_REOBSERVED": (4, "A prior adverse observation is now green on recheck, but a fixed incident is NOT independently verified. Check source identity, original logs and repeated results before considering closure."),
    "UNBASELINED_ADVERSE_CHECK": (2, "A newly observed adverse CI check has no baseline. Independently establish its first qualifying source-bound result; do not call this a new regression or infer the failure began now."),
    "MISSING_OR_PENDING_CHECK": (2, "Revalidate the exact commit and confirm a uniquely identified completed check; keep the case open until evidence is complete."),
    "PERSISTENT_ADVERSE_CHECK": (3, "Compare the repeated adverse check observations and CI logs; distinguish repeated observation from elapsed downtime."),
    "ADVERSE_CHECK_NEEDS_CONTEXT": (3, "Inspect source-bound check results and current CI logs; do not infer root cause or impact."),
    "INCONCLUSIVE_COMPLETED_CHECK": (4, "Confirm the final conclusion and source identity manually before classifying the check."),
    "RECOVERY_OBSERVED_NOT_CONFIRMED": (5, "Verify the apparent recovery with independent evidence before considering incident closure."),
}
_VALID_OUTCOME = frozenset({
    "STILL_ADVERSE", "CHECK_NOT_COMPLETED",
    "UNVERIFIED_MISSING_OR_AMBIGUOUS_CHECK", "OTHER_CONCLUSION_NOT_RESOLUTION",
    "SUCCESS_OBSERVED_NOT_RESOLUTION",
})
_VALID_REPO_OUTCOME = frozenset({
    "OBSERVED_CHECK_STATUS_NOT_ROOT_CAUSE",
    "SOURCE_CHANGED_REQUIRES_NEW_COMPARISON", "UNVERIFIED_READ_FAILED",
})
_VALID_CLASS = frozenset({
    "INITIAL_ADVERSE_TRANSITION", "UNBASELINED_ADVERSE_OBSERVED",
    "EVIDENCE_GAP_REVALIDATION",
    "PERSISTENT_ADVERSE_OBSERVED", "RECOVERY_OBSERVED_NOT_RESOLUTION",
})
_VALID_RECEIPT = frozenset({
    "NO_ELIGIBLE_FAILURES", "READ_ONLY_REVALIDATION_COMPLETE",
    "BOUNDED_READ_ONLY_REVALIDATION_COMPLETE_WITH_DEFERRED",
    "INCOMPLETE_READ_ONLY_REVALIDATION", "REQUEST_BUDGET_DEFERRED", "STOPPED",
})


def _check(condition, failure):
    if not condition:
        raise ValueError(failure)


def _source_ref(value, repo):
    return repo_evidence_ref(value, repo)


def _copy_ref(value, repo):
    # Human check links MUST be actual scoped CI check-run references.
    # Missing/ambiguous URLs fall back to exact original source commit.
    return value if check_run_ref(value, repo) else None


def _history(check):
    """Use only counts already derived from the canonical ledger."""
    v = check.get("historical_observations")
    if v is None:
        return None
    _check(type(v) is dict, "REVIEW_HISTORY_INVALID")
    samples = v.get("terminal_samples")
    streak = v.get("adverse_streak_samples")
    flips = v.get("adverse_success_flips_observed")
    capped = v.get("capped_at_12_samples")
    _check(type(samples) is int and 0 <= samples <= 12,
           "REVIEW_HISTORY_SAMPLE_BOUND")
    _check(type(streak) is int and 0 <= streak <= samples,
           "REVIEW_HISTORY_STREAK_BOUND")
    _check(type(flips) is int and 0 <= flips <= max(samples - 1, 0),
           "REVIEW_HISTORY_MOVEMENT_BOUND")
    _check(type(capped) is bool and (not capped or samples == 12),
           "REVIEW_HISTORY_CAP_INVALID")
    return {"sampled_terminal_observations": samples,
            "sampled_adverse_streak": streak,
            "sampled_terminal_state_flips": flips,
            "history_sample_cap_reached": capped}


def _item(*, source_sha, repo, revision, check_name, reason,
          provider_outcome, original_class, checked_at, evidence_ref,
          original_pattern):
    order, next_review = _BANDS[reason]
    # Same-revision case identity survives a new read or changed conclusion.
    # It is a referent, NOT a stored incident or authorization to close one.
    fingerprint = json.dumps(
        ["CI_CHECK_REVIEW_ID_V1", repo, revision, check_name],
        separators=(",", ":"), ensure_ascii=True,
    )
    case_key = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:24]
    identity = json.dumps(
        [source_sha, repo, revision, check_name, reason, provider_outcome,
         original_class, checked_at],
        separators=(",", ":"), ensure_ascii=True,
    )
    return {
        "id": hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20],
        "case_key": case_key,
        "case_identity_scope": "SOURCE_REVISION_CHECK_NAME_NOT_PERSISTED_CASE",
        "repository": repo,
        "check_name": check_name,
        "original_source_revision": revision,
        "evidence_ref": evidence_ref,
        "category": reason,
        "observed_outcome": provider_outcome,
        "original_evidence_class": original_class,
        "historical_sample_summary": original_pattern,
        "order_band_not_impact_severity": order,
        "proposed_human_review": next_review,
        "action_state": "HUMAN_REVIEW_REQUIRED_NOT_EXECUTED",
        "root_cause_verified": False,
        "independent_resolution_verified": False,
        "business_impact_verified": False,
        "execution_authority": False,
    }


def review_packet(receipt):
    """Deterministic local review routing; never invents a provider observation.

    Does not independently authenticate the upstream report. Call only on an
    investigation receipt that has passed original replay and normal sidecar
    invariants. Untrusted/malformed names and categories fail closed here.
    """
    _check(type(receipt) is dict, "REVIEW_RECEIPT_REQUIRED")
    _check(receipt.get("scope") == "READ_ONLY_AUTONOMOUS_CHECK_REVALIDATION"
           and receipt.get("schema_version") == 1
           and type(receipt.get("schema_version")) is int,
           "REVIEW_RECEIPT_SCOPE_INVALID")
    source = receipt.get("source_sha")
    _check(type(source) is str and _SHA.fullmatch(source),
           "REVIEW_SOURCE_SHA_REQUIRED")
    sequence = receipt.get("state_sequence")
    _check(type(sequence) is int and sequence >= 0,
           "REVIEW_SEQUENCE_INVALID")
    status = receipt.get("status")
    _check(type(status) is str and status in _VALID_RECEIPT,
           "REVIEW_STATUS_INVALID")
    checked_at = receipt.get("checked_at")
    _check(type(checked_at) is str and checked_at.endswith("Z")
           and len(checked_at) <= 40,
           "REVIEW_OBSERVATION_TIME_REQUIRED")
    investigations = receipt.get("investigations")
    _check(type(investigations) is list and len(investigations) <= 3,
           "REVIEW_REPOSITORY_LIMIT")
    deferred = receipt.get("deferred_count")
    _check(type(deferred) is int and 0 <= deferred <= 4,
           "REVIEW_DEFERRED_COUNT")
    _check(receipt.get("execution_authority") is False
           and receipt.get("root_cause_verified") is False
           and type(receipt.get("github_mutations")) is int
           and receipt["github_mutations"] == 0
           and type(receipt.get("events_written")) is int
           and receipt["events_written"] == 0
           and type(receipt.get("paid_calls")) is int
           and receipt["paid_calls"] == 0,
           "REVIEW_EXECUTION_AUTHORITY_REFUSED")
    by_repo = {}
    partly_covered = 0
    for row in investigations:
        _check(type(row) is dict, "REVIEW_INVESTIGATION_INVALID")
        quarantined = row.get("partial_check_coverage", False)
        _check(type(quarantined) is bool,
               "REVIEW_PARTIAL_COVERAGE_FLAG_INVALID")
        partly_covered += int(quarantined)
        repo = row.get("repository")
        revision = row.get("expected_revision")
        _check(type(repo) is str and _REPO.fullmatch(repo),
               "REVIEW_REPOSITORY_IDENTITY")
        _check(type(revision) is str and _SHA.fullmatch(revision),
               "REVIEW_ORIGINAL_SOURCE_INVALID")
        _check(repo not in by_repo, "REVIEW_DUPLICATE_REPOSITORY")
        by_repo[repo] = []
        _check(row.get("outcome") in _VALID_REPO_OUTCOME,
               "REVIEW_REPOSITORY_OUTCOME_INVALID")
        original_ref = f"https://github.com/{repo}/commit/{revision}"
        references = row.get("source_refs")
        _check(type(references) is list and references
               and all(_source_ref(ref, repo) for ref in references)
               and original_ref in references,
               "REVIEW_ORIGINAL_EVIDENCE_REF_INVALID")
        if row["outcome"] != "OBSERVED_CHECK_STATUS_NOT_ROOT_CAUSE":
            _check(row.get("checks") == [], "REVIEW_NONCOMPARABLE_CHECKS_INVALID")
            category = (
                "SOURCE_COMPARABILITY_LOST"
                if row["outcome"] == "SOURCE_CHANGED_REQUIRES_NEW_COMPARISON"
                else "PROVIDER_EVIDENCE_UNAVAILABLE"
            )
            by_repo[repo].append(_item(
                source_sha=source, repo=repo, revision=revision,
                check_name=None, reason=category, provider_outcome=row["outcome"],
                original_class=None, checked_at=checked_at,
                evidence_ref=original_ref, original_pattern=None,
            ))
            continue
        checks = row.get("checks")
        names = row.get("check_names")
        _check(type(checks) is list and len(checks) <= 500
               and type(names) is list and len(names) <= 500,
               "REVIEW_CHECK_LIST_BOUND")
        _check(all(type(name) is str and 0 < len(name) <= 200
                   for name in names), "REVIEW_CHECK_NAME_INVALID")
        _check(len(names) == len(set(names)), "REVIEW_DUPLICATE_CHECK")
        _check(len(checks) == len(names), "REVIEW_CHECK_COVERAGE_INCOMPLETE")
        classes = row.get("check_evidence_classes")
        if classes is not None:
            _check(type(classes) is dict and set(classes) == set(names)
                   and all(type(v) is str and v in _VALID_CLASS
                           for v in classes.values()),
                   "REVIEW_CLASSIFICATION_INVALID")
        observed_names = set()
        for check in checks:
            _check(type(check) is dict, "REVIEW_CHECK_REQUIRED")
            name = check.get("name")
            _check(type(name) is str and name in names
                   and name not in observed_names, "REVIEW_CHECK_IDENTITY_MISMATCH")
            observed_names.add(name)
            outcome = check.get("outcome")
            _check(type(outcome) is str and outcome in _VALID_OUTCOME,
                   "REVIEW_PROVIDER_OUTCOME_INVALID")
            cls = check.get("original_evidence_class")
            if cls is None:
                cls = row.get("follow_up_kind", "INITIAL_ADVERSE_TRANSITION")
            _check(type(cls) is str and cls in _VALID_CLASS,
                   "REVIEW_ORIGINAL_CLASS_INVALID")
            if classes is not None:
                _check(classes[name] == cls, "REVIEW_CLASSIFICATION_MISMATCH")
            elif check.get("original_evidence_class") is not None:
                _check(cls == row.get("follow_up_kind", "INITIAL_ADVERSE_TRANSITION"),
                       "REVIEW_LEGACY_CLASS_MISMATCH")
            relation = check.get("source_followup_relation")
            if "source_followup_relation" in check:
                # An explicitly supplied None is forged/invalid; only
                # complete legacy receipts may omit this optional field.
                from .evidence_relation import source_followup_relation
                try:
                    expected_relation = source_followup_relation(cls, outcome)
                except ValueError as exc:
                    raise ValueError("REVIEW_RELATION_SOURCE_INVALID") from None
                _check(type(relation) is str and relation == expected_relation,
                       "REVIEW_RELATION_NOT_SOURCE_BOUND")
            if relation == "RECOVERY_NOT_REPRODUCED":
                band = "RECOVERY_NOT_REPRODUCED"
            elif relation == "ORIGINAL_ADVERSE_NOT_REOBSERVED":
                band = "ORIGINAL_ADVERSE_NOT_REOBSERVED"
            elif outcome == "STILL_ADVERSE":
                band = ("NEW_ADVERSE_CHECK" if cls == "INITIAL_ADVERSE_TRANSITION"
                        else "UNBASELINED_ADVERSE_CHECK" if cls == "UNBASELINED_ADVERSE_OBSERVED"
                        else "PERSISTENT_ADVERSE_CHECK" if cls == "PERSISTENT_ADVERSE_OBSERVED"
                        else "ADVERSE_CHECK_NEEDS_CONTEXT")
            elif outcome in {"CHECK_NOT_COMPLETED",
                             "UNVERIFIED_MISSING_OR_AMBIGUOUS_CHECK"}:
                band = "MISSING_OR_PENDING_CHECK"
            elif outcome == "SUCCESS_OBSERVED_NOT_RESOLUTION":
                band = "RECOVERY_OBSERVED_NOT_CONFIRMED"
            else:
                band = "INCONCLUSIVE_COMPLETED_CHECK"
            check_ref = _copy_ref(check.get("source_ref"), repo) or original_ref
            proposal = _item(
                source_sha=source, repo=repo, revision=revision,
                check_name=name, reason=band, provider_outcome=outcome,
                original_class=cls, checked_at=checked_at,
                evidence_ref=check_ref,
                original_pattern=_history(check),
            )
            if relation is not None:
                proposal["source_followup_relation"] = relation
            by_repo[repo].append(proposal)
    # Human attention is bounded per repository as well as globally;
    # the high-volume repository cannot silence every other monitored project.
    candidates = sum(len(items) for items in by_repo.values())
    selected = []
    for repo, items in sorted(by_repo.items()):
        items.sort(key=lambda item: (item["order_band_not_impact_severity"],
                                     item["check_name"] or "", item["id"]))
        selected.extend(items[:_MAX_PER_REPOSITORY])
    selected.sort(key=lambda item: (item["order_band_not_impact_severity"],
                                    item["repository"], item["check_name"] or "",
                                    item["id"]))
    selected = selected[:_MAX_REVIEWS]
    for i, item in enumerate(selected, 1):
        item["review_order_not_impact_rank"] = i

    # Group only confirmed same-name, currently adverse check observations
    # which have distinct repository-scoped original GitHub check-run links.
    # This is a *coincidence of labels*, not evidence of shared infrastructure
    # root cause, correlated outages, impact, incident closure or permission.
    by_check_name = {}
    for item in selected:
        name = item["check_name"]
        if name is None or item["observed_outcome"] != "STILL_ADVERSE":
            continue
        reference = item["evidence_ref"]
        repository = item["repository"]
        if not check_run_ref(reference, repository):
            continue
        by_check_name.setdefault(name, {})[repository] = item
    coincidences = []
    for name, grouped in sorted(by_check_name.items()):
        if len(grouped) < 2:
            continue
        identities = [grouped[repo]["case_key"] for repo in sorted(grouped)]
        group_key = hashlib.sha256(json.dumps(
            ["CI_CHECK_NAME_COINCIDENCE_V1", name, identities],
            separators=(",", ":"), ensure_ascii=True,
        ).encode("utf-8")).hexdigest()[:24]
        coincidences.append({
            "id": group_key,
            "check_name": name,
            "repositories": sorted(grouped),
            "source_refs": sorted(item["evidence_ref"] for item in grouped.values()),
            "source_bound_case_keys": sorted(identities),
            "status": "SAME_NAME_OBSERVED_IN_MULTIPLE_REPOS",
            "interpretation": "NAME_MATCH_NOT_SHARED_ROOT_CAUSE",
            "proposed_human_review": (
                "Independently compare the original check runs; identical CI "
                "labels need not represent the same test or failure cause."
            ),
            "provider_reads_added": 0,
            "execution_authority": False,
        })
    omitted_coincidences = max(0, len(coincidences) - _MAX_COINCIDENCE_GROUPS)
    coincidences = coincidences[:_MAX_COINCIDENCE_GROUPS]
    return {
        "schema_version": 1,
        "scope": "PRIVATE_HUMAN_CHECK_REVIEW_ONLY",
        "source_sha": source,
        "state_sequence": sequence,
        "status": "REVIEW_PROPOSALS_NOT_EXECUTED" if selected else "NO_ELIGIBLE_REVIEW",
        "items": selected,
        "same_name_adverse_coincidences": coincidences,
        "coincidence_groups_omitted_due_to_bounds": omitted_coincidences,
        "candidates_considered": candidates,
        "omitted_due_to_review_bounds": candidates - len(selected),
        "deferred_repositories_not_inspected": deferred,
        "partial_original_check_coverage_repositories": partly_covered,
        "per_repo_review_limit": _MAX_PER_REPOSITORY,
        "max_reviews": _MAX_REVIEWS,
        "get_requests_added": 0,
        "external_state_writes": 0,
        "root_cause_verified": False,
        "execution_authority": False,
        "incident_closed": False,
        "revenue_verified": False,
        "business_impact_verified": False,
    }


def _safe(value):
    """Escape plain untrusted text for a private Markdown-like review bundle."""
    text = str(value).replace("\r", " ").replace("\n", " ")
    text = text.replace("\\", "\\\\")
    for symbol in (chr(96), "*", "_", "[", "]", "<", ">", "|", "(", ")"):
        text = text.replace(symbol, "\\" + symbol)
    return text


def review_lines(receipt):
    """Private Markdown lines, same privacy protection as existing report.md."""
    packet = review_packet(receipt)
    lines = ["", "## Source-bound incident review packet (human review only)", "",
             "These are suggested manual evidence checks, NOT repairs, root-cause diagnoses,"
             " verified impact, license permission, trading or deployment authority.",
             f'Eligible review items: {packet["candidates_considered"]}; '
             f'Shown: {len(packet["items"])}; '
             f'Omitted by review bounds: {packet["omitted_due_to_review_bounds"]}; '
             f'Deferred repositories: {packet["deferred_repositories_not_inspected"]}.']
    if packet["partial_original_check_coverage_repositories"]:
        lines.append(
            "Partial original CI check-name coverage: "
            + str(packet["partial_original_check_coverage_repositories"])
            + " repository comparisons contained duplicate names."
            + " Ambiguous names were quarantined; uniquely identified checks"
            + " were revalidated separately. Full check coverage is NOT verified."
        )
    if not packet["items"]:
        lines.append("No reviewable completed investigation evidence in this pass.")
    for item in packet["items"]:
        lines.append(
            "- " + str(item["review_order_not_impact_rank"]) + ". "
            + item["category"] + " — " + _safe(item["repository"])
            + (" / " + _safe(item["check_name"])
               if item["check_name"] is not None else "")
            + ". Case reference: " + item["case_key"]
            + ". Observed: " + item["observed_outcome"]
            + (". Source-versus-recheck: "
               + item["source_followup_relation"]
               if "source_followup_relation" in item else "")
            + ". Next manual check: " + item["proposed_human_review"]
            + " Original source: " + _safe(item["evidence_ref"])
        )
        if item["historical_sample_summary"] is not None:
            sample = item["historical_sample_summary"]
            lines.append(
                "  - Sampled history: " + str(sample["sampled_terminal_observations"])
                + " terminal observations; adverse streak "
                + str(sample["sampled_adverse_streak"])
                + "; transitions " + str(sample["sampled_terminal_state_flips"])
                + ("; capped at 12" if sample["history_sample_cap_reached"] else "")
                + ". Counts are NOT elapsed downtime, probabilities or diagnosis."
            )
    lines.append(
        "A matching adverse CI check name across repositories is not evidence of"
        " a shared cause, outage, incident impact or common fix."
    )
    for group in packet["same_name_adverse_coincidences"]:
        lines.append(
            "- Shared check-name review (noncausal): " + _safe(group["check_name"])
            + "; repositories " + ", ".join(_safe(repo) for repo in group["repositories"])
            + "; case references " + ", ".join(group["source_bound_case_keys"])
            + ". " + group["proposed_human_review"]
        )
    if packet["coincidence_groups_omitted_due_to_bounds"]:
        lines.append(
            "Additional same-name coincidences omitted by the fixed human"
            " review bound: "
            + str(packet["coincidence_groups_omitted_due_to_bounds"])
        )
    lines.append(
        "Every proposed check requires human verification. No provider calls,"
        " state changes, PR mutations, notifications or incident closures were added."
    )
    return lines
