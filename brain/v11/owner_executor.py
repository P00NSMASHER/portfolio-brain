"""Verify the configured owner worker from immutable GitHub delivery evidence.

Brain receives no cross-project writer credential. The separately authorized
owner session creates scoped branches and PRs; this reader only admits a
completion after exact provider checks, protected merge, and postmerge runs.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import urllib.request

from brain.v11.owner_inbox import canonical, digest, write_atomic

CONFIG = Path(__file__).with_name("owner-executor.json")
SHA = re.compile(r"[0-9a-f]{40}\Z")


class ExecutorError(ValueError):
    pass


def need(value, reason):
    if not value:
        raise ExecutorError(reason)


def configuration(path=CONFIG):
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    need(doc.get("schema_version") == 1 and
         doc.get("status") == "AUTHORIZED_OWNER_WORKER_CONFIGURED",
         "EXECUTOR_CONFIG_INVALID")
    need(type(doc.get("worker_id")) is str and len(doc["worker_id"]) == 32,
         "EXECUTOR_WORKER_ID_INVALID")
    need(type(doc.get("repositories")) is list and doc["repositories"],
         "EXECUTOR_REPOSITORIES_INVALID")
    authority = doc.get("authority", {})
    need(authority.get("code_write") ==
         "OWNER_SESSION_SCOPED_BRANCHES_AND_PULL_REQUESTS" and
         authority.get("protected_merge") ==
         "REQUIRED_CHECKS_AND_REPOSITORY_RULES" and
         authority.get("deployment") == "NOT_CONFIGURED" and
         authority.get("credential_location") ==
         "OWNER_SESSION_ONLY_NOT_BRAIN_RUNTIME", "EXECUTOR_AUTHORITY_INVALID")
    acceptance = doc.get("acceptance", {})
    need(acceptance.get("repository") in doc["repositories"] and
         type(acceptance.get("pr_number")) is int and
         SHA.fullmatch(acceptance.get("candidate_sha", "")) and
         SHA.fullmatch(acceptance.get("merge_sha", "")) and
         SHA.fullmatch(acceptance.get("attributed_commit_sha", "")),
         "EXECUTOR_ACCEPTANCE_INVALID")
    return doc


def configured_status():
    configuration()
    return "AUTHORIZED_OWNER_WORKER_CONFIGURED"


class GitHub:
    def __init__(self, token=""):
        self.token, self.reads = token, 0

    def get(self, repository, route):
        self.reads += 1
        need(self.reads <= 8, "EXECUTOR_READ_BUDGET_EXCEEDED")
        request = urllib.request.Request(
            "https://api.github.com/repos/" + repository + "/" + route,
            headers={"Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28",
                     "User-Agent": "portfolio-brain-owner-executor",
                     **({"Authorization": "Bearer " + self.token}
                        if self.token else {})})
        with urllib.request.urlopen(request, timeout=15) as response:
            need(response.status == 200, "EXECUTOR_PROVIDER_NOT_OK")
            return json.load(response)


def verify(api, config=None):
    config = config or configuration()
    item = config["acceptance"]
    repo, number = item["repository"], item["pr_number"]
    pr = api.get(repo, "pulls/" + str(number))
    need(pr.get("merged") is True and pr.get("state") == "closed" and
         pr.get("head", {}).get("sha") == item["candidate_sha"] and
         pr.get("base", {}).get("ref") == "main" and
         pr.get("merge_commit_sha") == item["merge_sha"],
         "EXECUTOR_PROTECTED_DELIVERY_UNVERIFIED")
    commits = api.get(repo, "pulls/" + str(number) + "/commits?per_page=100")
    attributed = [c for c in commits if c.get("sha") == item["attributed_commit_sha"]]
    need(len(attributed) == 1 and
         ("[owner task " + config["worker_id"] + "]") in
         attributed[0].get("commit", {}).get("message", ""),
         "EXECUTOR_ATTRIBUTION_UNVERIFIED")
    checks = api.get(repo, "commits/" + item["candidate_sha"] +
                     "/check-runs?per_page=100").get("check_runs", [])
    for name, issuer in item["required_checks"].items():
        found = [c for c in checks if c.get("name") == name]
        need(len(found) == 1 and found[0].get("head_sha") == item["candidate_sha"]
             and found[0].get("app", {}).get("id") == issuer
             and found[0].get("status") == "completed"
             and found[0].get("conclusion") == "success",
             "EXECUTOR_EXACT_HEAD_CHECK_UNVERIFIED")
    verified_runs = {}
    for name, run_id in item["postmerge_runs"].items():
        run = api.get(repo, "actions/runs/" + str(run_id))
        need(run.get("name") == name and run.get("head_branch") == "main"
             and run.get("head_sha") == item["merge_sha"]
             and run.get("status") == "completed"
             and run.get("conclusion") == "success",
             "EXECUTOR_POSTMERGE_RUN_UNVERIFIED")
        verified_runs[name] = run_id
    result = {
        "schema_version": 1,
        "status": "AUTHORIZED_OWNER_EXECUTOR_LIVE_VERIFIED",
        "worker_id": config["worker_id"],
        "worker_thread": config["worker_thread"],
        "repository": repo,
        "pr_number": number,
        "candidate_sha": item["candidate_sha"],
        "merge_sha": item["merge_sha"],
        "attributed_commit_sha": item["attributed_commit_sha"],
        "lifecycle": ["OBSERVED", "DIAGNOSED", "PATCHED", "TESTED",
                      "DELIVERED", "LIVE_VERIFIED"],
        "postmerge_runs": verified_runs,
        "provider_reads": api.reads,
        "provider_writes": 0,
        "brain_runtime_writer_credentials": False,
        "cross_project_deploy": "NOT_CONFIGURED",
    }
    result["receipt_sha256"] = digest(result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--token", default="")
    args = parser.parse_args(argv)
    try:
        write_atomic(args.output, verify(GitHub(args.token)))
        return 0
    except (ExecutorError, OSError, ValueError, TypeError, UnicodeError):
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
