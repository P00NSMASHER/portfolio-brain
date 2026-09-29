"""Bounded Step-2 live-shadow workflow dispatcher and verifier."""
from __future__ import annotations
import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPOSITORY = "P00NSMASHER/portfolio-brain"
TARGETS = (
    "hunter-autonomous-cycle.yml",
    "portfolio-autonomous-scheduler.yml",
    "runtime-hourly-sync.yml",
    "agent-heartbeat-sweep.yml",
)


class SmokeError(RuntimeError):
    pass


def request(token: str, method: str, suffix: str, payload: dict | None = None):
    if not suffix.startswith("/") or ".." in suffix or "://" in suffix:
        raise SmokeError("unsafe GitHub API suffix")
    body = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPOSITORY}{suffix}", data=body, method=method,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2026-03-10", "User-Agent": "portfolio-step2-smoke"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            raw = response.read()
    except Exception as exc:
        raise SmokeError(f"GitHub API request failed: {method} {suffix}") from exc
    return None if not raw else json.loads(raw.decode("utf-8"))


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def dispatch_and_wait(token: str, workflow: str) -> dict:
    started = datetime.now(timezone.utc) - timedelta(seconds=5)
    expected_sha = os.environ.get("GITHUB_SHA", "")
    request(token, "POST", f"/actions/workflows/{urllib.parse.quote(workflow, safe='')}/dispatches", {"ref": "main"})
    run = None
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        data = request(token, "GET", f"/actions/workflows/{urllib.parse.quote(workflow, safe='')}/runs?branch=main&event=workflow_dispatch&per_page=10")
        candidates = [
            row for row in data.get("workflow_runs", [])
            if row.get("event") == "workflow_dispatch"
            and row.get("head_branch") == "main"
            and row.get("head_sha") == expected_sha
            and parse_time(row["created_at"]) >= started
        ]
        if candidates:
            run = max(candidates, key=lambda row: row["id"])
            if run.get("status") == "completed":
                break
        time.sleep(3)
    if run is None:
        raise SmokeError(f"No dispatched run appeared for {workflow}")
    if run.get("status") != "completed":
        raise SmokeError(f"Timed out waiting for {workflow} run {run['id']}")
    if run.get("conclusion") != "success":
        raise SmokeError(f"{workflow} run {run['id']} concluded {run.get('conclusion')}")
    return {
        "workflow": workflow,
        "run_id": run["id"],
        "head_sha": run.get("head_sha"),
        "conclusion": run.get("conclusion"),
        "created_at": run.get("created_at"),
        "updated_at": run.get("updated_at"),
    }


def main() -> None:
    if os.environ.get("GITHUB_REF") != "refs/heads/main":
        raise SmokeError("Smoke proof runs only on main")
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        raise SmokeError("GITHUB_TOKEN required")
    rows = []
    for workflow in TARGETS:
        rows.append(dispatch_and_wait(token, workflow))
    receipt = {
        "status": "PASS",
        "mode": "STEP_2_LIVE_SHADOW_SMOKE",
        "runs": rows,
        "steps_3_to_8_started": False,
    }
    out = Path("state_journal/out/smoke")
    out.mkdir(parents=True, exist_ok=True)
    (out / "receipt.json").write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n")
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
