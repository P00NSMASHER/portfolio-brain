"""Read-only recovery for uncertain v10 GitHub draft-PR writes.

A previous branch/PR write may have succeeded before the caller received a
response. Never blind-retry it. Read the original GitHub branch, exact file
contents and uniquely matching draft PR, then return NOT RELEASED evidence.
No merge, deployment, token minting, duplicate PR or code execution.
"""
from __future__ import annotations
import argparse
import base64
import json
import os
from pathlib import Path
import urllib.parse

from brain.v10 import engineering_factory as factory

_INTENT_FIELDS = {
    "operation_id", "source_sha", "branch", "repository",
    "failure_run_id", "test_receipt_sha256", "original_run_verdict", "status",
}

def load_intent(path):
    path = Path(path)
    factory.require(path.is_file() and not path.is_symlink()
                    and 1 <= path.stat().st_size <= 8192,
                    "FACTORY_INTENT_INVALID")
    intent = factory._strict_json(path.read_bytes())
    factory.require(type(intent) is dict and set(intent) == _INTENT_FIELDS,
                    "FACTORY_INTENT_FIELDS")
    return intent

def _require_exact_pr(row, *, number, source, branch, head, marker,
                      list_entry=False):
    factory.require(
        type(row) is dict and type(row.get("number")) is int
        and row["number"] == number
        and row.get("state") == "open"
        and row.get("merged_at") is None
        and (row.get("merged") is False or
             (list_entry and "merged" not in row))
        and row.get("draft") is True
        and type(row.get("head")) is dict
        and type(row.get("base")) is dict
        and row["head"].get("sha") == head
        and row["head"].get("ref") == branch
        and type(row["head"].get("repo")) is dict
        and row["head"]["repo"].get("full_name") == factory.REPOSITORY
        and row["base"].get("ref") == "main"
        and row["base"].get("sha") == source
        and type(row["base"].get("repo")) is dict
        and row["base"]["repo"].get("full_name") == factory.REPOSITORY
        and type(row.get("body")) is str
        and marker in row["body"].splitlines(),
        "FACTORY_RECONCILED_DRAFT_IDENTITY_INVALID",
    )

