"""Source-pinned fix -> CI -> independent gate -> merge/readback control.

Produces an exact-SHA guarded *request* for existing owner workflows. This
module has no GitHub write/network capability, merge credentials, financial
scope, or authority to override branch protections and release freezes.
"""
from __future__ import annotations

import hashlib
import re

from brain.core import require
from brain.repair_patch_executor import PATH, SHA, HASH, generate
from brain.repair_provider import _head_ci_receipt, TRUSTED_CHECK_APP

INDEPENDENT_APP = 5121826
INDEPENDENT_GATE = "portfolio-phase1-gate"
TEST = re.compile(r"tests/test_readonly_checkout_[0-9a-f]{16}\.py\Z")
ALLOWED = frozenset({
    "P00NSMASHER/github-value-hunt-ledger",
    "P00NSMASHER/x402-product-factory",
})


def _digest(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _check_request(patch, pr, observed_files, original_source_bytes):
    require(type(patch) is dict
            and patch.get("status") == "REVIEWED_REPAIR_AND_REGRESSION_READY"
            and patch.get("repository") in ALLOWED
            and type(patch.get("source_path")) is str
            and PATH.fullmatch(patch["source_path"])
            and type(patch.get("test_path")) is str
            and TEST.fullmatch(patch["test_path"])
            and type(patch.get("source_head_sha")) is str
            and SHA.fullmatch(patch["source_head_sha"])
            and type(patch.get("changed_content")) is str
            and type(patch.get("test_content")) is str
            and _digest(patch["changed_content"]) == patch.get("changed_sha256")
            and _digest(patch["test_content"]) == patch.get("test_sha256")
            and patch.get("independent_gate_required") is True
            and patch.get("merge_authority") is False
            and patch.get("deployment_authority") is False
            and patch.get("payment_or_external_contact_authority") is False,
            "REPAIR_DELIVERY_PATCH_SCOPE_UNVERIFIED")
    require(type(pr) is dict
            and type(pr.get("number")) is int
            and pr["number"] > 0
            and type(pr.get("head")) is dict
            and type(pr.get("base")) is dict
            and type(pr["head"].get("repo")) is dict
            and type(pr["base"].get("repo")) is dict
            and pr["head"]["repo"].get("full_name") == patch["repository"]
            and pr["base"]["repo"].get("full_name") == patch["repository"]
            and pr["base"].get("ref") == "main"
            and type(pr["head"].get("sha")) is str
            and SHA.fullmatch(pr["head"]["sha"])
            and pr["head"]["sha"] != patch["source_head_sha"]
            and type(pr.get("draft")) is bool
            and pr.get("state") in {"open", "closed"}
            and type(pr.get("merged")) is bool,
            "REPAIR_DELIVERY_PR_SOURCE_IDENTITY_INVALID")
    require(type(observed_files) is dict
            and set(observed_files) == {patch["source_path"], patch["test_path"]}
            and all(type(value) is str and HASH.fullmatch(value)
                    for value in observed_files.values())
            and observed_files[patch["source_path"]] == patch["changed_sha256"]
            and observed_files[patch["test_path"]] == patch["test_sha256"],
            "REPAIR_DELIVERY_CHANGED_BLOBS_NOT_ORIGINAL_PATCH")
    # Replay the trusted deterministic recipe from the original source. A
    # caller cannot submit arbitrary Python/YAML and simply forge SHA-256s.
    recipe = generate({
        "schema_version": 1,
        "repository": patch["repository"],
        "source_head_sha": patch["source_head_sha"],
        "path": patch["source_path"],
        "original_sha256": patch["original_sha256"],
        "repair_kind": "READONLY_CI_CHECKOUT_HARDENING",
        "independent_gate_required": True,
    }, original_source_bytes)
    require(recipe["changed_content"] == patch["changed_content"]
            and recipe["test_content"] == patch["test_content"]
            and recipe["test_path"] == patch["test_path"],
            "REPAIR_DELIVERY_PATCH_NOT_TRUSTED_RECIPE_REPLAY")
    return pr["head"]["sha"]


def _independent(raw, head):
    require(type(raw) is dict
            and type(raw.get("total_count")) is int
            and 0 <= raw["total_count"] <= 100
            and type(raw.get("check_runs")) is list
            and len(raw["check_runs"]) == raw["total_count"],
            "REPAIR_DELIVERY_CHECK_PAGE_NOT_COMPLETE")
    seen, passed, invalid = set(), False, False
    for check in raw["check_runs"]:
        require(type(check) is dict
                and type(check.get("id")) is int and check["id"] > 0
                and check["id"] not in seen
                and type(check.get("app")) is dict
                and type(check["app"].get("id")) is int
                and check.get("head_sha") == head,
                "REPAIR_DELIVERY_CROSS_SHA_OR_DUPLICATE_CHECK")
        seen.add(check["id"])
        if check.get("name") != INDEPENDENT_GATE:
            continue
        if check["app"]["id"] == INDEPENDENT_APP and (
            check.get("status") == "completed"
            and check.get("conclusion") == "success"
        ):
            passed = True
        else:
            invalid = True
    return passed and not invalid


def evaluate_delivery(patch, pr, observed_files, candidate_checks, *,
                      original_source_bytes, current_main_sha=None,
                      main_checks=None):
    """Classify exactly one original PR without ever calling merge."""
    head = _check_request(patch, pr, observed_files, original_source_bytes)
    repo, number = patch["repository"], pr["number"]
    ci = _head_ci_receipt(candidate_checks, repo, number, head)
    independent_ok = _independent(candidate_checks, head)
    base_sha = pr["base"].get("sha")
    require(type(base_sha) is str and SHA.fullmatch(base_sha),
            "REPAIR_DELIVERY_BASE_HEAD_UNVERIFIED")
    result = {
        "schema_version": 1,
        "repository": repo, "pr_number": number,
        "source_head_sha": head,
        "source_original_base_sha": patch["source_head_sha"],
        "source_ci_status": ci["status"],
        "independent_gate_verified": independent_ok,
        "changed_paths": [patch["source_path"], patch["test_path"]],
        "status": "HOLD",
        "next_action": None, "merge_request": None,
        "technical_main_verified": False,
        "live_service_verified": False,
        "actual_customer_value_verified": False,
        "merge_or_release_authority_granted": False,
        "money_or_contact_authority_granted": False,
    }
    if (pr["state"] == "open"
            and base_sha != patch["source_head_sha"]):
        result["next_action"] = "REBASE_AND_REPLAY_PATCH_ON_CURRENT_MAIN"
        return result
    # A merged PR's base.sha is not a frozen historical reference: GitHub
    # can advance the target branch after merge. Closed, genuinely merged
    # proposals must instead pass exact merge SHA + current-main + main-CI
    # verification below. This exception never authorizes an open stale PR.

    if ci["status"] != "EXACT_HEAD_TECHNICAL_CHECKS_GREEN_NOT_RELEASE":
        result["next_action"] = "REPAIR_EXACT_HEAD_CI_OR_RESTORE_REQUIRED_TESTS"
        return result
    if not independent_ok:
        result["next_action"] = "OBTAIN_DISTINCT_TRUSTED_INDEPENDENT_GATE"
        return result
    if pr["state"] == "open":
        if pr["draft"]:
            result["next_action"] = "READY_FOR_REVIEW_NOT_READY_FOR_MERGE"
        elif pr.get("mergeable") is True and pr.get("mergeable_state") == "clean":
            # This is a data-only request. A separately authorized owner
            # action must still call GitHub with exact SHA and obey rulesets.
            result["status"] = "SAFE_SOURCE_VERIFIED_FOR_GUARDED_OWNER_ACTION"
            result["next_action"] = "USE_EXISTING_PROTECTED_MERGE_IF_AUTHORIZED"
            result["merge_request"] = {
                "repository": repo, "pr_number": number,
                "expected_head_sha": head,
                "merge_method": "squash",
            }
        else:
            result["next_action"] = "RECONCILE_LIVE_BRANCH_OR_RULESET"
        return result
    if not pr["merged"]:
        result["next_action"] = "CLOSED_UNMERGED_IS_NOT_A_FIX"
        return result
    merged_sha = pr.get("merge_commit_sha")
    require(type(merged_sha) is str and SHA.fullmatch(merged_sha),
            "REPAIR_DELIVERY_MERGE_IDENTITY_INVALID")
    if type(current_main_sha) is not str or not SHA.fullmatch(current_main_sha):
        result["next_action"] = "FETCH_REAL_CURRENT_MAIN"
        return result
    if current_main_sha != merged_sha:
        result["next_action"] = "VERIFY_MERGE_ANCESTRY_AND_CURRENT_FILE_CONTENT"
        return result
    if main_checks is None:
        result["next_action"] = "VERIFY_ORIGINAL_MAIN_HEAD_CHECKS"
        return result
    checked = _head_ci_receipt(main_checks, repo, number, merged_sha)
    if checked["status"] != "EXACT_HEAD_TECHNICAL_CHECKS_GREEN_NOT_RELEASE":
        result["next_action"] = "RESTORE_ORIGINAL_MAIN_REGRESSION_GATES"
        return result
    result["status"] = "MAIN_SOURCE_TECHNICALLY_VERIFIED_NOT_LIVE_DEPLOYMENT"
    result["next_action"] = "VERIFY_ACTUAL_RELEASE_OR_PRIVATE_PREVIEW_SEPARATELY"
    result["technical_main_verified"] = True
    return result



def main(argv=None):
    """Offline local private evidence gate; never performs a GitHub action."""
    import argparse
    import json
    from pathlib import Path
    from brain.repair_followthrough_cli import _safe_json
    from brain.render import write_report
    parser = argparse.ArgumentParser(description="Review exact-source repair delivery")
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    record = _safe_json(args.bundle)
    require(type(record) is dict and set(record) == {
        "patch", "original_source", "pr", "file_hashes",
        "candidate_checks", "main_sha", "main_checks",
    } and type(record["original_source"]) is str
            and len(record["original_source"]) <= 24000,
            "REPAIR_DELIVERY_INPUT_BUNDLE_UNTRUSTED")
    outcome = evaluate_delivery(
        record["patch"], record["pr"], record["file_hashes"],
        record["candidate_checks"],
        original_source_bytes=record["original_source"].encode(),
        current_main_sha=record["main_sha"], main_checks=record["main_checks"],
    )
    write_report(outcome, args.output)
    print(json.dumps({
        "status": outcome["status"],
        "merge_authority": False, "live_verified": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
