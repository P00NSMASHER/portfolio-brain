#!/usr/bin/env python3
"""Restore durable Portfolio Brain state for the read-only command center.

This bridge is intentionally OBSERVE-only. It restores sanitized GitHub Actions
artifacts into a temporary dashboard/live directory for rendering. If a valid
artifact is unavailable, it falls back to the checked-in seed and labels that
source explicitly. Stale artifacts are used but labeled STALE.
"""
from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from cost_governor.artifact_state import restore as restore_cost
from hunting.artifact_state import restore as restore_hunter
from notifications.artifact_state import restore as restore_notifications
from runtime.artifact_state import restore as restore_runtime
from runtime.state import bootstrap_state, validate_state as validate_runtime_state
from scheduler.artifact_state import restore as restore_scheduler

ROOT = Path(__file__).resolve().parents[1]

STALE_AFTER_MINUTES = {
    "runtime": 150,
    "scheduler": 150,
    "hunter": 450,
    "cost": 60,
    "notifications": 450,
}

SEEDS = {
    "scheduler": "scheduler/SCHEDULER_STATE_SEED.json",
    "hunter": "hunting/HUNTER_STATE_SEED.json",
    "cost": "cost_governor/COST_STATE_SEED.json",
    "notifications": "notifications/NOTIFICATION_STATE_SEED.json",
}

RESTORERS: dict[str, Callable[..., str]] = {
    "runtime": restore_runtime,
    "scheduler": restore_scheduler,
    "hunter": restore_hunter,
    "cost": restore_cost,
    "notifications": restore_notifications,
}


class LiveStateBridgeError(ValueError):
    pass


def _time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise LiveStateBridgeError("timestamp requires timezone")
    return parsed.astimezone(timezone.utc)


def _now_iso(now: datetime) -> str:
    return now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _state_filename(name: str) -> str:
    return {
        "runtime": "runtime_state.json",
        "scheduler": "scheduler_state.json",
        "hunter": "hunter_state.json",
        "cost": "cost_state.json",
        "notifications": "notification_state.json",
    }[name]


def _fallback(name: str, output: Path, *, now: datetime) -> str:
    output.parent.mkdir(parents=True, exist_ok=True)
    if name == "runtime":
        state = bootstrap_state(now=_now_iso(now))
        validate_runtime_state(state)
        output.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return "adapters/cursors/repositories.json"
    seed = ROOT / SEEDS[name]
    shutil.copyfile(seed, output)
    return SEEDS[name]


def _classify(meta: dict[str, Any], *, now: datetime, stale_after_minutes: int) -> tuple[str, float | None]:
    created = meta.get("artifact_created_at")
    if not isinstance(created, str) or not created:
        return "FALLBACK", None
    age = max(0.0, (now - _time(created)).total_seconds() / 60.0)
    return ("STALE" if age > stale_after_minutes else "LIVE"), round(age, 1)


def build_live_state(
    *,
    output_dir: Path,
    receipt_path: Path,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    output_dir.mkdir(parents=True, exist_ok=True)
    metadata_dir = output_dir / ".restore-metadata"
    metadata_dir.mkdir(parents=True, exist_ok=True)

    sources: dict[str, Any] = {}
    for name, restorer in RESTORERS.items():
        state_path = output_dir / _state_filename(name)
        metadata_path = metadata_dir / f"{name}.json"
        restore_status = "RESTORE_ERROR"
        error_class = None
        try:
            if name == "runtime":
                restore_status = restorer(output=state_path, metadata_output=metadata_path)
            else:
                restore_status = restorer(state_path, metadata_path)
        except Exception as exc:
            error_class = type(exc).__name__
            restore_status = "RESTORE_ERROR"

        metadata: dict[str, Any] = {}
        if metadata_path.exists():
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

        if restore_status.startswith("RESTORED") and state_path.exists():
            freshness, age = _classify(
                metadata,
                now=now,
                stale_after_minutes=STALE_AFTER_MINUTES[name],
            )
            source_ref = metadata.get("artifact_name")
            source_kind = "GITHUB_ACTIONS_ARTIFACT"
        else:
            source_ref = _fallback(name, state_path, now=now)
            source_kind = "CHECKED_IN_SEED"
            freshness = "FALLBACK"
            age = None

        state = json.loads(state_path.read_text(encoding="utf-8"))
        sources[name] = {
            "status": freshness,
            "source_kind": source_kind,
            "source_ref": source_ref,
            "restore_status": restore_status,
            "source_run_id": metadata.get("source_run_id"),
            "source_head_sha": metadata.get("source_head_sha"),
            "artifact_id": metadata.get("artifact_id"),
            "artifact_created_at": metadata.get("artifact_created_at"),
            "artifact_expires_at": metadata.get("artifact_expires_at"),
            "age_minutes": age,
            "stale_after_minutes": STALE_AFTER_MINUTES[name],
            "state_sequence": state.get("sequence"),
            "state_updated_at": state.get("updated_at"),
            "error_class": error_class,
        }

    statuses = {item["status"] for item in sources.values()}
    bridge_status = "LIVE" if statuses == {"LIVE"} else ("DEGRADED" if "FALLBACK" in statuses else "STALE")
    receipt = {
        "schema_version": "1.0.0",
        "bridge_id": "portfolio-command-center-live-state-v1",
        "authority_class": "OBSERVE",
        "mutation_capability": "NONE",
        "generated_at": _now_iso(now),
        "bridge_status": bridge_status,
        "sources": sources,
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description="Restore command-center durable state")
    parser.add_argument("--output-dir", default="dashboard/live")
    parser.add_argument("--receipt", default="dashboard/live/state_sources.json")
    parser.add_argument("--now", default=None)
    args = parser.parse_args()
    now = None if args.now is None else _time(args.now)
    receipt = build_live_state(
        output_dir=Path(args.output_dir),
        receipt_path=Path(args.receipt),
        now=now,
    )
    print(json.dumps({
        "bridge_status": receipt["bridge_status"],
        "sources": {k: v["status"] for k, v in receipt["sources"].items()},
    }, sort_keys=True))


if __name__ == "__main__":
    main()
