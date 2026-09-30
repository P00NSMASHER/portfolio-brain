#!/usr/bin/env python3
"""Restore newest sanitized persistent-agent heartbeat artifact."""
from __future__ import annotations

import argparse
import io
import json
import os
import time
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from runtime.artifact_http import open_url
from runtime.artifact_restore import InvalidStateArtifact
from runtime.artifact_restore import restore_latest_valid_state
from agents.heartbeat_state import ARTIFACT_NAME, validate_state

ROOT = Path(__file__).resolve().parents[1]


class RestoreError(RuntimeError):
    pass


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise InvalidStateArtifact("agent heartbeat timestamp requires timezone")
    return parsed.astimezone(timezone.utc)


def _state_from_archive(raw: bytes) -> dict:
    if len(raw) > 1_048_576:
        raise InvalidStateArtifact("agent heartbeat artifact exceeds byte budget")
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            matches = [
                info for info in archive.infolist()
                if info.filename == "agent_heartbeat_state.json" and not info.is_dir()
            ]
            if len(matches) != 1 or matches[0].file_size > 1_048_576:
                raise InvalidStateArtifact("agent heartbeat artifact member invalid")
            body = archive.read(matches[0])
    except (zipfile.BadZipFile, RuntimeError, OSError) as exc:
        raise InvalidStateArtifact("agent heartbeat artifact unreadable") from exc
    try:
        state = json.loads(body.decode("utf-8"))
        validate_state(state)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise InvalidStateArtifact("agent heartbeat artifact state invalid") from exc
    return state


def _later_equivalent_single_heartbeat(winner: dict, other: dict) -> bool:
    if winner["sequence"] != other["sequence"]:
        return False
    if len(winner["recent_events"]) != len(other["recent_events"]):
        return False
    if not winner["recent_events"] or winner["recent_events"][:-1] != other["recent_events"][:-1]:
        return False

    winner_event = winner["recent_events"][-1]
    other_event = other["recent_events"][-1]
    for key in ("agent_id", "activity_kind", "source_workflow", "work_ids"):
        if winner_event.get(key) != other_event.get(key):
            return False
    if _utc(winner_event["at"]) <= _utc(other_event["at"]):
        return False

    agent_id = winner_event["agent_id"]
    differing_agents = [
        aid for aid in winner["agents"]
        if winner["agents"][aid] != other["agents"][aid]
    ]
    if differing_agents != [agent_id]:
        return False
    winner_row = winner["agents"][agent_id]
    other_row = other["agents"][agent_id]
    for key in ("role_key", "status", "recent_work_ids", "last_activity_kind", "source_workflow"):
        if winner_row.get(key) != other_row.get(key):
            return False
    if winner_row.get("last_heartbeat_at") != winner_event["at"]:
        return False
    if other_row.get("last_heartbeat_at") != other_event["at"]:
        return False
    if winner_row.get("source_run_id") != winner_event["source_run_id"]:
        return False
    if other_row.get("source_run_id") != other_event["source_run_id"]:
        return False
    if winner["updated_at"] != winner_event["at"] or other["updated_at"] != other_event["at"]:
        return False
    return True


def _full_health_sweep(state: dict) -> tuple[list[dict], list[dict]] | None:
    agent_ids = set(state["agents"])
    count = len(agent_ids)
    if count < 1 or len(state["recent_events"]) < count:
        return None
    prefix = state["recent_events"][:-count]
    suffix = state["recent_events"][-count:]
    if {event.get("agent_id") for event in suffix} != agent_ids:
        return None
    if any(
        event.get("activity_kind") != "HEALTH_CHECK"
        or event.get("source_workflow") != "agent-heartbeat-sweep"
        or event.get("work_ids") != []
        for event in suffix
    ):
        return None
    ats = {event.get("at") for event in suffix}
    run_ids = {event.get("source_run_id") for event in suffix}
    if len(ats) != 1 or len(run_ids) != 1:
        return None
    return prefix, suffix


