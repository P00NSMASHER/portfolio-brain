"""Fail-closed Step 23 pre-arm validation.

This module has two modes:
- static: validate the repository contract without network access.
- live: repeat static validation, verify GitHub workflow registration on exact
  protected main, require no active checkpoint recovery PR, and require a
  canonical snapshot with zero unresolved journal events.

It never arms Step 23 and never counts workflow_dispatch runs as soak evidence.
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from operations.validate_operating_mode import scheduled_workflow_inventory, workflow_top_level_triggers
from acceptance.step23_live_collect import pending_event_count

ROOT = Path(__file__).resolve().parents[1]
SOAK_SECONDS = 7200
REQUIRED = {
    "portfolio-state-reducer": ("portfolio-state-reducer.yml", "11 4 * * *"),
    "runtime-hourly-sync": ("runtime-hourly-sync.yml", "17 * * * *"),
    "portfolio-autonomous-scheduler": ("portfolio-autonomous-scheduler.yml", "23 * * * *"),
    "hunter-autonomous-cycle": ("hunter-autonomous-cycle.yml", "47 */6 * * *"),
    "agent-heartbeat-sweep": ("agent-heartbeat-sweep.yml", "29 */2 * * *"),
    "portfolio-cost-watchdog": ("portfolio-cost-watchdog.yml", "53 * * * *"),
    "portfolio-notification-cycle": ("portfolio-notification-cycle.yml", "7 */6 * * *"),
    "command-center-pages": ("command-center-pages.yml", "37 * * * *"),
}
DELIVERY = ("portfolio-schedule-delivery", "portfolio-schedule-delivery.yml", "7,17,27,37,47,57 * * * *")


def req(ok: bool, message: str) -> None:
    if not ok:
        raise RuntimeError(message)


def load(path: str) -> Any:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def parse_time(value: Any, field: str) -> datetime:
    req(isinstance(value, str) and value, field + " missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RuntimeError(field + " invalid") from exc
    req(parsed.tzinfo is not None, field + " must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def validate_static(*, phase: str, now: datetime | None = None) -> dict[str, Any]:
    req(phase in {"prearm", "armed"}, "unsupported Step 23 doctor phase")
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    final = load("acceptance/FINAL_ACCEPTANCE_POLICY.json")["step23"]
    window = load("operations/STEP23_DELIVERY_WINDOW.json")
    control = load("operations/STEP23_CONTROL.json")
    delivery = load("operations/SCHEDULE_DELIVERY_POLICY.json")

    required_names = set(REQUIRED)
    req(set(final["required_workflows"]) == required_names, "Step 23 final required workflow set drifted")
    req(final["max_soak_duration_seconds"] == SOAK_SECONDS, "final Step 23 duration is not two hours")
    req(window["max_soak_duration_seconds"] == SOAK_SECONDS, "delivery-window Step 23 duration drifted")
    req(control["max_soak_duration_seconds"] == SOAK_SECONDS, "control Step 23 duration drifted")
    req(window["required_successes_per_workflow"] == final["min_successful_scheduled_cycles_per_workflow"],
        "Step 23 success-count contract drifted")
    req(set(window["temporary_crons"]) == required_names, "temporary-cron workflow inventory drifted")

    workflow_dir = ROOT / ".github" / "workflows"
    actual = scheduled_workflow_inventory(workflow_dir)
    delivery_name, delivery_file, delivery_cron = DELIVERY
    req(delivery["workflow"] == delivery_name and delivery["cron"] == delivery_cron,
        "schedule-delivery policy drifted")
    req(actual.get(delivery_name) == [delivery_cron], "schedule-delivery cron drifted")

    for name, (filename, steady_cron) in REQUIRED.items():
        triggers = workflow_top_level_triggers(workflow_dir / filename)
        req("schedule" in triggers and "workflow_dispatch" in triggers,
            f"{name} must retain schedule and workflow_dispatch triggers")
        temp = window["temporary_crons"][name]
        req(isinstance(temp, list), f"{name} temporary crons malformed")
        expected = [steady_cron, *temp]
        req(actual.get(name) == expected, f"{name} schedule inventory mismatch: {actual.get(name)} != {expected}")

    delivery_triggers = workflow_top_level_triggers(workflow_dir / delivery_file)
    req({"schedule", "workflow_run"} <= delivery_triggers,
        "schedule-delivery lost native schedule/workflow_run path")
    delivery_text = (workflow_dir / delivery_file).read_text(encoding="utf-8")
    req("python -m operations.schedule_clock" in delivery_text,
        "schedule-delivery lost redundant clock conversion path")
    req("portfolio-schedule-clock-" in delivery_text,
        "schedule-delivery lost immutable clock receipt")

    if phase == "prearm":
        req(window["status"] == "PREARM_READY" and control["status"] == "PREARM_READY",
            "Step 23 is not cleanly in PREARM_READY state")
        req(window["qualification_horizon_start"] is None and window["qualification_horizon_end"] is None,
            "pre-arm window carries a stale qualification horizon")
        req(control["qualification_horizon_start"] is None and control["qualification_horizon_end"] is None,
            "pre-arm control carries a stale qualification horizon")
        req(control["next_soak_start"] is None, "pre-arm control already carries a soak start")
        req(all(crons == [] for crons in window["temporary_crons"].values()),
            "expired/temporary Step 23 crons remain before re-arm")
    else:
        req(window["status"] in {"PREQUALIFYING", "ARMED_FIXED"} and control["status"] == window["status"],
            "armed Step 23 control/window status mismatch")
        start = parse_time(window["qualification_horizon_start"], "qualification_horizon_start")
        end = parse_time(window["qualification_horizon_end"], "qualification_horizon_end")
        req(end > start, "qualification horizon is empty")
        req(end > now, "qualification horizon is not in the future")
        req((end - start).total_seconds() >= SOAK_SECONDS,
            "qualification horizon cannot contain a full two-hour soak")
        req(any(window["temporary_crons"][name] for name in REQUIRED),
            "armed Step 23 has no temporary scheduled evidence wave")

    return {
        "phase": phase,
        "duration_seconds": SOAK_SECONDS,
        "required_successes_per_workflow": final["min_successful_scheduled_cycles_per_workflow"],
        "required_workflows": sorted(required_names),
        "schedule_delivery_cron": delivery_cron,
        "static_contract": "PASS",
    }


class API:
    def __init__(self, repo: str, token: str):
        self.repo = repo
        self.token = token
        self.requests = 0

    def get(self, path: str) -> Any:
        req(path.startswith("/") and "://" not in path and ".." not in path, "unsafe GitHub API path")
        self.requests += 1
        req(self.requests <= 60, "pre-arm doctor API budget exhausted")
        request = urllib.request.Request(
            "https://api.github.com/repos/" + self.repo + path,
            headers={
                "Authorization": "Bearer " + self.token,
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "portfolio-step23-prearm-doctor/1.0",
            },
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read(5_000_001)
        req(len(raw) <= 5_000_000, "pre-arm doctor provider response too large")
        return json.loads(raw)


def validate_live(*, exact_sha: str, phase: str) -> dict[str, Any]:
    result = validate_static(phase=phase)
    req(len(exact_sha) == 40 and all(ch in "0123456789abcdef" for ch in exact_sha),
        "exact main SHA malformed")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    token = os.environ.get("GITHUB_TOKEN", "")
    req(repo and token, "GitHub context required for live pre-arm doctor")
    api = API(repo, token)

    branch = api.get("/branches/main")
    req(branch.get("commit", {}).get("sha") == exact_sha, "protected main moved during pre-arm doctor")

    registrations = {}
    for name, (filename, _cron) in REQUIRED.items():
        encoded = urllib.parse.quote(filename, safe="")
        doc = api.get("/actions/workflows/" + encoded)
        req(doc.get("name") == name, f"{name} provider workflow name mismatch")
        req(doc.get("path") == ".github/workflows/" + filename, f"{name} provider workflow path mismatch")
        req(doc.get("state") == "active", f"{name} workflow registration is not active")
        runs = api.get("/actions/workflows/" + encoded + "/runs?event=schedule&per_page=5").get("workflow_runs", [])
        req(isinstance(runs, list) and runs, f"{name} has no native schedule delivery evidence")
        native = next((row for row in runs if row.get("event") == "schedule" and row.get("head_branch") == "main"), None)
        req(native is not None, f"{name} lacks a genuine main schedule run")
        registrations[name] = {
            "workflow_id": doc.get("id"),
            "state": doc.get("state"),
            "latest_native_schedule_run_id": native.get("id"),
            "latest_native_schedule_conclusion": native.get("conclusion"),
            "latest_native_schedule_created_at": native.get("created_at"),
        }

    delivery_name, delivery_file, _ = DELIVERY
    encoded = urllib.parse.quote(delivery_file, safe="")
    doc = api.get("/actions/workflows/" + encoded)
    req(doc.get("name") == delivery_name and doc.get("state") == "active",
        "schedule-delivery workflow registration is not active")
    delivery_runs = api.get("/actions/workflows/" + encoded + "/runs?event=schedule&per_page=5").get("workflow_runs", [])
    native_delivery = next((row for row in delivery_runs
                            if row.get("event") == "schedule" and row.get("head_branch") == "main"), None)
    req(native_delivery is not None, "schedule-delivery lacks genuine native schedule evidence")

    pulls = api.get("/pulls?state=open&per_page=100")
    checkpoint_candidates = [
        row for row in pulls
        if str((row.get("head") or {}).get("ref", "")).startswith("factory/checkpoint-archive-")
    ]
    req(not checkpoint_candidates, "active checkpoint recovery candidate blocks Step 23 pre-arm")

    pending = pending_event_count(token)
    req(pending == 0, f"canonical journal has {pending} unresolved pending events")

    req(api.get("/branches/main").get("commit", {}).get("sha") == exact_sha,
        "protected main moved during pre-arm doctor")
    result.update({
        "exact_main_sha": exact_sha,
        "live_contract": "PASS",
        "pending_events": pending,
        "checkpoint_candidates": 0,
        "registrations": registrations,
        "schedule_delivery": {
            "workflow_id": doc.get("id"),
            "state": doc.get("state"),
            "latest_native_schedule_run_id": native_delivery.get("id"),
            "latest_native_schedule_conclusion": native_delivery.get("conclusion"),
            "latest_native_schedule_created_at": native_delivery.get("created_at"),
        },
        "api_requests": api.requests,
    })
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=["prearm", "armed"], default="prearm")
    parser.add_argument("--mode", choices=["static", "live"], default="static")
    parser.add_argument("--exact-sha")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.mode == "live":
        req(bool(args.exact_sha), "--exact-sha is required for live mode")
        result = validate_live(exact_sha=args.exact_sha, phase=args.phase)
    else:
        result = validate_static(phase=args.phase)
    result.update(schema_version="1.0.0", status="PASS")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
