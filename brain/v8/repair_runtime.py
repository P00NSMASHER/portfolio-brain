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


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def digest_blob(raw):
    require(type(raw) is bytes, "GIT_BLOB_INVALID")
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()


def plan(source, original):
    """The only allowed content mutation, requiring authoritative exact text."""
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
        return None
    require(original.count(MISLEADING) == 1 and CORRECTION not in original,
            "RELEASE_DOCUMENT_DEFECT_NOT_IDENTICAL")
    corrected = original.replace(MISLEADING, CORRECTION, 1)
    require(corrected != original and MISLEADING not in corrected
            and corrected.count(CORRECTION) == 1
            and corrected.endswith(original.split(MISLEADING, 1)[1]),
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


def execute(api, *, installation, slug):
    """Execute one bounded docs-only draft proposal; never production delivery."""
    check_scope(api("GET", "installation/repositories?per_page=100"), installation, slug)
    prefix = "repos/" + TARGET + "/"
    info = api("GET", "repos/" + TARGET)
    require(type(info) is dict and info.get("full_name") == TARGET
            and info.get("archived") is False and info.get("default_branch") == "main",
            "TARGET_REPOSITORY_IDENTITY_CHANGED")
    before = api("GET", prefix + "branches/main")
    main_sha = before.get("commit", {}).get("sha")
    require(type(main_sha) is str and GIT_SHA.fullmatch(main_sha) is not None,
            "TARGET_MAIN_NOT_VERIFIED")

    # Both original Git blobs are SHA-checked; provider text is data, never code.
    original_source, canonical_blob = checked_document(
        api("GET", prefix + "contents/" + CANONICAL + "?ref=" + main_sha),
        "CANONICAL")
    previous, old_blob = checked_document(
        api("GET", prefix + "contents/" + DOC + "?ref=" + main_sha),
        "RELEASE_DOC")
    fixed = plan(original_source, previous)
    if fixed is None:
        return {"status": "ALREADY_CORRECT", "repository": TARGET,
                "target_source": main_sha, "provider_writes": 0,
                "merged": False, "deployed": False}
    branch = BRANCH_PREFIX + main_sha[:12]
    existing = api("GET", prefix + "pulls?state=open&per_page=100")
    require(type(existing) is list and len(existing) < 100
            and all(type(row) is dict for row in existing),
            "PR_CENSUS_INCOMPLETE")
    if any(type(row.get("head")) is dict
           and type(row["head"].get("ref")) is str
           and row["head"]["ref"].startswith(BRANCH_PREFIX)
           for row in existing):
        return {"status": "EXISTING_DRAFT_REQUIRES_RECONCILIATION",
                "repository": TARGET, "target_source": main_sha,
                "provider_writes": 0, "merged": False, "deployed": False}
    # No duplicate attempts after uncertain publication: a branch cannot be
    # repurposed or overwritten by this bounded recipe.
    try:
        existing_branch = api("GET", prefix + "branches/" + branch)
    except urllib.error.HTTPError as exc:
        require(exc.code == 404, "TARGET_BRANCH_READ_FAILED")
    else:
        require(type(existing_branch) is dict,
                "TARGET_BRANCH_STATE_INVALID")
        return {"status": "EXISTING_BRANCH_REQUIRES_RECONCILIATION",
                "repository": TARGET, "target_source": main_sha,
                "provider_writes": 0, "merged": False, "deployed": False}

    current = api("GET", prefix + "branches/main")
    require(current.get("commit", {}).get("sha") == main_sha,
            "SOURCE_ADVANCED_BEFORE_FIRST_WRITE")
    expected_raw = fixed.encode("utf-8")
    expected_blob = digest_blob(expected_raw)
    created = api("POST", prefix + "git/refs", {
        "ref": "refs/heads/" + branch, "sha": main_sha})
    require(type(created) is dict and created.get("ref") == "refs/heads/" + branch
            and created.get("object", {}).get("sha") == main_sha,
            "BRANCH_CREATION_NOT_VERIFIED")
    applied = api("PUT", prefix + "contents/" + DOC, {
        "message": "docs: flag obsolete Netlify release instructions",
        "content": base64.b64encode(expected_raw).decode("ascii"),
        "sha": old_blob, "branch": branch})
    commit_sha = applied.get("commit", {}).get("sha")
    require(type(commit_sha) is str and GIT_SHA.fullmatch(commit_sha) is not None
            and applied.get("content", {}).get("sha") == expected_blob,
            "REPAIR_COMMIT_NOT_VERIFIED")
    observed, observed_blob = checked_document(
        api("GET", prefix + "contents/" + DOC + "?ref=" + commit_sha),
        "REPAIRED")
    require(observed == fixed and observed_blob == expected_blob,
            "REPAIR_BYTE_READBACK_MISMATCH")
    comparison = api("GET", prefix + "compare/" + main_sha + "..." + commit_sha)
    files = comparison.get("files")
    require(type(files) is list and len(files) == 1
            and files[0].get("filename") == DOC
            and files[0].get("status") == "modified"
            and comparison.get("merge_base_commit", {}).get("sha") == main_sha,
            "PATCH_EXCEEDED_APPROVED_ONE_FILE")
    fresh = api("GET", prefix + "branches/main")
    require(fresh.get("commit", {}).get("sha") == main_sha,
            "TARGET_MAIN_DRIFT_DURING_REPAIR")
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
    number = opened.get("number")
    require(type(number) is int and number > 0,
            "PR_CREATION_NOT_VERIFIED")
    verified = api("GET", prefix + "pulls/" + str(number))
    require(verified.get("number") == number
            and verified.get("state") == "open"
            and verified.get("draft") is True
            and verified.get("merged") is False
            and verified.get("head", {}).get("sha") == commit_sha
            and verified.get("head", {}).get("ref") == branch
            and verified.get("head", {}).get("repo", {}).get("full_name") == TARGET
            and verified.get("base", {}).get("sha") == main_sha
            and verified.get("base", {}).get("ref") == "main"
            and verified.get("user", {}).get("login") == APP_SLUG + "[bot]",
            "DRAFT_PR_OR_AUTHOR_READBACK_INVALID")
    return {"status": "ORIGINAL_AUTHENTICATED_DRAFT_REPAIR_VERIFIED",
            "repository": TARGET, "target_source": main_sha,
            "canonical_blob": canonical_blob, "previous_blob": old_blob,
            "changed_blob": expected_blob, "repair_commit": commit_sha,
            "draft_pr": number, "provider_writes": 3,
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
        allowed = (path == "installation/repositories?per_page=100"
                   or path == "repos/" + TARGET
                   or path.startswith(prefix))
        require(method in {"GET", "POST", "PUT"} and allowed
                and all(x not in path for x in ("..", "%", "\n", "\r", "#")),
                "PROVIDER_ENDPOINT_OUT_OF_SCOPE")
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
