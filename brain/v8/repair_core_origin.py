"""Authenticated original Brain core admission before minting a scoped writer token."""
import json
import os
import re
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


def require(condition, code):
    if not condition:
        raise ValueError(code)


def admit(get, source, run_id):
    """Provider original is required; dispatch ACK is never enough."""
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
            and row.get("run_attempt") == 1
            and row.get("status") == "completed"
            and row.get("conclusion") == "success",
            "ORIGINAL_PRODUCTION_CORE_NOT_SUCCESS")
    kind = row.get("event")
    require(kind in {"workflow_dispatch", "schedule"},
            "PUSH_OR_MANUAL_RUNTIME_NOT_ALLOWED")
    jobs = get(ROOT + "actions/runs/" + run_id + "/jobs?per_page=100")
    rows = jobs.get("jobs") if type(jobs) is dict else None
    require(type(jobs) is dict and type(jobs.get("total_count")) is int
            and jobs["total_count"] == 1 and type(rows) is list
            and len(rows) == 1 and type(rows[0]) is dict,
            "ORIGINAL_JOB_CENSUS_UNVERIFIED")
    job = rows[0]
    steps = job.get("steps")
    require(job.get("name") == "monitor" and job.get("status") == "completed"
            and job.get("conclusion") == "success" and type(steps) is list
            and all(type(step) is dict for step in steps),
            "CORE_JOB_FAILED")
    names = {step.get("name") for step in steps if step.get("conclusion") == "success"}
    require(all(name in names for name in MANDATORY), "MANDATORY_CORE_STEP_INCOMPLETE")
    if kind == "workflow_dispatch":
        require(bool(names & AUTOMATIC), "ORIGINAL_DISPATCH_ORIGIN_NOT_AUTHENTICATED")
    return {"status": "ORIGINAL_AUTOMATIC_CORE_AUTHENTICATED",
            "source_sha": source, "run_id": run_id,
            "source_pinned": True, "writer_token_issued": False,
            "release_authority": False}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("ORIGIN_REDIRECT_REJECTED")


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
        req = urllib.request.Request("https://api.github.com" + path,
            headers={"Authorization": "Bearer " + token,
                     "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28"},method="GET")
        with opener.open(req,timeout=20) as response:
            raw = response.read(1048577)
        require(len(raw) <= 1048576, "ORIGIN_PROVIDER_RESPONSE_TOO_LARGE")
        return json.loads(raw)

    receipt = admit(get, claimed, run_id)
    dest = Path(os.environ.get("RUNNER_TEMP", "/tmp")) / "v8-origin.json"
    dest.write_text(json.dumps(receipt,sort_keys=True) + "\n")
    print("Original automatic Brain core verified before App token; no release.")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        raise SystemExit("V8_CORE_ORIGIN_UNVERIFIED; NO_WRITER_TOKEN") from None
