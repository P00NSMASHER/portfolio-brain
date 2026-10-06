"""Bounded native-schedule diagnostics and owner-authorized registration recovery.

A successful dispatch or runner check is never promoted to scheduled evidence.
This module does not run portfolio work or grant release/paid authority.
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

REPO = "P00NSMASHER/portfolio-brain"
ROOT = Path(__file__).resolve().parents[1]
CORE = (
    "portfolio-state-reducer", "runtime-hourly-sync", "portfolio-autonomous-scheduler",
    "hunter-autonomous-cycle", "agent-heartbeat-sweep", "portfolio-cost-watchdog",
    "portfolio-notification-cycle", "command-center-pages",
)
PROBE = "portfolio-schedule-delivery"
ACTIVE = {"queued", "in_progress", "pending", "waiting", "requested"}
REPAIRABLE = {"disabled_manually", "disabled_inactivity"}
RETIRED_RUN = 37380493270
RETIRED_SHA = "8cf8c0a4723b6786dce1a809f6c99ad99da631a2"
RETIRED_BRANCH = "audit/step23-exact-main-20261005"
RETIRED_PATH = ".github/workflows/step23-read-only-audit.yml"


def require(ok: bool, message: str) -> None:
    if not ok:
        raise RuntimeError(message)


def timestamp(value: str) -> datetime:
    require(isinstance(value, str), "MALFORMED_PROVIDER_TIMESTAMP")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(parsed.tzinfo is not None, "NAIVE_PROVIDER_TIMESTAMP")
    return parsed.astimezone(timezone.utc)


class API:
    def __init__(self, token: str):
        self.token = token
        self.requests = 0

    def call(self, path: str, method: str = "GET") -> Any:
        require((path == "" or path.startswith("/")) and ".." not in path and "://" not in path, "UNSAFE_API_PATH")
        require(method in {"GET", "PUT", "POST"}, "UNSUPPORTED_API_METHOD")
        require(self.requests < 80, "DELIVERY_API_BUDGET_EXHAUSTED")
        # Write destinations are a closed set, not caller-supplied URLs.
        if method == "PUT":
            require(re.fullmatch(r"/actions/workflows/[0-9]+/enable", path) is not None, "WRITE_NOT_ALLOWED")
        if method == "POST":
            require(path == f"/actions/runs/{RETIRED_RUN}/cancel", "WRITE_NOT_ALLOWED")
        self.requests += 1
        req = urllib.request.Request("https://api.github.com/repos/" + REPO + path,
            method=method, headers={"Authorization": "Bearer " + self.token,
                "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "portfolio-schedule-delivery/1.0"})
        with urllib.request.urlopen(req, timeout=15) as response:
            data = response.read(4_000_001)
        require(len(data) <= 4_000_000, "PROVIDER_RESPONSE_TOO_LARGE")
        return json.loads(data) if data else {}


def registry(api: API) -> dict[str, dict]:
    rows: list[dict] = []
    seen: set[int] = set()
    for page in range(1, 4):
        doc = api.call(f"/actions/workflows?per_page=100&page={page}")
        require(isinstance(doc, dict) and isinstance(doc.get("workflows"), list), "WORKFLOW_LIST_MALFORMED")
        batch = doc["workflows"]
        for row in batch:
            require(isinstance(row, dict) and type(row.get("id")) is int and row["id"] > 0,
                    "WORKFLOW_ID_MALFORMED")
            require(row["id"] not in seen, "WORKFLOW_PAGINATION_DRIFT")
            seen.add(row["id"])
            rows.append(row)
        if len(batch) < 100:
            break
    else:
        raise RuntimeError("WORKFLOW_LIST_INCOMPLETE")
    out = {}
    for name in (*CORE, PROBE):
        matches = [r for r in rows if r.get("path") == f".github/workflows/{name}.yml"]
        require(len(matches) <= 1, "DUPLICATE_WORKFLOW_REGISTRATION")
        if matches:
            require(matches[0].get("name") == name, "WORKFLOW_NAME_PATH_MISMATCH")
            out[name] = matches[0]
    return out


def summarize(name: str, workflow: dict | None, runs: list[dict], sha: str, now: datetime) -> dict:
    result = {"workflow": name, "registered": workflow is not None,
              "native_success_on_revision": False, "soak_credit": 0}
    if workflow is None:
        return {**result, "stage": "WORKFLOW_NOT_REGISTERED"}
    result.update(workflow_id=workflow["id"], state=workflow.get("state"), path=workflow["path"])
    if workflow.get("state") != "active":
        return {**result, "stage": "WORKFLOW_NOT_ACTIVE"}
    matched = []
    for run in runs:
        if (run.get("name") == name and run.get("path") == workflow["path"]
                and run.get("workflow_id") == workflow["id"] and run.get("head_branch") == "main"
                and run.get("event") == "schedule"):
            created = timestamp(run["created_at"])
            require(created <= now, "FUTURE_RUN_TIMESTAMP")
            matched.append(run)
    matched.sort(key=lambda r: (timestamp(r["created_at"]), r["id"]), reverse=True)
    fields = ("id", "event", "head_sha", "created_at", "run_started_at", "status", "conclusion")
    result["latest_native_run"] = {k: matched[0].get(k) for k in fields} if matched else None
    current = [r for r in matched if r.get("head_sha") == sha]
    if not current:
        return {**result, "stage": "NO_NATIVE_RUN_ON_CURRENT_REVISION"}
    newest = current[0]
    result["current_run"] = {k: newest.get(k) for k in fields}
    if newest.get("status") in ACTIVE:
        return {**result, "stage": "NATIVE_EVENT_CREATED_EXECUTION_PENDING"}
    if newest.get("status") != "completed" or newest.get("conclusion") != "success":
        return {**result, "stage": "NATIVE_RUN_FAILED_OR_SKIPPED"}
    age = (now - timestamp(newest["created_at"])).total_seconds()
    if age > 3600:
        return {**result, "stage": "NATIVE_SUCCESS_TOO_OLD_FOR_PREFLIGHT"}
    return {**result, "stage": "NATIVE_COMPLETION_OBSERVED", "native_success_on_revision": True}


def repair(api: API, workflows: dict[str, dict], sha: str, env: dict[str, str]) -> list[dict]:
    require(env.get("GITHUB_EVENT_NAME") == "push" and env.get("GITHUB_REF") == "refs/heads/main",
            "REGISTRATION_REPAIR_REQUIRES_PROTECTED_MAIN_PUSH")
    require(env.get("GITHUB_REPOSITORY") == REPO and env.get("GITHUB_SHA") == sha,
            "REGISTRATION_REPAIR_CONTEXT_MISMATCH")
    require(api.call("/branches/main")["commit"]["sha"] == sha, "MAIN_MOVED")
    actions = []
    old = api.call(f"/actions/runs/{RETIRED_RUN}")
    require(old.get("id") == RETIRED_RUN and old.get("head_sha") == RETIRED_SHA
            and old.get("head_branch") == RETIRED_BRANCH and old.get("path") == RETIRED_PATH,
            "RETIRED_RUN_IDENTITY_MISMATCH")
    if old.get("status") in ACTIVE:
        api.call(f"/actions/runs/{RETIRED_RUN}/cancel", "POST")
        checked = api.call(f"/actions/runs/{RETIRED_RUN}")
        actions.append({"run_id": RETIRED_RUN, "action": "CANCEL_REQUESTED",
                        "verified_status": checked.get("status"), "conclusion": checked.get("conclusion")})
    else:
        actions.append({"run_id": RETIRED_RUN, "action": "ALREADY_TERMINAL",
                        "conclusion": old.get("conclusion")})
    for name in (*CORE, PROBE):
        wf = workflows.get(name)
        if wf is None:
            actions.append({"workflow": name, "action": "NOT_REGISTERED_NO_BLIND_WRITE"})
            continue
        require(wf.get("name") == name and wf.get("path") == f".github/workflows/{name}.yml",
                "REPAIR_TARGET_IDENTITY_MISMATCH")
        if wf.get("state") not in REPAIRABLE:
            actions.append({"workflow": name, "action": "LEFT_UNCHANGED", "state": wf.get("state")})
            continue
        require(api.call("/branches/main")["commit"]["sha"] == sha, "MAIN_MOVED")
        api.call(f"/actions/workflows/{wf['id']}/enable", "PUT")
        confirmed = api.call(f"/actions/workflows/{wf['id']}")
        require(confirmed.get("id") == wf["id"] and confirmed.get("path") == wf["path"]
                and confirmed.get("name") == name and confirmed.get("state") == "active",
                "WORKFLOW_ENABLE_NOT_CONFIRMED")
        actions.append({"workflow": name, "action": "REGISTRATION_REENABLED_DELIVERY_UNPROVEN"})
    return actions


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repair", action="store_true")
    ap.add_argument("--output", type=Path, default=Path("operations/out/schedule_delivery.json"))
    args = ap.parse_args()
    now = datetime.now(timezone.utc)
    control=json.loads((ROOT/"operations"/"STEP23_CONTROL.json").read_text(encoding="utf-8"))
    report = {"schema_version": "1.0.0", "observed_at": now.isoformat(),
              "soak_status": control.get("status"), "next_soak_start": control.get("next_soak_start"),
              "acceptance_complete": False, "authority_granted": False, "actions": []}
    try:
        require(os.environ.get("GITHUB_REPOSITORY") == REPO, "WRONG_REPOSITORY")
        require(os.environ.get("GITHUB_REF") == "refs/heads/main", "NOT_MAIN")
        sha = os.environ["GITHUB_SHA"]
        require(re.fullmatch(r"[0-9a-f]{40}", sha) is not None, "INVALID_REVISION")
        api = API(os.environ["GITHUB_TOKEN"])
        repo = api.call("")
        require(repo.get("default_branch") == "main" and repo.get("archived") is False
                and repo.get("disabled", False) is False, "REPOSITORY_NOT_SCHEDULABLE")
        report.update(default_branch=repo["default_branch"], repository_archived=False)
        require(api.call("/branches/main")["commit"]["sha"] == sha, "MAIN_MOVED")
        run_id = os.environ["GITHUB_RUN_ID"]
        require(run_id.isdigit(), "INVALID_OBSERVER_RUN")
        own = api.call(f"/actions/runs/{run_id}")
        require(own.get("head_sha") == sha and own.get("path") == f".github/workflows/{PROBE}.yml",
                "OBSERVER_RUN_IDENTITY_MISMATCH")
        require(own.get("event") == os.environ["GITHUB_EVENT_NAME"], "OBSERVER_EVENT_MISMATCH")
        report.update(main_sha=sha, observer_run_id=int(run_id), observer_event=own["event"],
                      probe_is_native_schedule=own["event"] == "schedule")
        workflows = registry(api)
        if args.repair:
            report["actions"] = repair(api, workflows, sha, dict(os.environ))
            workflows = registry(api)
        summaries = []
        for name in (*CORE, PROBE):
            wf = workflows.get(name)
            runs = []
            if wf:
                doc = api.call(f"/actions/workflows/{wf['id']}/runs?event=schedule&branch=main&per_page=20")
                require(isinstance(doc.get("workflow_runs"), list), "RUN_HISTORY_MALFORMED")
                runs = doc["workflow_runs"]
            summaries.append(summarize(name, wf, runs, sha, now))
        report.update(workflows=summaries, api_requests=api.requests,
                      delivery_preflight_ready=all(r["native_success_on_revision"] for r in summaries[:8]),
                      status="DELIVERY_OBSERVED_NOT_SOAK_ACCEPTANCE")
        require(api.call("/branches/main")["commit"]["sha"] == sha, "MAIN_MOVED")
    except Exception as exc:
        report.update(status="DELIVERY_DIAGNOSTIC_FAILED_CLOSED", error_type=type(exc).__name__)
        raise
    finally:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
