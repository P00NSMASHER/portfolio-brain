#!/usr/bin/env python3
"""Publish the independent exact-head portfolio-phase1-gate.

This module is executed only from a fresh checkout of default-branch verifier
control code. Candidate code is tested in an isolated container before an App
token is minted and never receives verifier credentials.
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

REPOSITORY = "P00NSMASHER/portfolio-brain"
CHECK_NAME = "portfolio-phase1-gate"
FOUNDATION_CHECK = "validate"
FOUNDATION_APP_ID = 15368
VERIFIER_APP_ID = 5121826
IMMUTABLE_TRUST_ANCHORS = {
    ".github/workflows/portfolio-independent-verifier.yml",
    "verification/independent_verifier.py",
}
MAX_COMPARE_FILES = 300


class IndependentVerifierError(RuntimeError):
    pass


def req(ok: bool, message: str) -> None:
    if not ok:
        raise IndependentVerifierError(message)


def _sha40(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 40 and all(c in "0123456789abcdef" for c in value)


def _api(token: str, path: str, *, method: str = "GET", payload: dict[str, Any] | None = None) -> Any:
    req(isinstance(token, str) and token, "verifier token missing")
    req(
        path.startswith("/") and "://" not in path
        and all(segment != ".." for segment in path.split("/")),
        "unsafe GitHub API path",
    )
    data = None if payload is None else json.dumps(payload, separators=(",", ":")).encode("utf-8")
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "portfolio-brain-independent-verifier/1.0",
    }
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        f"https://api.github.com/repos/{REPOSITORY}{path}",
        data=data,
        headers=headers,
        method=method,
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read()
        return json.loads(raw.decode("utf-8")) if raw else {}


def _current_main_changed_files(compare: dict[str, Any]) -> set[str]:
    rows = compare.get("files")
    req(isinstance(rows, list), "current-main compare file listing malformed")
    # GitHub's compare API caps file output at 300 entries. Exactly 300 is
    # ambiguous, so fail closed rather than risk missing a trust-anchor change.
    req(len(rows) < MAX_COMPARE_FILES, "current-main compare file listing hit verifier bound")
    changed: set[str] = set()
    for row in rows:
        filename = row.get("filename")
        req(
            isinstance(filename, str) and filename and not filename.startswith("/"),
            "current-main compare filename invalid",
        )
        changed.add(filename)
    return changed


def verify_exact_head(
    *,
    token: str,
    pr_number: int,
    expected_head_sha: str,
    full_exit: int,
    phase1_exit: int,
    operating_exit: int,
) -> tuple[bool, str]:
    req(type(pr_number) is int and pr_number > 0, "PR number invalid")
    req(_sha40(expected_head_sha), "expected head SHA invalid")
    pr = _api(token, f"/pulls/{pr_number}")
    req(pr.get("head", {}).get("repo", {}).get("full_name") == REPOSITORY, "PR head repository mismatch")
    req(pr.get("base", {}).get("repo", {}).get("full_name") == REPOSITORY, "PR base repository mismatch")
    req(pr.get("base", {}).get("ref") == "main", "PR base is not main")
    req(pr.get("head", {}).get("sha") == expected_head_sha, "PR head moved after Foundation validation")

    main = _api(token, "/branches/main")
    main_sha = main.get("commit", {}).get("sha")
    req(_sha40(main_sha), "main head SHA invalid")
    compare = _api(
        token,
        "/compare/"
        + urllib.parse.quote(main_sha, safe="")
        + "..."
        + urllib.parse.quote(expected_head_sha, safe=""),
    )
    merge_base = compare.get("merge_base_commit", {}).get("sha")
    req(merge_base == main_sha, "candidate does not contain current main")
    changed_files = _current_main_changed_files(compare)
    touched_anchors = sorted(changed_files & IMMUTABLE_TRUST_ANCHORS)
    req(not touched_anchors, "candidate modifies immutable verifier trust anchor: " + ",".join(touched_anchors))

    checks = _api(token, f"/commits/{expected_head_sha}/check-runs?per_page=100").get("check_runs", [])
    foundation = [
        row for row in checks
        if row.get("name") == FOUNDATION_CHECK
        and row.get("app", {}).get("id") == FOUNDATION_APP_ID
        and row.get("conclusion") == "success"
    ]
    req(len(foundation) >= 1, "exact-head Foundation validation is not successful")

    tests_ok = full_exit == 0 and phase1_exit == 0 and operating_exit == 0
    summary = (
        "Independent isolated verification passed: full regressions, focused Phase 1 regressions, "
        "operating-mode validation, current-main ancestry, and exact-head Foundation validation."
        if tests_ok else
        f"Independent isolated verification failed: full={full_exit}, phase1={phase1_exit}, operating={operating_exit}."
    )
    return tests_ok, summary


def publish_check(*, token: str, head_sha: str, success: bool, summary: str) -> dict[str, Any]:
    req(_sha40(head_sha), "check head SHA invalid")
    req(isinstance(summary, str) and summary, "check summary missing")
    payload = {
        "name": CHECK_NAME,
        "head_sha": head_sha,
        "status": "completed",
        "conclusion": "success" if success else "failure",
        "output": {
            "title": "Portfolio Brain independent verifier",
            "summary": summary[:60000],
        },
    }
    result = _api(token, "/check-runs", method="POST", payload=payload)
    req(result.get("name") == CHECK_NAME, "published check name mismatch")
    req(result.get("head_sha") == head_sha, "published check head mismatch")
    req(result.get("app", {}).get("id") == VERIFIER_APP_ID, "check was not published by independent verifier App")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pr-number", type=int, required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--full-exit-file", type=Path, required=True)
    parser.add_argument("--phase1-exit-file", type=Path, required=True)
    parser.add_argument("--operating-exit-file", type=Path, required=True)
    args = parser.parse_args()

    token = os.environ.get("PORTFOLIO_VERIFIER_TOKEN", "")
    try:
        exits = [
            int(args.full_exit_file.read_text().strip()),
            int(args.phase1_exit_file.read_text().strip()),
            int(args.operating_exit_file.read_text().strip()),
        ]
        success, summary = verify_exact_head(
            token=token,
            pr_number=args.pr_number,
            expected_head_sha=args.head_sha,
            full_exit=exits[0],
            phase1_exit=exits[1],
            operating_exit=exits[2],
        )
        check = publish_check(token=token, head_sha=args.head_sha, success=success, summary=summary)
        print(json.dumps({
            "check_run_id": check.get("id"),
            "head_sha": args.head_sha,
            "success": success,
            "app_id": check.get("app", {}).get("id"),
        }, sort_keys=True))
        return 0 if success else 1
    except Exception as exc:
        # If source verification itself fails but the token is usable, publish a
        # red exact-head check rather than leaving protected integration ambiguous.
        try:
            publish_check(
                token=token,
                head_sha=args.head_sha,
                success=False,
                summary=f"Independent verifier blocked: {type(exc).__name__}: {str(exc)[:1000]}",
            )
        except Exception:
            pass
        raise


if __name__ == "__main__":
    raise SystemExit(main())
