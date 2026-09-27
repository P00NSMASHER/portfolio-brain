#!/usr/bin/env python3
"""Suppress public command-center deployment when only volatile metadata changed."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

VOLATILE_KEYS = {
    "snapshot_hash", "generated_at", "age_minutes", "artifact_id",
    "source_run_id", "source_head_sha", "artifact_created_at", "artifact_expires_at",
}

def material(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: material(item)
            for key, item in sorted(value.items())
            if key not in VOLATILE_KEYS
        }
    if isinstance(value, list):
        return [material(item) for item in value]
    return value

def fingerprint(value: dict[str, Any]) -> str:
    raw = json.dumps(material(value), sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(raw).hexdigest()

def should_publish(current: dict[str, Any], previous: dict[str, Any] | None) -> bool:
    if previous is None or fingerprint(current) != fingerprint(previous):
        return True
    # A static page needs a fresh timestamp even if its state is otherwise unchanged.
    # This does not assert that the underlying work succeeded; the UI checks both.
    def bridge_time(snapshot: dict[str, Any]) -> datetime | None:
        value = snapshot.get("state_sources", {}).get("generated_at")
        if not isinstance(value, str):
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

    now, then = bridge_time(current), bridge_time(previous)
    return now is not None and (then is None or (now - then).total_seconds() >= 60 * 60)

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--current", required=True)
    parser.add_argument("--previous", default=None)
    args = parser.parse_args()
    current = json.loads(Path(args.current).read_text())
    previous = None
    if args.previous and Path(args.previous).exists():
        try:
            previous = json.loads(Path(args.previous).read_text())
        except (OSError, json.JSONDecodeError):
            previous = None
    print("true" if should_publish(current, previous) else "false")

if __name__ == "__main__":
    main()
