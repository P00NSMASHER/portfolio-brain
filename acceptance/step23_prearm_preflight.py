"""Run a non-counting exact-main preflight of all eight Step 23 workloads."""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import re

from acceptance.step23_live_collect import pending_event_count

TARGETS = [
    ("portfolio-state-reducer", "portfolio-state-reducer.yml"),
    ("runtime-hourly-sync", "runtime-hourly-sync.yml"),
    ("portfolio-autonomous-scheduler", "portfolio-autonomous-scheduler.yml"),
    ("hunter-autonomous-cycle", "hunter-autonomous-cycle.yml"),
    ("agent-heartbeat-sweep", "agent-heartbeat-sweep.yml"),
    ("portfolio-cost-watchdog", "portfolio-cost-watchdog.yml"),
    ("portfolio-notification-cycle", "portfolio-notification-cycle.yml"),
    ("command-center-pages", "command-center-pages.yml"),
]
REDUCER = ("portfolio-state-reducer", "portfolio-state-reducer.yml")
LIVE_BARRIER_TARGETS = {"runtime-hourly-sync", "portfolio-autonomous-scheduler", "hunter-autonomous-cycle", "agent-heartbeat-sweep", "portfolio-notification-cycle", "command-center-pages"}
CORRELATION = re.compile(r"^prearm-[0-9]+-[a-z0-9-]+$")


