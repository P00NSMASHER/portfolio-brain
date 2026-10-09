"""Read-only technical transfer evidence, not operator feedback or adoption.

Uses the existing verified Brain report and the existing bounded GET-only GitHub
adapter. A linked draft PR with green checks proves neither integration nor
customer value, and can never grant code execution, payment or write authority.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from brain.core import BrainError, digest, require
from brain.intelligence import REPO, SHA

# These are source-reviewed *observability* gates for the first supported
# downstream project, not user-supplied names that could make a trivial
# check appear to certify a candidate. Adding other targets requires review.
_TARGETS = {
    "P00NSMASHER/github-value-hunt-ledger": {
        "required_checks": frozenset({
            "freight", "recoveryworks", "release-gate", "contracts", "verify"
        }),
        "allowed_changed_prefix": "freight/",
        "expected_check_app_id": 15368,  # GitHub Actions; NOT an independent auditor
        "skippable_check_names": frozenset({"deploy"}),
    },
}


def _request(input_data):
    require(type(input_data) is dict and set(input_data) == {
        "schema_version", "candidate_key", "target_repository",
        "pull_request_number", "expected_head_sha",
    }, "TRANSFER_INPUT_SCHEMA: only exact approved fields accepted")
    require(input_data["schema_version"] == 1, "TRANSFER_INPUT_VERSION")
    require(
        type(input_data["candidate_key"]) is str
        and 0 < len(input_data["candidate_key"]) <= 200
        and ":" in input_data["candidate_key"],
        "TRANSFER_CANDIDATE_KEY",
    )
    target = input_data["target_repository"]
    require(
        type(target) is str and REPO.fullmatch(target) is not None
        and target in _TARGETS,
        "TRANSFER_TARGET_NOT_APPROVED",
    )
    require(
        type(input_data["pull_request_number"]) is int
        and 0 < input_data["pull_request_number"] <= 1_000_000_000,
        "TRANSFER_PR_NUMBER",
    )
    require(
        type(input_data["expected_head_sha"]) is str
        and SHA.fullmatch(input_data["expected_head_sha"]) is not None,
        "TRANSFER_HEAD_SHA",
    )
    return input_data


def _canonical_source(report, candidate_key):
    require(type(report) is dict and report.get("status") == "PASS",
            "TRANSFER_CANONICAL_REPORT_NOT_PASS")
    require(SHA.fullmatch(report.get("source_sha", "")) is not None,
            "TRANSFER_SOURCE_SHA")
    require(report.get("pending_events") == 0,
            "TRANSFER_PENDING_EVENTS")
    candidates = report.get("reuse_candidates")
    require(type(candidates) is list, "TRANSFER_CANDIDATES_UNAVAILABLE")
    found = [x for x in candidates if x.get("key") == candidate_key]
    require(len(found) == 1, "TRANSFER_CANDIDATE_NOT_UNIQUE_IN_LEDGER_REPORT")
    item = found[0]
    require(
        item.get("data_kind") == "ACTUAL"
        and item.get("freshness") == "CURRENT"
        and item.get("utility_evidence") == "STRUCTURAL_ONLY_NOT_EXECUTED",
        "TRANSFER_SOURCE_NOT_ACTUAL_CURRENT",
    )
    require(
        type(item.get("repository")) is str and REPO.fullmatch(item["repository"])
        and type(item.get("head_sha")) is str and SHA.fullmatch(item["head_sha"])
        and type(item.get("path")) is str
        and item["source_ref"] ==
        f'https://github.com/{item["repository"]}/blob/{item["head_sha"]}/{item["path"]}',
        "TRANSFER_SOURCE_REF_UNBOUND",
    )
    require(
        SHA.fullmatch(item.get("blob_sha", "")) is not None
        and isinstance(item.get("code_sha256"), str)
        and re.fullmatch(r"[0-9a-f]{64}", item["code_sha256"]) is not None,
        "TRANSFER_SOURCE_BYTES_UNVERIFIED",
    )
    return item


def review_transfer(report, input_data, *, api):
    """Reconcile one source against actual target PR/CI GitHub metadata.

    The caller MUST supply an existing Store.read_report() result, which
    performs canonical SQLite ledger replay. This pure function does NOT
    mutate the ledger or call any GitHub write endpoint.
    """
    request = _request(input_data)
    source = _canonical_source(report, request["candidate_key"])
    target = request["target_repository"]
    number = request["pull_request_number"]
    expected = request["expected_head_sha"]
    policy = _TARGETS[target]
    prefix = f"/repos/{target}"

    metadata = api.get(prefix)
    require(
        type(metadata) is dict
        and metadata.get("full_name") == target
        and metadata.get("private") is False,
        "TRANSFER_TARGET_NOT_PUBLIC_EXACT_IDENTITY",
    )
    pr = api.get(f"{prefix}/pulls/{number}")
    require(
        type(pr) is dict and pr.get("number") == number
        and pr.get("state") in {"open", "closed"}
        and type(pr.get("draft")) is bool
        and type(pr.get("merged")) is bool,
        "TRANSFER_PR_PROVIDER_METADATA",
    )
    head, base = pr.get("head") or {}, pr.get("base") or {}
    require(
        head.get("sha") == expected
        and (head.get("repo") or {}).get("full_name") == target
        and (base.get("repo") or {}).get("full_name") == target
        and base.get("ref") == metadata.get("default_branch"),
        "TRANSFER_PR_WRONG_HEAD_REPO_OR_BASE",
    )
    require(
        type(pr.get("changed_files")) is int
        and 1 <= pr["changed_files"] <= 100,
        "TRANSFER_PR_FILE_SCOPE_UNAVAILABLE",
    )
    files = api.get(f"{prefix}/pulls/{number}/files?per_page=100")
    require(
        type(files) is list and len(files) == pr["changed_files"],
        "TRANSFER_PR_FILES_INCOMPLETE",
    )
    changed_paths = []
    for row in files:
        name = row.get("filename") if type(row) is dict else None
        require(
            type(name) is str
            and len(name) <= 500
            and name.startswith(policy["allowed_changed_prefix"])
            and ".." not in name.split("/"),
            "TRANSFER_PR_OUT_OF_APPROVED_SCOPE",
        )
        changed_paths.append(name)
    require(len(set(changed_paths)) == len(changed_paths),
            "TRANSFER_DUPLICATED_FILES")

    # Target author text is an asserted attribution, not independent causation.
    body = pr.get("body")
    attribution = (
        "EXACT_SOURCE_LINK_CLAIMED_IN_PR"
        if type(body) is str and source["source_ref"] in body
        else "ORIGIN_LINK_NOT_CORROBORATED"
    )

    check_document = api.get(
        f"{prefix}/commits/{expected}/check-runs?per_page=100"
    )
    require(
        type(check_document) is dict
        and type(check_document.get("total_count")) is int
        and 0 <= check_document["total_count"] <= 100
        and type(check_document.get("check_runs")) is list
        and len(check_document["check_runs"]) == check_document["total_count"],
        "TRANSFER_CHECK_COVERAGE_INCOMPLETE",
    )
    observed, ids, failures = {}, set(), []
    for row in check_document["check_runs"]:
        require(
            type(row) is dict and type(row.get("id")) is int
            and row["id"] not in ids
            and type(row.get("name")) is str
            and row.get("head_sha") == expected
            and type(row.get("app")) is dict
            and type(row["app"].get("id")) is int,
            "TRANSFER_CHECK_IDENTITY_UNVERIFIED",
        )
        ids.add(row["id"])
        name = row["name"]
        observed.setdefault(name, []).append(row)
        complete = row.get("status") == "completed"
        acceptable = (
            row.get("conclusion") == "success"
            or (
                name in policy["skippable_check_names"]
                and row.get("conclusion") == "skipped"
            )
        )
        if not complete or not acceptable:
            failures.append(name)
    missing = sorted(policy["required_checks"] - observed.keys())
    for name in sorted(policy["required_checks"] & observed.keys()):
        if not all(
            x.get("status") == "completed"
            and x.get("conclusion") == "success"
            and x["app"]["id"] == policy["expected_check_app_id"]
            for x in observed[name]
        ):
            failures.append(name)
    check_state = (
        "GITHUB_REPORTED_REQUIRED_CHECKS_SUCCESS"
        if not missing and not failures else "GITHUB_CHECK_EVIDENCE_INCOMPLETE"
    )
    # A green PR is NEVER evidence the target deployed or used the feature.
    qualified = (
        check_state == "GITHUB_REPORTED_REQUIRED_CHECKS_SUCCESS"
        and attribution == "EXACT_SOURCE_LINK_CLAIMED_IN_PR"
    )
    status = (
        ("MERGED_PR_METADATA_ONLY_NOT_DEPLOYMENT"
         if pr["merged"] else "DRAFT_PR_CHECKS_PASSED_NOT_ADOPTED"
         if pr["draft"] else "OPEN_PR_CHECKS_PASSED_NOT_ADOPTED")
        if qualified else "TRANSFER_TECHNICAL_EVIDENCE_BLOCKED"
    )
    return {
        "schema_version": 1,
        "status": status,
        "scope": "READ_ONLY_CROSS_PROJECT_TECHNICAL_OBSERVATION",
        "brain_report_source_sha": report["source_sha"],
        "brain_canonical_hash": report.get("canonical_hash"),
        "brain_state_sequence": report.get("state_sequence"),
        "candidate_key": source["key"],
        "origin": {
            "repository": source["repository"],
            "revision": source["head_sha"],
            "path": source["path"],
            "blob_sha": source["blob_sha"],
            "code_sha256": source["code_sha256"],
            "source_ref": source["source_ref"],
            "published_license_metadata": source.get("license"),
            "attribution": attribution,
            "original_code_executed": False,
        },
        "target": {
            "repository": target,
            "pr_number": number,
            "pr_url": f"https://github.com/{target}/pull/{number}",
            "pr_head_sha": expected,
            "base_branch": base["ref"],
            "draft": pr["draft"],
            "merged_pr_metadata": pr["merged"],
            "changed_paths": changed_paths,
        },
        "checks": {
            "status": check_state,
            "required_names": sorted(policy["required_checks"]),
            "missing_required": missing,
            "failed_or_incomplete_names": sorted(set(failures)),
            "provider_check_count": len(ids),
            "matched_required_count": sum(
                len(observed.get(name, [])) for name in policy["required_checks"]
            ),
            "skipped_deployment_proves_no_deployment": False,
            "ci_success_is_not_independent_customer_validation": True,
        },
        "integration": "NOT_VERIFIED_BY_PULL_REQUEST_CHECKS",
        "external_use": "NOT_VERIFIED",
        "operator_feedback": "NOT_COLLECTED",
        "customer_value": "NOT_VERIFIED",
        "realized_recovery": "NOT_VERIFIED",
        "revenue": "NOT_VERIFIED",
        "time_saved": "UNMEASURED",
        "event_written": False,
        "github_mutations": 0,
        "evidence_fingerprint": digest({
            "candidate_key": source["key"],
            "source_sha": source["code_sha256"],
            "target": target,
            "pr": number,
            "head": expected,
            "checks": sorted(ids),
            "paths": sorted(changed_paths),
            "status": status,
        }),
    }


def write_transfer_review(report, destination):
    """Private-by-default local receipts; never write Brain canonical state."""
    out = Path(destination)
    out.mkdir(parents=True, exist_ok=True)
    os.chmod(out, 0o700)
    output = out / "transfer-review.json"
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    os.chmod(output, 0o600)
    return output
