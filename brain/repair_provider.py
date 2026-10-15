"""Bounded original-GitHub evidence collection for unresolved project repairs.

This is an owner-invoked GET-only transport, separate from the canonical Brain
24-read observer. Only the two existing focus repositories and exact repair PR
numbers are addressed. Provider text is never interpreted as instructions.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import urllib.request
import urllib.error

from brain.core import BrainError, require
from brain.repair_autonomy import FOCUS
from brain.repair_followthrough import _prior, _provider
from brain.render import write_report

ROOT_URL = "https://api.github.com/repos/"
SHA = re.compile("[0-9a-f]{40}")
REPOS = frozenset(row[0] for row in FOCUS.values())
MAX_JOBS = 8
MAX_REQUESTS = 20


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise BrainError("REPAIR_GITHUB_REDIRECT_BLOCKED")


def _unique_json_pairs(pairs):
    obj = {}
    for key, value in pairs:
        require(key not in obj, "REPAIR_PROVIDER_DUPLICATE_JSON_KEY")
        obj[key] = value
    return obj


def github_transport(token):
    require(type(token) is str and 0 < len(token) <= 4096,
            "REPAIR_READ_TOKEN_NOT_AVAILABLE")
    opener = urllib.request.build_opener(_NoRedirect)

    def get(repository, suffix):
        require(repository in REPOS
                and type(suffix) is str
                and (suffix == "/branches/main"
                     or re.fullmatch(r"/pulls/[1-9][0-9]{0,9}", suffix)
                     or re.fullmatch(
                         r"/commits/[0-9a-f]{40}/check-runs\?per_page=100", suffix
                     )),
                "REPAIR_PROVIDER_ENDPOINT_NOT_ALLOWLISTED")
        path = ROOT_URL + repository + suffix
        request = urllib.request.Request(path, method="GET", headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json",
            "User-Agent": "brain-repair-evidence-readonly/1.0",
            "X-GitHub-Api-Version": "2022-11-28",
        })
        with opener.open(request, timeout=10) as response:
            require(response.status == 200,
                    "REPAIR_PROVIDER_NON_200")
            raw = response.read(1_000_001)
            require(len(raw) <= 1_000_000, "REPAIR_PROVIDER_PAYLOAD_TOO_LARGE")
        try:
            return json.loads(raw.decode("utf-8"),
                              object_pairs_hook=_unique_json_pairs)
        except (ValueError, UnicodeError) as exc:
            raise BrainError("REPAIR_PROVIDER_JSON_INVALID") from exc

    return get


def _work_inputs(queue, prior, limit):
    require(type(queue) is dict
            and queue.get("scope") == "OWNER_TASK_FIX_AND_VERIFY_NO_RELEASE_AUTHORITY"
            and queue.get("authority_to_merge_or_deploy") is False
            and type(queue.get("actions")) is list
            and len(queue["actions"]) <= 5
            and type(prior) is list and len(prior) <= 100
            and type(limit) is int and 1 <= limit <= MAX_JOBS,
            "REPAIR_PROVIDER_WORK_SCOPE_INVALID")
    jobs = {}
    for item in queue["actions"]:
        repo = item.get("repository")
        number = item.get("candidate_pr_number")
        head = item.get("source_head_sha")
        project = item.get("project_id")
        require(project in FOCUS and FOCUS[project][0] == repo
                and type(number) is int and 0 < number < 1_000_000_000
                and type(head) is str and SHA.fullmatch(head)
                and item.get("safe_automatic_merge_authority") is False,
                "REPAIR_PROVIDER_WORK_IDENTITY_INVALID")
        key = (repo, number)
        require(key not in jobs, "REPAIR_PROVIDER_DUPLICATE_WORK")
        jobs[key] = head
    for item in prior:
        require(type(item) is dict, "REPAIR_PROVIDER_PRIOR_NOT_OBJECT")
        # Validate original owner and source identity before any API lookup.
        # The next private history is still not treated as approval.
        item = _prior(item, 2**63-1)
        repo, number, head = (
            item.get("repository"), item.get("pr_number"), item.get("head_sha")
        )
        require(repo in REPOS
                and type(number) is int and 0 < number < 1_000_000_000
                and type(head) is str and SHA.fullmatch(head)
                and item.get("state") in {
                    "OBSERVED", "CLAIMED", "REPRODUCED", "PATCHED",
                    "CI_RED", "CI_GREEN", "INDEPENDENT_GREEN",
                    "DELIVERY_REQUESTED", "BLOCKED_EXTERNAL",
                    "MAIN_TECHNICALLY_VERIFIED",
                }, "REPAIR_PROVIDER_PRIOR_IDENTITY_INVALID")
        key = (repo, number)
        if key not in jobs and item["state"] != "MAIN_TECHNICALLY_VERIFIED":
            jobs[key] = head
    all_items = list(jobs.items())
    # Unfinished carryovers are not starved by most recently sampled PRs.
    carryovers = [item for item in all_items
                  if item[0] not in {
                      (w["repository"], w["candidate_pr_number"])
                      for w in queue["actions"]
                  }]
    active = [item for item in all_items if item not in carryovers]
    return carryovers + active, limit


def collect_original_proofs(queue, *, prior=None, transport,
                            max_jobs=MAX_JOBS, max_requests=MAX_REQUESTS,
                            selection_sequence=0):
    """Read exact original PR and main checks without mutation or replays."""
    require(callable(transport)
            and type(max_requests) is int and 3 <= max_requests <= MAX_REQUESTS
            and type(selection_sequence) is int
            and 0 <= selection_sequence < 2**63,
            "REPAIR_PROVIDER_GET_BUDGET_INVALID")
    work, limit = _work_inputs(
        queue, [] if prior is None else prior, max_jobs,
    )
    # The ordinary owner collector checks every case when it fits. The live
    # native Brain stage has budget for one, so rotate fairly rather than
    # reading the same top-ranked PR forever.
    if len(work) > limit:
        start = selection_sequence % len(work)
        work = [work[(start + offset) % len(work)]
                for offset in range(len(work))]
    requests, proofs, gaps, cache = 0, [], [], {}

    def get(repo, path):
        nonlocal requests
        require(requests < max_requests,
                "REPAIR_PROVIDER_GET_BUDGET_EXCEEDED")
        requests += 1
        return transport(repo, path)

    for (repo, number), expected in work[:limit]:
        # A provider 404 or missing permission is an explicit gap, never
        # equivalent to closed, merged, released or fixed.
        try:
            pr = get(repo, f"/pulls/{number}")
        except (OSError, urllib.error.URLError, BrainError, ValueError):
            gaps.append({
                "repository": repo, "pr_number": number,
                "status": "PR_PROVIDER_UNAVAILABLE_NOT_RESOLVED",
            })
            continue
        require(type(pr) is dict, "REPAIR_PROVIDER_PR_NOT_OBJECT")
        head, base = pr.get("head"), pr.get("base")
        require(type(head) is dict and type(base) is dict
                and type(head.get("repo")) is dict
                and type(base.get("repo")) is dict
                and pr.get("number") == number
                and head["repo"].get("full_name") == repo
                and base["repo"].get("full_name") == repo
                and base.get("ref") == "main"
                and pr.get("state") in {"open", "closed"}
                and type(pr.get("merged")) is bool,
                "REPAIR_PROVIDER_ORIGINAL_PR_UNTRUSTED")
        if (pr.get("head") or {}).get("sha") != expected:
            gaps.append({
                "repository": repo, "pr_number": number,
                "status": "EXACT_HEAD_CHANGED_RESCAN_BEFORE_REPAIR",
            })
            continue
        merged = pr["merged"]
        merge_sha = pr.get("merge_commit_sha") if merged else None
        require(not merged or (
                pr["state"] == "closed"
                and type(merge_sha) is str and SHA.fullmatch(merge_sha)
            ), "REPAIR_PROVIDER_MERGE_METADATA_INVALID")
        if not merged and pr["state"] == "closed":
            gaps.append({
                "repository": repo, "pr_number": number,
                "status": "CLOSED_WITHOUT_MERGE_NOT_FIXED",
            })
            continue
        if repo not in cache:
            try:
                main = get(repo, "/branches/main")
            except (OSError, urllib.error.URLError, BrainError, ValueError):
                gaps.append({
                    "repository": repo, "pr_number": number,
                    "status": "MAIN_PROVIDER_UNAVAILABLE",
                })
                continue
            main_sha = (main.get("commit") or {}).get("sha") if type(main) is dict else None
            require(type(main_sha) is str and SHA.fullmatch(main_sha),
                    "REPAIR_PROVIDER_MAIN_SHA_UNVERIFIED")
            cache[repo] = main_sha
        main_sha = cache[repo]
        checks = []
        if merged:
            if main_sha != merge_sha:
                gaps.append({
                    "repository": repo, "pr_number": number,
                    "status": "MERGE_IS_NOT_LATEST_MAIN_REQUIRE_ANCESTRY",
                })
                # Still record real original merge identity for the owner's
                # next source-bound comparison, but never fake main checks.
            else:
                raw_checks = get(
                    repo, f"/commits/{merge_sha}/check-runs?per_page=100",
                )
                require(type(raw_checks) is dict
                        and type(raw_checks.get("total_count")) is int
                        and 0 <= raw_checks["total_count"] <= 100
                        and type(raw_checks.get("check_runs")) is list
                        and len(raw_checks["check_runs"]) == raw_checks["total_count"],
                        "REPAIR_PROVIDER_CHECK_PAGE_TRUNCATED")
                for check in raw_checks["check_runs"]:
                    require(type(check) is dict
                            and type(check.get("id")) is int
                            and type(check.get("name")) is str
                            and type(check.get("app")) is dict
                            and check.get("head_sha") == merge_sha,
                            "REPAIR_PROVIDER_CHECK_ROW_UNVERIFIED")
                    checks.append({
                        "id": check["id"], "name": check["name"],
                        "app_id": check["app"].get("id"),
                        "head_sha": check.get("head_sha"),
                        "status": check.get("status"),
                        "conclusion": check.get("conclusion"),
                    })
        proof = {
            "repository": repo,
            "pr_number": number,
            "source_head_sha": expected,
            "pr_state": pr["state"],
            "merged": merged,
            "merge_commit_sha": merge_sha,
            "current_main_sha": main_sha,
            "main_checks": checks,
        }
        _provider(proof)
        proofs.append(proof)

    return {
        "schema_version": 1,
        "scope": "ORIGINAL_GITHUB_READ_ONLY_REPAIR_PROOFS",
        "source_credential_boundary": "EXISTING_GITHUB_READ_ONLY_TOKEN",
        "requests_used": requests,
        "request_limit": max_requests,
        "max_jobs": max_jobs,
        "selection_sequence": selection_sequence,
        "selection_rule": "CYCLIC_SOURCE_FAIRNESS_WITHIN_BOUNDED_GET_BUDGET",
        "observed_pr_count": len(proofs),
        "unsampled_due_to_job_limit": max(0, len(work) - limit),
        "proofs": proofs,
        "gaps": gaps,
        "original_api_response_not_signed": True,
        "automatic_merge_or_deployment_authority": False,
        "customer_or_external_action_authority": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Get read-only original GitHub repair PR evidence")
    parser.add_argument("--current", required=True, type=Path)
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    from brain.repair_followthrough_cli import _safe_json
    current = _safe_json(args.current)
    previous = _safe_json(args.previous) if args.previous else None
    if type(previous) is dict and "next_history" in previous:
        previous = previous["next_history"]
    token = os.environ.get("GITHUB_TOKEN", "")
    result = collect_original_proofs(
        current, prior=previous, transport=github_transport(token),
    )
    write_report(result, args.output)
    print(json.dumps({
        "status": "READ_ONLY_PROOF_COLLECTION_COMPLETE",
        "original_prs": result["observed_pr_count"],
        "gaps": len(result["gaps"]),
        "github_gets": result["requests_used"],
        "merged_or_released_claims": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
