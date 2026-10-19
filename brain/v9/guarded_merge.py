"""GitHub-native auto-merge admission controller.

No direct merge API, ruleset edits, workflow edits, or credential provisioning.
This module is inert unless explicitly invoked from reviewed trusted-main code.
It fails closed until a separately governed acceptance receipt exists for main.
"""
from __future__ import annotations
import argparse
import base64
import hashlib
import http.client
import json
import os
import re
import sys
from urllib.parse import quote

REPO = "P00NSMASHER/portfolio-brain"
REPO_ID = 1387747549
RULESET_ID = 24182301
SHA = re.compile(r"[a-f0-9]{40}\Z")
DATE = re.compile(r"[0-9]{8}\Z")
SAFE_PATH = re.compile(r"[A-Za-z0-9_./-]{1,240}\Z")
ALLOWED_PREFIXES = ("docs/genesis/", "docs/rebuild/")
LABEL = "brain:guarded-automerge"
TRUSTED_AUTHORS = frozenset(("P00NSMASHER", "portfolio-brain-v8-runtime[bot]"))
REQUIRED_CHECKS = {"validate": 15368, "portfolio-phase1-gate": 5121826}
MAX_FILES = 6
MAX_CHANGED_LINES = 240
MAX_BYTES = 1_048_576
MAX_REQUESTS = 40


class Denied(ValueError):
    """Fail-closed, sanitized admission reason."""


def require(ok, reason):
    if not ok:
        raise Denied(reason)


def sha(value):
    require(type(value) is str and SHA.fullmatch(value) is not None, "SHA_INVALID")
    return value


def git_blob_sha(raw):
    return hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()


def checked_document(value):
    require(type(value) is dict and value.get("type") == "file"
            and value.get("encoding") == "base64"
            and type(value.get("size")) is int and 0 < value["size"] <= 50000
            and type(value.get("sha")) is str and SHA.fullmatch(value["sha"])
            and type(value.get("content")) is str, "DOCUMENT_SCHEMA")
    try:
        raw = base64.b64decode(value["content"].replace("\n", ""), validate=True)
        raw.decode("utf-8")
    except (ValueError, UnicodeError):
        raise Denied("DOCUMENT_ENCODING") from None
    require(len(raw) == value["size"] and git_blob_sha(raw) == value["sha"],
            "DOCUMENT_BLOB_IDENTITY")
    require(not any(part in raw for part in (
        b"-----BEGIN PRIVATE KEY-----", b"ghp_", b"github_pat_", b"sk-proj-"
    )), "DOCUMENT_POSSIBLE_SECRET")
    return raw


def checked_path(path):
    require(type(path) is str and SAFE_PATH.fullmatch(path) is not None
            and all(p not in ("", ".", "..") for p in path.split("/"))
            and path.endswith(".md")
            and any(path.startswith(p) for p in ALLOWED_PREFIXES)
            and path not in ("docs/genesis/GUARDED_NATIVE_AUTOMERGE.md",),
            "NOT_LOW_RISK_DOCUMENT")
    return path


def ruleset_passes(r):
    require(type(r) is dict and r.get("id") == RULESET_ID
            and r.get("enforcement") == "active"
            and r.get("bypass_actors") == []
            and r.get("conditions", {}).get("ref_name") == {
                "include": ["refs/heads/main"], "exclude": []
            }, "PROTECTED_RULESET_MISMATCH")
    types = {x.get("type"): x for x in r.get("rules", []) if type(x) is dict}
    require({"deletion", "non_fast_forward", "pull_request",
             "required_status_checks"} <= types.keys(), "PROTECTED_RULES_MISSING")
    pull = types["pull_request"].get("parameters", {})
    require(pull.get("required_review_thread_resolution") is True
            and type(pull.get("required_approving_review_count")) is int
            and pull["required_approving_review_count"] >= 0,
            "REVIEW_GATE_MISSING")
    checks = types["required_status_checks"].get("parameters", {})
    listed = checks.get("required_status_checks")
    require(checks.get("strict_required_status_checks_policy") is True
            and type(listed) is list and all(type(x) is dict for x in listed),
            "INDEPENDENT_CHECK_GATE_MISSING")
    required = {(x.get("context"), x.get("integration_id")) for x in listed}
    require(set(REQUIRED_CHECKS.items()) <= required, "INDEPENDENT_CHECK_ISSUER_MISSING")


