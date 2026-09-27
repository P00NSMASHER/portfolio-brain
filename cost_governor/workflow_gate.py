#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

from cost_governor.cost_governor import (
    CostGovernorError,
    commit_reservation,
    load_state,
    make_github_job_request,
    now_iso,
    preflight,
    zero_usage,
)

def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n")

def _github_output(**values) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")

def governed_github_attempt(state, *, run_id: str, job_id: str, observed_attempt: int) -> int:
    """Map a GitHub rerun number onto the durable governed retry sequence.

    GitHub workload admission is no longer a paid-ledger reservation. New runs
    therefore use GitHub's observed run attempt directly. Historical reservations
    are still honored so a rerun that crosses the migration boundary cannot reset
    an already-recorded retry sequence.
    """
    if type(observed_attempt) is not int or observed_attempt < 1:
        raise ValueError("observed GitHub attempt must be a positive integer")
    group = f"github-job:{run_id}:{job_id}"
    prior = sorted({
        int(row["attempt"])
        for row in state.get("reservations", [])
        if row.get("retry_group") == group
    })
    if not prior:
        return observed_attempt
    highest = max(prior)
    if observed_attempt <= highest:
        return observed_attempt
    return highest + 1


def measured_github_usage(reservation: dict, *, at: str) -> dict:
    """Return bounded elapsed usage for a governed GitHub job.

    The reservation remains the fail-closed maximum while work is in flight or
    its outcome is unknown. A successful finalize must commit the elapsed
    governed execution, rounded up to whole runner minutes, instead of charging
    every job its full reservation estimate.
    """
    if reservation.get("resource_kind") != "GITHUB_JOB" or reservation.get("status") != "RESERVED":
        raise CostGovernorError("measured GitHub usage requires a reserved GitHub job")
    try:
        started = datetime.fromisoformat(str(reservation["created_at"]).replace("Z", "+00:00"))
        finished = datetime.fromisoformat(str(at).replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError) as exc:
        raise CostGovernorError("GitHub usage timestamps must be valid ISO-8601") from exc
    if started.tzinfo is None or finished.tzinfo is None:
        raise CostGovernorError("GitHub usage timestamps require timezone")
    elapsed_seconds = (finished.astimezone(timezone.utc) - started.astimezone(timezone.utc)).total_seconds()
    if elapsed_seconds < 0:
        raise CostGovernorError("GitHub usage cannot finish before reservation")
    actual = zero_usage()
    actual.update({
        "github_job_starts": 1,
        "github_runner_minutes": max(1, math.ceil(elapsed_seconds / 60)),
    })
    return actual


def preflight_command(args) -> int:
    at = os.environ.get("PORTFOLIO_COST_NOW") or now_iso()
    run_id = os.environ.get("GITHUB_RUN_ID") or args.run_id or "local-run"
    observed_attempt = int(os.environ.get("GITHUB_RUN_ATTEMPT") or args.attempt)
    state = load_state(args.state)
    attempt = governed_github_attempt(
        state,
        run_id=str(run_id),
        job_id=args.job_id,
        observed_attempt=observed_attempt,
    )
    request = make_github_job_request(
        workflow_id=args.workflow_id,
        job_id=args.job_id,
        run_id=str(run_id),
        attempt=attempt,
        project_ids=args.project_id,
        estimated_minutes=args.estimated_minutes,
        authority_class=args.authority,
        at=at,
    )
    state, decision = preflight(state, request, at=at)
    out = Path(args.output_dir)
    _write_json(out / "cost_state.json", state)
    _write_json(out / "cost_decision.json", decision)
    allowed = decision["status"] in {"RESERVED", "WORKLOAD_ADMITTED"} and decision["can_execute"] is True
    control_plane = "WORKLOAD" if request["resource_kind"] == "GITHUB_JOB" else "PAID_BUDGET"
    reasons = ",".join(decision.get("reason_codes") or [])
    _github_output(
        allowed=str(allowed).lower(),
        reservation_id=decision.get("reservation_id") or "",
        decision_status=decision["status"],
        reason_codes=reasons,
        control_plane=control_plane,
        observed_run_attempt=observed_attempt,
        governed_attempt=attempt,
    )
    print(json.dumps({
        "status": decision["status"],
        "allowed": allowed,
        "reservation_id": decision.get("reservation_id"),
        "reason_codes": decision.get("reason_codes") or [],
        "control_plane": control_plane,
        "observed_run_attempt": observed_attempt,
        "governed_attempt": attempt,
    }, sort_keys=True))
    return 0

def finalize_command(args) -> int:
    at = os.environ.get("PORTFOLIO_COST_NOW") or now_iso()
    state = load_state(args.state)
    decision = json.loads(Path(args.decision).read_text())
    reservation_id = decision.get("reservation_id")
    if reservation_id and decision.get("status") == "RESERVED":
        row = next((r for r in state["reservations"] if r["reservation_id"] == reservation_id), None)
        if row is not None and row["status"] == "RESERVED":
            actual_usage = measured_github_usage(row, at=at)
            state, commit = commit_reservation(
                state,
                reservation_id,
                actual_usage,
                at=at,
                evidence_ref=f"github-run:{os.environ.get('GITHUB_RUN_ID','local-run')}:finalized",
            )
            print(json.dumps({"status": commit["status"], "reservation_id": reservation_id}, sort_keys=True))
    _write_json(Path(args.output), state)
    return 0

def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    pre = sub.add_parser("preflight")
    pre.add_argument("--state", required=True)
    pre.add_argument("--output-dir", required=True)
    pre.add_argument("--workflow-id", required=True)
    pre.add_argument("--job-id", required=True)
    pre.add_argument("--project-id", action="append", required=True)
    pre.add_argument("--estimated-minutes", type=int, required=True)
    pre.add_argument("--authority", choices=["NONE", "OBSERVE", "EXPERIMENT", "MODIFY"], default="OBSERVE")
    pre.add_argument("--run-id", default=None)
    pre.add_argument("--attempt", type=int, default=1)
    pre.set_defaults(func=preflight_command)

    fin = sub.add_parser("finalize")
    fin.add_argument("--state", required=True)
    fin.add_argument("--decision", required=True)
    fin.add_argument("--output", required=True)
    fin.set_defaults(func=finalize_command)

    args = parser.parse_args()
    return args.func(args)

if __name__ == "__main__":
    raise SystemExit(main())
