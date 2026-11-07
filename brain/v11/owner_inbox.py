"""Produce restart-stable, source-pinned owner handoffs from the actual v9 queue.

This is an action *handoff*, not a source patcher or cross-repository writer.
The owner must re-read original GitHub evidence and reproduce the defect before
modifying source. No report may upgrade historical source signals into incidents.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

from brain.v9.batch_queue import PROJECTS

SHA40 = re.compile(r"[0-9a-f]{40}\Z")
SHA64 = re.compile(r"[0-9a-f]{64}\Z")
RUN_ID = re.compile(r"[1-9][0-9]{0,11}\Z")
MAX_INPUT = 2 * 1024 * 1024
MAX_JOBS = 16
MAX_STEPS = 40
MAX_OUTPUT_JOBS = 5

class InboxError(ValueError):
    pass


def need(ok, reason):
    if not ok:
        raise InboxError(reason)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def strict_load(path):
    p = Path(path)
    need(p.is_file() and not p.is_symlink() and
         0 < p.stat().st_size <= MAX_INPUT, "INBOX_INPUT_UNSAFE")
    def pairs(rows):
        result = {}
        for k, v in rows:
            need(k not in result, "INBOX_DUPLICATE_KEY")
            result[k] = v
        return result
    return json.loads(p.read_text(encoding="utf-8"), object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(
                          InboxError("INBOX_NONFINITE")))


def _original(job):
    need(type(job) is dict, "INBOX_JOB_INVALID")
    project = job.get("project_id")
    repository = job.get("repository")
    source = job.get("source_sha")
    work_id = job.get("work_id")
    need(project in PROJECTS and PROJECTS[project] == repository
         and type(source) is str and SHA40.fullmatch(source) is not None
         and type(work_id) is str and SHA64.fullmatch(work_id) is not None,
         "INBOX_JOB_IDENTITY_INVALID")
    need(job.get("stage") == "OBSERVED"
         and job.get("path") == "repository-observation"
         and type(job.get("priority")) is int and job["priority"] == 1
         and job.get("incident_classification") ==
             "ORIGINAL_MAIN_JOB_FAILURE_CONFIRMED_ROOT_CAUSE_OPEN"
         and job.get("automatic_execution_authority") is False
         and job.get("durable_claim_required_before_mutation") is True
         and job.get("source_reobservation_required") is True,
         "INBOX_NOT_ACTIONABLE_INCIDENT")
    owner, verifier = job.get("owner"), job.get("verifier")
    ident = re.compile(r"[a-z][a-z0-9._-]{0,79}\Z")
    need(type(owner) is str and ident.fullmatch(owner) is not None
         and type(verifier) is str and ident.fullmatch(verifier) is not None,
         "INBOX_OWNER_INVALID")
    proof = job.get("failure_evidence")
    need(type(proof) is dict
         and proof.get("status") == "ORIGINAL_MAIN_JOB_FAILURE_CONFIRMED"
         and proof.get("source_sha") == source
         and proof.get("root_cause_verified") is False
         and proof.get("event") in ("push", "schedule", "workflow_dispatch"),
         "INBOX_PROVIDER_PROOF_INVALID")
    run_id, job_id = proof.get("run_id"), proof.get("job_id")
    need(type(run_id) is int and RUN_ID.fullmatch(str(run_id)) is not None
         and type(job_id) is int and RUN_ID.fullmatch(str(job_id)) is not None
         and proof.get("url") ==
             f"https://github.com/{repository}/actions/runs/{run_id}/job/{job_id}",
         "INBOX_PROVIDER_IDENTITY_INVALID")
    stages = proof.get("failed_steps")
    need(type(stages) is list and 1 <= len(stages) <= MAX_STEPS,
         "INBOX_FAILURE_STEPS_INVALID")
    step_names = []
    seen_steps = set()
    for step in stages:
        need(type(step) is dict and type(step.get("number")) is int
             and 0 < step["number"] < 1000
             and type(step.get("name")) is str
             and 1 <= len(step["name"]) <= 180
             and "\n" not in step["name"],
             "INBOX_FAILURE_STEP_INVALID")
        need(step["number"] not in seen_steps, "INBOX_DUPLICATE_FAILURE_STEP")
        seen_steps.add(step["number"])
        step_names.append({"number": step["number"], "name": step["name"]})
    identity = {"repository": repository, "source_sha": source,
                "run_id": run_id, "job_id": job_id, "work_id": work_id}
    return {
        **identity,
        "project_id": project,
        "owner": owner,
        "independent_verifier": verifier,
        "stage": "ORIGINAL_FAILURE_OBSERVED_REPRODUCTION_REQUIRED",
        "original_run_event": proof["event"],
        "original_job_url": proof["url"],
        "failed_steps": step_names,
        "owner_action": "READ_ORIGINAL_LOGS_THEN_REPRODUCE_RED_BEFORE_PATCH",
        "required_delivery_evidence": [
            "original_failed_main_job", "exact_source_regression_red",
            "isolated_patch_green", "independent_exact_head_checks",
            "merged_commit", "actual_postmerge_runtime_readback"],
        "source_recheck_required": True,
        "cross_project_code_write_authorized": False,
        "technical_repair_verified": False,
        "production_verified": False,
        "handoff_id": digest(identity),
    }


def build(document, *, expected_source):
    need(type(expected_source) is str and SHA40.fullmatch(expected_source) is not None,
         "INBOX_EXPECTED_SOURCE_INVALID")
    need(type(document) is dict
         and document.get("schema_version") == 1
         and document.get("status") == "DURABLE_OWNER_QUEUE_UPDATED_NOT_RELEASED"
         and document.get("incident_gate") == "ORIGINAL_MAIN_FAILURE_PROOF_REQUIRED"
         and document.get("source_sha") == expected_source
         and document.get("production_accepted") is False
         and document.get("automatic_execution_authority") is False
         and document.get("provider_writes") == 0,
         "INBOX_NOT_AUTHENTICATED_CORE_REPORT")
    checkpoint = document.get("queue_checkpoint")
    need(type(checkpoint) is dict
         and type(checkpoint.get("sequence")) is int
         and checkpoint["sequence"] >= 0
         and type(checkpoint.get("chain_hash")) is str
         and SHA64.fullmatch(checkpoint["chain_hash"]) is not None
         and type(checkpoint.get("work_hash")) is str
         and SHA64.fullmatch(checkpoint["work_hash"]) is not None,
         "INBOX_CHECKPOINT_INVALID")
    metrics = document.get("metrics")
    need(type(metrics) is dict
         and type(metrics.get("stages")) is dict
         and type(metrics["stages"].get("OBSERVED")) is int
         and metrics["stages"]["OBSERVED"] >= 0,
         "INBOX_METRICS_INVALID")
    jobs = document.get("owner_jobs")
    need(type(jobs) is list and len(jobs) <= MAX_JOBS,
         "INBOX_JOB_COUNT_INVALID")
    ready, seen = [], set()
    for job in jobs:
        row = _original(job)
        need(row["handoff_id"] not in seen, "INBOX_DUPLICATE_INCIDENT")
        seen.add(row["handoff_id"])
        ready.append(row)
    ready.sort(key=lambda x:(x["project_id"], x["run_id"], x["job_id"], x["work_id"]))
    result = {
        "schema_version": 1,
        "source_sha": expected_source,
        "queue_checkpoint": checkpoint,
        "observed_not_necessarily_actionable": metrics["stages"]["OBSERVED"],
        "original_failure_handoffs": ready[:MAX_OUTPUT_JOBS],
        "deferred_original_failure_handoffs": max(0, len(ready)-MAX_OUTPUT_JOBS),
        "next_action": ("VERIFY_CURRENTNESS_BEFORE_OWNER_TRIAGE"
                        if ready else "NO_CONFIRMED_INCIDENT_FOR_OWNER"),
        "general_cross_project_executor": "NOT_CONFIGURED",
        "requires_provider_reread": True,
        "provider_writes": 0,
        "production_verified": False,
    }
    result["packet_sha256"] = digest(result)
    return result


def write_atomic(path, result):
    path = Path(path)
    need(path.parent.is_dir() and not path.is_symlink()
         and not path.exists(), "INBOX_OUTPUT_UNSAFE")
    fd, tmp = tempfile.mkstemp(prefix=".inbox-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(canonical(result) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--expected-sha", required=True)
    args = parser.parse_args(argv)
    try:
        result = build(strict_load(args.input), expected_source=args.expected_sha)
        write_atomic(args.output, result)
        print(canonical({"status": result["next_action"],
                         "handoffs": len(result["original_failure_handoffs"]),
                         "provider_writes": 0, "production_verified": False}))
        return 0
    except (InboxError, OSError, ValueError, TypeError, UnicodeError):
        print(canonical({"status": "OWNER_INBOX_UNVERIFIED",
                         "provider_writes": 0, "production_verified": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
