"""Small audited autonomous repair adapter: one genuine CaptureBrief doc defect.

This is a fixed, reversible, evidence-bound repair recipe.  It executes no
target-repository code and cannot merge, release, deploy or edit workflows.
Caller supplies a short-lived GitHub App token limited to CaptureBrief only.
"""
import base64
import hashlib
import json
import os
import re
import urllib.error
import urllib.request

TARGET = "P00NSMASHER/capturebrief"
OWNER = "P00NSMASHER"
APP_SLUG = "portfolio-brain-v8-runtime"
INSTALLATION = "172257326"
EXPECTED_TARGET_HEAD = "4a7c5d6c223b8488995ab221dc169ba32ae828f8"
EXPECTED_CANONICAL_BLOB = "f4182f742af5e793cb98efcf4b3dac5bfc0d9dd9"
EXPECTED_RELEASE_BLOB = "11eb0d1674bc7b2cf9ccb1a5aa907060f1e833c1"
ORIGINAL_DRAFT_PR = 47
ORIGINAL_DRAFT_HEAD = "33a0b2cd26921935bfca11a0b35e566ad0c735f1"
ORIGINAL_REPAIR_BLOB = "cba246861b93ffce495fbebcd5e2f0438d00ad4e"
SUCCESSOR_PR = 70
SUCCESSOR_BASE = "fb660e44eaf22c941e8aa25d42772c4768b76e20"
SUCCESSOR_HEAD = "f0a6bef1b6f9133501c2758747f1e2864e06365a"
SUCCESSOR_MERGE = "8b591cf42eaf1e4856adfdc766bacc5d3df9fa3e"
SUCCESSOR_BRANCH = "capturebrief-release-maintenance-20261021"
DOC = "PUBLIC-RELEASE.md"
CANONICAL = "DEPLOYMENT-TARGET.md"
BRANCH_PREFIX = "v8-capturebrief-hosting-doc-"
GIT_SHA = re.compile(r"[0-9a-f]{40}\Z")
MAX_RESPONSE = 1048576
MAX_REQUESTS = 22
MISLEADING = (
    "The existing CaptureBrief Netlify project remains the deployment target. Do not create\n"
    "a replacement site or publish the repository root.\n\n"
)
CORRECTION = (
    "> **Historical Netlify release artifact instructions — not the current website deployment path.**\n"
    "> CaptureBrief's authoritative website uses GitHub Pages, the gh-pages branch,\n"
    "> and https://p00nsmasher.github.io/capturebrief/. Do not publish the repository root.\n"
    "> The older Netlify ZIP, manual deployment and form steps below are retained\n"
    "> as historical build instructions, not as an active production-release procedure.\n\n"
)


HANDOFF_START = "## Existing-site handoff\n\n"
HANDOFF_END = "## Fulfillment readiness corrections"
HANDOFF_CORRECTION = (
    "## Current GitHub Pages release handoff\n\n"
    "The older Netlify release ZIP remains historical packaging evidence only,\n"
    "not a GitHub Pages deployment instruction. The authoritative website\n"
    "must be changed from its actual gh-pages branch, never from product-engine\n"
    "main or by uploading the older Netlify artifact bundle.\n"
    "Use the existing gh-pages site-quality workflow for independent website QA.\n\n"
    "After an authorized Pages release, independently verify the served homepage,\n"
    "sample page and assets at https://p00nsmasher.github.io/capturebrief/.\n"
    "CI success or deployment acknowledgement is not proof of publication.\n"
    "Do not submit test forms, contact customers or send messages without approval.\n\n"
)


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def digest_blob(raw):
    require(type(raw) is bytes, "GIT_BLOB_INVALID")
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()


