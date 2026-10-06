#!/usr/bin/env python3
"""Wake the sole canonical reducer while a production canonical consumer is active.

This coordinator grants no portfolio authority. It only requests the existing
portfolio-state-reducer workflow, whose reducer, provenance, lineage, and
snapshot validation remain authoritative and fail closed.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from operations.schedule_clock import API, req
from state_journal.contracts import WORKFLOW_PRODUCERS

REDUCER_NAME = "portfolio-state-reducer"
REDUCER_FILE = "portfolio-state-reducer.yml"
REDUCER_PATH = ".github/workflows/portfolio-state-reducer.yml"
ACTIVE_STATUSES = {"queued", "in_progress", "pending", "waiting", "requested"}
RECENT_REDUCER_SECONDS = 90
CANONICAL_CONSUMERS = set(WORKFLOW_PRODUCERS) | {"portfolio-cost-watchdog"}


def _parse_provider_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo is not None else None


def _exact_consumer(run: dict, main_sha: str) -> bool:
    path = run.get("path")
    if not isinstance(path, str) or not path.startswith(".github/workflows/") or not path.endswith(".yml"):
        return False
    stem = Path(path).stem
    return (
        stem in CANONICAL_CONSUMERS
        and run.get("name") == stem
        and run.get("head_branch") == "main"
        and run.get("head_sha") == main_sha
        and run.get("status") in ACTIVE_STATUSES
        and type(run.get("id")) is int
    )


def _exact_reducer(run: dict, main_sha: str) -> bool:
    return (
        run.get("name") == REDUCER_NAME
        and run.get("path") == REDUCER_PATH
        and run.get("head_branch") == "main"
        and run.get("head_sha") == main_sha
        and type(run.get("id")) is int
    )


def daemon_identity(api: API, run_id: int, attempt: int, main_sha: str) -> dict:
    run = api.call(f"/actions/runs/{run_id}")
    req(
        run.get("name") == "portfolio-schedule-clock-daemon"
        and run.get("path") == ".github/workflows/portfolio-schedule-clock-daemon.yml",
        "untrusted reducer-wake daemon source",
    )
    req(
        run.get("event") in {"push", "workflow_dispatch"}
        and run.get("head_branch") == "main"
        and run.get("head_sha") == main_sha,
        "reducer-wake daemon is not exact current main",
    )
    req(run.get("run_attempt") == attempt, "reducer-wake daemon attempt mismatch")
    req(run.get("status") in ACTIVE_STATUSES, "reducer-wake daemon is not active")
    return run


def execute(api: API, main_sha: str, *, at: datetime | None = None) -> dict:
    now = (at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    doc = api.call("/actions/runs?branch=main&per_page=100")
    rows = doc.get("workflow_runs")
    req(isinstance(rows, list), "reducer-wake run listing malformed")

    consumers = [row for row in rows if _exact_consumer(row, main_sha)]
    reducers = [row for row in rows if _exact_reducer(row, main_sha)]
    action = "NO_ACTIVE_CANONICAL_CONSUMER"
    evidence: list[int] = []

    if consumers:
        active_reducers = [row for row in reducers if row.get("status") in ACTIVE_STATUSES]
        if active_reducers:
            action = "REDUCER_ALREADY_ACTIVE"
            evidence = sorted(row["id"] for row in active_reducers)
        else:
            cutoff = now - timedelta(seconds=RECENT_REDUCER_SECONDS)
            recent_successes = []
            for row in reducers:
                updated = _parse_provider_time(row.get("updated_at"))
                if (
                    row.get("status") == "completed"
                    and row.get("conclusion") == "success"
                    and updated is not None
                    and updated >= cutoff
                ):
                    recent_successes.append(row)
            if recent_successes:
                action = "RECENT_REDUCER_SUCCESS"
                evidence = sorted(row["id"] for row in recent_successes)
            else:
                api.call(
                    f"/actions/workflows/{REDUCER_FILE}/dispatches",
                    "POST",
                    {"ref": "main"},
                )
                action = "REDUCER_WAKE_REQUESTED"

    return {
        "schema_version": "1.0.0",
        "status": "PASS",
        "authority_granted": False,
        "dispatch_authority_effect": "NONE",
        "main_sha": main_sha,
        "checked_at": now.isoformat().replace("+00:00", "Z"),
        "action": action,
        "active_consumer_run_ids": sorted(row["id"] for row in consumers),
        "reducer_evidence_run_ids": evidence,
        "api_requests": api.requests,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("operations/out/reducer_wake.json"),
    )
    args = parser.parse_args()

    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    req(bool(token), "reducer-wake token missing")
    run_id = int(os.environ["GITHUB_RUN_ID"])
    run_attempt = int(os.environ["GITHUB_RUN_ATTEMPT"])

    api = API(token, max_requests=8)
    main_sha = api.call("/branches/main")["commit"]["sha"]
    req(os.environ.get("GITHUB_SHA") == main_sha, "reducer-wake daemon checkout is stale")
    daemon_identity(api, run_id, run_attempt, main_sha)
    result = execute(api, main_sha)
    req(api.call("/branches/main")["commit"]["sha"] == main_sha, "main moved during reducer wake")
    result["daemon_run_id"] = run_id
    result["daemon_run_attempt"] = run_attempt
    result["api_requests"] = api.requests

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
