"""Preapproved, source-locked repair recipes for genuine Brain core failures.

This selector is strictly read-only. No network, model, agent secrets,
GitHub mutation, or test-success claim is possible here. If exactly one
reviewed source recipe matches a previously authenticated failure, it emits
a standard V10 manifest. V10 must then reproduce RED and prove GREEN in
its offline Docker suite and reverify the original GitHub failure before
a scoped App may create a DRAFT PR. Neither selector nor V10 can merge.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess

from brain.v10 import engineering_factory as factory
from brain.v11 import failure_triage, verified_delivery

REPO = factory.REPOSITORY
MAX_RECIPES = 8
MAX_MANIFEST_BYTES = 120_000
MAX_RECEIPT_BYTES = 6000
RECIPE_NAME = re.compile(r"[a-z][a-z0-9-]{2,63}\Z")
ALLOWED_STAGES = frozenset(failure_triage.STEP_FAMILIES.values())
ALLOWED_FILES = verified_delivery.LOW_RISK_BRAIN_FILES


def _source_head(root):
    root = Path(root)
    factory.require(not root.is_symlink() and root.is_dir(),
                    "RECIPE_WORKSPACE_UNSAFE")
    try:
        value = subprocess.run(
            ["git", "-C", str(root.resolve(strict=True)), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=15, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise factory.FactoryError("RECIPE_GIT_HEAD_UNAVAILABLE") from exc
    factory.require(value.returncode == 0 and
                    factory.VALID_SHA.fullmatch(value.stdout.strip()) is not None,
                    "RECIPE_SOURCE_IDENTITY_UNVERIFIED")
    clean = subprocess.run(
        ["git", "-C", str(root.resolve(strict=True)),
         "status", "--porcelain=v1", "--untracked-files=all"],
        capture_output=True, text=True, timeout=15, check=False)
    factory.require(clean.returncode == 0 and not clean.stdout.strip(),
                    "RECIPE_WORKSPACE_DIRTY")
    return value.stdout.strip()


def _strict_doc(file, *, max_size):
    path = Path(file)
    factory.require(path.is_file() and not path.is_symlink()
                    and 1 <= path.stat().st_size <= max_size,
                    "RECIPE_DOCUMENT_UNSAFE")
    return factory._strict_json(path.read_bytes())


def validate_receipt(receipt, *, source_sha):
    factory.require(type(receipt) is dict
                    and receipt.get("status") ==
                    "ORIGINAL_AUTOMATIC_FAILURE_CLASSIFIED_NOT_REPAIRED"
                    and receipt.get("repository") == REPO
                    and receipt.get("source_sha") == source_sha
                    and type(receipt.get("source_run_id")) is int
                    and 0 < receipt["source_run_id"] < 10**12
                    and receipt.get("original_event") in
                    {"schedule", "workflow_dispatch"}
                    and receipt.get("original_conclusion") in
                    {"failure", "timed_out"}
                    and receipt.get("stage_is_root_cause") is False
                    and receipt.get("candidate_patch_prepared") is False
                    and receipt.get("draft_pr_created") is False
                    and receipt.get("merged") is False
                    and receipt.get("production_accepted") is False
                    and type(receipt.get("provider_writes")) is int
                    and receipt["provider_writes"] == 0,
                    "RECIPE_ORIGINAL_FAILURE_RECEIPT_INVALID")
    stages = receipt.get("failed_stage_families")
    factory.require(type(stages) is list and 1 <= len(stages) <= 15
                    and all(type(stage) is str
                            and stage in ALLOWED_STAGES |
                            {"UNCLASSIFIED_ORIGINAL_STEP"}
                            for stage in stages)
                    and stages == sorted(set(stages)),
                    "RECIPE_STAGE_FAMILIES_INVALID")
    expected = factory.sha256(factory.canonical({
        "repository": REPO, "source_sha": source_sha,
        "run_id": receipt["source_run_id"], "stages": stages}).encode())
    factory.require(receipt.get("fingerprint_sha256") == expected,
                    "RECIPE_ORIGINAL_FAILURE_HASH_INVALID")
    return stages


def validate_registry(registry, *, source_sha, run_id):
    factory.require(type(registry) is dict
                    and set(registry) == {"schema_version", "repository", "recipes"}
                    and type(registry["schema_version"]) is int
                    and registry["schema_version"] == 1
                    and registry["repository"] == REPO
                    and type(registry["recipes"]) is list
                    and len(registry["recipes"]) <= MAX_RECIPES,
                    "RECIPE_REGISTRY_INVALID")
    reviewed = []
    ids = set()
    for row in registry["recipes"]:
        factory.require(type(row) is dict and
                        set(row) == {"id", "stage_family", "changes", "regression"}
                        and type(row["id"]) is str
                        and RECIPE_NAME.fullmatch(row["id"]) is not None
                        and row["id"] not in ids
                        and type(row["stage_family"]) is str
                        and row["stage_family"] in ALLOWED_STAGES,
                        "RECIPE_ENTRY_INVALID")
        ids.add(row["id"])
        factory.validate_reviewed_regression(row["regression"])
        changes = row["changes"]
        spec = {
            "schema_version": 1, "repository": REPO,
            "base_sha": source_sha, "failure_run_id": run_id,
            "changes": changes,
        }
        factory.validate_request(spec)
        # The existing bot release gate does not allow versioned control
        # planes, tests, privileged workflows or new file creation.
        factory.require(all(patch["path"] in ALLOWED_FILES for patch in changes),
                        "RECIPE_CHANGED_PATH_NOT_APPROVED")
        reviewed.append((row, spec))
    return reviewed


def choose(root, receipt, registry):
    """Classify one reviewed recipe; no proof of a completed fix or PR."""
    main_sha = _source_head(root)
    families = validate_receipt(receipt, source_sha=main_sha)
    approved = validate_registry(registry, source_sha=main_sha,
                                 run_id=receipt["source_run_id"])
    matches = [(row, spec) for row, spec in approved
               if row["stage_family"] in families]
    factory.require(len(matches) <= 1, "RECIPE_AMBIGUOUS_REVIEWED_MATCH")
    if not matches:
        return {"status": "NO_PREAPPROVED_SOURCE_FIX", "eligible": False,
                "source_sha": main_sha, "source_run_id": receipt["source_run_id"],
                "provider_writes": 0, "draft_pr_created": False}, None
    row, spec = matches[0]
    workspace = Path(root).resolve(strict=True)
    sources = {}
    for patch in spec["changes"]:
        path = workspace / patch["path"]
        factory.require(path.is_file() and not path.is_symlink()
                        and path.resolve(strict=True).is_relative_to(workspace)
                        and not any(ancestor.is_symlink() for ancestor in path.parents
                                    if ancestor != workspace
                                    and workspace in ancestor.parents),
                        "RECIPE_SOURCE_PATH_UNSAFE")
        sources[patch["path"]] = path.read_bytes()
    # A corrected (or otherwise changed) file no longer matches this recipe.
    # It must not turn an unrelated failure in the same stage into a writer request.
    if any(factory.sha256(sources[change["path"]]) != change["expected_sha256"]
           for change in spec["changes"]):
        return {"status": "NO_PREAPPROVED_SOURCE_FIX", "eligible": False,
                "reason": "REVIEWED_PREIMAGE_NOT_PRESENT",
                "source_sha": main_sha, "source_run_id": receipt["source_run_id"],
                "provider_writes": 0, "draft_pr_created": False}, None
    candidate = factory.prepare(spec, sources)
    return {
        "status": "SOURCE_LOCKED_REVIEWED_RECIPE_PREPARED_NOT_TESTED",
        "eligible": True, "recipe_id": row["id"],
        "source_sha": main_sha,
        "source_run_id": receipt["source_run_id"],
        "operation_id": candidate["operation_id"],
        "reviewed_regression_sha256": row["regression"]["sha256"],
        "reviewed_regression_path": row["regression"]["path"],
        "red_green_tested": False, "independent_check_passed": False,
        "draft_pr_created": False, "merged": False,
        "provider_writes": 0,
    }, spec


def _write_once(path, data):
    path = Path(path)
    factory.require(path.parent.is_dir() and not path.is_symlink(),
                    "RECIPE_OUTPUT_PATH_UNSAFE")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        out.write(factory.canonical(data) + "\n")
        out.flush()
        os.fsync(out.fileno())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--registry", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--spec", required=True)
    parser.add_argument("--decision", required=True)
    parser.add_argument("--reviewed-test", required=True)
    args = parser.parse_args(argv)
    try:
        receipt = _strict_doc(args.receipt, max_size=MAX_RECEIPT_BYTES)
        registry = _strict_doc(args.registry, max_size=MAX_MANIFEST_BYTES)
        decision, spec = choose(args.workspace, receipt, registry)
        if spec is not None:
            selected = [row for row in registry["recipes"]
                        if row["id"] == decision["recipe_id"]]
            factory.require(len(selected) == 1,
                            "RECIPE_REVIEWED_TEST_UNVERIFIED")
            _write_once(args.reviewed_test, selected[0]["regression"])
            _write_once(args.spec, spec)
        _write_once(args.decision, decision)
        print(json.dumps({"status": decision["status"],
                          "eligible": decision["eligible"],
                          "provider_writes": 0, "merged": False}, sort_keys=True))
        return 0
    except (factory.FactoryError, ValueError, OSError, subprocess.SubprocessError):
        print(json.dumps({"status": "RECIPE_SOURCE_NOT_AUTHORIZED",
                          "eligible": False, "provider_writes": 0,
                          "merged": False}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
