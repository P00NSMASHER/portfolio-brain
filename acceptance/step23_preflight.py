"""Run a non-counting Step 23 workload preflight on one exact protected main.

Every required workload is invoked through workflow_dispatch, so these runs can
never satisfy the Step 23 event=schedule acceptance requirement. Reducer
catch-ups are interleaved to keep canonical readers fresh, then pending journal
events must drain to zero.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from acceptance.step23_live_collect import pending_event_count

SHA40 = re.compile(r"^[0-9a-f]{40}$")
WORKFLOWS = [
    ("portfolio-state-reducer", "portfolio-state-reducer.yml"),
    ("runtime-hourly-sync", "runtime-hourly-sync.yml"),
    ("portfolio-autonomous-scheduler", "portfolio-autonomous-scheduler.yml"),
    ("hunter-autonomous-cycle", "hunter-autonomous-cycle.yml"),
    ("agent-heartbeat-sweep", "agent-heartbeat-sweep.yml"),
    ("portfolio-cost-watchdog", "portfolio-cost-watchdog.yml"),
    ("portfolio-notification-cycle", "portfolio-notification-cycle.yml"),
    ("command-center-pages", "command-center-pages.yml"),
]
REDUCER_FILE = "portfolio-state-reducer.yml"


def require(ok: bool, message: str) -> None:
    if not ok:
        raise RuntimeError(message)


class API:
    def __init__(self, repo: str, token: str):
        self.repo = repo
        self.token = token
        self.requests = 0

    def request(self, path: str, *, method: str = "GET", body: dict[str, Any] | None = None) -> Any:
        require(path.startswith("/") and ".." not in path and "://" not in path, "PREFLIGHT_UNSAFE_API_PATH")
        self.requests += 1
        require(self.requests <= 1200, "PREFLIGHT_API_BUDGET_EXHAUSTED")
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            f"https://api.github.com/repos/{self.repo}{path}",
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
                "User-Agent": "portfolio-step23-preflight/1.0",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as response:
            raw = response.read(5_000_001)
            status = response.status
        require(len(raw) <= 5_000_000, "PREFLIGHT_PROVIDER_RESPONSE_TOO_LARGE")
        if status == 204 or not raw:
            return None
        return json.loads(raw)

    def main_sha(self) -> str:
        return self.request("/branches/main")["commit"]["sha"]


def workflow_runs(api: API, workflow_file: str) -> list[dict[str, Any]]:
    doc = api.request(f"/actions/workflows/{workflow_file}/runs?event=workflow_dispatch&branch=main&per_page=50")
    rows = doc.get("workflow_runs", [])
    require(isinstance(rows, list), f"PREFLIGHT_RUN_LIST_MALFORMED:{workflow_file}")
    return rows


def dispatch_and_wait(api: API, workflow_name: str, workflow_file: str, exact_sha: str,
                      *, timeout_seconds: int = 1200) -> dict[str, Any]:
    require(api.main_sha() == exact_sha, "PREFLIGHT_MAIN_MOVED")
    before = {row.get("id") for row in workflow_runs(api, workflow_file)}
    api.request(f"/actions/workflows/{workflow_file}/dispatches", method="POST", body={"ref": "main"})
    deadline = time.monotonic() + timeout_seconds
    run_id = None
    while time.monotonic() < deadline:
        require(api.main_sha() == exact_sha, "PREFLIGHT_MAIN_MOVED")
        candidates = [
            row for row in workflow_runs(api, workflow_file)
            if row.get("id") not in before
            and row.get("event") == "workflow_dispatch"
            and row.get("head_branch") == "main"
            and row.get("head_sha") == exact_sha
            and type(row.get("id")) is int
        ]
        if candidates:
            candidates.sort(key=lambda row: row["id"])
            run_id = candidates[0]["id"]
            break
        time.sleep(3)
    require(type(run_id) is int, f"PREFLIGHT_DISPATCH_NOT_OBSERVED:{workflow_name}")

    while time.monotonic() < deadline:
        require(api.main_sha() == exact_sha, "PREFLIGHT_MAIN_MOVED")
        run = api.request(f"/actions/runs/{run_id}")
        if run.get("status") == "completed":
            require(run.get("conclusion") == "success",
                    f"PREFLIGHT_WORKFLOW_FAILED:{workflow_name}:{run_id}:{run.get('conclusion')}")
            require(run.get("head_sha") == exact_sha and run.get("event") == "workflow_dispatch",
                    f"PREFLIGHT_RUN_IDENTITY_DRIFT:{workflow_name}:{run_id}")
            return {
                "workflow": workflow_name,
                "workflow_file": workflow_file,
                "run_id": run_id,
                "event": "workflow_dispatch",
                "head_sha": exact_sha,
                "conclusion": "success",
                "created_at": run.get("created_at"),
                "completed_at": run.get("updated_at"),
            }
        time.sleep(5)
    raise RuntimeError(f"PREFLIGHT_WORKFLOW_TIMEOUT:{workflow_name}:{run_id}")


def wait_pending_zero(token: str, *, timeout_seconds: int = 240) -> int:
    deadline = time.monotonic() + timeout_seconds
    last = -1
    while time.monotonic() < deadline:
        last = pending_event_count(token)
        if last == 0:
            return 0
        time.sleep(8)
    raise RuntimeError(f"PREFLIGHT_PENDING_EVENTS_NOT_DRAINED:{last}")


def run_preflight(repo: str, token: str, exact_sha: str) -> dict[str, Any]:
    require(SHA40.fullmatch(exact_sha) is not None, "PREFLIGHT_EXACT_SHA_INVALID")
    api = API(repo, token)
    require(api.main_sha() == exact_sha, "PREFLIGHT_MAIN_MOVED")
    primary: list[dict[str, Any]] = []
    catchups: list[dict[str, Any]] = []

    # Establish a fresh exact-main canonical snapshot before any consumer runs.
    primary.append(dispatch_and_wait(api, "portfolio-state-reducer", REDUCER_FILE, exact_sha))

    for workflow_name, workflow_file in WORKFLOWS[1:]:
        primary.append(dispatch_and_wait(api, workflow_name, workflow_file, exact_sha))
        # Every producer may publish a journal event. Catch it up immediately so
        # the next canonical reader is testing freshness, not a known backlog.
        catchups.append(dispatch_and_wait(api, "portfolio-state-reducer", REDUCER_FILE, exact_sha))

    require({row["workflow"] for row in primary} == {name for name, _ in WORKFLOWS},
            "PREFLIGHT_REQUIRED_WORKFLOW_COVERAGE_INCOMPLETE")
    pending = wait_pending_zero(token)
    require(api.main_sha() == exact_sha, "PREFLIGHT_MAIN_MOVED")
    return {
        "schema_version": "1.0.0",
        "status": "PASS",
        "exact_main_sha": exact_sha,
        "acceptance_credit": False,
        "run_event_required": "workflow_dispatch",
        "required_workflow_runs": primary,
        "reducer_catchup_runs": catchups,
        "pending_events_final": pending,
        "api_requests": api.requests,
        "completed_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exact-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    token = os.environ.get("GITHUB_TOKEN", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    require(bool(token) and bool(repo), "PREFLIGHT_GITHUB_CONTEXT_REQUIRED")
    result = run_preflight(repo, token, args.exact_sha)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
