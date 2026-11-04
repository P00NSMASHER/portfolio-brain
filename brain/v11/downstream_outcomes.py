"""Fail-closed independent readback of real downstream repair delivery.

A source PR, even with green CI, is not a completed repair.  This verifier
requires an immutable *pre-repair* behavior contract, two independently issued
exact-head checks, protected integration, provider-confirmed deployment, and
fresh live behavior matching the contract. It never edits GitHub or the service.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit
import urllib.error
import urllib.request

SHA = re.compile(r"[0-9a-f]{40}\Z")
DIGEST = re.compile(r"[0-9a-f]{64}\Z")
PR = re.compile(r"[1-9][0-9]{0,8}\Z")
# Only independently pinned GitHub App issuers may certify a finished repair.
# Other repositories remain INELIGIBLE until independent issuers are reviewed.
INDEPENDENT = {
    "P00NSMASHER/portfolio-brain": {
        "validate": 15368,
        "portfolio-phase1-gate": 5121826,
    },
}
RULESETS = {"P00NSMASHER/portfolio-brain": 24182301}
ALLOWED_LIVE = {
    "P00NSMASHER/portfolio-brain": ("p00nsmasher.github.io", "/portfolio-brain/"),
}
MAX_HTTP = 128_000


class OutcomeHold(ValueError):
    """Missing, contradictory, or untrusted verification evidence."""


def need(value, reason):
    if not value:
        raise OutcomeHold(reason)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _json(raw, reason):
    try:
        return json.loads(raw)
    except (ValueError, UnicodeError, TypeError) as exc:
        raise OutcomeHold(reason) from exc


class GitHubReadOnly:
    """Bounded GET-only original provider client for the reviewed repository."""
    def __init__(self, token):
        need(type(token) is str and 20 <= len(token) <= 4096, "OUTCOME_TOKEN_MISSING")
        self.token = token
        self.reads = 0

    def get(self, repo, route):
        need(repo in INDEPENDENT, "OUTCOME_REPOSITORY_NOT_INDEPENDENTLY_ENROLLED")
        allowed = (
            re.fullmatch(r"pulls/[1-9][0-9]{0,8}", route) is not None
            or route == "branches/main"
            or route == "rulesets/" + str(RULESETS[repo])
            or re.fullmatch(r"commits/[0-9a-f]{40}/check-runs\?per_page=100", route) is not None
            or re.fullmatch(r"contents/repair/downstream-outcomes/[1-9][0-9]{0,8}\.json\?ref=[0-9a-f]{40}", route) is not None
            or re.fullmatch(r"deployments\?sha=[0-9a-f]{40}&per_page=100", route) is not None
            or re.fullmatch(r"deployments/[1-9][0-9]{0,11}/statuses\?per_page=100", route) is not None
        )
        need(allowed, "OUTCOME_UNAPPROVED_GITHUB_ROUTE")
        self.reads += 1
        need(self.reads <= 8, "OUTCOME_GITHUB_READ_BUDGET")
        request = urllib.request.Request(
            "https://api.github.com/repos/" + repo + "/" + route,
            headers={"Accept": "application/vnd.github+json",
                     "Authorization": "Bearer " + self.token,
                     "User-Agent": "brain-independent-outcome-readback",
                     "X-GitHub-Api-Version": "2022-11-28"})
        try:
            with urllib.request.build_opener(NoRedirect()).open(request, timeout=12) as response:
                need(response.status == 200, "OUTCOME_GITHUB_NOT_200")
                data = response.read(MAX_HTTP + 1)
        except (OSError, urllib.error.URLError) as exc:
            raise OutcomeHold("OUTCOME_GITHUB_UNAVAILABLE") from exc
        need(len(data) <= MAX_HTTP, "OUTCOME_GITHUB_RESPONSE_OVERSIZED")
        return _json(data.decode("utf-8"), "OUTCOME_GITHUB_JSON_INVALID")


def _allowed_url(repo, url):
    need(type(url) is str and len(url) <= 400, "OUTCOME_LIVE_URL_INVALID")
    p = urlsplit(url)
    host, prefix = ALLOWED_LIVE[repo]
    need(p.scheme == "https" and p.hostname == host and p.port is None
         and p.username is None and p.password is None
         and p.path.startswith(prefix) and len(p.path) > len(prefix)
         and not p.query and not p.fragment and not p.path.endswith("/")
         and not any(x in p.path for x in ("..", "//", "%", "\\")),
         "OUTCOME_LIVE_HOST_OR_PATH_DENIED")


def live_get(repo, url):
    """Read only a fixed public host; never send GitHub credentials to it."""
    _allowed_url(repo, url)
    request = urllib.request.Request(url, headers={
        "Accept": "application/json", "User-Agent": "brain-outcome-probe"})
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=12) as response:
            body = response.read(MAX_HTTP + 1)
            item = {"status": response.status, "body": body,
                    "content_type": response.headers.get("Content-Type", "")}
    except (OSError, urllib.error.URLError) as exc:
        raise OutcomeHold("OUTCOME_LIVE_READ_FAILED") from exc
    need(len(body) <= MAX_HTTP, "OUTCOME_LIVE_RESPONSE_OVERSIZED")
    return item


def _verified_checks(api, repo, head):
    document = api.get(repo, "commits/" + head + "/check-runs?per_page=100")
    rows = document.get("check_runs") if type(document) is dict else None
    need(type(rows) is list and type(document.get("total_count")) is int
         and len(rows) == document["total_count"] < 100,
         "OUTCOME_CI_CENSUS_INCOMPLETE")
    required = INDEPENDENT[repo]
    need(len(set(required.values())) >= 2, "OUTCOME_INDEPENDENT_ISSUERS_NOT_CONFIGURED")
    for name, issuer in required.items():
        matches = [r for r in rows if type(r) is dict and r.get("name") == name]
        need(len(matches) == 1
             and matches[0].get("head_sha") == head
             and matches[0].get("app", {}).get("id") == issuer
             and matches[0].get("status") == "completed"
             and matches[0].get("conclusion") == "success",
             "OUTCOME_INDEPENDENT_EXACT_HEAD_CHECK_MISSING")


def _approved_contract(api, repo, number, base):
    doc = api.get(repo, "contents/repair/downstream-outcomes/"
                  + str(number) + ".json?ref=" + base)
    need(type(doc) is dict and doc.get("type") == "file"
         and doc.get("encoding") == "base64"
         and type(doc.get("content")) is str
         and type(doc.get("sha")) is str
         and re.fullmatch(r"[0-9a-f]{40}", doc["sha"]) is not None
         and type(doc.get("size")) is int
         and 0 < doc["size"] <= 4096, "OUTCOME_PREAPPROVED_CONTRACT_MISSING")
    try:
        raw = base64.b64decode(doc["content"], validate=True)
    except (ValueError, TypeError) as exc:
        raise OutcomeHold("OUTCOME_CONTRACT_ENCODING_INVALID") from exc
    blob_sha = hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()
    need(len(raw) == doc["size"] and blob_sha == doc["sha"],
         "OUTCOME_APPROVED_SOURCE_BLOB_MISMATCH")
    contract = _json(raw.decode("utf-8"), "OUTCOME_CONTRACT_JSON_INVALID")
    need(type(contract) is dict and set(contract) == {
        "schema_version", "repository", "pr_number", "environment",
        "build_url", "behavior_url", "expected_behavior_sha256"}
         and contract["schema_version"] == 1
         and contract["repository"] == repo and contract["pr_number"] == number
         and type(contract["environment"]) is str
         and 1 <= len(contract["environment"]) <= 60
         and type(contract["expected_behavior_sha256"]) is str
         and DIGEST.fullmatch(contract["expected_behavior_sha256"]),
         "OUTCOME_CONTRACT_SCHEMA_OR_IDENTITY_INVALID")
    _allowed_url(repo, contract["build_url"])
    _allowed_url(repo, contract["behavior_url"])
    need(contract["build_url"] != contract["behavior_url"],
         "OUTCOME_BUILD_MARKER_NOT_FUNCTIONAL_PROBE")
    return contract


def verify(api, probe, *, repo, pr_number):
    """Only this original-provider + live-readback path emits COMPLETE."""
    need(repo in INDEPENDENT and type(pr_number) is int and 0 < pr_number < 10**9,
         "OUTCOME_REPOSITORY_OR_PR_NOT_ELIGIBLE")
    rule = api.get(repo, "rulesets/" + str(RULESETS[repo]))
    required = {(key, value) for key, value in INDEPENDENT[repo].items()}
    configured = [
        r.get("parameters", {}) for r in rule.get("rules", [])
        if type(r) is dict and r.get("type") == "required_status_checks"
    ] if type(rule) is dict else []
    need(type(rule) is dict and rule.get("enforcement") == "active"
         and rule.get("bypass_actors") == []
         and len(configured) == 1
         and configured[0].get("strict_required_status_checks_policy") is True
         and required <= {
             (x.get("context"), x.get("integration_id"))
             for x in configured[0].get("required_status_checks", [])
             if type(x) is dict
         }, "OUTCOME_PROTECTED_INDEPENDENT_GATE_NOT_VERIFIED")
    pr = api.get(repo, "pulls/" + str(pr_number))
    need(type(pr) is dict and pr.get("number") == pr_number
         and pr.get("state") == "closed" and pr.get("merged") is True
         and pr.get("base", {}).get("ref") == "main"
         and pr.get("base", {}).get("repo", {}).get("full_name") == repo,
         "OUTCOME_PR_NOT_PROTECTED_MERGE")
    base = pr["base"].get("sha")
    head = pr.get("head", {}).get("sha")
    merge = pr.get("merge_commit_sha")
    need(all(type(x) is str and SHA.fullmatch(x) for x in (base, head, merge))
         and len({base, head, merge}) == 3
         and pr.get("head", {}).get("repo", {}).get("full_name") == repo,
         "OUTCOME_EXACT_SOURCE_IDENTITY_INVALID")
    # Contract must predate the repair. A post-hoc probe expectation is rejected.
    contract = _approved_contract(api, repo, pr_number, base)
    _verified_checks(api, repo, head)
    main = api.get(repo, "branches/main")
    need(type(main) is dict and main.get("protected") is True
         and main.get("commit", {}).get("sha") == merge,
         "OUTCOME_CURRENT_MAIN_NOT_EXACT_MERGE")
    deployments = api.get(repo, "deployments?sha=" + merge + "&per_page=100")
    need(type(deployments) is list and len(deployments) < 100,
         "OUTCOME_DEPLOYMENT_CENSUS_INCOMPLETE")
    deployed = [d for d in deployments
                if type(d) is dict and d.get("sha") == merge
                and d.get("environment") == contract["environment"]]
    need(len(deployed) == 1 and type(deployed[0].get("id")) is int
         and 0 < deployed[0]["id"] < 10**12,
         "OUTCOME_EXACT_DEPLOYMENT_NOT_FOUND")
    deployment_id = deployed[0]["id"]
    statuses = api.get(repo, "deployments/" + str(deployment_id)
                       + "/statuses?per_page=100")
    need(type(statuses) is list and 0 < len(statuses) < 100
         and type(statuses[0]) is dict
         and statuses[0].get("deployment_id") == deployment_id
         and statuses[0].get("state") == "success",
         "OUTCOME_DELIVERY_NOT_CONFIRMED")
    build = probe(repo, contract["build_url"])
    need(type(build) is dict and build.get("status") == 200
         and type(build.get("body")) is bytes
         and 0 < len(build["body"]) <= MAX_HTTP
         and "json" in str(build.get("content_type", "")).lower(),
         "OUTCOME_LIVE_BUILD_NOT_VERIFIED")
    build_data = _json(build["body"].decode("utf-8"), "OUTCOME_LIVE_BUILD_INVALID")
    need(type(build_data) is dict and build_data.get("source_sha") == merge,
         "OUTCOME_LIVE_SOURCE_REVISION_MISMATCH")
    behavior = probe(repo, contract["behavior_url"])
    need(type(behavior) is dict and behavior.get("status") == 200
         and type(behavior.get("body")) is bytes
         and 16 <= len(behavior["body"]) <= MAX_HTTP
         and hashlib.sha256(behavior["body"]).hexdigest() ==
             contract["expected_behavior_sha256"],
         "OUTCOME_FUNCTIONAL_BEHAVIOR_NOT_VERIFIED")
    # Fresh original live response, not a unit test, merge check or self-report.
    return {
        "status": "VERIFIED_REAL_WORLD_REPAIR",
        "repository": repo, "pr_number": pr_number,
        "candidate_head_sha": head, "merge_main_sha": merge,
        "deployment_id": deployment_id,
        "live_behavior_sha256": hashlib.sha256(behavior["body"]).hexdigest(),
        "approved_pre_repair_base_sha": base,
        "independent_check_issuers": INDEPENDENT[repo],
        "verified_customer_revenue": None,
        "provider_writes": 0,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--pr", required=True, type=int)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        provider = GitHubReadOnly(os.environ.get("GITHUB_TOKEN") or "")
        result = verify(provider, live_get, repo=args.repository, pr_number=args.pr)
        need(args.output.parent.is_dir() and not args.output.exists()
             and not args.output.is_symlink(), "OUTCOME_OUTPUT_UNSAFE")
        with args.output.open("x", encoding="utf-8") as f:
            json.dump(result, f, sort_keys=True, indent=2)
            f.write("\n")
        print(json.dumps({"status": result["status"], "pr": args.pr, "provider_writes": 0}))
        return 0
    except (OutcomeHold, OSError, UnicodeError, ValueError) as exc:
        print(json.dumps({"status": "DOWNSTREAM_OUTCOME_UNVERIFIED",
                          "reason": str(exc), "provider_writes": 0}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
