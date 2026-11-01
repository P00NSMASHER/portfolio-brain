"""Bounded real-source patch and draft-PR factory for Portfolio Brain.

Only exact-current-main, original failed-core evidence permits a candidate.
A candidate is NOT a merged, deployed, accepted, or independently tested repair.
Code execution is confined to a non-networked, nonprivileged Docker container.
The only possible provider writes are a branch, exact-file commits, and a DRAFT PR.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request

REPOSITORY = "P00NSMASHER/portfolio-brain"
VALID_SHA = re.compile(r"[0-9a-f]{40}\Z")
VALID_HASH = re.compile(r"[0-9a-f]{64}\Z")
VALID_PATH = re.compile(r"(?:brain|tests|docs)/[a-zA-Z0-9_./-]+\.(?:py|json|md)\Z")
MAX_CHANGES = 4
MAX_FILE_BYTES = 256 * 1024
MAX_HTTP_BYTES = 2 * 1024 * 1024
TEST_IMAGE = "python:3.12-bookworm"

class FactoryError(ValueError):
    pass

def require(condition, code):
    if not condition:
        raise FactoryError(code)

def sha256(raw):
    return hashlib.sha256(raw).hexdigest()

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)

def safe_path(path):
    if type(path) is not str or VALID_PATH.fullmatch(path) is None:
        return False
    parts = path.split("/")
    return (all(part not in ("", ".", "..", ".git", "__pycache__") for part in parts)
            and not any(part.lower() in ("secrets", "private", "credentials", "tokens")
                        for part in parts))

def validate_request(spec):
    require(type(spec) is dict and set(spec) == {
        "schema_version", "repository", "base_sha", "failure_run_id", "changes",
    }, "FACTORY_REQUEST_FIELDS")
    require(type(spec["schema_version"]) is int and spec["schema_version"] == 1
            and spec["repository"] == REPOSITORY
            and type(spec["base_sha"]) is str and VALID_SHA.fullmatch(spec["base_sha"])
            and type(spec["failure_run_id"]) is int
            and 0 < spec["failure_run_id"] < 10**12,
            "FACTORY_IDENTITY_INVALID")
    changes = spec["changes"]
    require(type(changes) is list and 1 <= len(changes) <= MAX_CHANGES,
            "FACTORY_CHANGE_BOUND")
    seen = set()
    for change in changes:
        require(type(change) is dict and set(change) == {
            "path", "expected_sha256", "old", "new"
        }, "FACTORY_CHANGE_FIELDS")
        path = change["path"]
        require(safe_path(path) and path not in seen, "FACTORY_PATH_REFUSED")
        seen.add(path)
        require(type(change["expected_sha256"]) is str
                and VALID_HASH.fullmatch(change["expected_sha256"])
                and type(change["old"]) is str and type(change["new"]) is str
                and 12 <= len(change["old"]) <= 8192
                and 1 <= len(change["new"]) <= 16384
                and change["old"] != change["new"]
                and "\x00" not in change["new"]
                and "\x00" not in change["old"],
                "FACTORY_PATCH_INVALID")
    return spec

def prepare(spec, source_bytes):
    """Produce actual changed bytes, not a claimed completed repair."""
    validate_request(spec)
    require(type(source_bytes) is dict and set(source_bytes) ==
            {change["path"] for change in spec["changes"]},
            "FACTORY_SOURCES_INCOMPLETE")
    prepared = []
    for change in spec["changes"]:
        path = change["path"]
        raw = source_bytes[path]
        require(type(raw) is bytes and 1 <= len(raw) <= MAX_FILE_BYTES
                and sha256(raw) == change["expected_sha256"],
                "FACTORY_SOURCE_HASH_MISMATCH")
        try:
            original = raw.decode("utf-8")
        except UnicodeError as exc:
            raise FactoryError("FACTORY_SOURCE_ENCODING") from exc
        require(original.count(change["old"]) == 1, "FACTORY_ANCHOR_NOT_UNIQUE")
        updated = original.replace(change["old"], change["new"], 1).encode("utf-8")
        require(len(updated) <= MAX_FILE_BYTES and updated != raw,
                "FACTORY_OUTPUT_BOUND")
        prepared.append(dict(path=path, before_sha256=sha256(raw),
                             after_sha256=sha256(updated), updated_bytes=updated))
    identity = dict(repository=spec["repository"], base_sha=spec["base_sha"],
                    failure_run_id=spec["failure_run_id"],
                    changes=[{k:v for k,v in row.items() if k!="updated_bytes"}
                             for row in prepared])
    operation_id = sha256(canonical(identity).encode())
    return dict(status="SOURCE_PINNED_PATCH_PREPARED_NOT_TESTED",
                repository=REPOSITORY, base_sha=spec["base_sha"],
                failure_run_id=spec["failure_run_id"], operation_id=operation_id,
                branch="auto-repair/v10-" + operation_id[:16],
                changes=prepared, production_accepted=False)

def _strict_json(data):
    def no_duplicates(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "FACTORY_PROVIDER_DUPLICATE_KEY")
            result[key] = value
        return result
    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=no_duplicates,
                          parse_constant=lambda _: (_ for _ in ()).throw(
                              FactoryError("FACTORY_PROVIDER_NONFINITE")))
    except (UnicodeError, ValueError) as exc:
        raise FactoryError("FACTORY_PROVIDER_INVALID_JSON") from exc

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

class GitHubTransport:
    """One-repository GitHub App token; no arbitrary URLs, redirects, or logs."""
    def __init__(self, token):
        require(type(token) is str and 20 <= len(token) <= 4096,
                "FACTORY_APP_TOKEN_MISSING")
        self._token = token
        self._opener = urllib.request.build_opener(_NoRedirect())

    def request(self, method, suffix, payload=None):
        require(method in ("GET", "POST", "PUT"), "FACTORY_METHOD_REFUSED")
        route = (
            re.fullmatch(
                         r"(installation/repositories\?per_page=100|branches/main|"
                         r"branches/auto-repair/v10-[0-9a-f]{16}|"
                         r"pulls/[1-9]\d*|"
                         r"pulls\?head=P00NSMASHER%3Aauto-repair%2Fv10-[0-9a-f]{16}&state=open&per_page=100|"
                         r"actions/runs/[1-9]\d*|"
                         r"actions/runs/[1-9]\d*/jobs\?per_page=100|"
                         r"contents/(?:brain|tests|docs)/[a-zA-Z0-9_./-]+\."
                         r"(?:py|json|md)\?ref=[0-9a-f]{40})", suffix)
            if method == "GET" else
            (suffix == "git/refs" or suffix == "pulls") if method == "POST" else
            re.fullmatch(r"contents/(?:brain|tests|docs)/[a-zA-Z0-9_./-]+\."
                         r"(?:py|json|md)",suffix))
        require(bool(route), "FACTORY_ROUTE_REFUSED")
        if method in ("GET", "PUT") and suffix.startswith("contents/"):
            rawpath = suffix[len("contents/"):].split("?ref=", 1)[0]
            require(safe_path(rawpath), "FACTORY_ROUTE_REFUSED")
        if method == "GET":
            require(payload is None, "FACTORY_GET_BODY_REFUSED")
        else:
            require(type(payload) is dict, "FACTORY_WRITE_BODY_INVALID")
        body = None if payload is None else canonical(payload).encode()
        require(body is None or len(body) <= MAX_HTTP_BYTES,
                "FACTORY_WRITE_TOO_LARGE")
        url = ("https://api.github.com/" + suffix
               if suffix.startswith("installation/")
               else "https://api.github.com/repos/" + REPOSITORY + "/" + suffix)
        req = urllib.request.Request(
            url,
            method=method, data=body, headers={
                "Authorization": "Bearer " + self._token,
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
                "User-Agent": "Portfolio-Brain-v10-draft-factory",
            })
        try:
            with self._opener.open(req, timeout=15) as response:
                require(response.status in ((200,) if method == "GET"
                        else (200, 201)), "FACTORY_PROVIDER_STATUS_INVALID")
                raw = response.read(MAX_HTTP_BYTES + 1)
        except (urllib.error.URLError, OSError) as exc:
            # For POST/PUT this may have occurred after a remote write.
            raise FactoryError("FACTORY_PROVIDER_UNCERTAIN_RECONCILE") from exc
        require(len(raw) <= MAX_HTTP_BYTES, "FACTORY_PROVIDER_RESPONSE_BOUND")
        result = _strict_json(raw)
        if method == "GET" and suffix.startswith("pulls?head="):
            require(type(result) is list and len(result) < 100
                    and all(type(row) is dict for row in result),
                    "FACTORY_PR_LIST_TRUNCATED_OR_INVALID")
        else:
            require(type(result) is dict, "FACTORY_PROVIDER_INVALID_OBJECT")
        return result

def verify_original_failed_core(api, spec):
    """Original GitHub provider run and job steps; no user-supplied PASS flags."""
    validate_request(spec)
    repo = api.request("GET", "branches/main")
    require(repo.get("commit", {}).get("sha") == spec["base_sha"],
            "FACTORY_MAIN_MOVED")
    run_id = spec["failure_run_id"]
    run = api.request("GET", "actions/runs/" + str(run_id))
    require(run.get("id") == run_id and run.get("name") == "brain-cycle-v2"
            and run.get("path") == ".github/workflows/brain-cycle.yml"
            and run.get("repository", {}).get("full_name") == REPOSITORY
            and run.get("head_branch") == "main"
            and run.get("head_sha") == spec["base_sha"]
            and run.get("run_attempt") == 1
            and run.get("event") in ("schedule", "workflow_dispatch")
            and run.get("status") == "completed"
            and run.get("conclusion") in ("failure", "timed_out"),
            "FACTORY_NO_ORIGINAL_FAILED_CORE")
    jobs = api.request("GET", "actions/runs/" + str(run_id) +
                       "/jobs?per_page=100")
    rows = jobs.get("jobs")
    require(type(rows) is list and type(jobs.get("total_count")) is int
            and jobs["total_count"] == len(rows) and len(rows) <= 100,
            "FACTORY_JOB_CENSUS_INCOMPLETE")
    bad = []
    for job in rows:
        if (type(job) is dict and job.get("name") == "monitor"
                and job.get("run_id") == run_id and job.get("run_attempt") == 1
                and job.get("head_sha") == spec["base_sha"]
                and job.get("status") == "completed"
                and job.get("conclusion") in ("failure", "timed_out")):
            steps = job.get("steps")
            if type(steps) is list:
                bad.extend(step.get("name") for step in steps
                           if type(step) is dict and
                           step.get("conclusion") in ("failure", "timed_out")
                           and type(step.get("name")) is str)
    require(bool(bad), "FACTORY_FAILED_STEP_NOT_VERIFIED")
    return dict(status="ORIGINAL_FAILED_CORE_REPRODUCED_NOT_DIAGNOSED",
                source_sha=spec["base_sha"], run_id=run_id,
                failed_step_names=sorted(set(bad)), production_accepted=False)

def verify_original_sources(api, spec):
    """Every source is re-read at the exact original main before any write."""
    sources = {}
    for row in spec["changes"]:
        path = row["path"]
        data = api.request("GET", "contents/" + path +
                           "?ref=" + spec["base_sha"])
        require(data.get("type") == "file" and
                data.get("encoding") == "base64" and
                type(data.get("sha")) is str and VALID_SHA.fullmatch(data["sha"])
                and type(data.get("content")) is str,
                "FACTORY_PROVIDER_SOURCE_INVALID")
        try:
            raw = base64.b64decode(data["content"].replace("\n", ""),
                                   validate=True)
        except (ValueError, base64.binascii.Error) as exc:
            raise FactoryError("FACTORY_PROVIDER_SOURCE_INVALID") from exc
        require(type(data.get("size")) is int and len(raw) == data["size"]
                and len(raw) <= MAX_FILE_BYTES,
                "FACTORY_PROVIDER_SOURCE_INVALID")
        sources[path] = dict(sha=data["sha"], raw=raw)
    return sources

def run_isolated_tests(workspace, candidate, *, runner=subprocess.run):
    """Reproduce a failing regression on ORIGINAL bytes, then prove the fix.

    Green-only suites are NOT engineering repair evidence. The baseline
    must run at least one real test and fail as a unittest suite, while the
    patched copy must run the same number of tests and PASS. Both executions
    use the same isolated, network-disabled, nonroot Docker command.
    """
    supplied = Path(workspace)
    require(not supplied.is_symlink(), "FACTORY_WORKSPACE_INVALID")
    root = supplied.resolve(strict=True)
    require(root.is_dir(), "FACTORY_WORKSPACE_INVALID")
    require(type(candidate) is dict and candidate.get("status") ==
            "SOURCE_PINNED_PATCH_PREPARED_NOT_TESTED",
            "FACTORY_CANDIDATE_INVALID")
    with tempfile.TemporaryDirectory(prefix="brain-v10-isolated-") as tmp:
        stage = Path(tmp) / "checkout"
        shutil.copytree(root, stage, ignore=shutil.ignore_patterns(
            ".git", "node_modules", "private_runtime", "__pycache__", ".venv"),
            symlinks=True)
        # Only the ephemeral checkout is opened for nonroot access.
        # The original workspace is never chmod'd or modified.
        stage.chmod(0o755)
        targets = []
        for change in candidate["changes"]:
            target = stage / change["path"]
            require(target.is_file() and not target.is_symlink()
                    and target.resolve(strict=True).is_relative_to(stage.resolve())
                    and all(not ancestor.is_symlink() for ancestor in target.parents
                            if ancestor != stage and stage in ancestor.parents)
                    and sha256(target.read_bytes()) == change["before_sha256"],
                    "FACTORY_WORKTREE_SOURCE_CHANGED")
            targets.append((target,change))
        script = ('import sys,unittest;sys.path.insert(0,"/work");'
                  'suite=unittest.defaultTestLoader.discover('
                  '"/work/tests",pattern="test_*.py");'
                  'count=suite.countTestCases();'
                  'print("V10_TEST_COUNT="+str(count),file=sys.stderr);'
                  'sys.exit(3) if count<1 else None;'
                  'result=unittest.TextTestRunner(verbosity=1).run(suite);'
                  'raise SystemExit(not result.wasSuccessful())')
        command = [
            "docker", "run", "--rm", "--network", "none",
            "--read-only", "--user", "65534:65534",
            "--cap-drop=ALL", "--security-opt=no-new-privileges",
            "--pids-limit=128", "--memory=768m",
            "--mount", "type=bind,src=" + str(stage) + ",dst=/src,readonly",
            "--tmpfs", "/tmp:rw,nosuid,nodev,size=64m,mode=1777",
            "--tmpfs", "/work:rw,nosuid,nodev,size=512m,mode=1777",
            TEST_IMAGE, "sh", "-c",
            "cp -R /src/. /work/ && cd /work && python -I -B -c " +
            json.dumps(script),
        ]

        def execute():
            try:
                result = runner(command, capture_output=True, text=True,
                                timeout=300, check=False)
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise FactoryError("FACTORY_ISOLATED_TEST_UNAVAILABLE") from exc
            require(type(result.returncode) is int
                    and type(result.stdout) is str
                    and type(result.stderr) is str,
                    "FACTORY_ISOLATED_TEST_RESULT_INVALID")
            output = result.stdout + result.stderr
            match = re.search(r"V10_TEST_COUNT=([1-9][0-9]*)", output)
            require(match is not None and int(match[1]) <= 100000,
                    "FACTORY_TEST_CENSUS_UNVERIFIED")
            require(re.search(r"Ran [1-9][0-9]* tests? in ", output) is not None,
                    "FACTORY_TEST_CENSUS_UNVERIFIED")
            return result, int(match[1]), sha256(output.encode())

        original, red_count, original_hash = execute()
        require(original.returncode == 1
                and "FAILED" in (original.stdout + original.stderr),
                "FACTORY_REGRESSION_NOT_REPRODUCED")
        for target, change in targets:
            target.write_bytes(change["updated_bytes"])
        corrected, green_count, corrected_hash = execute()
        require(corrected.returncode == 0
                and green_count >= red_count
                and "OK" in (corrected.stdout + corrected.stderr),
                "FACTORY_ISOLATED_TEST_FAILED")
    return dict(status="ISOLATED_RED_GREEN_TESTS_PASSED_NOT_INDEPENDENT_CI",
                operation_id=candidate["operation_id"],
                baseline_test_cases=red_count, corrected_test_cases=green_count,
                baseline_output_sha256=original_hash,
                output_sha256=corrected_hash,
                regression_red_verified=True, corrected_green_verified=True,
                production_accepted=False, provider_writes=0)

def _write_intent(path, data):
    output = Path(path)
    require(output.parent.is_dir() and not output.is_symlink(),
            "FACTORY_INTENT_PATH_INVALID")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    try:
        fd = os.open(output, flags, 0o600)
    except FileExistsError as exc:
        raise FactoryError("FACTORY_PRIOR_INTENT_NEEDS_RECONCILIATION") from exc
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(canonical(data) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        # Preserve uncertain intent instead of silently allowing another write.
        raise
    return output

def create_draft(api, spec, candidate, tested, *, intent_path):
    """One unsafe-to-repeat write attempt; zero merge or deployment authority."""
    require(candidate["operation_id"] == tested.get("operation_id")
            and tested.get("status") == "ISOLATED_RED_GREEN_TESTS_PASSED_NOT_INDEPENDENT_CI"
            and tested.get("regression_red_verified") is True
            and tested.get("corrected_green_verified") is True
            and type(tested.get("baseline_test_cases")) is int
            and type(tested.get("corrected_test_cases")) is int
            and 1 <= tested["baseline_test_cases"] <= tested["corrected_test_cases"] <= 100000
            and type(tested.get("baseline_output_sha256")) is str
            and VALID_HASH.fullmatch(tested["baseline_output_sha256"])
            and type(tested.get("output_sha256")) is str
            and VALID_HASH.fullmatch(tested["output_sha256"]),
            "FACTORY_TEST_RECEIPT_MISMATCH")
    installation = api.request(
        "GET", "installation/repositories?per_page=100")
    entries = installation.get("repositories")
    require(type(entries) is list and type(installation.get("total_count")) is int
            and installation["total_count"] == len(entries) == 1
            and type(entries[0]) is dict
            and entries[0].get("full_name") == REPOSITORY,
            "FACTORY_TOKEN_SCOPE_NOT_SINGLE_REPOSITORY")
    evidence = verify_original_failed_core(api, spec)
    sources = verify_original_sources(api, spec)
    # A source transition during evidence collection must not cause an
    # unreviewed branch to be based on a different release.
    require(api.request("GET", "branches/main").get("commit", {}).get("sha")
            == spec["base_sha"], "FACTORY_MAIN_MOVED")
    reread = prepare(spec, {p: row["raw"] for p, row in sources.items()})
    require(reread["operation_id"] == candidate["operation_id"]
            and len(reread["changes"]) == len(candidate["changes"])
            and all(left == right for left,right in
                    zip(reread["changes"], candidate["changes"])),
            "FACTORY_SOURCE_MOVED_BEFORE_WRITE")
    intent = dict(operation_id=candidate["operation_id"],
                  source_sha=spec["base_sha"], branch=candidate["branch"],
                  repository=REPOSITORY, failure_run_id=spec["failure_run_id"],
                  test_receipt_sha256=sha256(canonical(tested).encode()),
                  original_run_verdict=evidence["status"],
                  status="EXTERNAL_WRITE_INTENT_MUST_RECONCILE")
    _write_intent(intent_path, intent)
    try:
        api.request("POST", "git/refs", {
            "ref": "refs/heads/" + candidate["branch"],
            "sha": spec["base_sha"],
        })
        final_sha = spec["base_sha"]
        for patch in candidate["changes"]:
            source = sources[patch["path"]]
            updated = api.request("PUT", "contents/" + patch["path"], {
                "message": "fix(v10): source-bound repair " +
                           candidate["operation_id"][:12],
                "content": base64.b64encode(patch["updated_bytes"]).decode(),
                "sha": source["sha"], "branch": candidate["branch"],
            })
            final_sha = updated.get("commit", {}).get("sha")
            require(type(final_sha) is str and VALID_SHA.fullmatch(final_sha),
                    "FACTORY_WRITE_SOURCE_UNVERIFIED")
        branch_ref = api.request("GET", "branches/" + candidate["branch"])
        require(branch_ref.get("commit", {}).get("sha") == final_sha,
                "FACTORY_DRAFT_BRANCH_READBACK_MISMATCH")
        for patch in candidate["changes"]:
            read = api.request("GET", "contents/" + patch["path"] +
                               "?ref=" + final_sha)
            require(read.get("type") == "file"
                    and read.get("encoding") == "base64"
                    and type(read.get("content")) is str,
                    "FACTORY_DRAFT_SOURCE_READBACK_MISMATCH")
            raw = base64.b64decode(read["content"].replace("\n", ""), validate=True)
            require(raw == patch["updated_bytes"],
                    "FACTORY_DRAFT_SOURCE_READBACK_MISMATCH")
        require(api.request("GET", "branches/main").get("commit", {}).get("sha")
                == spec["base_sha"], "FACTORY_MAIN_MOVED_DURING_WRITE")
        marker = "BRAIN_V10_OPERATION_ID: " + candidate["operation_id"]
        response = api.request("POST", "pulls", {
            "title": "fix(v10): verified original core " +
                     str(spec["failure_run_id"]),
            "head": candidate["branch"], "base": "main", "draft": True,
            "body": marker + "\nOriginal run: " + str(spec["failure_run_id"])
                + "\nExact source: " + spec["base_sha"]
                + "\nLocal isolated tests passed; independent CI and"
                  " source acceptance remain required. NO AUTOMERGE.",
        })
    except (FactoryError, ValueError, OSError) as exc:
        raise FactoryError("FACTORY_WRITE_UNCERTAIN_NEEDS_READBACK") from exc
    require(type(response.get("number")) is int and
            0 < response["number"] < 10**9,
            "FACTORY_PR_PROVIDER_READBACK_REQUIRED")
    # A POST response is not enough. Re-read the PR from GitHub and bind
    # exact head, branch, repository, main base, operation marker and draft.
    try:
        pr = api.request("GET", "pulls/" + str(response["number"]))
    except (FactoryError, ValueError, OSError) as exc:
        raise FactoryError("FACTORY_WRITE_UNCERTAIN_NEEDS_READBACK") from exc
    require(type(pr.get("head")) is dict and type(pr.get("base")) is dict
            and type(pr["head"].get("repo")) is dict
            and type(pr["base"].get("repo")) is dict
            and pr.get("number") == response["number"]
            and pr.get("state") == "open" and pr.get("draft") is True
            and pr.get("merged") is False
            and pr.get("head", {}).get("ref") == candidate["branch"]
            and pr["head"].get("sha") == final_sha
            and pr["head"].get("repo", {}).get("full_name") == REPOSITORY
            and pr.get("base", {}).get("ref") == "main"
            and pr["base"].get("repo", {}).get("full_name") == REPOSITORY
            and marker in (pr.get("body") or "").splitlines(),
            "FACTORY_PR_PROVIDER_READBACK_REQUIRED")
    # Main may advance after the final pre-POST read. Validate the actual
    # draft's base SHA and main again before claiming source-pinned identity.
    require(pr["base"].get("sha") == spec["base_sha"],
            "FACTORY_DRAFT_BASE_SOURCE_DRIFT")
    require(api.request("GET", "branches/main").get("commit", {}).get("sha")
            == spec["base_sha"], "FACTORY_MAIN_MOVED_AFTER_DRAFT")
    return dict(status="DRAFT_PR_CREATED_NOT_APPROVED",
                pr_number=response["number"],
                operation_id=candidate["operation_id"],
                source_sha=spec["base_sha"], branch=candidate["branch"],
                original_failed_core=evidence["run_id"],
                independent_ci_verified=False, merged=False,
                deployed=False, production_accepted=False)
