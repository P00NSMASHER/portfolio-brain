"""Separate read-only CI job: re-read exported bytes, replay, and prepare handoff.

The producer artifact is selected by the exact ID output of this run's build
job. Its receipt must match the actual consumer checkout, run and attempt. No
builder-provided task, command, file manifest or PASS is accepted on its own.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re
import subprocess

from software_factory.candidate_worker import DockerRunner, digest, object_hash, require
from software_factory.candidate_replay import read_bytes, read_json, replay_candidate
from software_factory.validate_candidate_worker import BASE, pilot_task

ROOT = Path(__file__).resolve().parents[1]


def validate_source_proof(proof: dict, task: dict, *, head: str, run_id: str,
                          run_attempt: str, image_id: str) -> None:
    require(isinstance(proof, dict) and proof.get("receipt_hash") == object_hash(
        {k: v for k, v in proof.items() if k != "receipt_hash"}), "producer receipt digest mismatch")
    require(proof.get("proof_kind") == "CONTROLLED_REAL_SOURCE_REPAIR_PILOT"
            and proof.get("queue_origin") == "EXPLICIT_CI_PILOT_NOT_LIVE_ALLOCATION",
            "unrecognized source proof class")
    require(re.fullmatch(r"[0-9a-f]{40}", head) and proof.get("worker_head_sha") == head,
            "producer/consumer head mismatch")
    require(re.fullmatch(r"[1-9][0-9]*", run_id) and proof.get("run_id") == run_id,
            "producer run mismatch")
    require(re.fullmatch(r"[1-9][0-9]*", run_attempt) and proof.get("run_attempt") == run_attempt,
            "producer attempt mismatch")
    require(proof.get("pilot_base_sha") == task["base_sha"]
            and proof.get("task_hash") == object_hash(task), "producer task mismatch")
    require(re.fullmatch(r"sha256:[0-9a-f]{64}", image_id) and proof.get("image_id") == image_id,
            "producer/replay image mismatch")
    for field in ("independent_verification", "production_changed", "merged", "deployed"):
        require(proof.get(field) is False, "source proof cannot upgrade authority")
    summary = proof.get("summary")
    require(isinstance(summary, dict) and summary.get("receipt_hash") == object_hash(
        {k: v for k, v in summary.items() if k != "receipt_hash"}), "source cycle digest mismatch")
    require(all(type(summary.get(k)) is int and summary[k] == v for k, v in
                {"attempted_count": 1, "completed_count": 1, "deferred_count": 0,
                 "remaining_queued_count": 0}.items()) and summary.get("authority_granted") is False,
            "source cycle is not a completed candidate build")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--proof-dir", required=True)
    parser.add_argument("--image-id", required=True)
    parser.add_argument("--expected-worker-head", required=True)
    parser.add_argument("--producer-artifact-id", required=True)
    parser.add_argument("--producer-artifact-digest", required=True)
    parser.add_argument("--output-dir", default="candidate-replay-proof")
    args = parser.parse_args()
    output = Path(args.output_dir).resolve()
    require(not output.exists(), "replay proof already exists")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    run = os.environ.get("GITHUB_RUN_ID", "")
    attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "")
    require(head == args.expected_worker_head, "actual replay checkout mismatch")
    require(re.fullmatch(r"[1-9][0-9]*", args.producer_artifact_id), "exact producer artifact ID required")
    require(re.fullmatch(r"(?:sha256:)?[0-9a-f]{64}", args.producer_artifact_digest),
            "producer artifact digest metadata required")
    job = {"schema_version": 1, "proof_kind": "SEPARATE_JOB_PATCH_REPLAY",
           "worker_head_sha": head, "pilot_base_sha": BASE, "run_id": run, "run_attempt": attempt,
           "consumer_job": os.environ.get("GITHUB_JOB"), "image_id": args.image_id,
           "producer_artifact_id": args.producer_artifact_id,
           "producer_artifact_digest_metadata": args.producer_artifact_digest,
           "independent_verification": False, "production_changed": False,
           "remote_submission_performed": False, "merged": False, "deployed": False,
           "delivered_improvements": 0}
    try:
        task = pilot_task(ROOT)
        producer = Path(args.proof_dir).resolve(strict=True)
        proof = read_json(producer, "pilot_receipt.json")
        validate_source_proof(proof, task, head=head, run_id=run, run_attempt=attempt, image_id=args.image_id)
        require(read_json(producer, "pilot_task.json") == task, "exported task differs from frozen source contract")
        require(digest(read_bytes(producer, "worker-source.bundle", 20 * 1024 * 1024))
                == proof.get("source_bundle_sha256"), "source bundle digest mismatch")
        task_hash = object_hash(task)
        build_dir = producer / "candidate_builds" / task_hash.split(":", 1)[1]
        require(not build_dir.is_symlink() and build_dir.resolve().is_relative_to(producer),
                "build artifact directory escaped root")
        build = read_json(build_dir, "build_receipt.json")
        require(all(row.get("runtime") == "docker" and row.get("image_id") == args.image_id
                    for row in build.get("tests", [])), "producer did not use expected isolated runtime")
        receipt = replay_candidate(task, approved_hash=task_hash, checkout=ROOT,
                                   artifact_dir=build_dir, runner=DockerRunner(args.image_id), output_dir=output)
        job.update(status="PASS", replay_receipt_hash=receipt["receipt_hash"],
                   candidate_commit_sha=receipt["candidate_commit_sha"],
                   candidate_git_tree_sha=receipt["candidate_git_tree_sha"],
                   replay_test_counts=[row["test_count"] for row in receipt["replay_tests"]],
                   factory_state="VERIFYING", source_proof_hash=proof["receipt_hash"])
    except Exception as exc:
        job.update(status="BLOCKED", error_class=type(exc).__name__, error=str(exc)[:300])
        raise
    finally:
        job["receipt_hash"] = object_hash(job)
        output.mkdir(parents=True, exist_ok=True)
        (output / "replay_job_receipt.json").write_text(json.dumps(job, indent=2) + "\n")
        print(json.dumps(job, indent=2))


if __name__ == "__main__":
    main()
