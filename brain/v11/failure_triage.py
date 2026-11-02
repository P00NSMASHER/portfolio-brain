"""Authenticate and classify genuine failed Brain cores without modifying source.

This is the bounded first stage of unattended repair, NOT a diagnosis or fix.
Only original GitHub first-attempt scheduled or signed-origin dispatched core
failures qualify. No LLM, paid APIs, credentials beyond read-only GitHub, PR,
merge, schedule changes, or unauthenticated source/log interpretation.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re

from brain.v10 import engineering_factory as factory

REPO = factory.REPOSITORY
MAX_JOBS = 100
RUN = re.compile(r"[1-9][0-9]{0,11}\Z")
# These are trusted-main workflow STEP NAMES, not cause attribution. Unknown
# names never become untrusted instructions or authorization to patch code.
STEP_FAMILIES = {
    "Checkout exact source without persisted credentials": "SOURCE_CHECKOUT",
    "Bind execution to unchanged current main": "SOURCE_DRIFT",
    "Verify external clock provenance when supplied": "SCHEDULER_ORIGIN",
    "Validate GitHub-native watchdog scheduling origin": "SCHEDULER_ORIGIN",
    "Verify independently signed Cloudflare Cron provenance": "SCHEDULER_ORIGIN",
    "Exact-SHA deterministic preflight": "PREFLIGHT",
    "Read-only public project monitoring": "PUBLIC_OBSERVATION",
    "Bounded public code and opportunity research": "PUBLIC_RESEARCH",
    "Evidence-bound deterministic experiment": "EXPERIMENT",
    "Verify authoritative state and zero event backlog": "STATE_VALIDATION",
    "Persist v9 owner work and bounded original publication evidence": "WORK_QUEUE",
    "Verify main and state parent before publication": "STATE_PREPUBLICATION",
    "Publish one nonsecret state transaction without force": "STATE_DELIVERY",
    "Preserve verifiable execution evidence": "EVIDENCE_ARCHIVE",
}


def intake(api, *, run_id, source_sha):
    factory.require(type(run_id) is int and
                    RUN.fullmatch(str(run_id)) is not None and
                    type(source_sha) is str and factory.VALID_SHA.fullmatch(source_sha),
                    "FAILURE_INTAKE_IDENTITY_INVALID")
    main = api.request("GET", "branches/main")
    factory.require(type(main) is dict and main.get("protected") is True
                    and main.get("commit", {}).get("sha") == source_sha,
                    "FAILURE_INTAKE_PROTECTED_MAIN_MOVED")
    run = api.request("GET", "actions/runs/" + str(run_id))
    factory.require(type(run) is dict
                    and run.get("id") == run_id
                    and run.get("name") == "brain-cycle-v2"
                    and run.get("path") == ".github/workflows/brain-cycle.yml"
                    and run.get("repository", {}).get("full_name") == REPO
                    and run.get("head_sha") == source_sha
                    and run.get("head_branch") == "main"
                    and type(run.get("run_attempt")) is int
                    and run["run_attempt"] == 1
                    and run.get("status") == "completed"
                    and run.get("conclusion") in {"failure", "timed_out"}
                    and run.get("event") in {"schedule", "workflow_dispatch"},
                    "FAILURE_INTAKE_NO_ORIGINAL_FAILED_CORE")
    jobs = api.request("GET", "actions/runs/" + str(run_id) +
                       "/jobs?per_page=100")
    rows = jobs.get("jobs") if type(jobs) is dict else None
    factory.require(type(rows) is list and
                    type(jobs.get("total_count")) is int and
                    len(rows) == jobs["total_count"] < MAX_JOBS,
                    "FAILURE_INTAKE_JOB_CENSUS_INCOMPLETE")
    monitors = [job for job in rows if type(job) is dict
                and job.get("name") == "monitor"]
    factory.require(len(monitors) == 1,
                    "FAILURE_INTAKE_MONITOR_UNVERIFIED")
    job = monitors[0]
    factory.require(job.get("run_id") == run_id
                    and job.get("run_attempt") == 1
                    and job.get("head_sha") == source_sha
                    and job.get("status") == "completed"
                    and job.get("conclusion") == run["conclusion"]
                    and type(job.get("steps")) is list
                    and 1 <= len(job["steps"]) <= 100,
                    "FAILURE_INTAKE_JOB_IDENTITY_INVALID")
    steps = job["steps"]
    factory.require(factory.verified_automatic_origin(run["event"], steps),
                    "FAILURE_INTAKE_AUTOMATIC_ORIGIN_UNVERIFIED")
    failed = [step for step in steps
              if type(step) is dict
              and step.get("conclusion") in {"failure", "timed_out"}]
    factory.require(bool(failed), "FAILURE_INTAKE_NO_FAILED_STEP")
    # Reconfirm original protected-main identity after provider sampling.
    source = api.request("GET", "branches/main")
    factory.require(source.get("protected") is True
                    and source.get("commit", {}).get("sha") == source_sha,
                    "FAILURE_INTAKE_SOURCE_DRIFT")
    families = sorted({STEP_FAMILIES.get(step.get("name"),
                                        "UNCLASSIFIED_ORIGINAL_STEP")
                       for step in failed})
    proof = {
        "schema_version": 1,
        "status": "ORIGINAL_AUTOMATIC_FAILURE_CLASSIFIED_NOT_REPAIRED",
        "repository": REPO,
        "source_sha": source_sha,
        "source_run_id": run_id,
        "original_job_id": job.get("id"),
        "original_event": run["event"],
        "original_conclusion": run["conclusion"],
        "failed_stage_families": families,
        "stage_is_root_cause": False,
        "candidate_patch_prepared": False,
        "draft_pr_created": False,
        "independent_check_passed": False,
        "merged": False,
        "deployed": False,
        "production_accepted": False,
        "provider_writes": 0,
        "next_action": "REQUIRE_EXACT_SOURCE_SAFE_RECIPE_AND_REAL_RED_GREEN_TESTS",
    }
    proof["fingerprint_sha256"] = factory.sha256(factory.canonical({
        "repository": REPO, "source_sha": source_sha, "run_id": run_id,
        "stages": families}).encode())
    return proof


def _write_exclusive(path, payload):
    target = Path(path)
    factory.require(target.parent.is_dir() and not target.is_symlink(),
                    "FAILURE_INTAKE_OUTPUT_UNSAFE")
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        out.write(factory.canonical(payload) + "\n")
        out.flush()
        os.fsync(out.fileno())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--run-id", required=True, type=int)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        api = factory.GitHubTransport(os.environ.get("GITHUB_TOKEN", ""))
        receipt = intake(api, run_id=args.run_id, source_sha=args.source_sha)
        _write_exclusive(args.output, receipt)
        print(json.dumps({"status": receipt["status"],
                          "source_run_id": receipt["source_run_id"],
                          "provider_writes": 0, "merged": False}, sort_keys=True))
        return 0
    except (factory.FactoryError, ValueError, OSError):
        print(json.dumps({"status": "ORIGINAL_FAILURE_UNVERIFIED_NOT_REPAIRED",
                          "provider_writes": 0, "merged": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
