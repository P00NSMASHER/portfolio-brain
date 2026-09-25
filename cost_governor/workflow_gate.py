#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from cost_governor.cost_governor import (
    commit_reservation,
    load_state,
    make_github_job_request,
    now_iso,
    preflight,
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

def preflight_command(args) -> int:
    at = os.environ.get("PORTFOLIO_COST_NOW") or now_iso()
    run_id = os.environ.get("GITHUB_RUN_ID") or args.run_id or "local-run"
    attempt = int(os.environ.get("GITHUB_RUN_ATTEMPT") or args.attempt)
    state = load_state(args.state)
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
    allowed = decision["status"] == "RESERVED" and decision["can_execute"] is True
    _github_output(
        allowed=str(allowed).lower(),
        reservation_id=decision.get("reservation_id") or "",
        decision_status=decision["status"],
    )
    print(json.dumps({
        "status": decision["status"],
        "allowed": allowed,
        "reservation_id": decision.get("reservation_id"),
    }, sort_keys=True))
    return 0

def finalize_command(args) -> int:
    state = load_state(args.state)
    decision = json.loads(Path(args.decision).read_text())
    reservation_id = decision.get("reservation_id")
    if reservation_id and decision.get("status") == "RESERVED":
        row = next((r for r in state["reservations"] if r["reservation_id"] == reservation_id), None)
        if row is not None and row["status"] == "RESERVED":
            state, commit = commit_reservation(
                state,
                reservation_id,
                row["estimated_usage"],
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
