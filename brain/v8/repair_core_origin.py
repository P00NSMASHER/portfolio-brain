"""Authenticated original Brain core admission before minting a scoped writer token."""
import json
import os
import re
import time
from pathlib import Path
import urllib.error
import urllib.request

REPOSITORY = "P00NSMASHER/portfolio-brain"
SHA = re.compile(r"[0-9a-f]{40}\Z")
RUN_ID = re.compile(r"[1-9][0-9]{0,15}\Z")
ROOT = "/repos/" + REPOSITORY + "/"
MANDATORY = (
    "Bind execution to unchanged current main",
    "Exact-SHA deterministic preflight",
    "Verify authoritative state and zero event backlog",
    "Publish one nonsecret state transaction without force",
    "Preserve verifiable execution evidence",
)
AUTOMATIC = {
    "Verify independently signed Cloudflare Cron provenance",
    "Validate GitHub-native watchdog scheduling origin",
    "Verify external clock provenance when supplied",
}


class OriginError(ValueError):
    """Only static, nonsecret diagnostic codes may cross this boundary."""


def require(condition, code):
    if not condition:
        raise OriginError(code)


def admit(get, source, run_id, *, sleep=time.sleep):
    """Require an immutable successful core, with bounded original-step readback.

    GitHub may briefly return an incomplete job-step list after a successful
    workflow_run event. Retry only genuinely incomplete original snapshots,
    never explicit failed steps, a changed job identity, or an adverse core.
    Exhaustion is a denial, not a fabricated receipt.
    """
    require(type(source) is str and SHA.fullmatch(source)
            and type(run_id) is str and RUN_ID.fullmatch(run_id),
            "SOURCE_OR_RUN_ID_INVALID")
    main = get(ROOT + "branches/main")
    require(type(main) is dict and type(main.get("commit")) is dict
            and main["commit"].get("sha") == source, "PROTECTED_MAIN_SOURCE_CHANGED")
    row = get(ROOT + "actions/runs/" + run_id)
    require(type(row) is dict and row.get("name") == "brain-cycle-v2"
            and row.get("path") == ".github/workflows/brain-cycle.yml"
            and row.get("repository", {}).get("full_name") == REPOSITORY
            and row.get("head_branch") == "main" and row.get("head_sha") == source
            and row.get("id") == int(run_id)
            and row.get("run_attempt") == 1
            and row.get("status") == "completed"
            and row.get("conclusion") == "success",
            "ORIGINAL_PRODUCTION_CORE_NOT_SUCCESS")
    kind = row.get("event")
    require(kind in {"workflow_dispatch", "schedule"},
            "PUSH_OR_MANUAL_RUNTIME_NOT_ALLOWED")
    path = ROOT + "actions/runs/" + run_id + "/jobs?per_page=100"
    original_job_id = None
    for attempt in range(4):
        jobs = get(path)
        rows = jobs.get("jobs") if type(jobs) is dict else None
        require(type(jobs) is dict and type(jobs.get("total_count")) is int
                and jobs["total_count"] == 1 and type(rows) is list
                and len(rows) == 1 and type(rows[0]) is dict,
                "ORIGINAL_JOB_CENSUS_UNVERIFIED")
        job = rows[0]
        job_id = job.get("id")
        require(type(job_id) is int and job_id > 0,
                "ORIGINAL_JOB_ID_INVALID")
        if original_job_id is None:
            original_job_id = job_id
        require(job_id == original_job_id, "ORIGINAL_JOB_ID_CHANGED")
        require(type(job.get("run_id")) is int
                and job["run_id"] == int(run_id)
                and job.get("run_attempt") == 1
                and job.get("head_sha") == source,
                "ORIGINAL_JOB_RUN_OR_SOURCE_MISMATCH")
        steps = job.get("steps")
        require(job.get("name") == "monitor" and type(steps) is list
                and all(type(step) is dict for step in steps),
                "CORE_JOB_INVALID")
        # A completed adverse job is never a transient incomplete snapshot.
        require(job.get("conclusion") in (None, "success")
                and job.get("status") in ("queued", "in_progress", "completed"),
                "CORE_JOB_FAILED")
        results = {}
        for step in steps:
            name, conclusion = step.get("name"), step.get("conclusion")
            if name not in MANDATORY and name not in AUTOMATIC:
                continue
            require(type(name) is str and name not in results,
                    "ORIGINAL_JOB_STEP_IDENTITY_INVALID")
            require(conclusion in (None, "success", "skipped", "failure",
                                    "cancelled", "timed_out", "neutral"),
                    "ORIGINAL_JOB_STEP_RESULT_INVALID")
            results[name] = conclusion
        require(all(results.get(name) in (None, "success") for name in MANDATORY),
                "MANDATORY_CORE_STEP_FAILED")
        mandatory_ready = all(results.get(name) == "success" for name in MANDATORY)
        origin_ready = kind == "schedule" or any(
            results.get(name) == "success" for name in AUTOMATIC)
        job_ready = job.get("status") == "completed" and job.get("conclusion") == "success"
        if mandatory_ready and origin_ready and job_ready:
            # No extra API read on the already-authenticated first snapshot.
            # But delayed rereads require confirming current main did not drift.
            if attempt:
                main_again = get(ROOT + "branches/main")
                require(type(main_again) is dict
                        and type(main_again.get("commit")) is dict
                        and main_again["commit"].get("sha") == source,
                        "PROTECTED_MAIN_SOURCE_CHANGED")
            return {"status": "ORIGINAL_AUTOMATIC_CORE_AUTHENTICATED",
                    "source_sha": source, "run_id": run_id,
                    "source_pinned": True, "writer_token_issued": False,
                    "release_authority": False}
        if attempt == 3:
            if not mandatory_ready:
                raise OriginError("MANDATORY_CORE_STEP_INCOMPLETE")
            if not origin_ready:
                raise OriginError("ORIGINAL_DISPATCH_ORIGIN_NOT_AUTHENTICATED")
            raise OriginError("CORE_JOB_INCOMPLETE")
        sleep(attempt + 1)
    raise OriginError("CORE_JOB_INCOMPLETE")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise OriginError("ORIGIN_REDIRECT_REJECTED")


