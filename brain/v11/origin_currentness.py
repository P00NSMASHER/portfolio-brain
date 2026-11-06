"""Read-only, bounded recheck of historical original-main repair handoffs.

An original failing main run remains valid history even after an identical
workflow subsequently succeeds. Never erase it or invent a fixed product bug.
A later successful *same repository/workflow/source/event* run means the old
failure is not a reason to open another repair PR. Unknown is never success.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import urllib.error
import urllib.request

from brain.v9.batch_queue import PROJECTS
from brain.v11.owner_inbox import canonical, digest, need, strict_load, write_atomic, InboxError

MAX_HANDOFFS = 5
MAX_RUNS = 100
MAX_HTTP_BYTES = 2 * 1024 * 1024
RUN_PATH = re.compile(r"actions/runs/[1-9][0-9]{0,11}\Z")
API_BASE = "https://api.github.com/repos/"
ALLOWED_REPOS = frozenset(PROJECTS.values())


class CurrentnessError(ValueError):
    pass


def require(condition, reason):
    if not condition:
        raise CurrentnessError(reason)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class PublicGitHub:
    """Only exact original-run, main-branch and bounded runs-list GETs."""
    def __init__(self, token=""):
        require(type(token) is str and len(token) <= 4096,
                "CURRENTNESS_TOKEN_INVALID")
        self.token = token
        self.reads = 0
        self.opener = urllib.request.build_opener(NoRedirect())

    def get(self, repository, route):
        require(type(repository) is str and repository in ALLOWED_REPOS,
                "CURRENTNESS_REPOSITORY_REFUSED")
        require(route in {"branches/main", "actions/runs?per_page=100"}
                or (type(route) is str and RUN_PATH.fullmatch(route) is not None),
                "CURRENTNESS_ROUTE_REFUSED")
        require(self.reads < MAX_HANDOFFS * 3, "CURRENTNESS_GET_BUDGET_EXCEEDED")
        self.reads += 1
        h = {"Accept": "application/vnd.github+json",
             "X-GitHub-Api-Version": "2022-11-28",
             "User-Agent": "portfolio-brain-original-currentness"}
        if self.token:
            h["Authorization"] = "Bearer " + self.token
        request = urllib.request.Request(API_BASE + repository + "/" + route,
                                         headers=h, method="GET")
        try:
            with self.opener.open(request, timeout=10) as response:
                require(response.status == 200, "CURRENTNESS_HTTP_NOT_OK")
                raw = response.read(MAX_HTTP_BYTES + 1)
        except (OSError, urllib.error.URLError) as exc:
            raise CurrentnessError("CURRENTNESS_PROVIDER_UNAVAILABLE") from exc
        require(0 < len(raw) <= MAX_HTTP_BYTES, "CURRENTNESS_RESPONSE_TOO_LARGE")
        def unique(pairs):
            result = {}
            for key, value in pairs:
                require(key not in result, "CURRENTNESS_DUPLICATE_JSON_KEY")
                result[key] = value
            return result
        try:
            doc = json.loads(raw.decode("utf-8"), object_pairs_hook=unique,
                             parse_constant=lambda _: (_ for _ in ()).throw(
                                 CurrentnessError("CURRENTNESS_NONFINITE")))
        except (UnicodeError, ValueError) as exc:
            raise CurrentnessError("CURRENTNESS_JSON_INVALID") from exc
        require(type(doc) is dict, "CURRENTNESS_RESPONSE_INVALID")
        return doc


def _verified_failure(original, item):
    repository = item["repository"]
    require(type(original) is dict
            and type(original.get("id")) is int
            and original["id"] == item["run_id"]
            and type(original.get("workflow_id")) is int
            and original["workflow_id"] > 0
            and type(original.get("name")) is str
            and 1 <= len(original["name"]) <= 150
            and type(original.get("path")) is str
            and original["path"].startswith(".github/workflows/")
            and original["path"].endswith(".yml")
            and original.get("repository", {}).get("full_name") == repository
            and original.get("head_repository", {}).get("full_name") == repository
            and original.get("head_branch") == "main"
            and original.get("head_sha") == item["source_sha"]
            and original.get("event") == item["original_run_event"]
            and type(original.get("run_attempt")) is int
            and original["run_attempt"] == 1
            and original.get("status") == "completed"
            and original.get("conclusion") in {"failure", "timed_out"},
            "CURRENTNESS_ORIGINAL_FAILURE_NOT_AUTHENTICATED")
    return (original["workflow_id"], original["path"],
            original["name"], original["event"])


def _latest_same_source(document, item, identity):
    require(type(document) is dict
            and type(document.get("total_count")) is int
            and 0 <= document["total_count"] <= 10**9
            and type(document.get("workflow_runs")) is list
            and len(document["workflow_runs"]) <= MAX_RUNS
            and len(document["workflow_runs"]) <= document["total_count"],
            "CURRENTNESS_RUN_CENSUS_INVALID")
    rows = document["workflow_runs"]
    require(all(type(r) is dict and type(r.get("id")) is int
                and 0 < r["id"] < 10**12 for r in rows)
            and len({r["id"] for r in rows}) == len(rows),
            "CURRENTNESS_RUN_ROW_INVALID")
    workflow_id, path, name, event = identity
    matched = []
    for r in rows:
        if not (r.get("workflow_id") == workflow_id
                and r.get("path") == path and r.get("name") == name
                and r.get("event") == event
                and r.get("repository", {}).get("full_name") == item["repository"]
                and r.get("head_branch") == "main"
                and r.get("head_sha") == item["source_sha"]
                and type(r.get("run_attempt")) is int
                and r["run_attempt"] == 1
                and r["id"] > item["run_id"]):
            continue
        if r.get("status") == "completed" and r.get("conclusion") in {
                "success", "failure", "timed_out", "cancelled"}:
            matched.append(r)
    return max(matched, key=lambda r: r["id"]) if matched else None


def evaluate(packet, api):
    """Only provider-corroborated later success may suppress an *old* handoff."""
    require(type(packet) is dict and type(packet.get("schema_version")) is int
            and packet["schema_version"] == 1
            and type(packet.get("packet_sha256")) is str
            and re.fullmatch(r"[0-9a-f]{64}", packet["packet_sha256"]) is not None
            and packet.get("production_verified") is False
            and packet.get("provider_writes") == 0
            and packet.get("general_cross_project_executor") == "NOT_CONFIGURED",
            "CURRENTNESS_INBOX_INVALID")
    body = dict(packet)
    recorded = body.pop("packet_sha256")
    require(digest(body) == recorded, "CURRENTNESS_INBOX_HASH_MISMATCH")
    rows = packet.get("original_failure_handoffs")
    require(type(rows) is list and len(rows) <= MAX_HANDOFFS,
            "CURRENTNESS_INBOX_WORK_BOUND")
    results = []
    for item in rows:
        require(type(item) is dict
                and item.get("repository") in ALLOWED_REPOS
                and type(item.get("run_id")) is int
                and 0 < item["run_id"] < 10**12
                and type(item.get("source_sha")) is str
                and re.fullmatch(r"[0-9a-f]{40}", item["source_sha"]) is not None
                and type(item.get("handoff_id")) is str
                and re.fullmatch(r"[0-9a-f]{64}", item["handoff_id"]) is not None,
                "CURRENTNESS_HANDOFF_INVALID")
        repository = item["repository"]
        base = {"handoff_id": item["handoff_id"], "repository": repository,
                "source_sha": item["source_sha"], "original_run_id": item["run_id"],
                "latest_run_id": None, "root_cause_verified": False,
                "live_repair_verified": False, "writer_authorized": False}
        try:
            first = api.get(repository, "actions/runs/" + str(item["run_id"]))
            identity = _verified_failure(first, item)
            branch = api.get(repository, "branches/main")
            require(branch.get("protected") is True
                    and type(branch.get("commit")) is dict,
                    "CURRENTNESS_PROTECTED_MAIN_UNVERIFIED")
            if branch["commit"].get("sha") != item["source_sha"]:
                base["status"] = "SOURCE_CHANGED_ORIGINAL_FAILURE_HISTORICAL"
            else:
                newest = _latest_same_source(
                    api.get(repository, "actions/runs?per_page=100"),
                    item, identity)
                if newest is None:
                    base["status"] = "NO_LATER_MATCHING_COMPLETED_RUN"
                else:
                    base["latest_run_id"] = newest["id"]
                    if newest["conclusion"] == "success":
                        base["status"] = "LATER_SAME_SOURCE_WORKFLOW_SUCCESS_ORIGINAL_FAILURE_HISTORICAL"
                    else:
                        base["status"] = "LATEST_SAME_SOURCE_WORKFLOW_NOT_SUCCESS"
        except (CurrentnessError, OSError, TypeError, KeyError, ValueError) as exc:
            known = str(exc) if isinstance(exc, CurrentnessError) else ""
            base["status"] = "CURRENTNESS_UNVERIFIED"
            base["reason"] = (known if known.startswith("CURRENTNESS_")
                              else "CURRENTNESS_SOURCE_UNAVAILABLE")
        base["reproduction_candidate"] = base["status"] in {
            "NO_LATER_MATCHING_COMPLETED_RUN",
            "LATEST_SAME_SOURCE_WORKFLOW_NOT_SUCCESS",
        }
        results.append(base)
    verdict = {
        "schema_version": 1,
        "source_sha": packet.get("source_sha"),
        "original_inbox_sha256": recorded,
        "provider_reads": api.reads,
        "items": results,
        "historical_or_changed": sum(r["status"].startswith(("LATER_SAME_SOURCE_WORKFLOW_SUCCESS_",
                                                               "SOURCE_CHANGED_")) for r in results),
        "reproduction_candidates": sum(r["reproduction_candidate"] for r in results),
        "provider_writes": 0,
        "code_changes": 0,
        "live_repairs_verified": 0,
        "general_cross_project_executor": "NOT_CONFIGURED",
    }
    verdict["verdict_sha256"] = digest(verdict)
    return verdict


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inbox", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        doc = strict_load(args.inbox)
        verdict = evaluate(doc, PublicGitHub(os.environ.get("GITHUB_TOKEN", "")))
        write_atomic(args.output, verdict)
        print(canonical({"status": "CURRENTNESS_CHECKED",
                         "historical_or_changed": verdict["historical_or_changed"],
                         "reproduction_candidates": verdict["reproduction_candidates"],
                         "provider_writes": 0, "live_repairs_verified": 0}))
        return 0
    except (InboxError, CurrentnessError, OSError, ValueError, TypeError):
        print(canonical({"status": "CURRENTNESS_UNVERIFIED",
                         "provider_writes": 0, "live_repairs_verified": 0}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
