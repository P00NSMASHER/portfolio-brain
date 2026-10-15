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
MAX_JOBS = 6
MAX_REQUESTS = 20
TRUSTED_CHECK_APP = 15368
REQUIRED_HEAD_CHECKS = {
    "P00NSMASHER/github-value-hunt-ledger":
        frozenset({"release-gate", "freight"}),
    "P00NSMASHER/x402-product-factory":
        frozenset({"test", "browser", "manufacturing", "pilot", "candidate-build"}),
}


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


def _head_ci_receipt(raw, repository, pr_number, head_sha):
    """Original exact-commit CI: diagnose work, NEVER approve deployment."""
    require(repository in REPOS
            and type(pr_number) is int and pr_number > 0
            and type(head_sha) is str and SHA.fullmatch(head_sha)
            and type(raw) is dict
            and type(raw.get("total_count")) is int
            and 0 <= raw["total_count"] <= 100
            and type(raw.get("check_runs")) is list
            and len(raw["check_runs"]) == raw["total_count"],
            "REPAIR_EXACT_HEAD_CI_PAGE_INCOMPLETE")
    seen, successful, adverse, incomplete = set(), set(), 0, 0
    bad = {"failure", "cancelled", "timed_out", "action_required",
           "startup_failure", "stale"}
    conclusions = bad | {"success", "neutral", "skipped", None}
    statuses = {"completed", "queued", "in_progress", "pending", "waiting"}
    for row in raw["check_runs"]:
        require(type(row) is dict
                and type(row.get("id")) is int and row["id"] > 0
                and row["id"] not in seen
                and row.get("head_sha") == head_sha
                and type(row.get("name")) is str
                and 1 <= len(row["name"]) <= 128
                and type(row.get("app")) is dict
                and type(row["app"].get("id")) is int
                and row["app"]["id"] > 0
                and row.get("status") in statuses
                and row.get("conclusion") in conclusions,
                "REPAIR_EXACT_HEAD_CI_ROW_INVALID")
        seen.add(row["id"])
        if row["status"] != "completed" or row["conclusion"] is None:
            incomplete += 1
        elif row["conclusion"] in bad:
            adverse += 1
        elif (row["app"]["id"] == TRUSTED_CHECK_APP
              and row["status"] == "completed"
              and row["conclusion"] == "success"):
            successful.add(row["name"])
    required = REQUIRED_HEAD_CHECKS[repository]
    missing = sorted(required - successful)
    state = (
        "ADVERSE_EXACT_HEAD_CHECKS_NEED_REPAIR" if adverse else
        "INCOMPLETE_EXACT_HEAD_CHECKS" if incomplete else
        "MISSING_REQUIRED_EXACT_HEAD_CHECKS" if missing else
        "EXACT_HEAD_TECHNICAL_CHECKS_GREEN_NOT_RELEASE"
    )
    return {
        "repository": repository,
        "pr_number": pr_number,
        "source_head_sha": head_sha,
        "status": state,
        "required_check_names": sorted(required),
        "required_not_successful": missing,
        "checked_count": len(seen),
        "adverse_count": adverse,
        "incomplete_count": incomplete,
        "trusted_app_id": TRUSTED_CHECK_APP,
        "technical_only_not_release": True,
        "external_contact_or_financial_authority": False,
    }