def plan(source, original):
    """Only correct the one source-pinned contradiction and obsolete handoff."""
    require(type(source) is str and type(original) is str
            and len(source) <= 12000 and len(original) <= 60000,
            "SOURCE_BOUNDS_INVALID")
    require("Use GitHub Pages, not Netlify." in source
            and "- Website branch: " + chr(96) + "gh-pages" + chr(96) in source
            and "https://p00nsmasher.github.io/capturebrief/" in source
            and "- Product engine and its regression tests: " + chr(96) + "main" + chr(96) in source,
            "DEPLOYMENT_CANONICAL_SOURCE_NOT_CORROBORATED")
    require(original.startswith("# Verified public release artifact\n\n")
            and "## Build and publication are separate\n" in original,
            "RELEASE_DOCUMENT_SHAPE_CHANGED")
    if CORRECTION in original and MISLEADING not in original:
        require(HANDOFF_CORRECTION in original, "PARTIALLY_REPAIRED_DOCUMENT")
        return None
    require(original.count(MISLEADING) == 1 and CORRECTION not in original
            and original.count(HANDOFF_START) == 1
            and original.count(HANDOFF_END) == 1,
            "RELEASE_DOCUMENT_DEFECT_NOT_IDENTICAL")
    before, rest = original.split(HANDOFF_START, 1)
    obsolete, tail = rest.split(HANDOFF_END, 1)
    require("manual deployment to the" in obsolete
            and "existing project's Deploys page" in obsolete
            and "Do not submit test forms or send notification emails" in obsolete,
            "UNREVIEWED_OBSOLETE_HANDOFF")
    corrected = (before.replace(MISLEADING, CORRECTION, 1)
                 + HANDOFF_CORRECTION + HANDOFF_END + tail)
    require(corrected != original and MISLEADING not in corrected
            and corrected.count(CORRECTION) == 1
            and corrected.count(HANDOFF_CORRECTION) == 1
            and corrected.split(HANDOFF_END, 1)[1] == tail,
            "REPAIR_CHANGED_UNREVIEWED_CONTENT")
    return corrected


def checked_document(value, label):
    require(type(value) is dict and value.get("type") == "file"
            and value.get("encoding") == "base64"
            and type(value.get("size")) is int
            and 1 <= value["size"] <= 65000
            and type(value.get("sha")) is str
            and GIT_SHA.fullmatch(value["sha"]) is not None
            and type(value.get("content")) is str,
            label + "_SOURCE_INVALID")
    encoded = value["content"].replace("\n", "")
    raw = base64.b64decode(encoded, validate=True)
    require(len(raw) == value["size"] and digest_blob(raw) == value["sha"],
            label + "_BLOB_MISMATCH")
    return raw.decode("utf-8"), value["sha"]


def check_scope(inventory, installation, slug):
    require(installation == INSTALLATION and slug == APP_SLUG,
            "UNREVIEWED_RUNTIME_APP_IDENTITY")
    require(type(inventory) is dict and type(inventory.get("total_count")) is int
            and inventory["total_count"] == 1
            and type(inventory.get("repositories")) is list
            and len(inventory["repositories"]) == 1
            and type(inventory["repositories"][0]) is dict
            and inventory["repositories"][0].get("full_name") == TARGET,
            "TOKEN_MUST_HAVE_EXACTLY_ONE_TARGET_REPOSITORY")


def immutable_git_get(api, path):
    """Retry only a temporarily invisible identical SHA, not a mutation."""
    for retry in range(3):
        try:
            return api("GET", path)
        except urllib.error.HTTPError as exc:
            if exc.code != 404 or retry == 2:
                raise
            import time
            time.sleep(1)
    raise ValueError("IMMUTABLE_GITHUB_OBJECT_NEVER_BECAME_VISIBLE")


def checked_candidate(api, *, prefix, main_sha, branch_sha, fixed):
    """Reconcile only the unchanged direct child containing precisely one doc edit."""
    require(type(branch_sha) is str and GIT_SHA.fullmatch(branch_sha),
            "EXISTING_BRANCH_COMMIT_UNVERIFIED")
    original_commit = immutable_git_get(api, prefix + "git/commits/" + branch_sha)
    require(type(original_commit) is dict
            and original_commit.get("sha") == branch_sha
            and type(original_commit.get("parents")) is list
            and len(original_commit["parents"]) == 1
            and original_commit["parents"][0].get("sha") == main_sha,
            "EXISTING_BRANCH_NOT_EXACT_CHILD_OF_REVIEWED_MAIN")
    observed = immutable_git_get(
        api, prefix + "contents/" + DOC + "?ref=" + branch_sha)
    actual, original_blob = checked_document(observed, "REPAIRED")
    expected_blob = digest_blob(fixed.encode("utf-8"))
    require(actual == fixed and original_blob == expected_blob,
            "EXISTING_BRANCH_BYTES_DIFFER_FROM_APPROVED_REPAIR")
    comparison = api("GET", prefix + "compare/" + main_sha + "..." + branch_sha)
    files = comparison.get("files") if type(comparison) is dict else None
    require(type(files) is list and len(files) == 1
            and type(files[0]) is dict
            and files[0].get("filename") == DOC
            and files[0].get("status") == "modified"
            and comparison.get("merge_base_commit", {}).get("sha") == main_sha
            and comparison.get("ahead_by") == 1
            and comparison.get("behind_by") == 0,
            "EXISTING_BRANCH_HAS_UNAPPROVED_CHANGE_OR_ANCESTRY")
    return expected_blob


