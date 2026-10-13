"""Deterministic, evidence-gated HUMAN review queue; never autonomous execution.

A pure projection over an already-verified Brain report. It does not mutate the
canonical report, change ledger hashes, query providers, verify commercial value,
grant source licenses, execute discovered code, send messages or open PRs.
"""
from __future__ import annotations

import hashlib
import json
import re

from .evidence_urls import blob_ref, check_run_ref, commit_ref, repo_evidence_ref

_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA64 = re.compile(r"^[0-9a-f]{64}$")
_MAX_ITEMS = 10
_PER_TARGET = 2
_MAX_CODE_REVIEWS = 6
_ALLOWED_EVIDENCE = frozenset({
    "ACTUAL_FRESH", "ACTUAL_STALE_BASELINE", "NON_ACTUAL", "HISTORICAL",
})


def _identifier(category, identity):
    serialized = json.dumps(
        [category, identity], sort_keys=True, ensure_ascii=False,
        separators=(",", ":"), allow_nan=False,
    )
    return hashlib.sha256(serialized.encode()).hexdigest()[:20]


def _reference(value):
    """Only canonical GitHub evidence. This never authorizes code reuse."""
    if type(value) is not str or not value.startswith("https://github.com/"):
        return False
    segments = value[len("https://github.com/"):].split("/", 2)
    if len(segments) < 3:
        return False
    repository = "/".join(segments[:2])
    return (repo_evidence_ref(value, repository)
            or blob_ref(value, repository))


def _sha40(value):
    return type(value) is str and _SHA40.fullmatch(value) is not None


def _sha64(value):
    return type(value) is str and _SHA64.fullmatch(value) is not None


def _proposal(category, band, key, headline, next_step, refs, *,
              evidence_quality, limitations, metadata=None):
    assert refs and all(_reference(ref) for ref in refs), "unbound review evidence"
    return {
        "id": _identifier(category, key),
        "category": category,
        "band": band,
        "subject": key,
        "headline": headline,
        "next_step": next_step,
        "evidence_quality": evidence_quality,
        "source_refs": sorted(set(refs)),
        "limitations": list(limitations),
        "metadata": metadata or {},
        "status": "HUMAN_REVIEW_PROPOSAL_NOT_EXECUTED",
        "action_authority": False,
        "verified_revenue": None,
    }


