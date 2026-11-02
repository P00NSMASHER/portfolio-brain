"""Independent trusted-main review of exact preapproved autonomous repair bytes.

The PR author's claimed receipt and operation ID are never sufficient. Before
a bot draft becomes ready, re-read the registry and original source from the
protected main SHA, reproduce the reviewed deterministic patch, and verify
the *exact* resulting candidate Git blobs. No network beyond original GitHub
GETs, no source execution, no mutation, no claim of real RED/GREEN artifacts.
"""
from __future__ import annotations

from brain.v10 import engineering_factory as factory
from brain.v9 import guarded_merge as gm

REGISTRY = "repair/V11_PREAPPROVED_SOURCE_RECIPES.json"
ROOT = "repos/" + factory.REPOSITORY + "/"
MAX_CANDIDATE_FILES = 4


class ReviewDenied(ValueError):
    pass


def require(condition, reason):
    if not condition:
        raise ReviewDenied("V11_APPROVED_PATCH_" + reason)


def read_blob(api, path, sha):
    """Get exact original provider content, rejecting nonregular/symlink blobs."""
    require(type(sha) is str and gm.SHA.fullmatch(sha) is not None,
            "SHA_INVALID")
    require(type(path) is str and path and
            not any(part in ("", ".", "..") for part in path.split("/")),
            "PATH_INVALID")
    try:
        content = api.get(ROOT + "contents/" + path + "?ref=" + sha)
        raw = gm.checked_document(content)
    except (gm.Denied, KeyError, ValueError, TypeError):
        raise ReviewDenied("V11_APPROVED_PATCH_PROVIDER_BLOB_INVALID") from None
    return raw


def verify_reviewed_patch(api, *, main_sha, head_sha, run_id,
                          operation_id, reviewed_regression_sha256,
                          changed_paths, failed_families):
    """Read-only proof that every changed byte is exactly a reviewed recipe."""
    require(type(main_sha) is str and gm.SHA.fullmatch(main_sha) is not None
            and type(head_sha) is str and gm.SHA.fullmatch(head_sha) is not None
            and main_sha != head_sha, "SOURCE_IDENTITY_INVALID")
    require(type(run_id) is int and 0 < run_id < 10**12
            and type(operation_id) is str
            and factory.VALID_HASH.fullmatch(operation_id) is not None,
            "OPERATION_ID_INVALID")
    require(type(reviewed_regression_sha256) is str
            and factory.VALID_HASH.fullmatch(reviewed_regression_sha256)
            is not None, "REVIEWED_REGRESSION_DIGEST_INVALID")
    require(type(changed_paths) is list
            and 1 <= len(changed_paths) <= MAX_CANDIDATE_FILES
            and changed_paths == sorted(set(changed_paths))
            and all(type(path) is str and factory.safe_path(path)
                    for path in changed_paths), "PR_PATHS_INVALID")
    require(type(failed_families) is set
            and 1 <= len(failed_families) <= 20
            and all(type(family) is str and family for family in failed_families),
            "FAILED_STAGE_NOT_AUTHENTICATED")

    # This file is read from *main*, never the untrusted PR branch or body.
    try:
        registry = factory._strict_json(read_blob(api, REGISTRY, main_sha))
        # Import at call time, after the trusted V11 admission module is loaded.
        from brain.v11 import approved_recipe_runner as recipes
        reviewed = recipes.validate_registry(
            registry, source_sha=main_sha, run_id=run_id)
    except (factory.FactoryError, ReviewDenied, ValueError, TypeError):
        raise ReviewDenied("V11_APPROVED_PATCH_REGISTRY_UNVERIFIED") from None

    matching = [(row, spec) for row, spec in reviewed
                if row["stage_family"] in failed_families]
    require(len(matching) == 1, "RECIPE_MISSING_OR_AMBIGUOUS")
    row, spec = matching[0]
    require(row["regression"]["sha256"] == reviewed_regression_sha256,
            "REVIEWED_REGRESSION_NOT_SOURCE_BOUND")
    expected_paths = sorted(change["path"] for change in spec["changes"])
    require(expected_paths == changed_paths,
            "UNREVIEWED_OR_MISSING_CHANGED_FILES")

    # Source must match the reviewed full-file SHA-256, not just substring.
    originals = {
        path: read_blob(api, path, main_sha) for path in changed_paths
    }
    try:
        prepared = factory.prepare(spec, originals)
    except factory.FactoryError:
        raise ReviewDenied("V11_APPROVED_PATCH_ORIGINAL_SOURCE_UNVERIFIED") from None
    require(prepared["operation_id"] == operation_id,
            "OPERATION_NOT_REPRODUCED")
    require(prepared["branch"] ==
            "auto-repair/v10-" + operation_id[:16],
            "BRANCH_NOT_REPRODUCED")
    for change in prepared["changes"]:
        candidate_raw = read_blob(api, change["path"], head_sha)
        require(candidate_raw == change["updated_bytes"]
                and factory.sha256(candidate_raw) == change["after_sha256"],
                "CANDIDATE_BLOB_NOT_REVIEWED_PATCH")
    # Historical runtime receipt contents are *not* independently observed.
    return {"recipe_id": row["id"],
            "operation_id": operation_id,
            "reviewed_changed_paths": expected_paths,
            "exact_reviewed_patch_verified": True,
            "reviewed_regression_sha256": reviewed_regression_sha256,
            "red_green_artifact_independently_verified": False,
            "provider_writes": 0}
