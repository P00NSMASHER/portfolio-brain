"""Inert, source-bound review model for *pre-check-completion* native enrollment.

NEVER imports a GitHub client, obtains credentials, edits rules, schedules work,
calls the native mutation, or authorizes a protected merge. All inputs are
fixtures/modelled observations. A future, separately reviewed production
integration MUST independently rederive them from original authenticated GitHub
provider reads; callers cannot elevate these booleans into authority.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

REPOSITORY = "P00NSMASHER/portfolio-brain"
REPOSITORY_ID = 1387747549
RULESET_ID = 24182301
SOURCE_SHA = "35ad71868f74e6d4f749a35630a1b86802b91ed0"
CHECK_ISSUERS = {"validate": 15368, "portfolio-phase1-gate": 5121826}
TRUSTED_AUTHORS = frozenset(("P00NSMASHER", "portfolio-brain-v8-runtime[bot]"))
LABEL = "brain:guarded-automerge"
SHA_RE = re.compile(r"[0-9a-f]{40}\Z")
PROOF_KEYS = (
    "source_acceptance_verified",
    "active_ruleset_verified",
    "zero_bypass_verified",
    "strict_required_checks_verified",
    "head_document_blobs_verified",
    "docs_only_scope_verified",
    "no_unresolved_review_threads",
    "trusted_head_ancestry_verified",
    "complete_check_census_verified",
)


@dataclass(frozen=True)
class Decision:
    status: str
    reason: str
    provider_writes: int = 0
    merge_authorized: bool = False
    revocation_authorized: bool = False


def _hold(reason):
    return Decision("HOLD", reason)


def _revoke(reason):
    # Advisory only: a future controller would need separate authority,
    # an exact-head conditional mutation and original-provider readback.
    return Decision("REVIEW_ONLY_REVOCATION_REQUIRED", reason)


def _sha(value):
    return type(value) is str and SHA_RE.fullmatch(value) is not None


def _validated_snapshot(snapshot):
    """Classify one simulated original-provider snapshot, NEVER a merge grant."""
    if type(snapshot) is not dict:
        return "PROVIDER_SNAPSHOT_NOT_OBJECT", None
    if not (snapshot.get("repository") == REPOSITORY
            and type(snapshot.get("repository_id")) is int
            and snapshot.get("repository_id") == REPOSITORY_ID
            and type(snapshot.get("ruleset_id")) is int
            and snapshot.get("ruleset_id") == RULESET_ID):
        return "ORIGINAL_REPOSITORY_RULESET_IDENTITY_UNVERIFIED", None
    if not (_sha(snapshot.get("main_sha"))
            and snapshot["main_sha"] == SOURCE_SHA
            and snapshot.get("source_acceptance_sha") == SOURCE_SHA
            and snapshot.get("protected_main") is True):
        return "CURRENT_SOURCE_ACCEPTANCE_UNVERIFIED", None
    if (type(snapshot.get("required_check_issuers")) is not dict
            or snapshot["required_check_issuers"] != CHECK_ISSUERS):
        return "INDEPENDENT_PROTECTED_CHECK_ISSUERS_CHANGED", None
    for key in PROOF_KEYS:
        if snapshot.get(key) is not True:
            return "ADVISORY_PROVIDER_PROOF_MISSING_" + key.upper(), None

    pr = snapshot.get("pr")
    if type(pr) is not dict:
        return "PR_IDENTITY_MISSING", None
    if not (type(pr.get("number")) is int and 0 < pr["number"] < 10**9
            and pr.get("state") == "open"
            and pr.get("draft") is False
            and pr.get("merged") is False
            and pr.get("mergeable") is True
            and pr.get("base_branch") == "main"
            and pr.get("base_sha") == SOURCE_SHA
            and _sha(pr.get("head_sha"))
            and pr["head_sha"] != SOURCE_SHA
            and type(pr.get("author")) is str
            and pr["author"] in TRUSTED_AUTHORS
            and pr.get("auto_merge") is None
            and type(pr.get("labels")) is list
            and all(type(x) is str for x in pr["labels"])
            and LABEL in pr["labels"]):
        return "ORIGINAL_PR_ADMISSION_IDENTITY_UNVERIFIED", None

    # BEHIND is deliberately excluded even though GitHub currently reports
    # viewerCanEnableAutoMerge=true for some stale PRs. They cannot complete
    # under strict up-to-date required status checks without another push.
    if not (pr.get("rest_mergeable_state") == "blocked"
            and pr.get("graphql_merge_state") == "BLOCKED"
            and pr.get("viewer_can_enable_auto_merge") is True):
        return "GITHUB_NATIVE_EARLY_ELIGIBILITY_NOT_PROVEN", None

    runs = snapshot.get("check_runs")
    if (type(runs) is not list or not (1 <= len(runs) < 100)
            or type(snapshot.get("check_total_count")) is not int
            or snapshot["check_total_count"] != len(runs)
            or any(type(run) is not dict for run in runs)):
        return "ORIGINAL_REQUIRED_CHECK_CENSUS_INCOMPLETE", None
    status_by_name = {}
    for name, app_id in CHECK_ISSUERS.items():
        matches = [check for check in runs
                   if type(check) is dict and check.get("name") == name]
        if len(matches) > 1:
            return "REQUIRED_CHECK_MISSING_OR_AMBIGUOUS", None
        if not matches:
            # The strict issuer-pinned protected rule still blocks the merge.
            # Some installed Apps only issue their check after other CI ends.
            status_by_name[name] = "not_issued"
            continue
        check = matches[0]
        if not (check.get("head_sha") == pr["head_sha"]
                and type(check.get("app_id")) is int
                and check["app_id"] == app_id):
            return "REQUIRED_CHECK_WRONG_HEAD_OR_ISSUER", None
        status = check.get("status")
        conclusion = check.get("conclusion")
        if status == "completed" and conclusion == "success":
            status_by_name[name] = "success"
        elif status in ("queued", "in_progress") and conclusion is None:
            status_by_name[name] = "pending"
        else:
            return "REQUIRED_CHECK_FAILED_AMBIGUOUS_OR_CANCELLED", None

    values = sorted(status_by_name.values())
    if values not in (["pending", "success"], ["not_issued", "success"]):
        return "MUST_HAVE_ONE_SUCCESS_AND_ONE_REQUIRED_CHECK_OUTSTANDING", None
    return None, (pr["number"], pr["head_sha"], pr["base_sha"])


def plan_early_enrollment(initial, final):
    """Two authenticated observations would be required by a future controller.

    This is a *review-only proposal* to enroll while exactly one of the two
    independently issued final-merge checks is still queued/in progress.
    No post/write is implemented. GitHub itself must enforce BOTH required
    checks and up-to-date protection at actual merge time.
    """
    first_problem, initial_identity = _validated_snapshot(initial)
    if first_problem:
        return _hold("INITIAL_" + first_problem)
    last_problem, final_identity = _validated_snapshot(final)
    if last_problem:
        return _hold("FINAL_" + last_problem)
    if initial_identity != final_identity:
        return _hold("PR_HEAD_BASE_OR_NUMBER_CHANGED_BETWEEN_READS")
    return Decision(
        status="REVIEW_ONLY_EARLY_ADMISSION_CANDIDATE",
        reason="EXACT_DOCS_SOURCE_VERIFIED_ONE_SUCCESS_ONE_REQUIRED_CHECK_OUTSTANDING_NO_WRITE_AUTHORITY",
    )


def interpret_provider_readback(record, *, expected_number, expected_head):
    """Advisory post-enrollment census; no mutation, merge or certification."""
    if not (_sha(expected_head) and type(expected_number) is int
            and type(record) is dict
            and record.get("number") == expected_number
            and record.get("head_sha") == expected_head
            and record.get("base_sha") == SOURCE_SHA):
        return _hold("PROVIDER_READBACK_IDENTITY_OR_HEAD_UNVERIFIED")
    state = record.get("state")
    if state == "open" and record.get("merged") is False:
        auto = record.get("auto_merge")
        if auto is None:
            return _hold("NOT_ENROLLED_DO_NOT_RETRY_UNCERTAIN_POST")
        if type(auto) is dict and auto.get("merge_method") == "squash":
            return Decision("GITHUB_NATIVE_ENROLLMENT_VISIBLE",
                            "WAIT_FOR_GITHUB_PROTECTED_FINAL_CHECKS_AND_INDEPENDENT_READBACK")
        return _hold("FOREIGN_OR_UNVERIFIED_ENROLLMENT")
    if (state == "closed" and record.get("merged") is True
            and _sha(record.get("merge_commit_sha"))):
        return Decision("GITHUB_REPORTED_MERGED_REQUIRES_INDEPENDENT_PROVENANCE",
                        "CHECK_ORIGINAL_NATIVE_MERGE_EVENTS_PROTECTED_MAIN_AND_FINAL_ISSUER_CHECKS")
    return _hold("PROVIDER_READBACK_UNRESOLVED")


def plan_post_enrollment_monitor(receipt, current):
    """Fail closed after visible enrollment without performing any provider write.

    The receipt is the immutable identity observed when native SQUASH enrollment
    became visible. The current value must be a newly derived, complete original-
    provider snapshot. A revocation result is an advisory escalation only; it
    deliberately carries no authority to disable enrollment or merge.
    """
    if not (type(receipt) is dict
            and receipt.get("repository") == REPOSITORY
            and type(receipt.get("repository_id")) is int
            and receipt.get("repository_id") == REPOSITORY_ID
            and type(receipt.get("ruleset_id")) is int
            and receipt.get("ruleset_id") == RULESET_ID
            and receipt.get("source_sha") == SOURCE_SHA
            and type(receipt.get("number")) is int
            and 0 < receipt["number"] < 10**9
            and _sha(receipt.get("head_sha"))
            and receipt["head_sha"] != SOURCE_SHA
            and receipt.get("base_sha") == SOURCE_SHA
            and receipt.get("merge_method") == "squash"):
        return _hold("ENROLLMENT_RECEIPT_IDENTITY_UNVERIFIED")

    if type(current) is not dict:
        return _revoke("CURRENT_PROVIDER_SNAPSHOT_UNREADABLE")
    if not (current.get("repository") == REPOSITORY
            and type(current.get("repository_id")) is int
            and current.get("repository_id") == REPOSITORY_ID
            and type(current.get("ruleset_id")) is int
            and current.get("ruleset_id") == RULESET_ID
            and current.get("main_sha") == SOURCE_SHA
            and current.get("source_acceptance_sha") == SOURCE_SHA
            and current.get("protected_main") is True
            and type(current.get("required_check_issuers")) is dict
            and current["required_check_issuers"] == CHECK_ISSUERS):
        return _revoke("REPOSITORY_RULESET_OR_SOURCE_CHANGED")
    for key in PROOF_KEYS:
        if current.get(key) is not True:
            return _revoke("PROVIDER_PROOF_INVALID_" + key.upper())

    pr = current.get("pr")
    if type(pr) is not dict:
        return _revoke("CURRENT_PR_IDENTITY_UNREADABLE")
    if pr.get("number") != receipt["number"]:
        return _revoke("PR_NUMBER_CHANGED_AFTER_ENROLLMENT")
    if pr.get("head_sha") != receipt["head_sha"]:
        return _revoke("HEAD_CHANGED_AFTER_ENROLLMENT")
    if (pr.get("base_branch") != "main"
            or pr.get("base_sha") != receipt["base_sha"]):
        return _revoke("BASE_CHANGED_AFTER_ENROLLMENT")

    if (pr.get("state") == "closed" and pr.get("merged") is True
            and _sha(pr.get("merge_commit_sha"))):
        return Decision(
            "GITHUB_REPORTED_MERGED_REQUIRES_INDEPENDENT_PROVENANCE",
            "CHECK_ORIGINAL_NATIVE_MERGE_EVENTS_PROTECTED_MAIN_AND_FINAL_ISSUER_CHECKS",
        )
    if not (pr.get("state") == "open"
            and pr.get("draft") is False
            and pr.get("merged") is False
            and pr.get("mergeable") is True):
        return _revoke("PR_STATE_NO_LONGER_SAFE_AFTER_ENROLLMENT")
    if type(pr.get("author")) is not str or pr["author"] not in TRUSTED_AUTHORS:
        return _revoke("TRUSTED_AUTHOR_CHANGED_AFTER_ENROLLMENT")
    if (type(pr.get("labels")) is not list
            or any(type(label) is not str for label in pr["labels"])
            or LABEL not in pr["labels"]):
        return _revoke("OPT_IN_LABEL_REMOVED")

    auto = pr.get("auto_merge")
    if auto is None:
        return _hold("NOT_ENROLLED_DO_NOT_RETRY_UNCERTAIN_POST")
    if type(auto) is not dict or auto.get("merge_method") != receipt["merge_method"]:
        return _revoke("FOREIGN_OR_UNVERIFIED_ENROLLMENT")

    runs = current.get("check_runs")
    if (type(runs) is not list or not (1 <= len(runs) < 100)
            or type(current.get("check_total_count")) is not int
            or current["check_total_count"] != len(runs)
            or any(type(run) is not dict for run in runs)):
        return _revoke("ORIGINAL_REQUIRED_CHECK_CENSUS_INCOMPLETE")

    states = []
    for name, app_id in CHECK_ISSUERS.items():
        matches = [run for run in runs if run.get("name") == name]
        if len(matches) > 1:
            return _revoke("REQUIRED_CHECK_MISSING_OR_AMBIGUOUS")
        if not matches:
            states.append("not_issued")
            continue
        run = matches[0]
        if not (run.get("head_sha") == receipt["head_sha"]
                and type(run.get("app_id")) is int
                and run["app_id"] == app_id):
            return _revoke("REQUIRED_CHECK_WRONG_HEAD_OR_ISSUER")
        if (run.get("status") == "completed"
                and run.get("conclusion") == "success"):
            states.append("success")
        elif (run.get("status") in ("queued", "in_progress")
                and run.get("conclusion") is None):
            states.append("pending")
        else:
            return _revoke("REQUIRED_CHECK_FAILED_AMBIGUOUS_OR_CANCELLED")

    if "success" not in states:
        return _revoke("NO_INDEPENDENT_REQUIRED_CHECK_SUCCESS")
    return Decision(
        "REVIEW_ONLY_ENROLLMENT_MONITOR",
        "WAIT_FOR_GITHUB_PROTECTED_FINAL_CHECKS_AND_INDEPENDENT_READBACK",
    )


if __name__ == "__main__":
    raise SystemExit("REVIEW_ONLY_NO_EXECUTABLE_ENROLLMENT")
