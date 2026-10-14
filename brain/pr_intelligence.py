"""Bounded source-pinned PR/CI observation for RETALLY and Product Factory.

This is read-only advisory evidence. A green draft is not a deployed or
authorized product, a buyer, or recovered funds. The existing adapter controls
the same 24 GitHub GET budget, including retries and paginated observations.
"""
from datetime import datetime
import re

from brain.adapters import policy
from brain.core import BrainError, require

FOCUS_REPOSITORIES = (
    ("retally", "P00NSMASHER/github-value-hunt-ledger"),
    ("product-factory", "P00NSMASHER/x402-product-factory"),
)
SAMPLE_SIZE = 15
_SHA = re.compile("[0-9a-f]{40}")
_REF = re.compile("[A-Za-z0-9][A-Za-z0-9._/-]{0,149}")
_ADVERSE = {"failure", "cancelled", "timed_out", "action_required",
            "startup_failure", "stale"}
_CONCLUSIONS = _ADVERSE | {"success", "neutral", "skipped", None}
_STATUSES = {"completed", "queued", "in_progress", "pending", "waiting", "requested"}


def _branch(value):
    require(type(value) is str and _REF.fullmatch(value)
            and ".." not in value and "//" not in value
            and not value.endswith(".lock"), "FOCUS_BRANCH_INVALID")
    return value


