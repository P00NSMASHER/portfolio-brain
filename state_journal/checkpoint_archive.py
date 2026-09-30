"""Generate a protected repository checkpoint/archive candidate from the latest canonical reducer snapshot."""
from __future__ import annotations

import argparse
import gzip
import json
import os
from datetime import datetime
from pathlib import Path

from runtime.artifact_restore import _atomic_write
from state_journal.archive import archived_provider_artifacts, build_rollover, load_active_manifest
from state_journal.contracts import canonical, require, strict_load
from state_journal.reducer import validate_snapshot
from state_journal.transport import EVENT_PREFIX, SNAPSHOT_ARTIFACT, GitHubReader, artifact_digest, extract_json

ROOT = Path(__file__).resolve().parents[1]


def latest_canonical(reader: GitHubReader) -> tuple[dict, dict, dict]:
    runs = reader.get(
        "/actions/workflows/portfolio-state-reducer.yml/runs"
        "?branch=main&status=success&per_page=20"
    ).get("workflow_runs", [])
    require(isinstance(runs, list), "Reducer run listing malformed")
    for run in runs:
        if not (
            run.get("name") == "portfolio-state-reducer"
            and run.get("path") == ".github/workflows/portfolio-state-reducer.yml"
            and run.get("head_branch") == "main"
            and run.get("status") == "completed"
            and run.get("conclusion") == "success"
            and type(run.get("id")) is int
        ):
            continue
        artifacts = reader.get(f"/actions/runs/{run['id']}/artifacts?per_page=100")
        rows = artifacts.get("artifacts", [])
        require(isinstance(rows, list), "Reducer artifact listing malformed")
        require(artifacts.get("total_count") == len(rows) and len(rows) <= 100,
                "Reducer artifact listing incomplete")
        matches = [
            row for row in rows
            if row.get("name") == SNAPSHOT_ARTIFACT and row.get("expired") is False
        ]
        require(len(matches) <= 1, "Reducer published multiple canonical snapshots")
        if not matches:
            continue
        meta = matches[0]
        raw = reader.archive(meta["id"])
        artifact_digest(meta, raw)
        state = extract_json(raw, "snapshot.json")
        validate_snapshot(state)
        require(state["mode"] == "CANONICAL" and state["production_authority"] is True,
                "Latest reducer snapshot is not production-authoritative")
        return state, run, meta
    raise ValueError("No live canonical reducer snapshot available for checkpoint rollover")


def _safe_previous_manifest_hash(root: Path) -> str | None:
    manifest = load_active_manifest(root)
    return None if manifest is None else manifest["manifest_hash"]


def _recovery_runs_are_archived(policy: dict, state: dict) -> bool:
    recovery = policy.get("recovery_run_ids", [])
    if not recovery:
        return True
    source_runs = {
        ref.get("source_run_id")
        for refs in state["evidence"].values()
        for ref in refs
        if ref.get("kind") == "GITHUB_ACTIONS"
    }
    return all(run_id in source_runs for run_id in recovery)


def _utc(value: str) -> datetime:
    require(isinstance(value, str), "Replay boundary timestamp missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Replay boundary timestamp invalid") from exc
    require(parsed.tzinfo is not None, "Replay boundary requires timezone")
    return parsed


def _known_provider_artifacts(state: dict, active: dict | None) -> dict[int, str]:
    result: dict[int, str] = {}
    for refs in state["evidence"].values():
        for ref in refs:
            if ref.get("kind") != "GITHUB_ACTIONS":
                continue
            artifact_id = ref["artifact_id"]
            archive_digest = ref["archive_digest"]
            old = result.get(artifact_id)
            require(old is None or old == archive_digest,
                    "Canonical provider artifact identity changed")
            result[artifact_id] = archive_digest
    for artifact_id, archive_digest in archived_provider_artifacts(active).items():
        old = result.get(artifact_id)
        require(old is None or old == archive_digest,
                "Archived provider artifact identity changed")
        result[artifact_id] = archive_digest
    return result


def _proposed_scan_start(policy: dict, active: dict | None) -> str:
    current = policy["artifact_scan_start"]
    _utc(current)
    if active is None:
        return current
    previous_source = active["source_artifact_created_at"]
    _utc(previous_source)
    require(_utc(previous_source) >= _utc(current),
            "Active archive source predates current replay boundary")
    return previous_source


