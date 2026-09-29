"""Complete only the scheduler REPAIR work proven by a remote submission receipt."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from scheduler.autonomous_scheduler import claim_work, complete_work, now_iso, validate_state
from software_factory.candidate_worker import object_hash, require


def finalize_scheduler_repair(state: dict, *, work: dict, submission: dict,
                              at: str | None = None) -> tuple[dict, str]:
    validate_state(state)
    require(submission.get("status") in {"REMOTE_CANDIDATE_SUBMITTED", "REMOTE_CANDIDATE_REUSED"}
            and submission.get("remote_candidate_present") is True,
            "remote candidate proof is not completion eligible")
    require(submission.get("independent_verification") is False
            and submission.get("pr_created") is False
            and submission.get("production_changed") is False,
            "submission receipt overclaims downstream completion")
    body = dict(submission)
    given = body.pop("receipt_hash", None)
    require(given == object_hash(body), "submission receipt hash mismatch")
    require(work.get("work_type") == "REPAIR" and work.get("source_ref") == submission.get("source_ref"),
            "scheduler work/submission source mismatch")
    require(work.get("assigned_agent_id") == "AGT-ENGINEER"
            and work.get("required_authority") == "MODIFY",
            "scheduler repair role/authority mismatch")
    fingerprint = work["fingerprint"]
    if fingerprint in state["completed_fingerprints"]:
        return state, "ALREADY_COMPLETE"
    matches = [row for row in state["work_items"] if row["fingerprint"] == fingerprint]
    require(len(matches) == 1, "scheduler repair fingerprint missing or duplicate")
    current = matches[0]
    require(current["source_ref"] == work["source_ref"], "scheduler repair identity drift")
    at = at or now_iso()
    if current["state"] == "QUEUED":
        state = claim_work(state, fingerprint, lease_owner="repair-candidate-cycle",
                           lease_seconds=300, at=at)
        state = complete_work(state, fingerprint, at=at)
        return state, "COMPLETED"
    require(current["state"] == "COMPLETE", "scheduler repair is active or not completion eligible")
    return state, "ALREADY_COMPLETE"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scheduler-state", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--submission", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    state = json.loads(args.scheduler_state.read_text())
    work = json.loads(args.work.read_text())
    submission = json.loads(args.submission.read_text())
    updated, disposition = finalize_scheduler_repair(state, work=work, submission=submission)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(updated, indent=2) + "\n")
    print(json.dumps({"status": disposition,
                      "source_ref": work["source_ref"],
                      "remote_commit_sha": submission["remote_commit_sha"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