def accepted_source(api, main):
    """Read only an independent, one-commit acceptance record for this source.

    A credential-bearing producer cannot issue acceptance through this function.
    Prior source receipts are intentionally ineligible.
    """
    short = main[:8]
    ref_prefix = "brain-acceptance-" + short + "-"
    try:
        matches = api.get("repos/" + REPO + "/git/matching-refs/heads/" + ref_prefix)
    except Denied as exc:
        if str(exc) == "HTTP_404":
            raise Denied("SOURCE_ACCEPTANCE_NOT_YET_RECORDED") from None
        raise
    require(type(matches) is list and len(matches) == 1, "ACCEPTANCE_BRANCH_NOT_UNIQUE")
    ref = matches[0]
    full_ref = ref.get("ref") if type(ref) is dict else None
    require(type(full_ref) is str and full_ref.startswith("refs/heads/" + ref_prefix)
            and DATE.fullmatch(full_ref[len("refs/heads/" + ref_prefix):]) is not None
            and ref.get("object", {}).get("type") == "commit",
            "ACCEPTANCE_BRANCH_IDENTITY")
    tip = sha(ref["object"].get("sha"))
    name = full_ref[len("refs/heads/"):]
    date = full_ref[len("refs/heads/" + ref_prefix):]
    commit = api.get("repos/" + REPO + "/git/commits/" + tip)
    require(type(commit) is dict and commit.get("sha") == tip
            and type(commit.get("parents")) is list
            and len(commit["parents"]) == 1
            and commit["parents"][0].get("sha") == main,
            "ACCEPTANCE_COMMIT_ANCESTRY")
    path = "acceptance/finish-soak-" + short + "-" + date + ".json"
    compare = api.get("repos/" + REPO + "/compare/" + main + "..." + tip)
    changed = compare.get("files") if type(compare) is dict else None
    require(type(changed) is list and len(changed) == 1
            and changed[0].get("filename") == path
            and changed[0].get("status") == "added"
            and compare.get("ahead_by") == 1
            and compare.get("behind_by") == 0
            and compare.get("merge_base_commit", {}).get("sha") == main,
            "ACCEPTANCE_BRANCH_SCOPE")
    data = api.get("repos/" + REPO + "/contents/" + path + "?ref=" + tip)
    raw = checked_document(data)
    try:
        record = json.loads(raw)
    except (ValueError, UnicodeError):
        raise Denied("ACCEPTANCE_JSON_INVALID") from None
    require(type(record) is dict
            and record.get("source_sha") == main
            and record.get("decision") == "RELEASED"
            and record.get("status") == "PASS"
            and record.get("scope") == "SOURCE_SPECIFIC_UNATTENDED_PRODUCTION_CORE_RELIABILITY_ONLY",
            "ACCEPTANCE_STATUS_OR_SOURCE")
    run = record.get("original_run_evidence", {})
    terminal = record.get("terminal_state_replay", {})
    proof = record.get("proof", {})
    require(type(run.get("completed_span_seconds")) is int
            and run["completed_span_seconds"] >= 21600
            and type(run.get("maximum_gap_seconds")) is int
            and run["maximum_gap_seconds"] <= 5400
            and run.get("all_success_attempt_one") is True
            and run.get("all_original_core_state_parent_child_links_contiguous") is True
            and terminal.get("pending_events") == 0
            and terminal.get("sqlite_integrity") == "PASS"
            and terminal.get("foreign_keys") == "PASS"
            and terminal.get("deterministic_report_reproduction") == "PASS"
            and proof.get("technical_workflow_conclusion") == "success",
            "ACCEPTANCE_ORIGINAL_EVIDENCE_MISSING")
    return {"acceptance_ref": name, "acceptance_commit": tip}