def apply_original_ci_to_owner_queue(continuation, source_checks):
    """Convert verified PR-head facts into owner next steps, not approval."""
    import copy
    require(type(continuation) is dict
            and continuation.get("scope") ==
                "BOUNDED_EXISTING_OWNER_FOLLOWTHROUGH_ONLY"
            and continuation.get("merge_or_deployment_authority") is False
            and type(continuation.get("actions")) is list
            and type(continuation.get("next_history")) is list
            and type(source_checks) is list and len(source_checks) <= MAX_JOBS,
            "REPAIR_SOURCE_CI_BINDING_SCOPE_INVALID")
    result = copy.deepcopy(continuation)
    matched, seen = 0, set()
    for evidence in source_checks:
        require(type(evidence) is dict
                and evidence.get("repository") in REPOS
                and type(evidence.get("pr_number")) is int
                and type(evidence.get("source_head_sha")) is str
                and SHA.fullmatch(evidence["source_head_sha"])
                and evidence.get("trusted_app_id") == TRUSTED_CHECK_APP
                and evidence.get("technical_only_not_release") is True
                and evidence.get("external_contact_or_financial_authority") is False
                and evidence.get("status") in {
                    "ADVERSE_EXACT_HEAD_CHECKS_NEED_REPAIR",
                    "INCOMPLETE_EXACT_HEAD_CHECKS",
                    "MISSING_REQUIRED_EXACT_HEAD_CHECKS",
                    "EXACT_HEAD_TECHNICAL_CHECKS_GREEN_NOT_RELEASE",
                },
                "REPAIR_SOURCE_CI_RECEIPT_UNTRUSTED")
        key = (evidence["repository"], evidence["pr_number"],
               evidence["source_head_sha"])
        require(key not in seen, "REPAIR_SOURCE_CI_RECEIPT_DUPLICATE")
        seen.add(key)
        targets = [
            task for task in result["actions"]
            if (task["repository"], task["source_pr"],
                task["source_head_sha"]) == key
        ]
        if not targets:
            # Ignore an already superseded PR: do not reassign an issue.
            continue
        require(len(targets) == 1, "REPAIR_SOURCE_CI_OWNER_AMBIGUOUS")
        task = targets[0]
        if task["technical_main_source_verified"]:
            continue
        condition = evidence["status"]
        task["original_source_ci_status"] = condition
        history = [
            row for row in result["next_history"]
            if row["repository"] == evidence["repository"]
            and row["pr_number"] == evidence["pr_number"]
            and row["head_sha"] == evidence["source_head_sha"]
        ]
        require(len(history) == 1, "REPAIR_SOURCE_CI_HISTORY_MISSING")
        prior_state = history[0]["state"]
        if prior_state == "BLOCKED_EXTERNAL":
            task["next_operation"] = "PRESERVE_EXTERNAL_HOLD_FIX_NEXT"
        elif (prior_state == "CI_RED"
              and history[0]["source_revision_attempts"] == 2
              and condition == "ADVERSE_EXACT_HEAD_CHECKS_NEED_REPAIR"):
            task["next_operation"] = "ESCALATE_REPRODUCIBLE_FAILURE_WITH_LOGS"
        elif condition == "ADVERSE_EXACT_HEAD_CHECKS_NEED_REPAIR":
            task["next_operation"] = "REPRODUCE_AND_FIX_REAL_FAILED_HEAD_CI"
            history[0]["state"] = "CI_RED"
            history[0]["last_progress_cycle"] = result["cycle"]
        elif condition == "EXACT_HEAD_TECHNICAL_CHECKS_GREEN_NOT_RELEASE":
            if prior_state not in {"INDEPENDENT_GREEN", "DELIVERY_REQUESTED"}:
                task["next_operation"] = "GET_INDEPENDENT_QA_AND_VERIFY_RELEASE_HOLDS"
                history[0]["state"] = "CI_GREEN"
                history[0]["last_progress_cycle"] = result["cycle"]
        else:
            if prior_state not in {"INDEPENDENT_GREEN", "DELIVERY_REQUESTED"}:
                task["next_operation"] = "RESTORE_MISSING_OR_INCOMPLETE_EXACT_CI"
                history[0]["state"] = "OBSERVED"
                history[0]["last_progress_cycle"] = result["cycle"]
        matched += 1
    result["original_ci_bound_actions"] = matched
    result["original_ci_provider_readonly"] = True
    result["merge_or_deployment_authority"] = False
    result["real_buyer_or_revenue_verified"] = False
    return result


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
    requests, proofs, gaps, source_checks, cache = 0, [], [], [], {}

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
        # Independent original candidate CI is the crucial missing link
        # between a detected defect and an actual patch/test instruction.
        # One bounded read can diagnose a source failure without GitHub writes.
        try:
            raw_head = get(
                repo, f"/commits/{expected}/check-runs?per_page=100",
            )
        except (OSError, urllib.error.URLError, BrainError, ValueError):
            gaps.append({
                "repository": repo, "pr_number": number,
                "status": "EXACT_HEAD_CHECKS_UNAVAILABLE_NOT_GREEN",
            })
        else:
            source_checks.append(
                _head_ci_receipt(raw_head, repo, number, expected)
            )
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
        "source_checks": source_checks,
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
