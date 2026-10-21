"""Trusted-main, event-driven PR discovery for the native guarded merger.

Never executes pull-request source. One independent verification event admits
at most three explicitly labeled, trusted-author Markdown-only PRs. It does
not create scheduled tasks, checks, credentials, or direct merge operations.
"""
import json
import os
import re
import sys

from brain.v9.guarded_merge import (
    Denied, GitHub, LABEL, REPO, TRUSTED_AUTHORS, run, sha,
    native_auto_merge_enabled,
)

MAX_CANDIDATES = 3


def safe_denial_code(error):
    """Expose only policy-defined codes; never echo provider or token text."""
    if type(error) is Denied:
        code = str(error)
        if re.fullmatch(r"[A-Z][A-Z0-9_]{0,79}", code):
            return code
    return "UNCLASSIFIED_FAILURE"


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
    rows = enumeration.get(root + "pulls?state=open&per_page=100")
    if type(rows) is not list or len(rows) >= 100 or any(type(x) is not dict for x in rows):
        raise Denied("RUNNER_OPEN_PR_CENSUS_INCOMPLETE")
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
        # A top-level failure is never evidence of zero provider writes.
        # Retain the conservative no-retry state and a bounded diagnostic.
        print(json.dumps({"status": "RUNNER_BLOCKED",
                          "reason_code": safe_denial_code(error),
                          "provider_writes": "UNVERIFIED_NO_RETRY"}, sort_keys=True))
        return 2


if __name__ == "__main__":
    sys.exit(main())