def check_pr(pr, number, source):
    require(type(pr) is dict and pr.get("number") == number
            and pr.get("state") == "open" and pr.get("draft") is False
            and pr.get("merged") is False and pr.get("mergeable") is True
            and pr.get("mergeable_state") == "clean"
            and pr.get("base", {}).get("ref") == "main"
            and pr.get("base", {}).get("sha") == source
            and pr.get("base", {}).get("repo", {}).get("full_name") == REPO
            and pr.get("head", {}).get("repo", {}).get("full_name") == REPO
            and pr.get("user", {}).get("login") in TRUSTED_AUTHORS,
            "PR_IDENTITY_OR_MERGEABILITY")
    head = sha(pr.get("head", {}).get("sha"))
    require(type(pr.get("node_id")) is str and 10 < len(pr["node_id"]) < 200,
            "PR_NODE_ID_MISSING")
    labels = pr.get("labels")
    require(type(labels) is list and all(type(x) is dict for x in labels)
            and LABEL in {x.get("name") for x in labels}, "TRUSTED_LABEL_MISSING")
    changed = pr.get("changed_files")
    require(type(changed) is int and 1 <= changed <= MAX_FILES
            and type(pr.get("additions")) is int
            and type(pr.get("deletions")) is int
            and 0 < pr["additions"] + pr["deletions"] <= MAX_CHANGED_LINES,
            "PR_CHANGE_BOUNDS")
    return head


def checked_checks(checks, head):
    require(type(checks) is dict and type(checks.get("total_count")) is int
            and 0 <= checks["total_count"] < 100
            and type(checks.get("check_runs")) is list
            and len(checks["check_runs"]) == checks["total_count"],
            "CHECK_CENSUS_INCOMPLETE")
    for check_name, app_id in REQUIRED_CHECKS.items():
        matches = [x for x in checks["check_runs"]
                   if type(x) is dict and x.get("name") == check_name]
        require(len(matches) == 1
                and matches[0].get("status") == "completed"
                and matches[0].get("conclusion") == "success"
                and matches[0].get("app", {}).get("id") == app_id
                and matches[0].get("head_sha") == head,
                "INDEPENDENT_HEAD_CHECK_FAILED")


THREADS_QUERY = """query($id: ID!) {
  node(id: $id) { ... on PullRequest {
    id
    reviewThreads(first: 100) {
      pageInfo { hasNextPage }
      nodes { isResolved }
    }
  } }
}"""
ENABLE_MUTATION = """mutation($id: ID!) {
  enablePullRequestAutoMerge(input: { pullRequestId: $id, mergeMethod: SQUASH }) {
    pullRequest { id autoMergeRequest { enabledAt } }
  }
}"""


def checked_threads(response, node_id):
    require(type(response) is dict and not response.get("errors"), "REVIEW_THREADS_QUERY_FAILED")
    node = response.get("data", {}).get("node")
    rows = node.get("reviewThreads") if type(node) is dict and node.get("id") == node_id else None
    require(type(rows) is dict and rows.get("pageInfo", {}).get("hasNextPage") is False
            and type(rows.get("nodes")) is list
            and len(rows["nodes"]) <= 100
            and all(type(x) is dict and x.get("isResolved") is True for x in rows["nodes"]),
            "UNRESOLVED_OR_INCOMPLETE_REVIEW_THREADS")


def check_files(api, number, head, expected):
    root = "repos/" + REPO + "/"
    files = api.get(root + "pulls/" + str(number) + "/files?per_page=100")
    require(type(files) is list and len(files) == expected, "PR_FILES_NOT_COMPLETE")
    seen = set()
    for file in files:
        require(type(file) is dict and file.get("status") in ("added", "modified"),
                "PR_UNSAFE_FILE_STATUS")
        path = checked_path(file.get("filename"))
        require(path not in seen, "PR_DUPLICATE_FILE")
        seen.add(path)
        content = api.get(root + "contents/" + quote(path, safe="/") + "?ref=" + head)
        raw = checked_document(content)
        require(content["sha"] == file.get("sha")
                and len(raw) <= 50000, "PR_CHANGED_FILE_MISMATCH")