def checked_draft(api, *, prefix, number, branch, branch_sha, main_sha, base_sha=None):
    """A bot-owned original draft is not a delivery, merge or production change."""
    require(type(number) is int and 0 < number < 10**9,
            "ORIGINAL_DRAFT_NUMBER_INVALID")
    require(base_sha is None or (type(base_sha) is str and GIT_SHA.fullmatch(base_sha)),
            "DRAFT_BASE_SOURCE_INVALID")
    verified = None
    for retry in range(3):
        try:
            verified = api("GET", prefix + "pulls/" + str(number))
            break
        except urllib.error.HTTPError as exc:
            if exc.code != 404 or retry == 2:
                raise
            import time
            time.sleep(1)
    require(type(verified) is dict
            and verified.get("number") == number
            and verified.get("state") == "open"
            and verified.get("draft") is True
            and verified.get("merged") is False
            and verified.get("head", {}).get("sha") == branch_sha
            and verified.get("head", {}).get("ref") == branch
            and verified.get("head", {}).get("repo", {}).get("full_name") == TARGET
            and verified.get("base", {}).get("sha") == (main_sha if base_sha is None else base_sha)
            and verified.get("base", {}).get("ref") == "main"
            and verified.get("user", {}).get("login") == APP_SLUG + "[bot]",
            "ORIGINAL_BOT_DRAFT_NOT_VERIFIED")
    return True


def checked_original_superseded_draft(api, *, prefix):
    """Verify immutable original proposal identity without treating closure as delivery."""
    branch = BRANCH_PREFIX + EXPECTED_TARGET_HEAD[:12]
    original = api("GET", prefix + "pulls/" + str(ORIGINAL_DRAFT_PR))
    body = original.get("body") if type(original) is dict else None
    fingerprint = ("AUTO_REPAIR_FINGERPRINT: " + EXPECTED_TARGET_HEAD
                   + "/" + EXPECTED_RELEASE_BLOB)
    require(type(original) is dict
            and original.get("number") == ORIGINAL_DRAFT_PR
            and original.get("state") == "closed"
            and original.get("draft") is True
            and original.get("merged") is False
            and original.get("head", {}).get("sha") == ORIGINAL_DRAFT_HEAD
            and original.get("head", {}).get("ref") == branch
            and original.get("head", {}).get("repo", {}).get("full_name") == TARGET
            and original.get("base", {}).get("ref") == "main"
            and original.get("user", {}).get("login") == APP_SLUG + "[bot]"
            and type(body) is str and fingerprint in body.splitlines()
            and ("superseded" in body.casefold())
            and ("PR #70" in body)
            and SUCCESSOR_MERGE in body,
            "ORIGINAL_SUPERSEDED_DRAFT_NOT_VERIFIED")
    commit = immutable_git_get(api, prefix + "git/commits/" + ORIGINAL_DRAFT_HEAD)
    require(type(commit) is dict and commit.get("sha") == ORIGINAL_DRAFT_HEAD
            and type(commit.get("parents")) is list
            and len(commit["parents"]) == 1
            and commit["parents"][0].get("sha") == EXPECTED_TARGET_HEAD,
            "ORIGINAL_SUPERSEDED_COMMIT_NOT_EXACT_CHILD")
    observed = immutable_git_get(
        api, prefix + "contents/" + DOC + "?ref=" + ORIGINAL_DRAFT_HEAD)
    _, blob = checked_document(observed, "ORIGINAL_SUPERSEDED_REPAIR")
    require(blob == ORIGINAL_REPAIR_BLOB,
            "ORIGINAL_SUPERSEDED_REPAIR_BLOB_MISMATCH")
    comparison = api(
        "GET", prefix + "compare/" + EXPECTED_TARGET_HEAD + "..." + ORIGINAL_DRAFT_HEAD)
    files = comparison.get("files") if type(comparison) is dict else None
    require(type(files) is list and len(files) == 1
            and type(files[0]) is dict
            and files[0].get("filename") == DOC
            and files[0].get("status") == "modified"
            and comparison.get("merge_base_commit", {}).get("sha")
                == EXPECTED_TARGET_HEAD
            and comparison.get("ahead_by") == 1
            and comparison.get("behind_by") == 0,
            "ORIGINAL_SUPERSEDED_DRAFT_SCOPE_CHANGED")
    return branch