def reconcile_draft(api, spec, candidate, intent):
    """A successful response only proves a draft exists, never release."""
    factory.validate_request(spec)
    factory.require(type(candidate) is dict
                    and candidate.get("status") ==
                    "SOURCE_PINNED_PATCH_PREPARED_NOT_TESTED",
                    "FACTORY_CANDIDATE_INVALID")
    factory.require(type(intent) is dict and set(intent) == _INTENT_FIELDS,
                    "FACTORY_INTENT_FIELDS")
    expected = dict(
        operation_id=candidate["operation_id"],
        source_sha=spec["base_sha"],
        branch="auto-repair/v10-" + candidate["operation_id"][:16],
        repository=factory.REPOSITORY,
        failure_run_id=spec["failure_run_id"],
        original_run_verdict="ORIGINAL_FAILED_CORE_REPRODUCED_NOT_DIAGNOSED",
        status="EXTERNAL_WRITE_INTENT_MUST_RECONCILE",
    )
    factory.require(all(intent.get(key) == val for key, val in expected.items())
                    and type(intent.get("test_receipt_sha256")) is str
                    and factory.VALID_HASH.fullmatch(intent["test_receipt_sha256"]),
                    "FACTORY_INTENT_IDENTITY_INVALID")

    # Verify original failure and current main again; neither the intent nor a
    # provider PR list by itself is proof of the legitimate original incident.
    original = factory.verify_original_failed_core(api, spec)
    factory.require(original["status"] == expected["original_run_verdict"],
                    "FACTORY_ORIGINAL_RUN_NOT_RECONCILED")
    branch = api.request("GET", "branches/" + candidate["branch"])
    head = branch.get("commit", {}).get("sha")
    factory.require(type(head) is str and factory.VALID_SHA.fullmatch(head)
                    and head != spec["base_sha"],
                    "FACTORY_DRAFT_BRANCH_UNVERIFIED")

    for change in candidate["changes"]:
        route = "contents/" + change["path"] + "?ref=" + head
        doc = api.request("GET", route)
        factory.require(doc.get("type") == "file"
                        and doc.get("encoding") == "base64"
                        and type(doc.get("content")) is str
                        and type(doc.get("size")) is int
                        and 0 < doc["size"] <= factory.MAX_FILE_BYTES,
                        "FACTORY_DRAFT_SOURCE_READBACK_MISMATCH")
        try:
            original_bytes = base64.b64decode(
                doc["content"].replace("\n", ""), validate=True)
        except (ValueError, base64.binascii.Error) as exc:
            raise factory.FactoryError("FACTORY_DRAFT_SOURCE_READBACK_MISMATCH") from exc
        factory.require(
            len(original_bytes) == doc["size"]
            and original_bytes == change["updated_bytes"],
            "FACTORY_DRAFT_SOURCE_READBACK_MISMATCH",
        )

    # Exact owner and exact deterministic branch, no arbitrary GitHub search.
    query = ("pulls?head=P00NSMASHER%3Aauto-repair%2Fv10-"
             + candidate["operation_id"][:16] + "&state=open&per_page=100")
    matches = api.request("GET", query)
    factory.require(type(matches) is list and len(matches) == 1,
                    "FACTORY_DRAFT_PR_NOT_UNIQUELY_OBSERVED")
    pr = matches[0]
    number = pr.get("number")
    factory.require(type(number) is int and 0 < number < 10**9,
                    "FACTORY_DRAFT_PR_NUMBER_INVALID")
    marker = "BRAIN_V10_OPERATION_ID: " + candidate["operation_id"]
    _require_exact_pr(pr, number=number, source=spec["base_sha"],
                      branch=candidate["branch"], head=head, marker=marker,
                      list_entry=True)
    reread = api.request("GET", "pulls/" + str(number))
    _require_exact_pr(reread, number=number, source=spec["base_sha"],
                      branch=candidate["branch"], head=head, marker=marker)
    factory.require(api.request("GET", "branches/" + candidate["branch"])
                    .get("commit", {}).get("sha") == head
                    and api.request("GET", "branches/main")
                    .get("commit", {}).get("sha") == spec["base_sha"],
                    "FACTORY_SOURCE_MOVED_DURING_RECONCILIATION")
    return dict(status="ORIGINAL_GITHUB_DRAFT_RECONCILED_NOT_RELEASED",
                repository=factory.REPOSITORY, pr_number=number,
                source_sha=spec["base_sha"], candidate_sha=head,
                branch=candidate["branch"],
                operation_id=candidate["operation_id"],
                provider_writes=0, independent_gate_passed=False,
                merged=False, deployed=False, production_accepted=False)

def main(argv=None):
    from brain.v10 import __main__ as cli
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--intent", required=True)
    parser.add_argument("--receipt", required=True)
    args = parser.parse_args(argv)
    try:
        spec = cli._read_spec(args.manifest)
        original = cli._checkout_sources(args.workspace, spec)
        candidate = factory.prepare(spec, original)
        intent = load_intent(args.intent)
        api = factory.GitHubTransport(
            os.environ.get("PORTFOLIO_RUNTIME_TOKEN", ""))
        result = reconcile_draft(api, spec, candidate, intent)
        cli._write_receipt(args.receipt, result)
        print(json.dumps({"status": result["status"],
                          "pr_number": result["pr_number"],
                          "production_accepted": False}, sort_keys=True))
        return 0
    except (factory.FactoryError, ValueError, OSError) as exc:
        code = str(exc) if isinstance(exc, factory.FactoryError) else (
            "FACTORY_DRAFT_RECONCILIATION_UNAVAILABLE")
        print(json.dumps({"status": "BLOCKED", "code": code,
                          "production_accepted": False}, sort_keys=True))
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