def read_json(opener, token, path, sleep=time.sleep):
    """Retry only bounded transient read failures; never retry admission denials."""
    req = urllib.request.Request("https://api.github.com" + path,
        headers={"Authorization": "Bearer " + token,
                 "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28"}, method="GET")
    for attempt in range(3):
        try:
            with opener.open(req, timeout=20) as response:
                raw = response.read(1048577)
            break
        except urllib.error.HTTPError as exc:
            code = "ORIGIN_HTTP_" + str(exc.code) if exc.code in {401, 403, 404, 429, 500, 502, 503, 504} else "ORIGIN_HTTP_REJECTED"
            retry = exc.code in {429, 500, 502, 503, 504}
            exc.close()
            if not retry or attempt == 2:
                raise OriginError(code) from None
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt == 2:
                raise OriginError("ORIGIN_TRANSPORT_UNAVAILABLE") from None
        sleep(attempt + 1)
    require(len(raw) <= 1048576, "ORIGIN_PROVIDER_RESPONSE_TOO_LARGE")
    try:
        return json.loads(raw)
    except (ValueError, UnicodeError):
        raise OriginError("ORIGIN_JSON_INVALID") from None


def main():
    token = os.environ.get("GH_TOKEN", "")
    source = os.environ.get("GITHUB_SHA", "")
    claimed = os.environ.get("BRAIN_SOURCE_SHA", "")
    run_id = os.environ.get("BRAIN_RUN_ID", "")
    require(type(token) is str and len(token) > 10
            and source == claimed, "SOURCE_OR_TOKEN_MISSING")
    opener = urllib.request.build_opener(NoRedirect())

    def get(path):
        require(path.startswith(ROOT) and (
            path == ROOT + "branches/main"
            or re.fullmatch(re.escape(ROOT) + r"actions/runs/[1-9][0-9]{0,15}", path)
            or re.fullmatch(re.escape(ROOT) + r"actions/runs/[1-9][0-9]{0,15}/jobs\?per_page=100", path)
        ), "UNREVIEWED_API_PATH")
        return read_json(opener, token, path)

    receipt = admit(get, claimed, run_id)
    dest = Path(os.environ.get("RUNNER_TEMP", "/tmp")) / "v8-origin.json"
    dest.write_text(json.dumps(receipt,sort_keys=True) + "\n")
    print("Original automatic Brain core verified before App token; no release.")


if __name__ == "__main__":
    try:
        main()
    except OriginError as exc:
        raise SystemExit("V8_CORE_ORIGIN_UNVERIFIED; " + str(exc) + "; NO_WRITER_TOKEN") from None
    except Exception:
        raise SystemExit("V8_CORE_ORIGIN_UNVERIFIED; ORIGIN_INTERNAL_ERROR; NO_WRITER_TOKEN") from None