def _strict_pr(raw, repo):
    """Keep only safe provider identity facts; never emit PR titles or body."""
    require(type(raw) is dict and type(raw.get("number")) is int
            and 0 < raw["number"] < 100000000, "FOCUS_PR_NUMBER_INVALID")
    number = raw["number"]
    require(raw.get("state") == "open" and type(raw.get("draft")) is bool,
            "FOCUS_PR_STATE_UNVERIFIED")
    require(raw.get("html_url") == f"https://github.com/{repo}/pull/{number}",
            "FOCUS_PR_URL_INVALID")
    head, base = raw.get("head"), raw.get("base")
    require(type(head) is dict and type(base) is dict
            and type(head.get("repo")) is dict
            and type(base.get("repo")) is dict
            and head["repo"].get("full_name") == repo
            and base["repo"].get("full_name") == repo,
            "FOCUS_PR_FORK_OR_BASE_UNVERIFIED")
    sha = head.get("sha")
    require(type(sha) is str and _SHA.fullmatch(sha),
            "FOCUS_PR_HEAD_SHA_INVALID")
    href, bref = _branch(head.get("ref")), _branch(base.get("ref"))
    updated = raw.get("updated_at")
    require(type(updated) is str
            and re.fullmatch(
                "[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z",
                updated), "FOCUS_PR_TIME_INVALID")
    try:
        datetime.strptime(updated, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise BrainError("FOCUS_PR_TIME_INVALID") from exc
    title = raw.get("title")
    require(type(title) is str and len(title) <= 500,
            "FOCUS_PR_TITLE_INVALID")
    return {
        "number": number,
        "head_sha": sha,
        "head_ref": href,
        "base_ref": bref,
        "updated_at": updated,
        "draft": raw["draft"],
        "url": f"https://github.com/{repo}/pull/{number}",
        # The RETALLY ledger contains unrelated projects; title only filters.
        "retally_named": "retally" in title.casefold(),
    }


def _candidate_from_list(rows, repo, project_id, default_branch):
    require(type(rows) is list and len(rows) <= SAMPLE_SIZE,
            "FOCUS_PR_BOUNDED_PAGE_INVALID")
    valid, invalid, ids = [], 0, set()
    for raw in rows:
        try:
            pr = _strict_pr(raw, repo)
            require(pr["number"] not in ids, "FOCUS_PR_DUPLICATE")
            ids.add(pr["number"])
            valid.append(pr)
        except (BrainError, KeyError, TypeError, UnicodeError, ValueError):
            invalid += 1
    valid.sort(key=lambda p: (p["updated_at"], p["number"]), reverse=True)
    matching = [p for p in valid
                if project_id != "retally" or p["retally_named"]]
    base = {
        "sampled_count": len(rows),
        "discarded_rows": invalid,
        "sampling_scope": "LATEST_15_OPEN_PRS_NOT_EXHAUSTIVE",
    }
    if not matching:
        return dict(base, status="NO_MATCHING_PR_IN_BOUNDED_SAMPLE")
    top = matching[0]
    parent = next((p["number"] for p in valid
                   if p["number"] != top["number"]
                   and p["head_ref"] == top["base_ref"]), None)
    return dict(
        base,
        status="PR_OBSERVED_CHECKS_NOT_YET_VERIFIED",
        pr_number=top["number"],
        pr_url=top["url"],
        head_sha=top["head_sha"],
        head_ref=top["head_ref"],
        base_ref=top["base_ref"],
        draft=top["draft"],
        updated_at=top["updated_at"],
        stacked_on_nondefault_branch=top["base_ref"] != default_branch,
        sampled_parent_pr=parent,
        dependency_scope="BRANCH_REFERENCE_ONLY_NOT_VERIFIED_GIT_ANCESTRY",
    )


def _exact_checks(page, sha):
    """Reject incomplete/duplicate/cross-commit check evidence as unverified."""
    require(type(page) is dict
            and type(page.get("total_count")) is int
            and 0 <= page["total_count"] <= 100
            and type(page.get("check_runs")) is list
            and len(page["check_runs"]) == page["total_count"],
            "FOCUS_CHECK_PAGE_INCOMPLETE")
    seen = set()
    counts = {"success": 0, "neutral": 0, "skipped": 0,
              "adverse": 0, "incomplete": 0}
    for row in page["check_runs"]:
        require(type(row) is dict and type(row.get("id")) is int
                and row["id"] > 0 and row["id"] not in seen
                and row.get("head_sha") == sha
                and row.get("status") in _STATUSES
                and row.get("conclusion") in _CONCLUSIONS,
                "FOCUS_CHECK_IDENTITY_INVALID")
        seen.add(row["id"])
        conclusion = row["conclusion"]
        if row["status"] != "completed" or conclusion is None:
            counts["incomplete"] += 1
        elif conclusion in _ADVERSE:
            counts["adverse"] += 1
        else:
            counts[conclusion] += 1
    state = (
        "NO_CHECK_RUNS_OBSERVED" if not seen else
        "ADVERSE_CHECKS_OBSERVED" if counts["adverse"] else
        "INCOMPLETE_CHECKS_OBSERVED" if counts["incomplete"] else
        "SKIPPED_CHECKS_NOT_ACCEPTANCE" if counts["skipped"] else
        "CHECKS_GREEN_NOT_RELEASE_OR_BUSINESS_ACCEPTANCE"
    )
    return dict(counts, status=state, checked_head_sha=sha,
                complete_single_page=True, count=len(seen))


def _unavailable(status):
    return {"status": status, "checks": {
        "status": "NOT_VERIFIED", "complete_single_page": False,
    }}


def _action(review, experiment):
    if type(review.get("pr_number")) is not int:
        return "Collect bounded source-pinned PR evidence; then " + experiment
    number = review["pr_number"]
    ci = review["checks"]["status"]
    if ci == "ADVERSE_CHECKS_OBSERVED":
        return f"Investigate exact-head adverse CI for PR #{number}; then " + experiment
    if ci != "CHECKS_GREEN_NOT_RELEASE_OR_BUSINESS_ACCEPTANCE":
        return f"Verify exact-head checks for PR #{number}; then " + experiment
    if review["stacked_on_nondefault_branch"]:
        parent = review["sampled_parent_pr"]
        dependency = (f"PR #{parent}" if parent is not None
                      else "the unsampled parent branch")
        return (f"Independently review {dependency} before PR #{number}; then "
                + experiment)
    return f"Independently review PR #{number}; then " + experiment


def observe_priority_prs(api, observed_sources, *, review_contracts):
    """Two bounded PR pages then up to two exact-head check pages.

    No extra adapter, state writer, schedule, provider scope, or authority.
    Source pagination/retries use the original shared 24-GET maximum.
    """
    ceiling = policy()["max_requests_per_operation"]
    require(ceiling == 24 and type(observed_sources) is dict
            and type(review_contracts) is dict, "FOCUS_INPUT_INVALID")
    reports = {}
    for project, repo in FOCUS_REPOSITORIES:
        source = observed_sources.get(repo)
        contract = review_contracts.get(project)
        require(type(contract) is dict
                and type(contract.get("next_test")) is str,
                "FOCUS_WORK_CONTRACT_MISSING")
        if source is None:
            reports[project] = _unavailable("SOURCE_UNOBSERVED")
            continue
        if not callable(getattr(api, "get", None)):
            reports[project] = _unavailable("GET_ADAPTER_UNAVAILABLE")
            continue
        if type(api.requests) is not int or api.requests >= ceiling:
            reports[project] = _unavailable("REQUEST_BUDGET_UNAVAILABLE")
            continue
        try:
            default = _branch(source.get("default_branch"))
            page = api.get(
                f"/repos/{repo}/pulls?state=open&per_page={SAMPLE_SIZE}"
                "&sort=updated&direction=desc"
            )
            report = _candidate_from_list(page, repo, project, default)
            if "pr_number" not in report:
                report["checks"] = _unavailable("NOT_SELECTED")["checks"]
            reports[project] = report
        except (BrainError, KeyError, TypeError, ValueError, UnicodeError):
            reports[project] = _unavailable("PR_PAGE_UNVERIFIED")
    for project, repo in FOCUS_REPOSITORIES:
        result = reports[project]
        if "pr_number" not in result:
            result["review_action"] = _action(result, review_contracts[project]["next_test"])
            continue
        if type(api.requests) is not int or api.requests >= ceiling:
            result["checks"] = _unavailable("REQUEST_BUDGET_UNAVAILABLE")["checks"]
            result["status"] = "PR_OBSERVED_CHECKS_UNVERIFIED"
        else:
            try:
                checks = api.get(
                    f"/repos/{repo}/commits/{result['head_sha']}/"
                    "check-runs?per_page=100"
                )
                result["checks"] = _exact_checks(checks, result["head_sha"])
                result["status"] = "PR_AND_CHECKS_OBSERVED"
            except (BrainError, KeyError, ValueError, TypeError, UnicodeError):
                result["checks"] = _unavailable("CHECK_PAGE_UNVERIFIED")["checks"]
                result["status"] = "PR_OBSERVED_CHECKS_UNVERIFIED"
        result["review_action"] = _action(result, review_contracts[project]["next_test"])
        result["production_merge_authority"] = False
        result["payment_or_external_contact_authority"] = False
        result["buyer_value_verified"] = False
    return reports