def _later_equivalent_health_sweep(winner: dict, other: dict) -> bool:
    if winner["sequence"] != other["sequence"]:
        return False
    winner_parts = _full_health_sweep(winner)
    other_parts = _full_health_sweep(other)
    if winner_parts is None or other_parts is None:
        return False
    winner_prefix, winner_sweep = winner_parts
    other_prefix, other_sweep = other_parts
    if winner_prefix != other_prefix:
        return False

    winner_by_agent = {event["agent_id"]: event for event in winner_sweep}
    other_by_agent = {event["agent_id"]: event for event in other_sweep}
    if set(winner_by_agent) != set(other_by_agent):
        return False
    winner_at = next(iter(winner_by_agent.values()))["at"]
    other_at = next(iter(other_by_agent.values()))["at"]
    if _utc(winner_at) <= _utc(other_at):
        return False

    for agent_id in sorted(winner["agents"]):
        winner_event = winner_by_agent[agent_id]
        other_event = other_by_agent[agent_id]
        for key in ("agent_id", "activity_kind", "source_workflow", "work_ids"):
            if winner_event.get(key) != other_event.get(key):
                return False

        winner_row = winner["agents"][agent_id]
        other_row = other["agents"][agent_id]
        for key in ("role_key", "status", "recent_work_ids", "last_activity_kind", "source_workflow"):
            if winner_row.get(key) != other_row.get(key):
                return False
        if winner_row.get("last_heartbeat_at") != winner_event["at"]:
            return False
        if other_row.get("last_heartbeat_at") != other_event["at"]:
            return False
        if winner_row.get("source_run_id") != winner_event["source_run_id"]:
            return False
        if other_row.get("source_run_id") != other_event["source_run_id"]:
            return False

    if winner["updated_at"] != winner_at or other["updated_at"] != other_at:
        return False
    return True


def _later_equivalent_heartbeat_batch(winner: dict, other: dict) -> bool:
    if winner["sequence"] != other["sequence"]:
        return False
    winner_events = winner["recent_events"]
    other_events = other["recent_events"]
    if len(winner_events) != len(other_events) or not winner_events:
        return False

    prefix_length = 0
    while (
        prefix_length < len(winner_events)
        and winner_events[prefix_length] == other_events[prefix_length]
    ):
        prefix_length += 1
    winner_suffix = winner_events[prefix_length:]
    other_suffix = other_events[prefix_length:]
    if not winner_suffix or not other_suffix:
        return False
    winner_by_agent = {event["agent_id"]: event for event in winner_suffix}
    other_by_agent = {event["agent_id"]: event for event in other_suffix}
    if (
        len(winner_by_agent) != len(winner_suffix)
        or len(other_by_agent) != len(other_suffix)
        or set(winner_by_agent) != set(other_by_agent)
    ):
        return False

    winner_times = {event["at"] for event in winner_suffix}
    other_times = {event["at"] for event in other_suffix}
    if len(winner_times) != 1 or len(other_times) != 1:
        return False
    winner_at = next(iter(winner_times))
    other_at = next(iter(other_times))
    if _utc(winner_at) <= _utc(other_at):
        return False
    if len({(event["activity_kind"], event["source_workflow"]) for event in winner_suffix}) != 1:
        return False
    if len({(event["activity_kind"], event["source_workflow"]) for event in other_suffix}) != 1:
        return False
    if len({event["source_run_id"] for event in winner_suffix}) != 1:
        return False
    if len({event["source_run_id"] for event in other_suffix}) != 1:
        return False
    differing_agents = {
        agent_id
        for agent_id in winner["agents"]
        if winner["agents"][agent_id] != other["agents"][agent_id]
    }
    if differing_agents != set(winner_by_agent):
        return False

    for agent_id, winner_event in winner_by_agent.items():
        other_event = other_by_agent[agent_id]
        for key in ("agent_id", "activity_kind", "source_workflow", "work_ids"):
            if winner_event.get(key) != other_event.get(key):
                return False

        winner_row = winner["agents"][agent_id]
        other_row = other["agents"][agent_id]
        for key in ("role_key", "status", "recent_work_ids", "last_activity_kind", "source_workflow"):
            if winner_row.get(key) != other_row.get(key):
                return False
        if winner_row.get("last_heartbeat_at") != winner_event["at"]:
            return False
        if other_row.get("last_heartbeat_at") != other_event["at"]:
            return False
        if winner_row.get("source_run_id") != winner_event["source_run_id"]:
            return False
        if other_row.get("source_run_id") != other_event["source_run_id"]:
            return False

    return winner["updated_at"] == winner_at and other["updated_at"] == other_at


def _later_equivalent_heartbeat(winner: dict, other: dict) -> bool:
    return (
        _later_equivalent_single_heartbeat(winner, other)
        or _later_equivalent_heartbeat_batch(winner, other)
        or _later_equivalent_health_sweep(winner, other)
    )


