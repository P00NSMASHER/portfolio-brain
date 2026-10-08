"""Native GitHub Actions watchdog. Metadata checks are not soak acceptance."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re

SHA = re.compile(r"[0-9a-f]{40}\Z")
CORE = ".github/workflows/brain-cycle.yml"
CLOCK = ".github/workflows/brain-clock.yml"
THRESHOLD_SECONDS = 2100
MAX_ACTIVE_AGE = 1200

class ClockError(ValueError):
    pass

def require(condition, error):
    if not condition:
        raise ClockError(error)

def utc(value):
    require(isinstance(value, str) and value.endswith("Z"), "TIME_NOT_UTC")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ClockError("TIME_INVALID") from exc

def decide(document, source_sha, *, now=None):
    """Dispatch only if no healthy same-source core in 35 minutes and none active."""
    require(isinstance(source_sha, str) and SHA.fullmatch(source_sha), "SOURCE_SHA_INVALID")
    now = now or datetime.now(timezone.utc)
    require(now.tzinfo is not None and now.utcoffset().total_seconds() == 0, "NOW_NOT_UTC")
    require(type(document) is dict and type(document.get("total_count")) is int, "RUN_INVENTORY_INVALID")
    rows = document.get("workflow_runs")
    require(type(rows) is list and 0 <= document["total_count"] and
            len(rows) == min(document["total_count"], 100), "RUN_INVENTORY_TRUNCATED")
    seen = set()
    live = []
    for row in rows:
        require(type(row) is dict and type(row.get("id")) is int and row["id"]>0 and
                row["id"] not in seen, "RUN_ID_DUPLICATED")
        seen.add(row["id"])
        require(row.get("path") in (None, CORE), "WRONG_WORKFLOW_IN_INVENTORY")
        require(row.get("event") in ("push", "workflow_dispatch", "schedule"), "UNKNOWN_CORE_EVENT")
        created = utc(row.get("created_at"))
        require((created-now).total_seconds()<=60, "FUTURE_RUN")
        if row.get("head_sha")==source_sha and row.get("head_branch")=="main":
            live.append((created,row))
    active = sorted(((t,r) for t,r in live if r.get("status")!="completed"), reverse=True, key=lambda x:x[0])
    if active:
        age = (now-active[0][0]).total_seconds()
        return {"schema_version":1, "status":"ACTIVE" if age <= MAX_ACTIVE_AGE else "BLOCKED_STALE_ACTIVE",
                "dispatch":False,"source_sha":source_sha,"run_id":active[0][1]["id"],
                "age_seconds":int(age),"soak_pass":False}
    success = sorted(((t,r) for t,r in live if r.get("status")=="completed" and
                       r.get("conclusion")=="success"),reverse=True,key=lambda x:x[0])
    if success:
        created,run=success[0]
        completed=utc(run.get("updated_at"))
        require(created<=completed<=now, "COMPLETION_TIME_INVALID")
        age=(now-completed).total_seconds()
        if age < THRESHOLD_SECONDS:
            return {"schema_version":1,"status":"FRESH","dispatch":False,
                    "source_sha":source_sha,"run_id":run["id"],
                    "age_seconds":int(age),"soak_pass":False}
    failed=[r["id"] for _,r in live if r.get("status")=="completed" and
            r.get("conclusion")!="success"]
    return {"schema_version":1,"status":"DUE","dispatch":True,
            "source_sha":source_sha,"most_recent_success_id":success[0][1]["id"] if success else None,
            "recent_failed_run_ids":failed[:10], "soak_pass":False}

def verify_parent(parent, source_sha, clock_run_id, core_actor, *, now=None):
    """Require a GitHub-observed schedule, not a claimed scheduled/manual marker."""
    require(isinstance(source_sha,str) and SHA.fullmatch(source_sha), "SOURCE_SHA_INVALID")
    require(type(clock_run_id) is int and clock_run_id>0, "CLOCK_ID_INVALID")
    require(core_actor=="github-actions[bot]", "NOT_GITHUB_BOT_DISPATCH")
    require(type(parent) is dict and parent.get("id")==clock_run_id, "CLOCK_PARENT_ID_MISMATCH")
    require(parent.get("name")=="brain-clock-v2" and parent.get("event")=="schedule" and
            parent.get("path")==CLOCK, "NOT_NATIVE_GITHUB_CLOCK")
    require(parent.get("head_branch")=="main" and parent.get("head_sha")==source_sha, "CLOCK_SOURCE_MISMATCH")
    require(parent.get("run_attempt")==1 and parent.get("status") in ("in_progress","completed")
            and parent.get("conclusion") in (None,"success"), "CLOCK_PARENT_FAILED_OR_RETRIED")
    now=now or datetime.now(timezone.utc)
    age=(now-utc(parent.get("created_at"))).total_seconds()
    require(0 <= age <= 1200, "CLOCK_PARENT_STALE")
    return {"schema_version":1,"kind":"github_schedule","clock_run_id":clock_run_id,
            "source_sha":source_sha,"provider_event":"schedule",
            "core_actor":core_actor,"independent_verification":"REQUIRED",
            "soak_pass":False}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("mode",choices=["decide","verify"])
    p.add_argument("--input",required=True,type=Path)
    p.add_argument("--output",required=True,type=Path)
    p.add_argument("--source-sha",required=True)
    p.add_argument("--clock-run-id",type=int)
    p.add_argument("--core-actor")
    a=p.parse_args()
    try:
        data=json.loads(a.input.read_text())
        result=decide(data,a.source_sha) if a.mode=="decide" else verify_parent(
            data,a.source_sha,a.clock_run_id,a.core_actor)
    except (ClockError,OSError,ValueError,TypeError,KeyError) as exc:
        result={"schema_version":1,"status":"BLOCKED","dispatch":False,
                "reason":str(exc)[:200],"soak_pass":False}
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(result,sort_keys=True,indent=2)+"\n")
    print(json.dumps(result,sort_keys=True))
    return int(result.get("status") in ("BLOCKED","BLOCKED_STALE_ACTIVE"))

if __name__=="__main__":
    raise SystemExit(main())