def _validate_replay_retention(
    reader: GitHubReader,
    *,
    policy: dict,
    state: dict,
    active: dict | None,
    proposed_scan_start: str,
) -> dict:
    current_scan_start = policy["artifact_scan_start"]
    current_at = _utc(current_scan_start)
    proposed_at = _utc(proposed_scan_start)
    require(proposed_at >= current_at,
            "Checkpoint rollover may not widen replay history implicitly")
    rows = reader.list_recent_artifacts(
        current_scan_start,
        max_pages=policy["limits"]["max_artifact_pages"],
    )
    known = _known_provider_artifacts(state, active)
    covered = 0
    retained = 0
    scanned = 0
    for row in rows:
        if not (
            row.get("name", "").startswith(EVENT_PREFIX)
            and row.get("workflow_run", {}).get("head_branch") == "main"
        ):
            continue
        scanned += 1
        artifact_id = row.get("id")
        require(type(artifact_id) is int and artifact_id > 0,
                "Replay event artifact identity missing")
        expected_digest = known.get(artifact_id)
        if expected_digest is not None:
            require(row.get("digest") == expected_digest,
                    "Previously consumed replay artifact digest changed")
            covered += 1
            continue
        require(row.get("expired") is False,
                f"Expired unconsumed replay evidence: artifact {artifact_id}")
        created_at = _utc(row.get("created_at"))
        if created_at < proposed_at:
            require(False,
                    f"Checkpoint would drop unconsumed replay event artifact {artifact_id}")
        retained += 1
    return {
        "current_scan_start": current_scan_start,
        "proposed_scan_start": proposed_scan_start,
        "scanned_journal_events": scanned,
        "covered_journal_events": covered,
        "retained_replay_events": retained,
    }


def generate(root: Path, *, reader: GitHubReader) -> dict:
    policy_path = root / "state_journal" / "POLICY.json"
    policy = strict_load(policy_path.read_bytes())
    state, run, artifact = latest_canonical(reader)
    active = load_active_manifest(root)
    if active is not None and active["archived_sequence"] >= state["sequence"]:
        return {
            "status": "NOOP",
            "reason": "ACTIVE_ARCHIVE_IS_CURRENT",
            "archived_sequence": active["archived_sequence"],
            "source_sequence": state["sequence"],
        }

    require(_recovery_runs_are_archived(policy, state),
            "Recovery run ids are not all represented in canonical evidence")
    proposed_scan_start = _proposed_scan_start(policy, active)
    if active is not None:
        require(state["checkpoint"]["checkpoint_hash"] == active["new_checkpoint_hash"],
                "Canonical source does not descend from active checkpoint lineage")
        require(_utc(artifact["created_at"]) > _utc(active["source_artifact_created_at"]),
                "Checkpoint source freshness did not advance")
    retention = _validate_replay_retention(
        reader,
        policy=policy,
        state=state,
        active=active,
        proposed_scan_start=proposed_scan_start,
    )
    manifest, archive_raw, checkpoint_doc, checkpoint_raw, archive_path = build_rollover(
        state,
        source_reducer_run_id=run["id"],
        source_artifact_id=artifact["id"],
        source_head_sha=run["head_sha"],
        source_artifact_digest=artifact["digest"],
        source_artifact_created_at=artifact["created_at"],
        artifact_scan_start=proposed_scan_start,
        previous_manifest_hash=_safe_previous_manifest_hash(root),
    )
    archive_file = root / archive_path
    immutable_manifest = root / manifest["manifest_path"]
    archive_file.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(archive_file, archive_raw)
    _atomic_write(immutable_manifest, canonical(manifest) + b"\n")
    _atomic_write(root / "state_journal" / "ARCHIVE_MANIFEST.json", canonical(manifest) + b"\n")
    _atomic_write(root / "state_journal" / "CHECKPOINT.json.gz", checkpoint_raw)
    validated = load_active_manifest(root)
    require(validated is not None and validated["manifest_hash"] == manifest["manifest_hash"],
            "Written checkpoint/archive lineage did not validate")

    policy["artifact_scan_start"] = manifest["artifact_scan_start"]
    policy["recovery_run_ids"] = []
    _atomic_write(policy_path, json.dumps(policy, sort_keys=True, indent=2).encode("utf-8") + b"\n")
    return {
        "status": "PASS",
        "archive_id": manifest["archive_id"],
        "manifest_hash": manifest["manifest_hash"],
        "archived_sequence": manifest["archived_sequence"],
        "checkpoint_sequence": manifest["checkpoint_sequence"],
        "archived_state_hash": manifest["archived_state_hash"],
        "new_checkpoint_hash": checkpoint_doc["checkpoint_hash"],
        "archive_path": archive_path,
        "source_reducer_run_id": run["id"],
        "source_artifact_id": artifact["id"],
        "source_artifact_digest": artifact["digest"],
        "artifact_scan_start": manifest["artifact_scan_start"],
        "replay_retention": retention,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, default=Path("state_journal/out/checkpoint_archive_receipt.json"))
    args = parser.parse_args()
    token = os.environ.get("GITHUB_TOKEN", "")
    require(bool(token), "GITHUB_TOKEN required to create checkpoint/archive candidate")
    root = args.root.resolve()
    policy = strict_load((root / "state_journal" / "POLICY.json").read_bytes())
    result = generate(
        root,
        reader=GitHubReader(token, max_requests=policy["limits"]["max_read_requests"]),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(args.output, canonical(result) + b"\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