def _resolve_equivalent_heartbeat_fork(
    data: dict,
    *,
    current_run: str | None,
    expected_head_branch: str | None,
    download,
    max_candidates: int = 5,
) -> tuple[dict, list[int]]:
    candidates = [
        item
        for item in data.get("artifacts", [])
        if not item.get("expired")
        and str((item.get("workflow_run") or {}).get("id")) != str(current_run)
        and (
            expected_head_branch is None
            or (item.get("workflow_run") or {}).get("head_branch") == expected_head_branch
        )
    ]
    candidates.sort(key=lambda item: (item.get("created_at", ""), item.get("id", 0)), reverse=True)
    valid = []
    for item in candidates[:max_candidates]:
        url = item.get("archive_download_url")
        if not isinstance(url, str) or not url:
            continue
        try:
            state = _state_from_archive(download(url))
        except Exception:
            continue
        valid.append((item, state))
    if len(valid) < 2:
        raise InvalidStateArtifact("agent heartbeat fork recovery requires two valid candidates")
    highest_sequence = max(state["sequence"] for _, state in valid)
    highest = [entry for entry in valid if entry[1]["sequence"] == highest_sequence]
    if len(highest) < 2:
        raise InvalidStateArtifact("agent heartbeat fork recovery found no highest-sequence fork")

    winners = []
    for entry in highest:
        item, state = entry
        if all(
            other is entry or _later_equivalent_heartbeat(state, other[1])
            for other in highest
        ):
            winners.append(entry)
    if len(winners) != 1:
        raise InvalidStateArtifact("agent heartbeat fork has no unique later equivalent update")
    return {"artifacts": [winners[0][0]]}, [int(entry[0].get("id")) for entry in highest]


def restore(output: Path, metadata_output: Path | None = None) -> str:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("PORTFOLIO_GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    run = os.environ.get("GITHUB_RUN_ID")
    if not token or not repo:
        return "NO_ACTIONS_CONTEXT"
    used = 0

    def get(url: str) -> bytes:
        nonlocal used
        last = None
        for attempt in range(3):
            if used >= 6:
                raise RestoreError("agent heartbeat artifact request budget exceeded")
            used += 1
            request = urllib.request.Request(
                url,
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {token}",
                    "X-GitHub-Api-Version": "2022-11-28",
                    "User-Agent": "portfolio-brain-agent-heartbeat/1.0",
                },
                method="GET",
            )
            try:
                with open_url(request, timeout=20) as response:
                    return response.read()
            except Exception as exc:
                last = exc
                if attempt < 2:
                    time.sleep(attempt + 1)
        raise RestoreError(str(last))

    data = json.loads(
        get(f"https://api.github.com/repos/{repo}/actions/artifacts?name={ARTIFACT_NAME}&per_page=100").decode()
    )
    cache: dict[str, bytes] = {}
    def download(url: str) -> bytes:
        if url not in cache:
            cache[url] = get(url)
        return cache[url]
    try:
        return restore_latest_valid_state(
            data,
            current_run=run,
            expected_head_branch=os.environ.get("GITHUB_REF_NAME"),
            download=download,
            output=output,
            member_name="agent_heartbeat_state.json",
            expected_state_id="portfolio-agent-heartbeat-state",
            max_archive_bytes=1_048_576,
            max_state_bytes=1_048_576,
            validator=validate_state,
            metadata_output=metadata_output,
        )
    except InvalidStateArtifact as exc:
        if str(exc) != "conflicting state artifacts at highest sequence":
            raise
        recovered, fork_ids = _resolve_equivalent_heartbeat_fork(
            data,
            current_run=run,
            expected_head_branch=os.environ.get("GITHUB_REF_NAME"),
            download=download,
        )
        restore_latest_valid_state(
            recovered,
            current_run=run,
            expected_head_branch=os.environ.get("GITHUB_REF_NAME"),
            download=download,
            output=output,
            member_name="agent_heartbeat_state.json",
            expected_state_id="portfolio-agent-heartbeat-state",
            max_archive_bytes=1_048_576,
            max_state_bytes=1_048_576,
            validator=validate_state,
            metadata_output=metadata_output,
        )
        return "RESTORED_LATER_EQUIVALENT_HEARTBEAT_AFTER_CONCURRENT_FORK_" + "_".join(map(str, fork_ids))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--metadata-output", default=None)
    args = parser.parse_args()
    print(
        restore(
            Path(args.output),
            None if args.metadata_output is None else Path(args.metadata_output),
        )
    )


if __name__ == "__main__":
    main()
