"""Complete read-only GitHub core-cycle inventory with bounded pagination.

The inventory is *metadata only*: never an acceptance PASS. The caller must
independently verify all jobs, artifacts and durable state for every run.
"""
from urllib.parse import quote

from soak_v3.audit import EvidenceError, require, utc

CORE_PATH = ".github/workflows/brain-cycle.yml"
ALLOWED_EVENTS = frozenset({"schedule", "workflow_dispatch", "push"})
PER_PAGE = 100
MAX_PAGES = 5

def collect_core_run_inventory(api, *, started_at, ended_at, max_pages=MAX_PAGES):
    start, end = utc(started_at), utc(ended_at)
    require(start <= end and (end-start).total_seconds() <= 43200,
            "INVENTORY_WINDOW_INVALID")
    require(type(max_pages) is int and 1 <= max_pages <= MAX_PAGES,
            "INVENTORY_PAGE_LIMIT_INVALID")
    query = quote(started_at + ".." + ended_at, safe="")
    all_runs = []
    total_count = None
    for page in range(1, max_pages+1):
        result = api.json(f"/actions/runs?per_page={PER_PAGE}&page={page}&created={query}")
        require(type(result.get("total_count")) is int and
                0 <= result["total_count"] <= max_pages*PER_PAGE,
                "INVENTORY_UNBOUNDED_OR_INVALID")
        if total_count is None:
            total_count = result["total_count"]
        else:
            require(result["total_count"] == total_count,
                    "INVENTORY_CHANGING_DURING_SCAN")
        runs = result.get("workflow_runs")
        require(type(runs) is list, "INVENTORY_MISSING_PAGE")
        expected = min(PER_PAGE, total_count-len(all_runs))
        require(len(runs) == expected, "INVENTORY_TRUNCATED_PAGE")
        all_runs.extend(runs)
        if len(all_runs) == total_count:
            break
    require(len(all_runs) == total_count, "INVENTORY_PAGE_BOUND_EXCEEDED")
    identities = set()
    core = []
    for run in all_runs:
        require(type(run) is dict and type(run.get("id")) is int and
                run["id"] > 0 and run["id"] not in identities,
                "INVENTORY_DUPLICATE_OR_INVALID_RUN")
        identities.add(run["id"])
        created=utc(run.get("created_at"))
        require(start <= created <= end, "INVENTORY_RUN_OUTSIDE_TIME_RANGE")
        if run.get("path") != CORE_PATH:
            continue
        require(run.get("event") in ALLOWED_EVENTS,
                "INVENTORY_UNEXPECTED_CORE_TRIGGER")
        require(run.get("run_attempt") in (None,1) or
                (type(run["run_attempt"]) is int and run["run_attempt"]>1),
                "INVENTORY_RUN_ATTEMPT_INVALID")
        core.append({
            "run_id": run["id"],
            "event": run["event"],
            "run_attempt": run.get("run_attempt",1),
            "head_sha": run.get("head_sha"),
            "status": run.get("status"),
            "conclusion": run.get("conclusion"),
            "created_at": run["created_at"],
            "run_started_at": run.get("run_started_at"),
            "updated_at": run.get("updated_at"),
            "html_url": run.get("html_url"),
        })
    # IDs returned by GitHub are distinct; chronology is explicit and stable.
    core.sort(key=lambda x:(x["created_at"],x["run_id"]))
    return {
        "scope": "COMPLETE_GITHUB_CORE_METADATA_INVENTORY_ONLY",
        "total_repo_runs_in_window": total_count,
        "core_runs": core,
        "core_count": len(core),
        "provenance": "GITHUB_API_PROVIDER_METADATA",
        "soak_pass": False,
        "coverage_complete": True,
    }
