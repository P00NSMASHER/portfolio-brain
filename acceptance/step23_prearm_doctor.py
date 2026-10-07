"""Fail-closed Step 23 pre-arm doctor.

Static mode validates the acceptance/configuration contract. Strict mode adds
live GitHub and canonical-journal checks that must pass before Step 23 is armed.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from operations.validate_operating_mode import workflow_schedule_crons
from acceptance.step23_live_collect import pending_event_count

ROOT = Path(__file__).resolve().parents[1]
SHA40 = re.compile(r"^[0-9a-f]{40}$")
REQUIRED = {
    "portfolio-state-reducer",
    "runtime-hourly-sync",
    "portfolio-autonomous-scheduler",
    "hunter-autonomous-cycle",
    "agent-heartbeat-sweep",
    "portfolio-cost-watchdog",
    "portfolio-notification-cycle",
    "command-center-pages",
}


def require(ok: bool, message: str) -> None:
    if not ok:
        raise RuntimeError(message)


def load(path: str) -> dict[str, Any]:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def parse_time(value: object) -> datetime:
    require(isinstance(value, str), "STEP23_DOCTOR_TIMESTAMP_MISSING")
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(dt.tzinfo is not None, "STEP23_DOCTOR_TIMESTAMP_NAIVE")
    return dt.astimezone(timezone.utc)


def static_checks() -> dict[str, Any]:
    policy = load("acceptance/FINAL_ACCEPTANCE_POLICY.json")["step23"]
    window = load("operations/STEP23_DELIVERY_WINDOW.json")
    control = load("operations/STEP23_CONTROL.json")

    require(set(policy["required_workflows"]) == REQUIRED, "STEP23_DOCTOR_WORKFLOW_POLICY_DRIFT")
    require(set(window["temporary_crons"]) == REQUIRED, "STEP23_DOCTOR_TEMP_CRON_INVENTORY_DRIFT")
    require(policy["max_soak_duration_seconds"] == 7200, "STEP23_DOCTOR_SOAK_NOT_TWO_HOURS")
    require(policy["min_successful_scheduled_cycles_per_workflow"] == 2,
            "STEP23_DOCTOR_SUCCESS_MINIMUM_NOT_TWO")
    require(window["max_soak_duration_seconds"] == policy["max_soak_duration_seconds"],
            "STEP23_DOCTOR_WINDOW_DURATION_DRIFT")
    require(control["max_soak_duration_seconds"] == policy["max_soak_duration_seconds"],
            "STEP23_DOCTOR_CONTROL_DURATION_DRIFT")
    require(window["required_successes_per_workflow"] == policy["min_successful_scheduled_cycles_per_workflow"],
            "STEP23_DOCTOR_WINDOW_SUCCESS_DRIFT")
    require(control["required_successes_per_workflow"] == policy["min_successful_scheduled_cycles_per_workflow"],
            "STEP23_DOCTOR_CONTROL_SUCCESS_DRIFT")

    workflow_dir = ROOT / ".github" / "workflows"
    schedules: dict[str, list[str]] = {}
    for name in sorted(REQUIRED):
        crons = workflow_schedule_crons(workflow_dir / f"{name}.yml")
        require(isinstance(crons, list) and crons, f"STEP23_DOCTOR_SCHEDULE_MISSING:{name}")
        expected_temp = window["temporary_crons"][name]
        require(all(cron in crons for cron in expected_temp), f"STEP23_DOCTOR_TEMP_CRON_NOT_REGISTERED:{name}")
        schedules[name] = crons

    observer = (workflow_dir / "step23-live-soak-observer.yml").read_text(encoding="utf-8")
    require('policy["max_soak_duration_seconds"]' in observer,
            "STEP23_DOCTOR_OBSERVER_DURATION_NOT_POLICY_BOUND")
    require('policy["min_successful_scheduled_cycles_per_workflow"]' in observer,
            "STEP23_DOCTOR_OBSERVER_SUCCESS_NOT_POLICY_BOUND")

    return {
        "status": "STATIC_PASS",
        "duration_seconds": policy["max_soak_duration_seconds"],
        "required_successes_per_workflow": policy["min_successful_scheduled_cycles_per_workflow"],
        "required_workflows": sorted(REQUIRED),
        "schedules": schedules,
        "control_status": control.get("status"),
    }


class API:
    def __init__(self, repo: str, token: str):
        self.repo = repo
        self.token = token
        self.requests = 0

    def get(self, path: str) -> Any:
        require(path.startswith("/") and ".." not in path and "://" not in path, "STEP23_DOCTOR_UNSAFE_API_PATH")
        self.requests += 1
        require(self.requests <= 30, "STEP23_DOCTOR_API_BUDGET_EXHAUSTED")
        req = urllib.request.Request(
            f"https://api.github.com/repos/{self.repo}{path}",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "portfolio-step23-prearm-doctor/1.0",
            },
        )
        with urllib.request.urlopen(req, timeout=20) as response:
            raw = response.read(5_000_001)
        require(len(raw) <= 5_000_000, "STEP23_DOCTOR_PROVIDER_RESPONSE_TOO_LARGE")
        return json.loads(raw)


def strict_arm_checks(exact_sha: str, now: datetime | None = None) -> dict[str, Any]:
    static = static_checks()
    require(SHA40.fullmatch(exact_sha) is not None, "STEP23_DOCTOR_EXACT_SHA_INVALID")
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    control = load("operations/STEP23_CONTROL.json")
    window = load("operations/STEP23_DELIVERY_WINDOW.json")

    require(control.get("status") in {"PREQUALIFYING", "ARMED_FIXED"}, "STEP23_DOCTOR_NOT_ARMABLE")
    horizon_start = parse_time(control.get("qualification_horizon_start"))
    horizon_end = parse_time(control.get("qualification_horizon_end"))
    require(horizon_end > horizon_start and horizon_end > now, "STEP23_DOCTOR_HORIZON_EXPIRED")
    require(parse_time(window.get("qualification_horizon_start")) == horizon_start
            and parse_time(window.get("qualification_horizon_end")) == horizon_end,
            "STEP23_DOCTOR_HORIZON_CONFIG_DRIFT")

    token = os.environ.get("GITHUB_TOKEN", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    require(bool(token) and bool(repo), "STEP23_DOCTOR_GITHUB_CONTEXT_REQUIRED")
    api = API(repo, token)

    main = api.get("/branches/main")
    require(main.get("commit", {}).get("sha") == exact_sha, "STEP23_DOCTOR_MAIN_MOVED")

    pulls = api.get("/pulls?state=open&per_page=100")
    checkpoint = [
        row for row in pulls
        if str((row.get("head") or {}).get("ref", "")).startswith("factory/checkpoint-archive-")
    ]
    require(not checkpoint, "STEP23_DOCTOR_CHECKPOINT_CANDIDATE_OPEN")

    reducers = api.get("/actions/workflows/portfolio-state-reducer.yml/runs?branch=main&status=success&per_page=20")
    reducer_runs = reducers.get("workflow_runs", [])
    require(isinstance(reducer_runs, list) and reducer_runs, "STEP23_DOCTOR_CANONICAL_REDUCER_MISSING")
    snapshot_found = False
    for run in reducer_runs:
        if run.get("head_sha") != exact_sha:
            continue
        arts = api.get(f"/actions/runs/{run['id']}/artifacts?per_page=100")
        if any(a.get("name") == "portfolio-canonical-shadow-state" and a.get("expired") is False
               for a in arts.get("artifacts", [])):
            snapshot_found = True
            break
    require(snapshot_found, "STEP23_DOCTOR_EXACT_MAIN_CANONICAL_SNAPSHOT_MISSING")

    pending = pending_event_count(token)
    require(pending == 0, f"STEP23_DOCTOR_PENDING_EVENTS:{pending}")
    require(api.get("/branches/main").get("commit", {}).get("sha") == exact_sha, "STEP23_DOCTOR_MAIN_MOVED")

    return {
        **static,
        "status": "PASS",
        "exact_main_sha": exact_sha,
        "qualification_horizon_start": horizon_start.isoformat().replace("+00:00", "Z"),
        "qualification_horizon_end": horizon_end.isoformat().replace("+00:00", "Z"),
        "checkpoint_candidates": 0,
        "pending_events": 0,
        "canonical_snapshot_exact_main": True,
        "api_requests": api.requests,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exact-sha")
    parser.add_argument("--static-only", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = static_checks() if args.static_only else strict_arm_checks(args.exact_sha or "")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
