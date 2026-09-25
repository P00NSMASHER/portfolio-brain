#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import urllib.request
from pathlib import Path

from cost_governor.cost_governor import hard_stop_reason, load_state, policy

def managed_run_ids(runs, *, current_run_id: str | None, managed_names: set[str], limit: int) -> list[int]:
    out = []
    for run in runs:
        if str(run.get("id")) == str(current_run_id):
            continue
        if run.get("status") not in {"queued", "in_progress"}:
            continue
        if run.get("name") not in managed_names:
            continue
        out.append(int(run["id"]))
        if len(out) >= limit:
            break
    return out

def _request(url: str, token: str, *, method: str = "GET") -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "portfolio-brain-cost-watchdog/1.0",
        },
        method=method,
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        return response.read()

def cancel_if_needed(state) -> dict:
    p = policy()
    reason = hard_stop_reason(state)
    if reason is None:
        return {"status": "NO_HARD_STOP", "cancelled_run_ids": [], "reason": None}
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    current = os.environ.get("GITHUB_RUN_ID")
    if not token or not repo:
        return {"status": "HARD_STOP_NO_ACTIONS_CONTEXT", "cancelled_run_ids": [], "reason": reason}
    body = _request(f"https://api.github.com/repos/{repo}/actions/runs?per_page=100", token)
    runs = json.loads(body.decode()).get("workflow_runs", [])
    ids = managed_run_ids(
        runs,
        current_run_id=current,
        managed_names=set(p["managed_workflow_names"]),
        limit=p["max_cancellations_per_cycle"],
    )
    cancelled = []
    for run_id in ids:
        _request(f"https://api.github.com/repos/{repo}/actions/runs/{run_id}/cancel", token, method="POST")
        cancelled.append(run_id)
    return {"status": "HARD_STOP_ENFORCED", "cancelled_run_ids": cancelled, "reason": reason}

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", default="cost_governor/live/cost_state.json")
    args = parser.parse_args()
    result = cancel_if_needed(load_state(args.state))
    print(json.dumps(result, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