def req(ok: bool, message: str) -> None:
    if not ok:
        raise RuntimeError(message)


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class API:
    def __init__(self, repo: str, token: str):
        self.repo = repo
        self.token = token
        self.requests = 0

    def request(self, path: str, *, method: str = "GET", payload: dict[str, Any] | None = None) -> tuple[int, bytes]:
        req(path.startswith("/") and "://" not in path and ".." not in path, "unsafe GitHub API path")
        self.requests += 1
        req(self.requests <= 1200, "pre-arm preflight API budget exhausted")
        body = None if payload is None else json.dumps(payload).encode()
        request = urllib.request.Request(
            "https://api.github.com/repos/" + self.repo + path,
            data=body,
            method=method,
            headers={
                "Authorization": "Bearer " + self.token,
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
                "User-Agent": "portfolio-step23-prearm-preflight/1.0",
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read(5_000_001)
            status = response.status
        req(len(raw) <= 5_000_000, "provider response too large")
        return status, raw

    def get(self, path: str) -> Any:
        status, raw = self.request(path)
        req(status == 200, f"unexpected GitHub GET status {status}")
        return json.loads(raw)

    def post(self, path: str, payload: dict[str, Any]) -> None:
        status, _ = self.request(path, method="POST", payload=payload)
        req(status == 204, f"unexpected GitHub dispatch status {status}")


def assert_main(api: API, exact_sha: str) -> None:
    observed = api.get("/branches/main").get("commit", {}).get("sha")
    req(observed == exact_sha, f"PREARM_MAIN_MOVED expected={exact_sha} observed={observed}")



# Producer workflows are already serialized by the shared
# portfolio-state-writer-v1 job concurrency group. The canonical reducer runs
# in an independent lane so it can catch up while producers are queued or
# waiting on stale canonical state. A repository-wide "all writers idle" gate
# therefore creates a deadlock-prone condition without adding safety.

def wait_for_correlated_run(
    api: API,
    *,
    filename: str,
    exact_sha: str,
    correlation: str,
    discovery_timeout: int = 180,
    queue_timeout: int = 1800,
    execution_timeout: int = 1800,
    on_started: Any = None,
) -> dict[str, Any]:
    encoded = urllib.parse.quote(filename, safe="")
    deadline = time.monotonic() + discovery_timeout
    selected = None
    while time.monotonic() < deadline:
        runs = api.get(
            f"/actions/workflows/{encoded}/runs?event=workflow_dispatch&branch=main&per_page=50"
        ).get("workflow_runs", [])
        req(isinstance(runs, list), "workflow run listing malformed")
        matches = [
            row for row in runs
            if row.get("event") == "workflow_dispatch"
            and row.get("head_branch") == "main"
            and row.get("head_sha") == exact_sha
            and row.get("display_title") == correlation
            and type(row.get("id")) is int
        ]
        if len(matches) == 1:
            selected = matches[0]
            break
        req(len(matches) <= 1, f"ambiguous correlated pre-arm run for {filename}")
        time.sleep(3)
    req(selected is not None, f"timed out locating correlated pre-arm run for {filename}")

    run_id = int(selected["id"])
    queue_deadline = time.monotonic() + queue_timeout
    execution_deadline = None
    started_barrier_ran = False
    while True:
        now = time.monotonic()
        row = api.get(f"/actions/runs/{run_id}")
        status = row.get("status")
        if status == "in_progress":
            if execution_deadline is None:
                execution_deadline = now + execution_timeout
            if on_started is not None and not started_barrier_ran:
                on_started(run_id)
                started_barrier_ran = True
                row = api.get(f"/actions/runs/{run_id}")
                status = row.get("status")
        if status == "completed":
            req(row.get("conclusion") == "success",
                f"{filename} pre-arm run {run_id} concluded {row.get('conclusion')}")
            req(row.get("head_sha") == exact_sha and row.get("event") == "workflow_dispatch",
                f"{filename} pre-arm run identity drifted")
            return row
        if execution_deadline is None:
            if now >= queue_deadline:
                raise RuntimeError(f"timed out waiting for {filename} pre-arm run {run_id} to start")
        elif now >= execution_deadline:
            raise RuntimeError(f"timed out waiting for {filename} pre-arm run {run_id} to complete")
        time.sleep(5)


def dispatch(
    api: API,
    *,
    workflow: str,
    filename: str,
    exact_sha: str,
    correlation: str,
    on_started: Any = None,
) -> dict[str, Any]:
    req(CORRELATION.fullmatch(correlation) is not None, "unsafe pre-arm correlation id")
    assert_main(api, exact_sha)
    encoded = urllib.parse.quote(filename, safe="")
    payload = {"ref": "main", "inputs": {"prearm_id": correlation}}
    transient_statuses: list[int] = []
    row = None
    expected_timeout = f"timed out locating correlated pre-arm run for {filename}"

    for attempt in range(2):
        try:
            api.post(f"/actions/workflows/{encoded}/dispatches", payload)
        except urllib.error.HTTPError as exc:
            if exc.code not in {500, 502, 503, 504}:
                raise
            transient_statuses.append(exc.code)
            try:
                row = wait_for_correlated_run(
                    api,
                    filename=filename,
                    exact_sha=exact_sha,
                    correlation=correlation,
                    discovery_timeout=60 if attempt == 0 else 120,
                    on_started=on_started,
                )
            except RuntimeError as recovery:
                if str(recovery) != expected_timeout:
                    raise
                if attempt == 1:
                    raise RuntimeError(
                        f"transient GitHub dispatch remained unresolved for {filename}"
                    ) from recovery
                continue
            break
        else:
            row = wait_for_correlated_run(
                api,
                filename=filename,
                exact_sha=exact_sha,
                correlation=correlation,
                on_started=on_started,
            )
            break

    req(row is not None, f"pre-arm dispatch produced no run for {filename}")
    assert_main(api, exact_sha)
    return {
        "workflow": workflow,
        "filename": filename,
        "run_id": row["id"],
        "event": row["event"],
        "head_sha": row["head_sha"],
        "conclusion": row["conclusion"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "correlation": correlation,
        "dispatch_transient_http_statuses": transient_statuses,
        "acceptance_credit": False,
    }


def drain(
    api: API,
    *,
    exact_sha: str,
    prefix: str,
    github_token: str,
    correlation_seed: str,
    drains: list[dict[str, Any]],
    max_rounds: int = 4,
) -> int:
    req(correlation_seed.isdigit(), "pre-arm correlation seed must be numeric")
    if pending_event_count(github_token) == 0:
        return 0
    for round_number in range(1, max_rounds + 1):
        correlation = f"prearm-{correlation_seed}-{prefix}-drain-{round_number}"
        drains.append(dispatch(
            api,
            workflow=REDUCER[0],
            filename=REDUCER[1],
            exact_sha=exact_sha,
            correlation=correlation,
        ))
        pending = pending_event_count(github_token)
        if pending == 0:
            return 0
    raise RuntimeError(f"canonical pending events did not drain after {max_rounds} reducer rounds")


def force_started_reducer_barrier(
    api: API,
    *,
    exact_sha: str,
    prefix: str,
    github_token: str,
    correlation_seed: str,
    drains: list[dict[str, Any]],
) -> None:
    """Run one reducer after the target has acquired the writer lane.

    Hunter and command-center can sit queued long enough for state to become
    stale after the orchestrator's ordinary pre-drain. Once either target is
    in_progress it owns the serialized writer lane, so no producer can race a
    fresh reducer snapshot before its canonical reads.
    """
    req(correlation_seed.isdigit(), "pre-arm correlation seed must be numeric")
    correlation = f"prearm-{correlation_seed}-{prefix}-livebarrier"
    drains.append(dispatch(
        api,
        workflow=REDUCER[0],
        filename=REDUCER[1],
        exact_sha=exact_sha,
        correlation=correlation,
    ))
    pending = pending_event_count(github_token)
    req(pending == 0, f"started reducer barrier left {pending} pending events")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exact-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    repo = os.environ.get("GITHUB_REPOSITORY", "")
    token = os.environ.get("GITHUB_TOKEN", "")
    orchestrator = os.environ.get("GITHUB_RUN_ID", "local")
    req(repo and token, "GitHub context required for pre-arm preflight")
    req(len(args.exact_sha) == 40, "exact main SHA malformed")

    api = API(repo, token)
    assert_main(api, args.exact_sha)
    target_runs: list[dict[str, Any]] = []
    reducer_drains: list[dict[str, Any]] = []

    # Establish a clean canonical baseline before any non-counting producer run.
    # Normal background producers may remain queued/running in their shared
    # serialized writer lane; the reducer's independent lane is the safety
    # barrier, not repository-wide silence.
    drain(
        api, exact_sha=args.exact_sha, prefix="initial", github_token=token,
        correlation_seed=orchestrator, drains=reducer_drains
    )

    for index, (workflow, filename) in enumerate(TARGETS, start=1):
        # Re-drain immediately before each target. This preserves a fresh
        # canonical boundary without requiring unrelated background writers to
        # become globally idle.
        drain(
            api,
            exact_sha=args.exact_sha,
            prefix=f"{index}-{workflow}-predrain",
            github_token=token,
            correlation_seed=orchestrator,
            drains=reducer_drains,
        )
        correlation = f"prearm-{orchestrator}-{index}-{workflow}"
        on_started = None
        if workflow in LIVE_BARRIER_TARGETS:
            def on_started(_run_id: int, *, _index=index, _workflow=workflow) -> None:
                force_started_reducer_barrier(
                    api,
                    exact_sha=args.exact_sha,
                    prefix=f"{_index}-{_workflow}",
                    github_token=token,
                    correlation_seed=orchestrator,
                    drains=reducer_drains,
                )
        target_runs.append(dispatch(
            api,
            workflow=workflow,
            filename=filename,
            exact_sha=args.exact_sha,
            correlation=correlation,
            on_started=on_started,
        ))
        # Every producer may publish an immutable event. Reduce it before the
        # next consumer so stale-state waits cannot cascade through preflight.
        drain(
            api,
            exact_sha=args.exact_sha,
            prefix=f"{index}-{workflow}",
            github_token=token,
            correlation_seed=orchestrator,
            drains=reducer_drains,
        )

    pending_final = pending_event_count(token)
    req(pending_final == 0, f"pre-arm ended with {pending_final} pending events")
    assert_main(api, args.exact_sha)

    result = {
        "schema_version": "1.0.0",
        "status": "PASS",
        "exact_main_sha": args.exact_sha,
        "generated_at": iso_now(),
        "acceptance_credit": False,
        "target_runs": target_runs,
        "reducer_drains": reducer_drains,
        "pending_events_final": pending_final,
        "api_requests": api.requests,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