def require_current_correction(source, release):
    """Require current documents to retain the reviewed hosting correction."""
    require(type(source) is str and type(release) is str
            and len(source) <= 12000 and len(release) <= 60000,
            "CURRENT_CORRECTION_SOURCE_BOUNDS_INVALID")
    require("Use GitHub Pages, not Netlify." in source
            and "- Website branch: `gh-pages`" in source
            and "https://p00nsmasher.github.io/capturebrief/" in source
            and "- Product engine and its regression tests: `main`" in source,
            "CURRENT_CANONICAL_HOSTING_SEMANTICS_REGRESSED")
    require(release.startswith("# Verified public release artifact\n\n")
            and "authoritative website uses GitHub Pages" in release
            and "`gh-pages` branch" in release
            and "https://p00nsmasher.github.io/capturebrief/" in release
            and "legacy packaging tools" in release
            and "do not\nselect the current hosting provider or authorize a website deployment" in release
            and "## Current GitHub Pages release handoff" in release
            and "does not prove the intended content is live" in release
            and MISLEADING not in release
            and HANDOFF_START not in release,
            "CURRENT_RELEASE_CORRECTION_SEMANTICS_REGRESSED")


def resembles_successor_correction(source, release):
    """Select only the reviewed correction family; unrelated drift stays generic."""
    return (type(source) is str and type(release) is str
            and "Use GitHub Pages, not Netlify." in source
            and "authoritative website uses GitHub Pages" in release
            and "## Current GitHub Pages release handoff" in release)


def readback_superseded_draft_successor(api, *, prefix, current_main,
                                        source, release,
                                        canonical_blob, release_blob):
    """Read-only terminal proof for the original draft and merged successor."""
    require_current_correction(source, release)
    original_branch = checked_original_superseded_draft(api, prefix=prefix)
    successor = api("GET", prefix + "pulls/" + str(SUCCESSOR_PR))
    require(type(successor) is dict
            and successor.get("number") == SUCCESSOR_PR
            and successor.get("state") == "closed"
            and successor.get("draft") is False
            and successor.get("merged") is True
            and successor.get("head", {}).get("sha") == SUCCESSOR_HEAD
            and successor.get("head", {}).get("ref") == SUCCESSOR_BRANCH
            and successor.get("head", {}).get("repo", {}).get("full_name") == TARGET
            and successor.get("base", {}).get("sha") == SUCCESSOR_BASE
            and successor.get("base", {}).get("ref") == "main"
            and successor.get("merge_commit_sha") == SUCCESSOR_MERGE,
            "SUCCESSOR_MERGED_PR_NOT_VERIFIED")
    successor_diff = api(
        "GET", prefix + "compare/" + SUCCESSOR_BASE + "..." + SUCCESSOR_HEAD)
    files = successor_diff.get("files") if type(successor_diff) is dict else None
    require(type(files) is list
            and all(type(row) is dict for row in files)
            and {(row.get("filename"), row.get("status")) for row in files} == {
                (".github/workflows/product-core.yml", "modified"),
                (".github/workflows/public-release.yml", "modified"),
                (DOC, "modified"),
            }
            and successor_diff.get("merge_base_commit", {}).get("sha") == SUCCESSOR_BASE
            and successor_diff.get("ahead_by") == 1
            and successor_diff.get("behind_by") == 0,
            "SUCCESSOR_REVIEWED_SCOPE_CHANGED")
    merge = immutable_git_get(api, prefix + "git/commits/" + SUCCESSOR_MERGE)
    parents = merge.get("parents") if type(merge) is dict else None
    require(type(merge) is dict
            and merge.get("sha") == SUCCESSOR_MERGE
            and type(parents) is list
            and all(type(row) is dict for row in parents)
            and any(row.get("sha") == SUCCESSOR_HEAD for row in parents),
            "SUCCESSOR_MERGE_COMMIT_NOT_VERIFIED")
    ancestry = api(
        "GET", prefix + "compare/" + SUCCESSOR_MERGE + "..." + current_main)
    require(type(ancestry) is dict
            and ancestry.get("merge_base_commit", {}).get("sha") == SUCCESSOR_MERGE
            and ancestry.get("behind_by") == 0,
            "SUCCESSOR_MERGE_NOT_IN_CURRENT_MAIN")
    latest = api("GET", prefix + "branches/main")
    require(type(latest) is dict
            and latest.get("commit", {}).get("sha") == current_main,
            "TERMINAL_TARGET_MAIN_MOVED_DURING_READBACK")
    return {
        "status": "ORIGINAL_BOT_DRAFT_SUPERSEDED_BY_MERGED_SUCCESSOR",
        "repository": TARGET,
        "target_source": current_main,
        "original_source": EXPECTED_TARGET_HEAD,
        "original_draft_pr": ORIGINAL_DRAFT_PR,
        "original_draft_branch": original_branch,
        "original_draft_head": ORIGINAL_DRAFT_HEAD,
        "original_draft_merged": False,
        "successor_pr": SUCCESSOR_PR,
        "successor_head": SUCCESSOR_HEAD,
        "successor_merge_commit": SUCCESSOR_MERGE,
        "successor_merged": True,
        "current_canonical_blob": canonical_blob,
        "current_release_blob": release_blob,
        "correction_semantics_verified": True,
        "provider_writes": 0,
        "deployed": False,
        "live_verified": False,
    }