def _change_proposals(changes):
    proposals = []
    for item in sorted(changes, key=lambda row: row["repository"]):
        quality = item["evidence_quality"]
        if quality not in _ALLOWED_EVIDENCE:
            raise ValueError("unsupported evidence quality: fail closed")
        refs = item["source_refs"]
        repository = item["repository"]
        if (type(repository) is not str
                or type(refs) is not list or len(refs) != 2
                or not commit_ref(refs[0], repository, item.get("previous_revision"))
                or not commit_ref(refs[1], repository, item.get("current_revision"))):
            raise ValueError("repository change has missing source-bound evidence")
        for observed in item["check_deteriorations"] + item["check_recoveries"]:
            if (type(observed) is not dict
                    or not (check_run_ref(observed.get("source_ref"), repository)
                            or commit_ref(observed.get("source_ref"), repository,
                                          item.get("current_revision")))):
                raise ValueError("check transition source is not bound to its repository")
        delta = item["open_issue_pr_tally"]["net_delta"]
        kinds = item["change_types"]
        deteriorations = item["check_deteriorations"]
        recoveries = item["check_recoveries"]
        base = [repository, item["previous_observed_at"], item["current_observed_at"]]
        metadata = {
            "repository": repository,
            "previous_observed_at": item["previous_observed_at"],
            "current_observed_at": item["current_observed_at"],
            "tally_delta_including_prs": delta,
            "observed_check_deteriorations": len(deteriorations),
            "observed_check_recoveries": len(recoveries),
        }
        if not kinds:
            continue
        if quality != "ACTUAL_FRESH":
            proposals.append(_proposal(
                "REVALIDATE_EVIDENCE", "EVIDENCE_QUALITY_BLOCKER", base,
                "Refresh an incomplete or old repository comparison.",
                "Acquire two current, actual observations before classifying change timing.",
                refs, evidence_quality=quality,
                limitations=["Not verified as a recent incident, regression or recovery."],
                metadata=metadata,
            ))
        elif deteriorations:
            proposals.append(_proposal(
                "INVESTIGATE_CHECK_CHANGE", "OBSERVED_TECHNICAL_PROBLEM", base,
                "Inspect a completed check's observed adverse transition.",
                "Review both original check runs on the same revision; determine cause before any repair.",
                refs + [row["source_ref"] for row in deteriorations],
                evidence_quality=quality,
                limitations=["A check conclusion is not proof of root cause, impact or commercial loss."],
                metadata=metadata,
            ))
        elif item["revision_changed"]:
            proposals.append(_proposal(
                "REVIEW_SOURCE_REVISION", "CURRENT_TECHNICAL_MOVEMENT", base,
                "Review an observed repository source revision change.",
                "Compare reviewed commits and actual test outcomes; do not infer improvement.",
                refs, evidence_quality=quality,
                limitations=["Revision movement does not establish deployed benefit."],
                metadata=metadata,
            ))
        elif recoveries:
            proposals.append(_proposal(
                "REVIEW_CHECK_RECOVERY", "CURRENT_TECHNICAL_MOVEMENT", base,
                "Verify an observed check recovery before closing an incident.",
                "Inspect matching completed check runs; verify any claimed fix independently.",
                refs + [row["source_ref"] for row in recoveries],
                evidence_quality=quality,
                limitations=["A green check does not verify root-cause resolution."],
                metadata=metadata,
            ))
        elif delta:
            proposals.append(_proposal(
                "REVIEW_TRACKER_TALLY", "CURRENT_TRACKER_MOVEMENT", base,
                "Inspect a change in the GitHub open issue-and-PR tally.",
                "Review the actual opened/closed issues and PRs; do not equate a tally change with workload value.",
                refs, evidence_quality=quality,
                limitations=["GitHub open_issues_count includes pull requests; no incident or closure inferred."],
                metadata=metadata,
            ))
    return proposals


def _candidate_proposals(candidates):
    # Round-robin across independently inspected target areas. Reuse score
    # is structural only, not subjective priority, safety, rights or revenue.
    buckets = {}
    seen = set()
    for candidate in candidates:
        if type(candidate) is not dict:
            continue
        key = candidate.get("key")
        if type(key) is not str or key in seen:
            continue
        seen.add(key)
        repository = candidate.get("repository")
        revision = candidate.get("head_sha")
        source_path = candidate.get("path")
        if (candidate.get("data_kind") != "ACTUAL"
                or candidate.get("freshness") != "CURRENT"
                or not candidate.get("test_paths")
                or not _sha40(candidate.get("blob_sha"))
                or not _sha64(candidate.get("code_sha256"))
                or not _sha40(revision)
                or type(repository) is not str
                or type(source_path) is not str
                or key != repository + ":" + source_path
                or not blob_ref(candidate.get("source_ref"), repository,
                                revision, source_path)
                or type(candidate.get("reuse_score")) is not int):
            continue
        target = candidate.get("target")
        if type(target) is not str or not target:
            continue
        feedback = candidate.get("feedback")
        # Do not re-suggest an operator-dismissed or already-reported
        # integration merely because it is structurally well ranked.
        if (type(feedback) is dict
                and feedback.get("basis") == "OPERATOR_REPORTED"
                and feedback.get("outcome") in {"NOT_USEFUL", "INTEGRATED"}):
            continue
        buckets.setdefault(target, []).append(candidate)

    for target in buckets:
        buckets[target].sort(key=lambda c: (-c["reuse_score"], c["key"]))

    selected = []
    for depth in range(_PER_TARGET):
        for target in sorted(buckets):
            group = buckets[target]
            if depth >= len(group) or len(selected) == _MAX_CODE_REVIEWS:
                continue
            candidate = group[depth]
            feedback = candidate.get("feedback")
            license_hint = candidate.get("license", "UNKNOWN")
            if type(license_hint) is not str or not license_hint or len(license_hint) > 100:
                raise ValueError("candidate license metadata malformed")
            rights_review = (
                "MISSING_OR_INCONCLUSIVE_LICENSE_METADATA"
                if license_hint.strip().upper() in {
                    "UNKNOWN", "NOASSERTION", "NONE", "UNLICENSED"
                }
                else "DECLARED_LICENSE_METADATA_NOT_INDEPENDENTLY_VERIFIED"
            )
            selected.append(_proposal(
                "REVIEW_THIRD_PARTY_SOURCE", "STRUCTURAL_REVIEW_ONLY",
                [candidate["target"], candidate["key"], candidate["code_sha256"]],
                "Evaluate an inspected implementation with structurally related tests.",
                "Independently review provenance, license terms, test applicability and local project requirements before considering a proposal.",
                [candidate["source_ref"]], evidence_quality="ACTUAL_CURRENT_SOURCE_BYTES",
                limitations=[
                    "Source and test paths were inspected, not executed or adopted.",
                    "License metadata is not a grant of permission.",
                    "No customer demand, engineering time saved, revenue or safety measured.",
                ],
                metadata={
                    "target":target,
                    "candidate_key":candidate["key"],
                    "structural_score_not_probability":candidate["reuse_score"],
                    "test_path_count_not_executed":len(candidate["test_paths"]),
                    "license_metadata_only":license_hint,
                    "license_review_status":rights_review,
                    "source_reuse_permission_confirmed":False,
                    "immutable_repo_revision_path_pin_verified":True,
                    "code_bytes_independently_executed_or_tested":False,
                    "declared_license_independently_verified":False,
                    "operator_feedback_not_independent":bool(feedback),
                },
            ))
    return selected