def observe(api, number, expected_main):
    """All evidence originates with the provider; no caller-supplied green flags."""
    require(type(number) is int and 0 < number < 10**9, "PR_NUMBER_INVALID")
    sha(expected_main)
    root = "repos/" + REPO + "/"
    info = api.get("repos/" + REPO)
    require(type(info) is dict and info.get("id") == REPO_ID
            and info.get("full_name") == REPO
            and info.get("default_branch") == "main"
            and info.get("archived") is False, "REPOSITORY_IDENTITY_CHANGED")
    if info.get("allow_auto_merge") is not True:
        return {"status": "REPOSITORY_AUTO_MERGE_SETTING_DISABLED",
                "provider_writes": 0, "enrolled": False}
    ruleset_passes(api.get(root + "rulesets/" + str(RULESET_ID)))
    main = api.get(root + "branches/main")
    require(main.get("protected") is True
            and main.get("commit", {}).get("sha") == expected_main,
            "PROTECTED_MAIN_SOURCE_MOVED")
    acceptance = accepted_source(api, expected_main)
    pr = api.get(root + "pulls/" + str(number))
    head = check_pr(pr, number, expected_main)
    if pr.get("auto_merge") is not None:
        require(pr["auto_merge"].get("merge_method") == "squash",
                "EXISTING_NATIVE_AUTO_MERGE_NOT_OURS")
        return {"status": "ALREADY_ENROLLED", "number": number,
                "head_sha": head, "base_sha": expected_main,
                "provider_writes": 0, "enrolled": True}
    checked_checks(api.get(root + "commits/" + head + "/check-runs?per_page=100"), head)
    check_files(api, number, head, pr["changed_files"])
    checked_threads(api.graphql(THREADS_QUERY, {"id": pr["node_id"]}), pr["node_id"])
    # Single final source/PR reread; native GitHub protection independently
    # enforces up-to-date checks even if another actor races this observer.
    # Repeat the trusted platform ruleset on the last read boundary.
    ruleset_passes(api.get(root + "rulesets/" + str(RULESET_ID)))
    live = api.get(root + "branches/main")
    again = api.get(root + "pulls/" + str(number))
    require(live.get("commit", {}).get("sha") == expected_main
            and again.get("head", {}).get("sha") == head
            and again.get("base", {}).get("sha") == expected_main
            and again.get("draft") is False and again.get("state") == "open"
            and again.get("auto_merge") is None
            and {x.get("name") for x in again.get("labels", []) if type(x) is dict} >= {LABEL},
            "PR_CHANGED_DURING_ADMISSION")
    return {"status": "ADMISSIBLE", "number": number,
            "node_id": pr["node_id"], "head_sha": head,
            "base_sha": expected_main, "acceptance": acceptance,
            "provider_writes": 0, "enrolled": False}


def run(api, *, number, expected_main, apply=False):
    proof = observe(api, number, expected_main)
    if proof["status"] != "ADMISSIBLE" or not apply:
        return {k: v for k, v in proof.items() if k != "node_id"}
    node_id = proof["node_id"]
    try:
        result = api.graphql(ENABLE_MUTATION, {"id": node_id})
    except Exception:
        raise Denied("AUTO_MERGE_WRITE_UNCERTAIN_READBACK_REQUIRED") from None
    require(type(result) is dict and not result.get("errors")
            and result.get("data", {}).get("enablePullRequestAutoMerge", {})
                .get("pullRequest", {}).get("id") == node_id,
            "AUTO_MERGE_WRITE_UNCERTAIN_READBACK_REQUIRED")
    current = api.get("repos/" + REPO + "/pulls/" + str(number))
    require(type(current) is dict
            and current.get("head", {}).get("sha") == proof["head_sha"],
            "AUTO_MERGE_PROVIDER_READBACK_UNVERIFIED")
    # GitHub may merge immediately when the required checks are already green.
    # Treat that outcome as a merge only after the original provider says so.
    if current.get("state") == "closed" and current.get("merged") is True:
        require(type(current.get("merge_commit_sha")) is str
                and SHA.fullmatch(current["merge_commit_sha"]),
                "AUTO_MERGE_COMPLETION_UNVERIFIED")
        return {"status": "NATIVE_AUTO_MERGE_COMPLETED",
                "number": number, "head_sha": proof["head_sha"],
                "base_sha": expected_main, "provider_writes": 1,
                "enrolled": True, "merged": True,
                "merge_commit_sha": current["merge_commit_sha"]}
    require(current.get("auto_merge") is not None
            and current["auto_merge"].get("merge_method") == "squash"
            and current.get("state") == "open",
            "AUTO_MERGE_PROVIDER_READBACK_UNVERIFIED")
    return {"status": "NATIVE_AUTO_MERGE_ENROLLED",
            "number": number, "head_sha": proof["head_sha"],
            "base_sha": expected_main, "provider_writes": 1,
            "enrolled": True, "merged": False}