def readback_original_draft_after_source_drift(api, *, prefix, current_main):
    """Read-only proof that the original bot draft survived unrelated main drift.

    This never retargets a writer, rebases, retries or declares delivery. A
    changed source document or absent original draft preserves the ordinary
    no-mutation drift outcome. Malformed evidence fails closed.
    """
    require(type(current_main) is str and GIT_SHA.fullmatch(current_main)
            and current_main != EXPECTED_TARGET_HEAD,
            "DRIFT_SOURCE_INVALID")
    branch = BRANCH_PREFIX + EXPECTED_TARGET_HEAD[:12]
    source, canonical_blob = checked_document(
        api("GET", prefix + "contents/" + CANONICAL + "?ref=" + current_main),
        "DRIFT_CANONICAL")
    original, original_blob = checked_document(
        api("GET", prefix + "contents/" + DOC + "?ref=" + current_main),
        "DRIFT_RELEASE_DOC")
    if (canonical_blob != EXPECTED_CANONICAL_BLOB
            or original_blob != EXPECTED_RELEASE_BLOB):
        if resembles_successor_correction(source, original):
            return readback_superseded_draft_successor(
                api, prefix=prefix, current_main=current_main,
                source=source, release=original,
                canonical_blob=canonical_blob, release_blob=original_blob)
        return None
    corrected = plan(source, original)
    if corrected is None:
        return None
    census = api("GET", prefix + "pulls?state=open&per_page=100")
    require(type(census) is list and len(census) < 100
            and all(type(p) is dict for p in census),
            "DRIFT_OPEN_PR_CENSUS_INCOMPLETE")
    matches = [p for p in census
               if type(p.get("head")) is dict
               and p["head"].get("ref") == branch]
    if not matches:
        return None
    require(len(matches) == 1, "DRIFT_ORIGINAL_DRAFT_AMBIGUOUS")
    branch_row = api("GET", prefix + "branches/" + branch)
    require(type(branch_row) is dict and type(branch_row.get("commit")) is dict,
            "DRIFT_ORIGINAL_BRANCH_UNVERIFIED")
    candidate_sha = branch_row["commit"].get("sha")
    checked_candidate(api, prefix=prefix, main_sha=EXPECTED_TARGET_HEAD,
                      branch_sha=candidate_sha, fixed=corrected)
    number = matches[0].get("number")
    checked_draft(api, prefix=prefix, number=number, branch=branch,
                  branch_sha=candidate_sha, main_sha=EXPECTED_TARGET_HEAD,
                  base_sha=current_main)
    latest = api("GET", prefix + "branches/main")
    require(type(latest) is dict and latest.get("commit", {}).get("sha") == current_main,
            "DRIFT_TARGET_MAIN_MOVED_DURING_READBACK")
    return {"status": "ORIGINAL_BOT_DRAFT_STILL_PENDING_AFTER_TARGET_DRIFT",
            "repository": TARGET, "target_source": current_main,
            "original_source": EXPECTED_TARGET_HEAD, "draft_pr": number,
            "repair_commit": candidate_sha, "source_documents_unchanged": True,
            "provider_writes": 0, "merged": False, "deployed": False}


