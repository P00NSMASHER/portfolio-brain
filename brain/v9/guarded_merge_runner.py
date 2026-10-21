"""Trusted-main, event-driven PR discovery for the native guarded merger.

Never executes pull-request source. One independent verification event admits
at most three explicitly labeled, trusted-author Markdown-only PRs. It does
not create scheduled tasks, checks, credentials, or direct merge operations.
"""
import json
import os
import sys

from brain.v9.guarded_merge import (
    Denied, GitHub, LABEL, REPO, TRUSTED_AUTHORS, run, sha,
    native_auto_merge_enabled,
)

MAX_CANDIDATES = 3
OPEN_PR_PAGE_SIZE = 20
MAX_OPEN_PR_PAGES = 5  # Five full pages (100 PRs) are intentionally rejected.

# Diagnostics expose only fixed, source-reviewed codes. Never print provider
# error bodies, credentials, or arbitrary exception text.
SAFE_RUNNER_DENIALS = frozenset({
    "SHA_INVALID",
    "GITHUB_TOKEN_MISSING",
    "REPOSITORY_IDENTITY_CHANGED",
    "REPOSITORY_REST_SETTING_INVALID",
    "REPOSITORY_GRAPHQL_SETTING_UNVERIFIED",
    "REPOSITORY_SETTING_CONFLICT",
    "RUNNER_PROTECTED_MAIN_MOVED",
    "RUNNER_OPEN_PR_CENSUS_INCOMPLETE",
    "RUNNER_OPEN_PR_CENSUS_CHANGED",
    "RUNNER_PR_NUMBER_INVALID",
    "RUNNER_DUPLICATE_CANDIDATES",
    "GITHUB_ROUTE_NOT_ALLOWLISTED",
    "GITHUB_METHOD_INVALID",
    "GITHUB_GRAPHQL_NOT_APPROVED",
    "GITHUB_PROVIDER_UNAVAILABLE",
    "GITHUB_RESPONSE_TOO_LARGE",
    "GITHUB_RESPONSE_NOT_JSON",
    "HTTP_401",
    "HTTP_403",
    "HTTP_404",
    "HTTP_429",
    "HTTP_500",
    "HTTP_502",
    "HTTP_503",
    "HTTP_504",
})


def blocked_report(error):
    """Keep write uncertainty unchanged while revealing bounded failure class."""
    code = str(error) if isinstance(error, Denied) else ""
    return {
        "status": "RUNNER_BLOCKED",
        "reason_code": code if code in SAFE_RUNNER_DENIALS else "UNCLASSIFIED",
        "provider_writes": "UNVERIFIED_NO_RETRY",
    }


def _read_open_pr_pages(api, root):
    """Bounded, complete census; no first-page-only admission."""
    collected = []
    seen = set()
    for page in range(1, MAX_OPEN_PR_PAGES + 1):
        path = (root + "pulls?state=open&per_page=" + str(OPEN_PR_PAGE_SIZE)
                + "&page=" + str(page))
        batch = api.get(path)
        if (type(batch) is not list or len(batch) > OPEN_PR_PAGE_SIZE
                or any(type(row) is not dict for row in batch)):
            raise Denied("RUNNER_OPEN_PR_CENSUS_INCOMPLETE")
        for row in batch:
            number = row.get("number")
            if type(number) is not int or not 0 < number < 10**9:
                raise Denied("RUNNER_PR_NUMBER_INVALID")
            if number in seen:
                raise Denied("RUNNER_DUPLICATE_CANDIDATES")
            seen.add(number)
            collected.append(row)
        if len(batch) < OPEN_PR_PAGE_SIZE:
            return collected
    # At least 100 open PRs, or the response was truncated at our hard cap.
    raise Denied("RUNNER_OPEN_PR_CENSUS_INCOMPLETE")


def complete_open_pull_census(api, root):
    """Two consistent original reads or zero admission; no provider writes.

    GitHub pagination is not an atomic snapshot. A changing census is an
    uncertainty, never permission to use a partial list. Individual eligible
    PRs still undergo all source-bound final pre-enrollment rechecks.
    """
    first = _read_open_pr_pages(api, root)
    second = _read_open_pr_pages(api, root)
    if first != second:
        raise Denied("RUNNER_OPEN_PR_CENSUS_CHANGED")
    return second


def dispatch_once(make_client, expected_main, *, apply=True):
    sha(expected_main)
    enumeration = make_client()
    root = "repos/" + REPO + "/"
    info = enumeration.get("repos/" + REPO)
    if not native_auto_merge_enabled(enumeration, info):
        return {"status": "REPOSITORY_AUTO_MERGE_SETTING_DISABLED",
                "candidate_count": 0, "provider_writes": 0, "decisions": []}
    main = enumeration.get(root + "branches/main")
    if main.get("protected") is not True or main.get("commit", {}).get("sha") != expected_main:
        raise Denied("RUNNER_PROTECTED_MAIN_MOVED")
    rows = complete_open_pull_census(enumeration, root)
    chosen = []
    for row in rows:
        if row.get("state") != "open" or row.get("draft") is not False:
            continue
        if row.get("user", {}).get("login") not in TRUSTED_AUTHORS:
            continue
        if row.get("base", {}).get("ref") != "main":
            continue
        if LABEL not in {item.get("name") for item in row.get("labels", [])
                         if type(item) is dict}:
            continue
        number = row.get("number")
        if type(number) is not int or number <= 0:
            raise Denied("RUNNER_PR_NUMBER_INVALID")
        chosen.append(number)
    require_unique = len(set(chosen)) == len(chosen)
    if not require_unique:
        raise Denied("RUNNER_DUPLICATE_CANDIDATES")
    chosen.sort()
    decisions = []
    writes = 0
    for number in chosen[:MAX_CANDIDATES]:
        try:
            result = run(make_client(), number=number,
                         expected_main=expected_main, apply=apply)
            state = result["status"]
            effect = result["provider_writes"]
        except Denied as exc:
            state = "BLOCKED:" + str(exc)
            effect = "UNKNOWN_AFTER_POST" if str(exc).startswith("AUTO_MERGE_") else 0
        decisions.append({"pr_number": number, "status": state,
                          "provider_writes": effect})
        if effect == "UNKNOWN_AFTER_POST":
            # A write may have succeeded. Never try another candidate.
            return {"status": "POST_WRITE_UNCERTAIN_MANUAL_RECONCILIATION",
                    "candidate_count": len(chosen), "provider_writes": "UNKNOWN",
                    "decisions": decisions}
        writes += effect
    return {"status": "OBSERVED",
            "candidate_count": len(chosen),
            "processed": len(decisions),
            "more_candidates_waiting": len(chosen) > MAX_CANDIDATES,
            "provider_writes": writes,
            "decisions": decisions}


def main():
    token = os.environ.get("GH_TOKEN", "")
    source = os.environ.get("GITHUB_SHA", "")
    try:
        result = dispatch_once(lambda: GitHub(token), source, apply=True)
        print(json.dumps(result, sort_keys=True))
        return 2 if result["status"] == "POST_WRITE_UNCERTAIN_MANUAL_RECONCILIATION" else 0
    except (Denied, ValueError) as error:
        print(json.dumps(blocked_report(error), sort_keys=True))
        return 2


if __name__ == "__main__":
    sys.exit(main())
