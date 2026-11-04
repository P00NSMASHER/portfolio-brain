"""Single-use App5121826 verifier migration, pinned to owner-reviewed PR #845.

This policy is merged to protected main by ordinary independent checks FIRST.
Never imports or executes candidate-side control code with credentials. Its only
provider mutation is publishing one issuer-authenticated exact-head check.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import urllib.error
import urllib.request

REPOSITORY = "P00NSMASHER/portfolio-brain"
BASELINE_SHA = "15969a677135957d41abe55a3e8401da198048c2"
PR_NUMBER = 845
PR_BRANCH = "security/fail-closed-rename-trust-anchor-20261104"
FOUNDATION_APP = 15368
INDEPENDENT_APP = 5121826
CHECK_NAME = "portfolio-phase1-gate"
SOURCE_BLOBS = {
    "verification/independent_verifier.py": "b180a5c066285ab908e2d3e272e5fe7cbfe275c5",
    "tests/test_independent_verifier.py": "71714b75afb1cb58766162f8c00fa8450d0c9731",
}
MAIN_PREIMAGES = {
    "verification/independent_verifier.py": "0fdc89d7c4b9d5bfc4e89d16d2b749c33ff2bfde",
    "tests/test_independent_verifier.py": "9c31d5b887fd6c71de0ef10fac92d20dcd77c2b7",
}
SHA = re.compile(r"[0-9a-f]{40}\Z")
MAX_RESPONSE = 2_000_000


class MigrationDenied(ValueError):
    pass


def need(condition, reason):
    if not condition:
        raise MigrationDenied(reason)


def sha_ok(value):
    return type(value) is str and SHA.fullmatch(value) is not None


def json_strict(raw):
    def unique(pairs):
        output = {}
        for k, v in pairs:
            need(k not in output, "MIGRATION_PROVIDER_DUPLICATE_KEY")
            output[k] = v
        return output

    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=unique,
                          parse_constant=lambda _:
                          (_ for _ in ()).throw(MigrationDenied("MIGRATION_PROVIDER_NONFINITE")))
    except (ValueError, UnicodeError) as exc:
        raise MigrationDenied("MIGRATION_PROVIDER_INVALID_JSON") from exc


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, new_url):
        return None


def valid_route(method, path):
    if method == "POST":
        return path == "/check-runs"
    if method != "GET":
        return False
    if path in ("/branches/main", "/pulls/845"):
        return True
    if re.fullmatch(r"/compare/[0-9a-f]{40}\.\.\.[0-9a-f]{40}", path):
        return True
    if re.fullmatch(r"/commits/[0-9a-f]{40}/check-runs\?per_page=100", path):
        return True
    if re.fullmatch(r"/check-runs/[1-9][0-9]{0,15}", path):
        return True
    return any(
        re.fullmatch(r"/contents/" + re.escape(name) + r"\?ref=[0-9a-f]{40}", path)
        for name in SOURCE_BLOBS
    )


def github_api(token, path, *, method="GET", payload=None):
    need(type(token) is str and 20 <= len(token) <= 4096,
         "MIGRATION_SCOPED_TOKEN_MISSING")
    need(valid_route(method, path), "MIGRATION_API_ROUTE_NOT_ALLOWED")
    need(payload is None if method == "GET" else type(payload) is dict,
         "MIGRATION_API_REQUEST_INVALID")
    body = None if payload is None else json.dumps(
        payload, sort_keys=True, allow_nan=False, separators=(",", ":")).encode()
    need(body is None or len(body) < 10_000, "MIGRATION_API_PAYLOAD_BOUND")
    url = "https://api.github.com/repos/" + REPOSITORY + path
    request = urllib.request.Request(
        url, data=body, method=method,
        headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "portfolio-brain-single-pr-trust-root-migration",
            **({"Content-Type": "application/json"} if body else {}),
        },
    )
    opener = urllib.request.build_opener(NoRedirect())
    try:
        with opener.open(request, timeout=25) as response:
            need(response.status == (201 if method == "POST" else 200),
                 "MIGRATION_PROVIDER_STATUS_INVALID")
            raw = response.read(MAX_RESPONSE + 1)
    except (urllib.error.URLError, OSError) as exc:
        # Publication may have succeeded despite a network/readback error.
        raise MigrationDenied("MIGRATION_PROVIDER_UNCERTAIN_READBACK_REQUIRED") from exc
    need(len(raw) <= MAX_RESPONSE, "MIGRATION_PROVIDER_RESPONSE_TOO_LARGE")
    result = json_strict(raw)
    need(type(result) is dict, "MIGRATION_PROVIDER_OBJECT_INVALID")
    return result


def file_blob(read, path, ref):
    response = read("/contents/" + path + "?ref=" + ref)
    need(type(response) is dict and response.get("type") == "file"
         and response.get("encoding") == "base64"
         and sha_ok(response.get("sha"))
         and type(response.get("size")) is int
         and 1 <= response["size"] < 260_000
         and type(response.get("content")) is str,
         "MIGRATION_FILE_EVIDENCE_INVALID")
    try:
        raw = base64.b64decode(response["content"].replace("\n", ""), validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise MigrationDenied("MIGRATION_FILE_EVIDENCE_INVALID") from exc
    need(len(raw) == response["size"], "MIGRATION_FILE_SIZE_INVALID")
    native_blob = hashlib.sha1(
        b"blob " + str(len(raw)).encode() + b"\x00" + raw).hexdigest()
    need(response["sha"] == native_blob, "MIGRATION_FILE_BLOB_HASH_MISMATCH")
    return native_blob


def check_census(read, head, *, require_original_failure):
    result = read("/commits/" + head + "/check-runs?per_page=100")
    rows = result.get("check_runs") if type(result) is dict else None
    need(type(rows) is list and type(result.get("total_count")) is int
         and len(rows) == result["total_count"] < 100
         and all(type(row) is dict for row in rows),
         "MIGRATION_CHECK_CENSUS_INCOMPLETE")
    foundation = [r for r in rows if r.get("name") == "validate"]
    need(len(foundation) == 1
         and foundation[0].get("app", {}).get("id") == FOUNDATION_APP
         and foundation[0].get("head_sha") == head
         and foundation[0].get("status") == "completed"
         and foundation[0].get("conclusion") == "success",
         "MIGRATION_EXACT_HEAD_FOUNDATION_REQUIRED")
    gate = [r for r in rows if r.get("name") == CHECK_NAME]
    if require_original_failure:
        need(len(gate) == 1 and gate[0].get("app", {}).get("id") == INDEPENDENT_APP
             and gate[0].get("head_sha") == head
             and gate[0].get("status") == "completed"
             and gate[0].get("conclusion") == "failure",
             "MIGRATION_ORIGINAL_IMMUTABLE_GATE_NOT_REJECTED")
    else:
        need(all(r.get("app", {}).get("id") == INDEPENDENT_APP
                 and r.get("head_sha") == head
                 and r.get("conclusion") != "success" for r in gate),
             "MIGRATION_EXISTING_GREEN_GATE_UNEXPECTED")


def verify_source(read, head, trusted_main, *, require_original_failure=False):
    """Read only original GitHub facts; no local asserted PASS flags."""
    need(sha_ok(head) and sha_ok(trusted_main), "MIGRATION_SOURCE_SHA_INVALID")
    main = read("/branches/main")
    need(type(main) is dict and main.get("protected") is True
         and main.get("commit", {}).get("sha") == trusted_main,
         "MIGRATION_PROTECTED_MAIN_MOVED")
    lineage = read("/compare/" + BASELINE_SHA + "..." + trusted_main)
    need(type(lineage) is dict
         and lineage.get("merge_base_commit", {}).get("sha") == BASELINE_SHA
         and type(lineage.get("behind_by")) is int
         and lineage["behind_by"] == 0,
         "MIGRATION_TRUST_ROOT_ANCESTRY_INVALID")
    pr = read("/pulls/845")
    need(type(pr) is dict and pr.get("number") == PR_NUMBER
         and pr.get("state") == "open"
         and pr.get("draft") is True and pr.get("merged") is False
         and pr.get("user", {}).get("login") == "P00NSMASHER"
         and pr.get("base", {}).get("ref") == "main"
         and pr.get("base", {}).get("sha") == trusted_main
         and pr.get("base", {}).get("repo", {}).get("full_name") == REPOSITORY
         and pr.get("head", {}).get("sha") == head
         and pr.get("head", {}).get("ref") == PR_BRANCH
         and pr.get("head", {}).get("repo", {}).get("full_name") == REPOSITORY,
         "MIGRATION_PR_IDENTITY_OR_DRAFT_MISMATCH")
    compare = read("/compare/" + trusted_main + "..." + head)
    rows = compare.get("files") if type(compare) is dict else None
    need(type(rows) is list and len(rows) == len(SOURCE_BLOBS)
         and compare.get("merge_base_commit", {}).get("sha") == trusted_main
         and type(compare.get("behind_by")) is int
         and compare["behind_by"] == 0,
         "MIGRATION_SOURCE_COMPARE_INCOMPLETE")
    observed = {}
    for row in rows:
        need(type(row) is dict
             and row.get("status") == "modified"
             and type(row.get("filename")) is str
             and row["filename"] in SOURCE_BLOBS
             and row["filename"] not in observed
             and row.get("previous_filename") is None
             and row.get("sha") == SOURCE_BLOBS[row["filename"]],
             "MIGRATION_UNREVIEWED_CHANGE_OR_RENAME")
        observed[row["filename"]] = row["sha"]
    need(observed == SOURCE_BLOBS, "MIGRATION_SOURCE_FILE_SET_MISMATCH")
    for path, expected_blob in SOURCE_BLOBS.items():
        need(file_blob(read, path, head) == expected_blob,
             "MIGRATION_REVIEWED_SOURCE_BLOB_CHANGED")
        need(file_blob(read, path, trusted_main) == MAIN_PREIMAGES[path],
             "MIGRATION_TRUSTED_PREIMAGE_DRIFT")
    check_census(read, head, require_original_failure=require_original_failure)
    latest = read("/pulls/845")
    current = read("/branches/main")
    need(current.get("protected") is True
         and current.get("commit", {}).get("sha") == trusted_main
         and latest.get("head", {}).get("sha") == head
         and latest.get("base", {}).get("sha") == trusted_main
         and latest.get("draft") is True and latest.get("merged") is False,
         "MIGRATION_FINAL_SOURCE_DRIFT")
    return {
        "status": "EXACT_SOURCE_INDEPENDENTLY_READ_NOT_APPROVED",
        "source_sha": head, "main_sha": trusted_main,
        "candidate_files": sorted(observed),
        "verified_original_app_failure": require_original_failure,
        "provider_writes": 0,
    }


def issue_exact_check(read, write, head, trusted_main):
    # Verify the original fail-closed App verdict before issuing any exception.
    evidence = verify_source(
        read, head, trusted_main, require_original_failure=True)
    summary = (
        "One-time owner-authorized trust-anchor migration for PR #845. "
        "Protected-main policy independently verified the exactly two immutable "
        "reviewed blobs, original protected preimages, source ancestry, "
        "genuine App15368 exact-head Foundation, original App5121826 red "
        "immutability control, and isolated full/focused/operating tests. "
        "NO ruleset change, token expansion or bypass.")
    payload = {
        "name": CHECK_NAME, "head_sha": head,
        "status": "completed", "conclusion": "success",
        "output": {"title": "One-time source-bound trust-anchor migration",
                   "summary": summary},
    }
    posted = write("/check-runs", payload)
    need(type(posted) is dict and type(posted.get("id")) is int
         and posted["id"] > 0, "MIGRATION_CHECK_ID_MISSING")
    check = read("/check-runs/" + str(posted["id"]))
    need(type(check) is dict and check.get("id") == posted["id"]
         and check.get("name") == CHECK_NAME
         and check.get("head_sha") == head
         and check.get("app", {}).get("id") == INDEPENDENT_APP
         and check.get("status") == "completed"
         and check.get("conclusion") == "success",
         "MIGRATION_INDEPENDENT_APP_READBACK_INVALID")
    return {
        "status": "GENUINE_INDEPENDENT_APP_CHECK_PUBLISHED_NOT_MERGED",
        "check_run_id": check["id"], "app_id": INDEPENDENT_APP,
        "head_sha": head, "main_sha": trusted_main,
        "files": evidence["candidate_files"], "provider_writes": 1,
        "merged": False, "live_verified": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("preflight", "publish"), required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--trusted-main", required=True)
    args = parser.parse_args()
    if args.mode == "preflight":
        token = os.environ.get("GITHUB_TOKEN", "")
    else:
        token = os.environ.get("PORTFOLIO_VERIFIER_TOKEN", "")
    def get(path):
        return github_api(token, path)
    try:
        if args.mode == "preflight":
            result = verify_source(get, args.head, args.trusted_main)
        else:
            result = issue_exact_check(
                get, lambda path, payload: github_api(
                    token, path, method="POST", payload=payload),
                args.head, args.trusted_main)
        print(json.dumps(result, sort_keys=True))
        return 0
    except MigrationDenied as exc:
        # The failed provider call may have reached GitHub; never auto-retry POST.
        print(json.dumps({"status": "BLOCKED_OR_UNCERTAIN",
                          "reason": str(exc), "merged": False},
                         sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