def execute(api, *, installation, slug):
    """One exact-source, resumable, doc-only draft proposal; never delivery."""
    check_scope(api("GET", "installation/repositories?per_page=100"),
                installation, slug)
    prefix = "repos/" + TARGET + "/"
    info = api("GET", "repos/" + TARGET)
    require(type(info) is dict and info.get("full_name") == TARGET
            and info.get("archived") is False and info.get("default_branch") == "main",
            "TARGET_REPOSITORY_IDENTITY_CHANGED")
    before = api("GET", prefix + "branches/main")
    main_sha = before.get("commit", {}).get("sha")
    require(type(main_sha) is str and GIT_SHA.fullmatch(main_sha) is not None,
            "TARGET_MAIN_NOT_VERIFIED")
    if main_sha != EXPECTED_TARGET_HEAD:
        pending = readback_original_draft_after_source_drift(
            api, prefix=prefix, current_main=main_sha)
        if pending is not None:
            return pending
        return {"status": "TARGET_SOURCE_CHANGED_NO_MUTATION",
                "repository": TARGET, "target_source": main_sha,
                "provider_writes": 0, "merged": False, "deployed": False}
    original_source, canonical_blob = checked_document(
        api("GET", prefix + "contents/" + CANONICAL + "?ref=" + main_sha),
        "CANONICAL")
    previous, old_blob = checked_document(
        api("GET", prefix + "contents/" + DOC + "?ref=" + main_sha),
        "RELEASE_DOC")
    require(canonical_blob == EXPECTED_CANONICAL_BLOB
            and old_blob == EXPECTED_RELEASE_BLOB,
            "REVIEWED_SOURCE_BLOBS_MOVED")
    fixed = plan(original_source, previous)
    if fixed is None:
        return {"status": "ALREADY_CORRECT", "repository": TARGET,
                "target_source": main_sha, "provider_writes": 0,
                "merged": False, "deployed": False}
    branch = BRANCH_PREFIX + main_sha[:12]
    expected_blob = digest_blob(fixed.encode("utf-8"))
    prs = api("GET", prefix + "pulls?state=open&per_page=100")
    require(type(prs) is list and len(prs) < 100
            and all(type(item) is dict for item in prs),
            "ORIGINAL_OPEN_PR_CENSUS_INCOMPLETE")
    matches = [p for p in prs
               if type(p.get("head")) is dict
               and type(p["head"].get("ref")) is str
               and p["head"]["ref"].startswith(BRANCH_PREFIX)]
    require(len(matches) <= 1
            and (not matches or matches[0].get("head", {}).get("ref") == branch),
            "UNRELATED_OR_MULTIPLE_BOT_REPAIR_PRS")
    try:
        existing = api("GET", prefix + "branches/" + branch)
    except urllib.error.HTTPError as exc:
        require(exc.code == 404, "TARGET_BRANCH_READ_FAILED")
        existing = None

    if existing is not None:
        require(type(existing) is dict
                and type(existing.get("commit")) is dict,
                "EXISTING_TARGET_BRANCH_UNTRUSTED")
        branch_sha = existing["commit"].get("sha")
        checked_candidate(api, prefix=prefix, main_sha=main_sha,
                          branch_sha=branch_sha, fixed=fixed)
        print("V8_SAFE_STAGE: EXISTING_EXACT_BRANCH_RECONCILED", flush=True)
        writes = 0
    else:
        require(not matches, "DRAFT_WITHOUT_EXPECTED_BRANCH_NOT_VERIFIED")
        live = api("GET", prefix + "branches/main")
        require(live.get("commit", {}).get("sha") == main_sha,
                "TARGET_MAIN_DRIFT_BEFORE_CREATE")
        created = api("POST", prefix + "git/refs", {
            "ref": "refs/heads/" + branch, "sha": main_sha})
        require(type(created) is dict
                and created.get("ref") == "refs/heads/" + branch
                and created.get("object", {}).get("sha") == main_sha,
                "ORIGINAL_BRANCH_WRITE_NOT_VERIFIED")
        print("V8_SAFE_STAGE: BRANCH_CREATED", flush=True)
        applied = api("PUT", prefix + "contents/" + DOC, {
            "message": "docs: flag obsolete Netlify release instructions",
            "content": base64.b64encode(fixed.encode("utf-8")).decode("ascii"),
            "sha": old_blob, "branch": branch})
        branch_sha = applied.get("commit", {}).get("sha") if type(applied) is dict else None
        require(type(branch_sha) is str and GIT_SHA.fullmatch(branch_sha)
                and applied.get("content", {}).get("sha") == expected_blob,
                "ORIGINAL_REPAIR_COMMIT_NOT_VERIFIED")
        print("V8_SAFE_STAGE: EXACT_DOCUMENT_WRITE_ACCEPTED", flush=True)
        checked_candidate(api, prefix=prefix, main_sha=main_sha,
                          branch_sha=branch_sha, fixed=fixed)
        writes = 2

    if matches:
        p = matches[0]
        number = p.get("number")
        checked_draft(api, prefix=prefix, number=number, branch=branch,
                      branch_sha=branch_sha, main_sha=main_sha)
        return {"status": "ORIGINAL_AUTHENTICATED_DRAFT_REPAIR_VERIFIED",
                "repository": TARGET, "target_source": main_sha,
                "canonical_blob": canonical_blob, "previous_blob": old_blob,
                "changed_blob": expected_blob, "repair_commit": branch_sha,
                "draft_pr": number, "provider_writes": 0,
                "resumed_from_verified_existing_branch": True,
                "merged": False, "deployed": False}
    fresh = api("GET", prefix + "branches/main")
    require(fresh.get("commit", {}).get("sha") == main_sha,
            "TARGET_MAIN_DRIFT_BEFORE_DRAFT")
    print("V8_SAFE_STAGE: SUBMITTING_ONE_DRAFT_PR", flush=True)
    try:
        opened = api("POST", prefix + "pulls", {
            "title": "docs: correct outdated CaptureBrief deployment instructions",
            "head": branch, "base": "main", "draft": True,
            "maintainer_can_modify": False,
            "body": (
                "Original source defect: PUBLIC-RELEASE.md incorrectly names "
                "Netlify as current hosting. DEPLOYMENT-TARGET.md identifies "
                "GitHub Pages/gh-pages. This deterministic bounded proposal "
                "changes ONLY PUBLIC-RELEASE.md and preserves historical build "
                "instructions as explicitly historical. Independent "
                "project-specific QA and protected review are REQUIRED. "
                "AUTO_REPAIR_FINGERPRINT: " + main_sha + "/" + old_blob
                + "\nNo automated merge, deployment, customer contact, or paid API."
            )})
    except urllib.error.HTTPError as exc:
        # Numeric status only; never print provider JSON, token or headers.
        print("V8_SAFE_DRAFT_PROVIDER_STATUS: " + str(exc.code),flush=True)
        raise
    number = opened.get("number") if type(opened) is dict else None
    checked_draft(api, prefix=prefix, number=number, branch=branch,
                  branch_sha=branch_sha, main_sha=main_sha)
    return {"status": "ORIGINAL_AUTHENTICATED_DRAFT_REPAIR_VERIFIED",
            "repository": TARGET, "target_source": main_sha,
            "canonical_blob": canonical_blob, "previous_blob": old_blob,
            "changed_blob": expected_blob, "repair_commit": branch_sha,
            "draft_pr": number, "provider_writes": writes + 1,
            "resumed_from_verified_existing_branch": existing is not None,
            "merged": False, "deployed": False}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("UNTRUSTED_HTTP_REDIRECT")


