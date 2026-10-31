"""Read-only GitHub source-bound owner activation and post-activation proof.

An observer SUCCESS is not a twelve-hour PASS. Earlier source cores can be
replayed for ancestry, but cannot earn owner-window duration credit.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re

OBSERVER = ".github/workflows/reliability-day.yml"
OBSERVER_RUNS = "/actions/workflows/reliability-day.yml/runs?branch=main&per_page=100"
MINIMUM_SECONDS = 43_200
MAX_GAP_SECONDS = 5_400
TERMINAL_REPAIR_SECONDS = 1_800
SHA = re.compile(r"[0-9a-f]{40}\Z")


class OwnerWindowError(ValueError):
    pass


def require(condition, reason):
    if not condition:
        raise OwnerWindowError(reason)


def utc(value):
    require(type(value) is str and value.endswith("Z"), "ACTIVATION_TIMESTAMP_INVALID")
    try:
        date = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise OwnerWindowError("ACTIVATION_TIMESTAMP_INVALID") from exc
    require(date.tzinfo is not None, "ACTIVATION_TIMESTAMP_INVALID")
    return date.astimezone(timezone.utc)


def _run_identity(run, source):
    return (
        type(run) is dict
        and run.get("head_sha") == source
        and run.get("head_branch") == "main"
        and run.get("path") == OBSERVER
        and run.get("event") == "workflow_run"
        and run.get("run_attempt") == 1
        and type(run.get("id")) is int
        and run["id"] > 0
    )


def _observer_job(api, run_id, source, *, pending_allowed):
    result = api.json(f"/actions/runs/{run_id}/jobs?filter=all&per_page=100")
    jobs = result.get("jobs") if type(result) is dict else None
    require(type(result) is dict and result.get("total_count") == 1
            and type(jobs) is list and len(jobs) == 1,
            "ACTIVATION_JOB_CENSUS_INVALID")
    job = jobs[0]
    require(type(job) is dict
            and job.get("run_id") == run_id
            and job.get("head_sha") == source
            and job.get("run_attempt") == 1
            and job.get("name") == "observe",
            "ACTIVATION_JOB_IDENTITY_INVALID")
    if pending_allowed:
        require(job.get("status") in ("in_progress", "completed")
                and (job.get("status") != "completed" or job.get("conclusion") == "success"),
                "ACTIVATION_CURRENT_JOB_NOT_RUNNING")
    else:
        require(job.get("status") == "completed" and job.get("conclusion") == "success",
                "ACTIVATION_JOB_NOT_SUCCESS")
    return job


def activation(api, source, *, current_run_id=None):
    """Choose first original source-bound successful observer, never a skipped run.

    Initial self-observation may use its own verified in-progress job. Producer
    and independent verifier must use a *completed* original observer.
    """
    require(type(source) is str and SHA.fullmatch(source) is not None,
            "ACTIVATION_SOURCE_INVALID")
    response = api.json(OBSERVER_RUNS)
    rows = response.get("workflow_runs") if type(response) is dict else None
    require(type(rows) is list and type(response.get("total_count")) is int
            and len(rows) <= 100, "ACTIVATION_RUN_CENSUS_INVALID")
    matching = sorted((r for r in rows if _run_identity(r, source)),
                      key=lambda r: (r["created_at"], r["id"]))
    eligible = []
    for row in matching:
        if row.get("status") == "completed" and row.get("conclusion") == "success":
            _observer_job(api, row["id"], source, pending_allowed=False)
            eligible.append(row)
        elif row.get("status") == "completed" and row.get("conclusion") != "skipped":
            raise OwnerWindowError("ACTIVATION_EARLIER_OBSERVER_ADVERSE")
    if eligible:
        first = eligible[0]
        return {"run_id": first["id"], "created": utc(first["created_at"])}
    require(type(current_run_id) is int and current_run_id > 0,
            "ACTIVATION_ORIGINAL_SUCCESSFUL_OBSERVER_NOT_FOUND")
    current = api.json(f"/actions/runs/{current_run_id}")
    require(_run_identity(current, source)
            and current.get("status") == "in_progress"
            and current.get("conclusion") is None,
            "ACTIVATION_CURRENT_RUN_IDENTITY_INVALID")
    _observer_job(api, current_run_id, source, pending_allowed=True)
    return {"run_id": current_run_id, "created": utc(current["created_at"])}


def post_activation(summary, activation_record):
    """Evaluate already independently authenticated automatic core records."""
    start = activation_record["created"]
    require(isinstance(start, datetime) and start.tzinfo is not None,
            "ACTIVATION_START_INVALID")
    rows = summary.get("automatic") if type(summary) is dict else None
    require(type(rows) is list, "ACTIVATION_AUTOMATIC_CENSUS_INVALID")
    after = [row for row in rows if row["created"] >= start and row["completed"] > start]
    after.sort(key=lambda x: x["completed"])
    if not after:
        return {"status": "COLLECTING", "automatic": [], "completed_span_seconds": 0,
                "maximum_gap_seconds": 0, "terminal": None}
    gaps = [int((right["completed"] - left["completed"]).total_seconds())
            for left, right in zip(after, after[1:])]
    require(all(0 < gap <= MAX_GAP_SECONDS for gap in gaps),
            "POST_ACTIVATION_AUTOMATIC_GAP_INVALID")
    first = after[0]
    terminal = next((r for r in after[1:] if
                    int((r["completed"] - first["completed"]).total_seconds()) >= MINIMUM_SECONDS), None)
    proof_rows = after[:after.index(terminal) + 1] if terminal else after
    span = int((proof_rows[-1]["completed"] - first["completed"]).total_seconds())
    return {"status": "PASS" if terminal else "COLLECTING", "automatic": proof_rows,
            "completed_span_seconds": span, "maximum_gap_seconds": max(gaps) if gaps else 0,
            "terminal": terminal}


def evidence_fields(activation_record, scoped):
    first = scoped["automatic"][0]
    terminal = scoped["terminal"]
    require(terminal is not None and scoped["status"] == "PASS",
            "POST_ACTIVATION_12H_NOT_COMPLETE")
    fmt = lambda v: v.isoformat(timespec="seconds").replace("+00:00", "Z")
    return {
        "owner_activation_observer_run_id": activation_record["run_id"],
        "owner_activation_observer_created_utc": fmt(activation_record["created"]),
        "post_activation_qualifying_cores": len(scoped["automatic"]),
        "post_activation_first_run_id": first["id"],
        "post_activation_first_completed_utc": fmt(first["completed"]),
        "post_activation_terminal_run_id": terminal["id"],
        "post_activation_terminal_completed_utc": fmt(terminal["completed"]),
        "post_activation_completed_span_seconds": scoped["completed_span_seconds"],
        "post_activation_maximum_gap_seconds": scoped["maximum_gap_seconds"],
    }


def verify_post_activation(api, source, summary, evidence, *, now=None):
    """Independently replay exact original activation and receipt assertions."""
    actual = activation(api, source)
    scoped = post_activation(summary, actual)
    require(scoped["status"] == "PASS", "POST_ACTIVATION_12H_NOT_COMPLETE")
    instant = datetime.now(timezone.utc) if now is None else now
    require(isinstance(instant, datetime) and instant.tzinfo is not None
            and instant >= scoped["terminal"]["completed"] + timedelta(seconds=TERMINAL_REPAIR_SECONDS),
            "POST_ACTIVATION_TERMINAL_REPAIR_PENDING")
    expected = evidence_fields(actual, scoped)
    require(type(evidence) is dict
            and all(evidence.get(k) == v for k, v in expected.items()),
            "POST_ACTIVATION_RECEIPT_EVIDENCE_MISMATCH")
    return scoped