class GitHub:
    """Fixed GitHub host, bounded response, no untrusted route forwarding."""
    def __init__(self, token):
        require(type(token) is str and 20 <= len(token) <= 4096,
                "GITHUB_TOKEN_MISSING")
        self.token, self.calls = token, 0

    def _request(self, method, path, body=None):
        self.calls += 1
        require(self.calls <= MAX_REQUESTS and method in ("GET", "POST")
                and type(path) is str and not any(x in path for x in ("..", "%2e", "#", "\r", "\n"))
                and (path == "graphql" or path.startswith("repos/" + REPO + "/")
                     or path == "repos/" + REPO),
                "GITHUB_ROUTE_NOT_ALLOWLISTED")
        require((method == "POST") == (path == "graphql")
                and (method == "POST") == (body is not None),
                "GITHUB_METHOD_INVALID")
        connection = http.client.HTTPSConnection("api.github.com", timeout=15)
        headers = {"Authorization": "Bearer " + self.token,
                   "Accept": "application/vnd.github+json",
                   "X-GitHub-Api-Version": "2022-11-28",
                   "User-Agent": "portfolio-brain-guarded-merger"}
        raw = None
        if body is not None:
            raw = json.dumps(body, separators=(",", ":")).encode("utf-8")
            require(len(raw) <= 12000, "GITHUB_GRAPHQL_REQUEST_BOUND")
            headers["Content-Type"] = "application/json"
        try:
            connection.request(method, "/" + path, body=raw, headers=headers)
            response = connection.getresponse()
            require(response.status == 200, "HTTP_" + str(response.status))
            data = response.read(MAX_BYTES + 1)
            require(len(data) <= MAX_BYTES, "GITHUB_RESPONSE_TOO_LARGE")
        except (OSError, http.client.HTTPException):
            raise Denied("GITHUB_PROVIDER_UNAVAILABLE") from None
        finally:
            connection.close()
        try:
            return json.loads(data)
        except (ValueError, UnicodeError):
            raise Denied("GITHUB_RESPONSE_NOT_JSON") from None

    def get(self, path):
        return self._request("GET", path)

    def graphql(self, query, variables):
        require(query in (THREADS_QUERY, ENABLE_MUTATION)
                and type(variables) is dict and set(variables) == {"id"},
                "GITHUB_GRAPHQL_NOT_APPROVED")
        return self._request("POST", "graphql", {"query": query, "variables": variables})


def main(argv=None):
    parser = argparse.ArgumentParser(description="Source-bound guarded native auto-merge")
    parser.add_argument("--pr", required=True, type=int)
    parser.add_argument("--expected-main", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = run(GitHub(os.environ.get("GH_TOKEN", "")),
                     number=args.pr, expected_main=args.expected_main, apply=args.apply)
        print(json.dumps(result, sort_keys=True))
        return 0 if result["status"] in ("ADMISSIBLE", "ALREADY_ENROLLED",
                                         "NATIVE_AUTO_MERGE_ENROLLED", "NATIVE_AUTO_MERGE_COMPLETED") else 2
    except Denied as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc),
                          "provider_writes": 0}, sort_keys=True))
        return 2


if __name__ == "__main__":
    sys.exit(main())