class GitHubAPI:
    def __init__(self, token):
        require(type(token) is str and len(token) >= 20,
                "MISSING_RUNTIME_TOKEN")
        self.token = token
        self.count = 0
        self.opener = urllib.request.build_opener(NoRedirect())

    def __call__(self, method, path, body=None):
        self.count += 1
        require(self.count <= MAX_REQUESTS, "PROVIDER_BUDGET_EXCEEDED")
        prefix = "repos/" + TARGET + "/"
        item = path[len(prefix):] if path.startswith(prefix) else None
        if method == "GET":
            allowed = (path in {"installation/repositories?per_page=100",
                               "repos/" + TARGET}
                       or item in {"branches/main", "pulls?state=open&per_page=100"}
                       or (type(item) is str and (
                           re.fullmatch(r"branches/v8-capturebrief-hosting-doc-[0-9a-f]{12}", item) is not None
                           or re.fullmatch(r"pulls/[1-9][0-9]{0,8}", item) is not None
                           or re.fullmatch(r"contents/(?:PUBLIC-RELEASE|DEPLOYMENT-TARGET)\.md\?ref=[0-9a-f]{40}", item) is not None
                           or re.fullmatch(r"compare/[0-9a-f]{40}\.\.\.[0-9a-f]{40}", item) is not None
                           or re.fullmatch(r"git/commits/[0-9a-f]{40}", item) is not None
                       )))
        else:
            allowed = path.startswith(prefix)
        # SHA...SHA is GitHub's exact immutable comparison syntax, not a
        # traversal. The GET-only full-path allowlist must match before this
        # narrow exception; no other dot-containing route is admitted.
        exact_sha_compare = (
            method == "GET"
            and type(item) is str
            and re.fullmatch(
                r"compare/[0-9a-f]{40}\.\.\.[0-9a-f]{40}", item
            ) is not None
        )
        require(
            method in {"GET", "POST", "PUT"}
            and allowed
            and (exact_sha_compare or ".." not in path)
            and all(x not in path for x in ("%", "\n", "\r", "#")),
            "PROVIDER_ENDPOINT_OUT_OF_SCOPE",
        )
        require((method == "GET") == (body is None), "PROVIDER_REQUEST_METHOD_BODY_INVALID")
        if method == "POST":
            require(path in {prefix + "git/refs", prefix + "pulls"},
                    "POST_NOT_APPROVED")
        if method == "PUT":
            require(path == prefix + "contents/" + DOC,
                    "PUT_NOT_APPROVED")
        raw = None if body is None else json.dumps(body, allow_nan=False).encode()
        require(raw is None or len(raw) <= 90000,
                "REQUEST_TOO_LARGE")
        req = urllib.request.Request(
            "https://api.github.com/" + path, data=raw, method=method,
            headers={"Authorization": "Bearer " + self.token,
                     "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28",
                     **({"Content-Type": "application/json"} if raw else {})})
        with self.opener.open(req, timeout=20) as response:
            data = response.read(MAX_RESPONSE + 1)
        require(len(data) <= MAX_RESPONSE, "PROVIDER_RESPONSE_TOO_LARGE")
        return json.loads(data)


def main():
    api = GitHubAPI(os.environ.get("GH_TOKEN", ""))
    result = execute(api, installation=os.environ.get("INSTALLATION_ID", ""),
                     slug=os.environ.get("APP_SLUG", ""))
    result["schema_version"] = 1
    result["runtime_source"] = os.environ.get("GITHUB_SHA")
    require(type(result["runtime_source"]) is str
            and GIT_SHA.fullmatch(result["runtime_source"]) is not None,
            "RUNNER_SOURCE_UNVERIFIED")
    result["reliability_accepted"] = False
    result["general_code_repair_authority"] = False
    output = os.environ.get("RUNNER_TEMP", "") + "/v8-capturebrief-repair.json"
    with open(output, "x", encoding="utf-8") as f:
        json.dump(result, f, sort_keys=True, indent=2)
        f.write("\n")
    print("V8_SCOPED_REPAIR:", result["status"], "writes:", result["provider_writes"])


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # No token, provider response, untrusted data or traceback in CI logs.
        raise SystemExit("V8_SCOPED_REPAIR_BLOCKED; NO_RELEASE_AUTHORITY") from None

