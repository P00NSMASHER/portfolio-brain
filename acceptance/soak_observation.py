"""Bounded, read-only run observation for Portfolio Brain Step 23.

These helpers do not start workflows, change evidence classification, or relax
any acceptance threshold. They distinguish a changing run's status from a
changing pagination membership, rebuild failure history on every observation,
and require a fresh final run census before a receipt is created.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Protocol


class ReadAPI(Protocol):
    def get(self, path: str) -> Any: ...


class ObservationChanged(RuntimeError):
    """The provider changed list membership during a bounded observation."""


def parse_time(value: str) -> datetime:
    if not isinstance(value, str):
        raise RuntimeError("scheduled run timestamp is not a string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RuntimeError("scheduled run timestamp is malformed") from exc
    if parsed.tzinfo is None:
        raise RuntimeError("scheduled run timestamp has no timezone")
    return parsed.astimezone(timezone.utc)


def _rows(doc: Any, expected_event: str) -> list[dict[str, Any]]:
    if expected_event not in {"schedule", "workflow_dispatch"}:
        raise ValueError("unsupported observed event")
    if not isinstance(doc, dict) or not isinstance(doc.get("workflow_runs"), list):
        raise RuntimeError("transport run listing malformed")
    rows = doc["workflow_runs"]
    for row in rows:
        if not isinstance(row, dict) or type(row.get("id")) is not int or row["id"] <= 0:
            raise RuntimeError("transport run identity malformed")
        parse_time(row.get("created_at"))
        if not isinstance(row.get("name"), str) or not row["name"]:
            raise RuntimeError("transport workflow name malformed")
        if not isinstance(row.get("head_sha"), str):
            raise RuntimeError("transport run source identity malformed")
        if row.get("head_branch") != "main" or row.get("event") != expected_event:
            raise RuntimeError("provider returned a wrong-branch or wrong-event run")
        if type(row.get("run_attempt", 1)) is not int or row.get("run_attempt", 1) < 1:
            raise RuntimeError("transport run attempt malformed")
        if row.get("status") not in {"queued", "in_progress", "completed", "waiting", "requested", "pending"}:
            raise RuntimeError("transport run status malformed")
        if row["status"] == "completed" and not isinstance(row.get("conclusion"), str):
            raise RuntimeError("completed transport run has no conclusion")
    return rows


def _identity(row: dict[str, Any]) -> tuple:
    """Stable fields: status/updated_at can legitimately change while reading."""
    return (
        row["id"], row["created_at"], row["name"], row["head_sha"],
        row["head_branch"], row["event"], row.get("workflow_id"),
        row.get("path"), row.get("run_attempt", 1),
    )


def _runs_for_event(
    gh: ReadAPI, workflows: set[str], exact_sha: str, start: datetime, event: str,
    *, max_pages: int = 20, max_attempts: int = 3,
) -> dict[str, list[dict[str, Any]]]:
    """Return one stable exact-head event census with bounded race retries."""
    if (start.tzinfo is None or event not in {"schedule", "workflow_dispatch"}
            or not 1 <= max_pages <= 20 or not 1 <= max_attempts <= 3):
        raise ValueError("invalid bounded observation parameters")
    path=f"/actions/runs?branch=main&event={event}&per_page=100"
    for attempt in range(max_attempts):
        rows: list[dict[str, Any]] = []
        first_page: list[dict[str, Any]] = []
        seen: set[int] = set()
        previous_time: datetime | None = None
        try:
            for page in range(1, max_pages + 1):
                batch = _rows(gh.get(path + f"&page={page}"), event)
                if page == 1:
                    first_page = batch
                for row in batch:
                    created = parse_time(row["created_at"])
                    if row["id"] in seen or (previous_time is not None and created > previous_time):
                        raise ObservationChanged(f"{event} run pagination membership drift")
                    previous_time = created
                    seen.add(row["id"])
                    rows.append(row)
                if not batch and len(rows) >= 1000:
                    raise RuntimeError(f"{event} run listing reached provider result cap")
                if len(batch) < 100 or (batch and parse_time(batch[-1]["created_at"]) < start):
                    break
            else:
                raise RuntimeError(f"{event} run listing incomplete at page bound")

            refreshed = _rows(gh.get(path + "&page=1"), event)
            if tuple(map(_identity, refreshed)) != tuple(map(_identity, first_page)):
                raise ObservationChanged(f"{event} run list membership changed during pagination")
            freshest = {row["id"]: row for row in refreshed}
            rows = [freshest.get(row["id"], row) for row in rows]
            out: dict[str, list[dict[str, Any]]] = {name: [] for name in workflows}
            for row in rows:
                if (row["name"] in workflows and row["head_sha"] == exact_sha
                        and parse_time(row["created_at"]) >= start):
                    out[row["name"]].append(row)
            for value in out.values():
                value.sort(key=lambda row: (parse_time(row["created_at"]), row["id"]))
            return out
        except ObservationChanged:
            if attempt == max_attempts - 1:
                raise
    raise AssertionError("unreachable")


def scheduled_runs(
    gh: ReadAPI, workflows: set[str], exact_sha: str, start: datetime,
    *, max_pages: int = 20, max_attempts: int = 3,
) -> dict[str, list[dict[str, Any]]]:
    """Backward-compatible strict native schedule census."""
    return _runs_for_event(
        gh,workflows,exact_sha,start,"schedule",
        max_pages=max_pages,max_attempts=max_attempts,
    )


def transport_runs(
    gh: ReadAPI, workflows: set[str], exact_sha: str, start: datetime,
    *, max_pages: int = 20, max_attempts: int = 3,
) -> dict[str, list[dict[str, Any]]]:
    """Return native schedule plus workflow_dispatch candidates.

    This helper does not decide whether a workflow_dispatch is trustworthy.
    Step 23 must separately bind every counted dispatch to a validated
    redundant-clock receipt.
    """
    out: dict[str, list[dict[str, Any]]] = {name: [] for name in workflows}
    seen: set[int] = set()
    for event in ("schedule","workflow_dispatch"):
        grouped=_runs_for_event(
            gh,workflows,exact_sha,start,event,
            max_pages=max_pages,max_attempts=max_attempts,
        )
        for name,rows in grouped.items():
            for row in rows:
                if row["id"] in seen:
                    raise RuntimeError("duplicate transport run across event censuses")
                seen.add(row["id"])
                out[name].append(row)
    for value in out.values():
        value.sort(key=lambda row: (parse_time(row["created_at"]), row["id"]))
    return out


def reset_history(
    grouped: dict[str, list[dict[str, Any]]], start: datetime,
    maximum: int, cancellation_successor: Callable[[dict, list[dict]], dict | None],
) -> tuple[list[dict[str, Any]], datetime]:
    """Rebuild every real failure from the original window, including --once.

    The existing cancellation classifier is supplied by the collector and is
    not weakened. A fresh process cannot silently reset the failure counter.
    """
    if type(maximum) is not int or maximum < 0 or start.tzinfo is None:
        raise ValueError("invalid reset policy")
    failures: list[tuple[datetime, int, str, dict[str, Any]]] = []
    seen: set[int] = set()
    for name, rows in grouped.items():
        for row in rows:
            if row["id"] in seen:
                raise RuntimeError("duplicate run in reset history")
            seen.add(row["id"])
            if row.get("status") != "completed" or row.get("conclusion") == "success":
                continue
            if row.get("conclusion") == "cancelled" and cancellation_successor(row, rows) is not None:
                continue
            completed = parse_time(row["updated_at"])
            if completed < parse_time(row["created_at"]):
                raise RuntimeError("failure completed before creation")
            if parse_time(row["created_at"]) < start:
                continue
            failures.append((completed, row["id"], name, row))
    failures.sort(key=lambda failure: (failure[0], failure[1]))
    if len(failures) > maximum:
        raise RuntimeError("STEP23_MAX_RESETS_EXCEEDED")
    effective = start
    resets: list[dict[str, Any]] = []
    for completed, run_id, name, row in failures:
        resets.append({
            "previous_start": effective.isoformat().replace("+00:00", "Z"),
            "reset_at": completed.isoformat().replace("+00:00", "Z"),
            "reason": f"{name} run {run_id} conclusion={row.get('conclusion')}",
        })
        effective = max(effective, completed)
    return resets, effective


def run_census(grouped: dict[str, list[dict[str, Any]]]) -> tuple:
    """Fields that must not change while final artifacts are being checked."""
    return tuple(sorted(
        (name, _identity(row), row.get("status"), row.get("conclusion"), row.get("updated_at"))
        for name, rows in grouped.items() for row in rows
    ))


def final_census_unchanged(
    before: dict[str, list[dict[str, Any]]],
    after: dict[str, list[dict[str, Any]]],
) -> bool:
    """Never certify a new active run, new failure, deletion, or changed attempt."""
    return set(before) == set(after) and run_census(before) == run_census(after)


def write_failure_progress(argv: list[str], exc: Exception) -> None:
    """Keep terminal failure visible to the workflow's always-upload step.

    Third-party exception messages may contain request details, so only known
    internal status codes (or a generic code) are written to the receipt.
    """
    import argparse
    import json
    import re
    from pathlib import Path
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--output-meta", type=Path)
    parser.add_argument("--output-receipt", type=Path)
    args, _ = parser.parse_known_args(argv)
    if args.output_meta is None:
        return
    codes = {
        "STEP23_SOAK_WINDOW_EXPIRED", "STEP23_SOAK_TIMEOUT",
        "STEP23_MAIN_MOVED", "STEP23_MAX_RESETS_EXCEEDED",
    }
    first_word = str(exc).split(" ", 1)[0]
    code = first_word if first_word in codes else "STEP23_OBSERVATION_ERROR"
    cfg = {}
    if args.config and args.config.is_file():
        try:
            value = json.loads(args.config.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                cfg = value
        except (OSError, ValueError):
            pass
    sha = cfg.get("exact_main_sha")
    if not isinstance(sha, str) or re.fullmatch(r"[0-9a-f]{40}", sha) is None:
        sha = None
    meta = {
        "schema_version": "1.0.0", "status": code,
        "exact_main_sha": sha, "acceptance_complete": False,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    args.output_meta.parent.mkdir(parents=True, exist_ok=True)
    args.output_meta.write_text(json.dumps(meta, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    if args.output_receipt:
        args.output_receipt.unlink(missing_ok=True)
