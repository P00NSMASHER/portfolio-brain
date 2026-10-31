"""One-time owner-authorized, independently issued trust-root bootstrap.

This is NOT a general PR verifier and does not replace the protected ruleset.
Trusted-main workflow uses network-disabled test containers, then gives this
module only a repository-scoped App5121826 token to publish ONE exact-head
issuer-pinned bootstrap check if all reviewed candidate blob IDs match.
No request under this module touches any branch or ruleset.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import urllib.request
from pathlib import Path
from typing import Any

REPO = "P00NSMASHER/portfolio-brain"
PR = 804
BRANCH = "audit/source-admission-crosspath-20261030"
BOOTSTRAP_NAME = "portfolio-trust-anchor-bootstrap"
VERIFIER_APP_ID = 5121826
FOUNDATION_APP_ID = 15368
SHA = re.compile(r"[0-9a-f]{40}\Z")
# Pinned original reviewed candidate *file blobs*. A later legitimate merge
# with current main may change PR HEAD while preserving these exact bytes.
# Any modification to approved proposal content requires a newly reviewed
# protected-bootstrap policy release, not a mutable PR body/label override.
EXPECTED = {
    "verification/independent_verifier.py": "b8d16baead36388c4b05ea5b616484b8058259d2",
    "verification/source_admission.py": "2c61ff091b33479679105dc2209a5e88a1296dc8",
    "brain/validate.py": "0f57d9ed09b54cfadb32cd35d5e3a042b8015b03",
    ".github/workflows/reliability-day.yml": "92a90327544e175aaebeb89d2a46414070925b87",
    ".github/workflows/portfolio-source-acceptance-producer.yml": "cc10791403f38ca5bb223ba26dd1e69259120e4a",
    "tests/test_independent_verifier.py": "6d9789e826b78c5d9433616aaf48b99f9fe874a5",
    "tests/test_source_merge_admission.py": "a83f909a3bc9854719a3cce9083921355f41959d",
    "tests/test_source_observation_activation.py": "3177be6864aa5ecd0bcf10bd7790f7416b3e7346",
    "docs/rebuild/SOURCE_ADMISSION_CUTOVER.md": "f90818af1f194445ee66830d9dc0e668b895165a",
    "tests/test_observation_user_hold.py": "a3ad9f5e8e02ba3844f7e80cce689e8923fce997",
    "tests/test_standalone_x402_protocol.py": "710c6f1aacc41b15dd63bd06730981e8e86ff5e0",
}


class BootstrapDenied(RuntimeError):
    pass


def must(ok: bool, code: str) -> None:
    if not ok:
        raise BootstrapDenied(code)


def _api(token: str, path: str, *, method="GET", payload=None) -> Any:
    must(type(token) is str and bool(token), "CREDENTIAL_MISSING")
    must(type(path) is str and path.startswith("/")
         and not path.startswith("//") and "://" not in path
         and ".." not in path.split("/"), "API_PATH_INVALID")
    must(method in {"GET", "POST"}, "API_METHOD_FORBIDDEN")
    must(method != "POST" or path == "/check-runs", "API_WRITE_FORBIDDEN")
    if method == "GET":
        approved = (
            path in {"/branches/main", "/pulls/804"}
            or re.fullmatch(r"/compare/[0-9a-f]{40}\.\.\.[0-9a-f]{40}", path) is not None
            or re.fullmatch(r"/commits/[0-9a-f]{40}/check-runs\?per_page=100", path)
                is not None
        )
        # For contents, bind the request to one approved immutable path and
        # a syntactically exact SHA. verify_candidate separately pins the HEAD.
        approved = approved or any(
            re.fullmatch(r"/contents/" + re.escape(filename)
                         + r"\?ref=[0-9a-f]{40}", path) is not None
            for filename in EXPECTED
        )
        must(approved, "API_ROUTE_NOT_ALLOWLISTED")
    data = None if payload is None else json.dumps(payload, separators=(",", ":")).encode()
    req = urllib.request.Request(
        "https://api.github.com/repos/" + REPO + path,
        data=data,
        headers={"Authorization": "Bearer " + token,
                 "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28",
                 "User-Agent": "PortfolioBrain-trust-anchor-bootstrap",
                 **({"Content-Type": "application/json"} if data is not None else {})},
        method=method,
    )
    with urllib.request.urlopen(req, timeout=25) as response:
        raw=response.read(2_000_001)
    must(len(raw) <= 2_000_000, "API_RESPONSE_TOO_LARGE")
    return json.loads(raw) if raw else {}


def verify_candidate(read, head: str, *, exits: tuple[int, int, int]) -> dict:
    """Read-only, head-bound review independent of owner PR metadata claims."""
    must(type(head) is str and SHA.fullmatch(head) is not None, "HEAD_INVALID")
    must(exits == (0, 0, 0), "ISOLATED_TESTS_NOT_PASSING")
    main = read("/branches/main")
    source = main.get("commit", {}).get("sha")
    must(main.get("protected") is True and type(source) is str
         and SHA.fullmatch(source) is not None, "MAIN_UNPROTECTED")
    pr = read("/pulls/804")
    must(pr.get("number") == PR and pr.get("state") == "open"
         and pr.get("draft") is False and pr.get("merged") is False
         and pr.get("user", {}).get("login") == "P00NSMASHER"
         and pr.get("head", {}).get("sha") == head
         and pr.get("head", {}).get("ref") == BRANCH
         and pr.get("head", {}).get("repo", {}).get("full_name") == REPO
         and pr.get("base", {}).get("ref") == "main"
         and pr.get("base", {}).get("repo", {}).get("full_name") == REPO,
         "CANDIDATE_PR_IDENTITY_CHANGED")
    compare = read("/compare/" + source + "..." + head)
    files = compare.get("files")
    must(compare.get("merge_base_commit", {}).get("sha") == source
         and compare.get("behind_by") == 0
         and type(files) is list and 0 < len(files) < 300
         and {f.get("filename") for f in files if type(f) is dict} == set(EXPECTED)
         and all(type(f) is dict and f.get("status") in {"added", "modified"}
                 for f in files),
         "UNREVIEWED_CANDIDATE_DIFF")
    for filename, blob in EXPECTED.items():
        doc = read("/contents/" + filename + "?ref=" + head)
        must(type(doc) is dict and doc.get("type") == "file"
             and doc.get("sha") == blob and doc.get("encoding") == "base64",
             "CANDIDATE_FILE_BLOB_CHANGED")
    check_doc = read("/commits/" + head + "/check-runs?per_page=100")
    checks = check_doc.get("check_runs")
    must(type(check_doc.get("total_count")) is int
         and type(checks) is list
         and len(checks) == check_doc["total_count"] < 100,
         "FOUNDATION_CENSUS_INCOMPLETE")
    green = [row for row in checks if type(row) is dict
             and row.get("name") == "validate"]
    must(len(green) == 1 and green[0].get("app", {}).get("id") == FOUNDATION_APP_ID
         and green[0].get("head_sha") == head
         and green[0].get("status") == "completed"
         and green[0].get("conclusion") == "success",
         "EXACT_HEAD_FOUNDATION_REQUIRED")
    main_final = read("/branches/main")
    must(main_final.get("protected") is True
         and main_final.get("commit", {}).get("sha") == source,
         "PROTECTED_MAIN_CHANGED")
    return {"head_sha": head, "base_sha": source, "scope": "TRUST_ANCHOR_PR_804_ONLY"}


def issue_check(write_token: str, head_sha: str, summary: str) -> dict:
    """Sole allowed mutation, authenticated by a real independent GitHub App."""
    must(type(head_sha) is str and SHA.fullmatch(head_sha) is not None, "HEAD_INVALID")
    must(type(summary) is str and len(summary) < 3000, "SUMMARY_INVALID")
    doc = _api(write_token, "/check-runs", method="POST", payload={
        "name": BOOTSTRAP_NAME,
        "head_sha": head_sha,
        "status": "completed",
        "conclusion": "success",
        "output": {
            "title": "Source-bound trust-anchor bootstrap (single upgrade)",
            "summary": summary,
        },
    })
    must(doc.get("name") == BOOTSTRAP_NAME and doc.get("head_sha") == head_sha
         and doc.get("app", {}).get("id") == VERIFIER_APP_ID
         and doc.get("status") == "completed"
         and doc.get("conclusion") == "success",
         "INDEPENDENT_BOOTSTRAP_CHECK_UNVERIFIED")
    return {"check_run_id": doc.get("id"), "app_id": VERIFIER_APP_ID,
            "head_sha": head_sha, "success": True}


def main() -> int:
    p=argparse.ArgumentParser()
    p.add_argument("--head-sha", required=True)
    p.add_argument("--full-exit-file", type=Path, required=True)
    p.add_argument("--phase1-exit-file", type=Path, required=True)
    p.add_argument("--operating-exit-file", type=Path, required=True)
    a=p.parse_args()
    exits=tuple(int(p.read_text(encoding="utf-8").strip()) for p in
                (a.full_exit_file, a.phase1_exit_file, a.operating_exit_file))
    # Both original reads and the one check publication use the *separate*
    # App5121826 principal; candidate code never receives this credential.
    independent_token = os.environ.get("PORTFOLIO_VERIFIER_TOKEN", "")
    verified=verify_candidate(
        lambda route: _api(independent_token, route),
        a.head_sha, exits=exits,
    )
    result=issue_check(
        independent_token, a.head_sha,
        "Independently re-ran full, phase1 and operating-mode tests in network-disabled "
        "containers; pinned all eleven reviewed candidate file blobs, verified exact "
        "GitHub PR head/current-main ancestry, and checked issuer-pinned Foundation. "
        "One authorized verifier trust-root upgrade only; no 12-hour acceptance.",
    )
    print(json.dumps({**result, "base_sha": verified["base_sha"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
