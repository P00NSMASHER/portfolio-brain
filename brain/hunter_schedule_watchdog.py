"""Bounded independent-clock catch-up for the 15 unchanged GitHub scout crons.

This never counts a dispatch request as execution, never writes Hunter files,
and never activates adaptive/generated workers. The already-authorized
Portfolio Brain App requests one existing repository_dispatch per missed slot.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import os
from pathlib import Path
import re
import subprocess
import sys

TARGET = "P00NSMASHER/github-value-hunt-ledger"
SOURCE_PATH = ".github/workflows/public-repo-hunter.yml"
CRONS = {
    "7 2,14 * * *": "HUNTER-01",
    "15 2,14 * * *": "HUNTER-02",
    "23 2,14 * * *": "HUNTER-03",
    "31 2,14 * * *": "HUNTER-04",
    "39 2,14 * * *": "HUNTER-05",
    "47 2,14 * * *": "HUNTER-06",
    "55 2,14 * * *": "HUNTER-07",
    "3 3,15 * * *": "HUNTER-08",
    "11 3,15 * * *": "HUNTER-09",
    "19 3,15 * * *": "HUNTER-10",
    "27 3,15 * * *": "HUNTER-11",
    "35 3,15 * * *": "HUNTER-12",
    "43 3,15 * * *": "HUNTER-13",
    "51 3,15 * * *": "HUNTER-14",
    "7 4,16 * * *": "INTEGRATOR",
}
TITLE = re.compile(r"^Hunter (.+) slot=(native|20\d{2}-\d{2}-\d{2}T\d{2}:\d{2}:00Z)$")
SHA = re.compile(r"^[0-9a-f]{40}$")
GRACE = dt.timedelta(minutes=30)
MAX_AGE = dt.timedelta(hours=12)
INFLIGHT_AGE = dt.timedelta(hours=2)
RETRY_AGE = dt.timedelta(minutes=40)
MAX_OBSERVED_RECOVERIES = 2
MAX_PER_CYCLE = 1
# GitHub workflow concurrency has at most one pending run per group. A burst
# of accepted dispatches cancels older pending executions even when
# cancel-in-progress is false; serialize catch-up until the previous run ends.
ACTIVE_STATUSES = frozenset({"queued", "in_progress", "pending", "waiting", "requested"})


class EvidenceError(ValueError):
    pass


def api(path, payload=None):
    base = f"repos/{TARGET}/"
    if not path.startswith(base):
        raise EvidenceError("Cross-repository API request rejected")
    if payload is not None and path != base + "dispatches":
        raise EvidenceError("Write endpoint not in existing recovery scope")
    cmd = ["gh", "api", "--method", "POST" if payload is not None else "GET", path]
    if payload is not None:
        cmd += ["--input", "-"]
    result = subprocess.run(
        cmd, input=json.dumps(payload).encode() if payload is not None else None,
        capture_output=True, check=True, timeout=35,
    )
    return json.loads(result.stdout) if result.stdout else None


def timestamp(s):
    value = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    if value.utcoffset() != dt.timedelta(0):
        raise EvidenceError("Non-UTC GitHub timestamp")
    return value


def slot_label(value):
    if value.tzinfo is None or value.utcoffset() != dt.timedelta(0):
        raise EvidenceError("Slot is not in UTC")
    return value.strftime("%Y-%m-%dT%H:%M:00Z")


def check_source(yaml):
    crons = re.findall(r'^\s+- cron: "([^"]+)"\s*$', yaml, re.M)
    if len(crons) != 15 or len(set(crons)) != 15 or set(crons) != set(CRONS):
        raise EvidenceError("Original 15 Hunter schedules no longer match frozen routing")
    for required in (
        "run-name: >-", "github.event.schedule",
        "github.event.client_payload.scheduled_slot",
        "github.actor == 'portfolio-brain-v8-runtime[bot]'",
        "github.event.client_payload.expected_main == github.sha",
        "hunter-integrator-", "needs.scout.outputs.worker != 'INTEGRATOR'",
        "types: [retally-scout-recovery-v1]",
        "group: starblox-roblox-accelerator-main-writer",
    ):
        if required not in yaml:
            raise EvidenceError("Hunter schedule or App authority unverified")


def recent_due_slots(now):
    if now.utcoffset() != dt.timedelta(0):
        raise EvidenceError("Clock must be UTC")
    due = []
    for cron, worker in CRONS.items():
        minute, hours, _, _, _ = cron.split()
        options = []
        for d in range(3):
            date = (now - dt.timedelta(days=d)).date()
            for hour in hours.split(","):
                t = dt.datetime(date.year, date.month, date.day, int(hour),
                                int(minute), tzinfo=dt.timezone.utc)
                if GRACE <= now - t <= MAX_AGE:
                    options.append(t)
        if options:
            due.append({"worker": worker, "cron": cron,
                        "slot": slot_label(max(options))})
    return sorted(due, key=lambda x: (x["slot"], x["worker"]))


def belongs(run, slot, now):
    m = TITLE.fullmatch(str(run.get("display_title", "")))
    if not m:
        return False
    event = run.get("event")
    try:
        created = timestamp(run["created_at"])
        expected = timestamp(slot["slot"])
    except (KeyError, ValueError, TypeError):
        return False
    if not expected - dt.timedelta(minutes=2) <= created <= now:
        return False
    if event == "schedule":
        return (m.group(1), m.group(2)) == (slot["cron"], "native")
    if event == "repository_dispatch":
        return (m.group(1), m.group(2)) == (slot["worker"], slot["slot"])
    return False


def completed_receipt(run, worker, read=api):
    """Require an actual successful worker job and its nonempty retained artifact."""
    if run.get("status") != "completed" or run.get("conclusion") != "success":
        return False
    rid, attempt = run.get("id"), run.get("run_attempt")
    if type(rid) is not int or type(attempt) is not int or rid <= 0 or attempt <= 0:
        return False
    jobs = read(f"repos/{TARGET}/actions/runs/{rid}/jobs?per_page=100")
    artifacts = read(f"repos/{TARGET}/actions/runs/{rid}/artifacts?per_page=100")
    jobs = jobs.get("jobs") if isinstance(jobs, dict) else None
    artifacts = artifacts.get("artifacts") if isinstance(artifacts, dict) else None
    if not isinstance(jobs, list) or not isinstance(artifacts, list):
        raise EvidenceError("Job/artifact inventory unavailable")
    done = {j.get("name") for j in jobs if j.get("conclusion") == "success"}
    required = {"scout"} if worker == "INTEGRATOR" else {"scout", "candidate-inspection"}
    if not required.issubset(done):
        return False
    expected = (f"hunter-integrator-{rid}-{attempt}" if worker == "INTEGRATOR"
                else f"hunter-inspection-{rid}-{attempt}")
    return any(a.get("name") == expected and a.get("expired") is False
               and type(a.get("size_in_bytes")) is int and a["size_in_bytes"] > 0
               for a in artifacts)


def reconcile(now, runs, verify=completed_receipt):
    if not isinstance(runs, list):
        raise EvidenceError("Missing GitHub run inventory")
    due, completed, active, exhausted = [], [], [], []
    for slot in recent_due_slots(now):
        matches = [r for r in runs if belongs(r, slot, now)]
        if any(r.get("status") in ACTIVE_STATUSES
               and now - timestamp(r["created_at"]) <= INFLIGHT_AGE
               for r in matches):
            active.append(slot)
            continue
        if any(verify(r, slot["worker"]) for r in matches if
               r.get("status") == "completed" and r.get("conclusion") == "success"):
            completed.append(slot)
            continue
        attempts = [r for r in matches if r.get("event") == "repository_dispatch"]
        if len(attempts) >= MAX_OBSERVED_RECOVERIES:
            exhausted.append({**slot, "attempts": len(attempts)})
            continue
        if attempts and any(now - timestamp(r["created_at"]) < RETRY_AGE for r in attempts):
            active.append(slot)
            continue
        due.append({**slot, "observed_recovery_attempts": len(attempts)})
    # A run for ANOTHER Hunter can still occupy the one-slot shared queue.
    # Do not send another recovery while any real upstream Scout run is
    # queued, pending, waiting, requested, or still executing.
    blocking = sorted({r["id"] for r in runs
                       if type(r.get("id")) is int
                       and r.get("status") in ACTIVE_STATUSES
                       and dt.timedelta(0) <= now - timestamp(r["created_at"]) <= INFLIGHT_AGE})
    return {"due": [] if blocking else due[:MAX_PER_CYCLE],
            "backlog": len(due), "blocking_run_ids": blocking,
            "completed": completed, "active": active, "exhausted": exhausted,
            "slots_checked": len(recent_due_slots(now))}


def snapshot(now):
    main = api(f"repos/{TARGET}/branches/main")
    sha = ((main or {}).get("commit") or {}).get("sha")
    if not isinstance(sha, str) or not SHA.fullmatch(sha):
        raise EvidenceError("Unable to verify protected Hunter main")
    file = api(f"repos/{TARGET}/contents/{SOURCE_PATH}?ref={sha}")
    if not isinstance(file, dict) or file.get("encoding") != "base64":
        raise EvidenceError("Hunter workflow source missing")
    check_source(base64.b64decode(file["content"]).decode())
    inventory = api(f"repos/{TARGET}/actions/workflows/public-repo-hunter.yml/runs?per_page=100")
    runs = inventory.get("workflow_runs") if isinstance(inventory, dict) else None
    if not isinstance(runs, list):
        raise EvidenceError("No source-bound scout run inventory")
    if len(runs) == 100 and now - timestamp(runs[-1]["created_at"]) < MAX_AGE:
        raise EvidenceError("Run inventory truncated: do not infer missed slots")
    return sha, runs


def save(filename, data):
    path = Path(filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--plan")
    p.add_argument("--dispatch")
    p.add_argument("--receipt", required=True)
    args = p.parse_args()
    if bool(args.plan) == bool(args.dispatch):
        raise EvidenceError("Exactly one action required")
    now = dt.datetime.now(dt.timezone.utc)
    sha, runs = snapshot(now)
    decision = reconcile(now, runs)
    if args.plan:
        result = {"stage": "READ_ONLY_PLAN", "ledger_sha": sha,
                  "at": now.isoformat(), "decision": decision,
                  "dispatch_is_execution": False}
        save(args.plan, result)
        save(args.receipt, result)
        if os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
                f.write("due=" + str(bool(decision["due"])).lower() + "\n")
        print(json.dumps({"checked": decision["slots_checked"],
                          "due": len(decision["due"]), "backlog": decision["backlog"],
                          "exhausted": len(decision["exhausted"])}))
        return
    proposed = json.loads(Path(args.dispatch).read_text(encoding="utf-8"))
    if proposed.get("stage") != "READ_ONLY_PLAN" or proposed.get("ledger_sha") != sha:
        raise EvidenceError("Stale or untrusted recovery plan")
    planned = {(x["worker"], x["slot"]) for x in proposed["decision"]["due"]}
    eligible = [s for s in decision["due"] if (s["worker"], s["slot"]) in planned]
    accepted = []
    for due in eligible:
        latest = api(f"repos/{TARGET}/branches/main")["commit"]["sha"]
        if latest != sha:
            raise EvidenceError("Hunter main moved before dispatch")
        api(f"repos/{TARGET}/dispatches", payload={
            "event_type": "retally-scout-recovery-v1",
            "client_payload": {
                "worker": due["worker"], "expected_main": sha,
                "scheduled_slot": due["slot"]}})
        accepted.append({"worker": due["worker"], "slot": due["slot"],
                         "status": "REQUEST_ACCEPTED_NOT_EXECUTION_PROOF"})
    result = {"stage": "BOUNDED_RECOVERY", "ledger_sha": sha,
              "at": now.isoformat(), "accepted": accepted,
              "remaining": decision["backlog"] - len(accepted),
              "unresolved": decision["exhausted"], "execution_verified": False}
    save(args.receipt, result)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (EvidenceError, subprocess.CalledProcessError, subprocess.TimeoutExpired,
            OSError, ValueError, KeyError, TypeError) as exc:
        print("HUNTER_RECOVERY_HOLD: " + type(exc).__name__ + ": " +
              str(exc)[:240], file=sys.stderr)
        raise SystemExit(2)