def decision_queue(report, *, max_items=_MAX_ITEMS):
    """Return stable, source-labeled suggestions derived from verified reports.

    Call only on reports that came from the canonical ledger. Unknown/bad
    report states do not receive action recommendations.
    """
    if type(max_items) is not int or not 1 <= max_items <= _MAX_ITEMS:
        raise ValueError("decision review output limit outside fixed bound")
    if type(report) is not dict:
        raise ValueError("report object required")
    if report.get("status") != "PASS" or report.get("schema_version") != 2:
        return {
            "status": "NO_VERIFIED_RECOMMENDATIONS",
            "items": [], "scope": "HUMAN_REVIEW_ONLY",
            "source_sha": report.get("source_sha"),
        }
    sha = report.get("source_sha")
    if type(sha) is not str or not _SHA40.fullmatch(sha):
        raise ValueError("source-bound report required")
    changes = report.get("repository_changes")
    candidates = report.get("reuse_candidates")
    if type(changes) is not list or type(candidates) is not list:
        raise ValueError("canonical report evidence missing")
    proposed = _change_proposals(changes) + _candidate_proposals(candidates)
    proposed.sort(key=lambda item: (
        {
            "OBSERVED_TECHNICAL_PROBLEM": 0,
            "EVIDENCE_QUALITY_BLOCKER": 1,
            "CURRENT_TECHNICAL_MOVEMENT": 2,
            "CURRENT_TRACKER_MOVEMENT": 3,
            "STRUCTURAL_REVIEW_ONLY": 4,
        }[item["band"]],
        item["subject"] if type(item["subject"]) is str
        else json.dumps(item["subject"], sort_keys=True),
        item["id"],
    ))
    selected = proposed[:max_items]
    for i, item in enumerate(selected, 1):
        item["review_order_not_value_rank"] = i
    return {
        "schema_version": 1,
        "status": "PROPOSED_REVIEW_NOT_EXECUTED" if selected else "NO_EVIDENCE_BACKED_PROPOSALS",
        "scope": "HUMAN_REVIEW_ONLY_NO_DOWNSTREAM_AUTHORITY",
        "source_sha": sha,
        "state_sequence": report.get("state_sequence"),
        "items": selected,
        "proposals_considered": len(proposed),
        "selection_method": "DETERMINISTIC_EVIDENCE_GATE_THEN_TARGET_ROUND_ROBIN",
        "max_candidate_reviews_per_target": _PER_TARGET,
        "operator_outcome_verified": False,
        "verified_revenue": None,
        "execution_authority": False,
    }
