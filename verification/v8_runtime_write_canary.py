"""One-shot, scoped GitHub App write proof. Only ephemeral draft PR and branch changes."""
import base64
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

TARGET = "P00NSMASHER/capturebrief"
DENIED = "P00NSMASHER/portfolio-brain"
APP_ID = "172257326"
APP_SLUG = "portfolio-brain-v8-runtime"
MAX_RESPONSE = 1024 * 1024
SHA = re.compile(r"[0-9a-f]{40}\Z")
RUN_ID = re.compile(r"[0-9]{6,20}\Z")


class FailClosed(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise FailClosed("UNEXPECTED_REDIRECT")


class GitHub:
    def __init__(self, token):
        if not token or len(token) < 20:
            raise FailClosed("TOKEN_MISSING")
        self.opener = urllib.request.build_opener(NoRedirect())
        self.token = token

    def request(self, method, path, body=None, errors=()):
        if not (path == "/installation/repositories?per_page=100" or
                path.startswith("/repos/" + TARGET + "/") or
                path.startswith("/repos/" + DENIED + "/")):
            raise FailClosed("UNREVIEWED_ENDPOINT")
        if method not in ("GET", "POST", "PUT", "PATCH", "DELETE"):
            raise FailClosed("UNREVIEWED_METHOD")
        raw = None if body is None else json.dumps(body, sort_keys=True).encode()
        request = urllib.request.Request(
            "https://api.github.com" + path, data=raw,
            headers={"Authorization": "Bearer " + self.token,
                     "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28",
                     **({"Content-Type": "application/json"} if raw else {})},
            method=method,
        )
        try:
            with self.opener.open(request, timeout=20) as result:
                status = result.status
                data = result.read(MAX_RESPONSE + 1)
        except urllib.error.HTTPError as exc:
            if exc.code in errors:
                return exc.code, {}
            raise FailClosed("PROVIDER_" + method + "_" + str(exc.code)) from None
        if len(data) > MAX_RESPONSE:
            raise FailClosed("RESPONSE_TOO_LARGE")
        if status not in (200, 201, 204):
            raise FailClosed("UNEXPECTED_STATUS")
        try:
            parsed = json.loads(data) if data else {}
        except ValueError:
            raise FailClosed("MALFORMED_RESPONSE") from None
        if not isinstance(parsed, (dict, list)):
            raise FailClosed("RESPONSE_SHAPE")
        return status, parsed


def check_preconditions(client, installed_id, app_slug, run_id, source_sha):
    if installed_id != APP_ID or app_slug != APP_SLUG:
        raise FailClosed("RUNTIME_APP_IDENTITY_MISMATCH")
    if RUN_ID.fullmatch(run_id) is None or SHA.fullmatch(source_sha) is None:
        raise FailClosed("RUN_OR_SOURCE_INVALID")
    _, inventory = client.request("GET", "/installation/repositories?per_page=100")
    repos = inventory.get("repositories")
    if (inventory.get("total_count") != 1 or type(repos) is not list
            or len(repos) != 1 or not isinstance(repos[0], dict)
            or repos[0].get("full_name") != TARGET):
        raise FailClosed("TOKEN_REPOSITORY_BOUNDARY_FAILED")
    _, repo = client.request("GET", "/repos/" + TARGET + "/branches/main")
    main_sha = repo.get("commit", {}).get("sha")
    if not isinstance(main_sha, str) or SHA.fullmatch(main_sha) is None:
        raise FailClosed("TARGET_MAIN_SOURCE_INVALID")
    return main_sha


def test_external_denial(client, run_id, source_sha):
    # This harmless branch operation must be rejected: only TARGET is in token inventory.
    name = "v8-runtime-denied-" + run_id
    path = "/repos/" + DENIED + "/git/refs"
    status, _ = client.request("POST", path, {
        "ref": "refs/heads/" + name, "sha": source_sha}, errors=(403, 404))
    if status in (403, 404):
        return status
    # A successful unapproved write is a critical failure. Remove its branch.
    ref = "/repos/" + DENIED + "/git/refs/heads/" + name
    client.request("DELETE", ref)
    raise FailClosed("CROSS_REPOSITORY_WRITE_UNEXPECTEDLY_SUCCEEDED")


def run(client, installed_id, app_slug, run_id, source_sha):
    before = check_preconditions(client, installed_id, app_slug, run_id, source_sha)
    denied_status = test_external_denial(client, run_id, source_sha)

    branch = "v8-runtime-canary-" + run_id
    path = ".v8-runtime-write-proof/" + run_id + ".txt"
    ref = "/repos/" + TARGET + "/git/ref/heads/" + branch
    delete_ref = "/repos/" + TARGET + "/git/refs/heads/" + branch
    _, old = client.request("GET", ref, errors=(404,))
    if old:
        raise FailClosed("CANARY_BRANCH_EXISTS")

    content = ("V8 RUNTIME WRITE CANARY\n"
               "Temporary non-executable verification content.\n"
               "No customer data, payment, configuration, or production change.\n"
               "Run: " + run_id + "\n")
    number = None
    branch_attempted = False
    draft_verified = False
    commit_sha = None
    cleanup_errors = []
    try:
        branch_attempted = True
        status, created = client.request("POST", "/repos/" + TARGET + "/git/refs", {
            "ref": "refs/heads/" + branch, "sha": before})
        if status != 201 or created.get("ref") != "refs/heads/" + branch:
            raise FailClosed("BRANCH_CREATION_UNVERIFIED")

        status, saved = client.request("PUT", "/repos/" + TARGET + "/contents/" + path, {
            "message": "test(v8): isolated, reversible runtime credential verification",
            "content": base64.b64encode(content.encode()).decode(),
            "branch": branch,
        })
        commit_sha = saved.get("commit", {}).get("sha")
        if status != 201 or not isinstance(commit_sha, str) or not SHA.fullmatch(commit_sha):
            raise FailClosed("WRITE_COMMIT_UNVERIFIED")
        _, original = client.request("GET",
                                     "/repos/" + TARGET + "/contents/" + path +
                                     "?ref=" + urllib.parse.quote(branch, safe=""))
        try:
            readback = base64.b64decode(original.get("content", ""), validate=False).decode()
        except (ValueError, UnicodeDecodeError):
            raise FailClosed("WRITE_READBACK_INVALID") from None
        if readback != content or original.get("path") != path:
            raise FailClosed("WRITE_READBACK_MISMATCH")

        status, opened = client.request("POST", "/repos/" + TARGET + "/pulls", {
            "title": "[verification] ephemeral V8 runtime write canary",
            "body": ("Automated, non-deploying credential validation only. "
                     "This draft will be closed immediately. Run " + run_id),
            "head": branch, "base": "main", "draft": True,
            "maintainer_can_modify": False,
        })
        number = opened.get("number")
        if (status != 201 or type(number) is not int or number <= 0
                or opened.get("draft") is not True
                or opened.get("head", {}).get("ref") != branch
                or opened.get("base", {}).get("ref") != "main"):
            raise FailClosed("DRAFT_PR_CREATION_UNVERIFIED")
        _, check = client.request("GET", "/repos/" + TARGET + "/pulls/" + str(number))
        if (check.get("draft") is not True or check.get("state") != "open"
                or check.get("head", {}).get("sha") != commit_sha
                or check.get("head", {}).get("ref") != branch
                or check.get("merged_at") is not None):
            raise FailClosed("DRAFT_PR_READBACK_FAILED")
        draft_verified = True
    finally:
        # Reconcile uncertain PR creation from original provider before cleanup.
        if branch_attempted:
            try:
                _, listing = client.request("GET", "/repos/" + TARGET
                                            + "/pulls?state=all&head=P00NSMASHER%3A"
                                            + urllib.parse.quote(branch, safe="") + "&per_page=100")
                if type(listing) is not list:
                    raise FailClosed("PR_CENSUS_INVALID")
                owned = [p for p in listing
                         if p.get("head", {}).get("ref") == branch
                         and p.get("title") == "[verification] ephemeral V8 runtime write canary"]
                if len(owned) > 1:
                    raise FailClosed("MULTIPLE_CANARY_PRS")
                for p in owned:
                    number = p["number"]
                    if p.get("state") == "open":
                        client.request("PATCH", "/repos/" + TARGET + "/pulls/" + str(number),
                                       {"state": "closed"})
                    _, checked = client.request("GET", "/repos/" + TARGET + "/pulls/" + str(number))
                    if checked.get("state") != "closed" or checked.get("merged_at") is not None:
                        raise FailClosed("CANARY_PR_NOT_CLOSED")
            except Exception as error:
                cleanup_errors.append("PR_CLEANUP_" + type(error).__name__)
            try:
                status, found = client.request("GET", ref, errors=(404,))
                if status == 200:
                    client.request("DELETE", delete_ref)
                gone, _ = client.request("GET", ref, errors=(404,))
                if gone != 404:
                    raise FailClosed("CANARY_BRANCH_NOT_DELETED")
            except Exception as error:
                cleanup_errors.append("REF_CLEANUP_" + type(error).__name__)

    if cleanup_errors:
        raise FailClosed(";".join(cleanup_errors))
    if not draft_verified or number is None or not commit_sha:
        raise FailClosed("POSITIVE_WRITE_INCOMPLETE")

    _, current = client.request("GET", "/repos/" + TARGET + "/branches/main")
    if current.get("commit", {}).get("sha") != before:
        raise FailClosed("TARGET_MAIN_DRIFT_AFTER_TEST")

    return {
        "schema_version": 1,
        "proof": "ORIGINAL_PROVIDER_WRITE_AND_CLEANUP",
        "runtime_app": APP_SLUG,
        "installation": APP_ID,
        "repository": TARGET,
        "target_main_source": before,
        "write_commit": commit_sha,
        "draft_pr_number": number,
        "draft_verified_then_closed": True,
        "temporary_branch_deleted": True,
        "cross_repo_write_denied_http": denied_status,
        "scoped_token_repository_count": 1,
        "production_deployed": False,
        "merge_authority_tested": False,
        "continuous_autonomous_repairs_verified": False,
        "acceptance_started": False,
    }


def main():
    env = os.environ
    client = GitHub(env.get("GH_TOKEN", ""))
    result = run(client, env.get("INSTALLATION_ID", ""),
                 env.get("APP_SLUG", ""), env.get("GITHUB_RUN_ID", ""),
                 env.get("CANDIDATE_SOURCE_SHA", ""))
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Do not leak tokens, provider payloads, or response text.
        kind = str(exc) if isinstance(exc, FailClosed) else type(exc).__name__
        print("V8_RUNTIME_WRITE_CANARY_FAILED: " + kind[:100], file=sys.stderr)
        raise SystemExit(1) from None
