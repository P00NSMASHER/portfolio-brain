"""Generate a protected repository checkpoint/archive candidate from the latest canonical reducer snapshot."""
from __future__ import annotations

import argparse
import gzip
import json
import os
from pathlib import Path

from runtime.artifact_restore import _atomic_write
from state_journal.archive import ACTIVE_MANIFEST, build_rollover, load_active_manifest
from state_journal.contracts import MAX_SNAPSHOT_BYTES, canonical, require, strict_load
from state_journal.reducer import validate_snapshot
from state_journal.transport import SNAPSHOT_ARTIFACT, GitHubReader, artifact_digest, extract_json

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
        state = extract_json(raw, "snapshot.json", max_bytes=MAX_SNAPSHOT_BYTES)
        validate_snapshot(state)
        require(state["mode"] == "CANONICAL" and state["production_authority"] is True,
                "Latest reducer snapshot is not production-authoritative")
        return state, run, meta
    raise ValueError("No live canonical reducer snapshot available for checkpoint rollover")


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
    manifest, archive_raw, checkpoint_doc, checkpoint_raw, archive_path = build_rollover(
        state,
        source_reducer_run_id=run["id"],
        source_artifact_id=artifact["id"],
        source_head_sha=run["head_sha"],
        source_artifact_digest=artifact["digest"],
        source_artifact_created_at=artifact["created_at"],
        previous_manifest=active,
    )
    archive_file = root / archive_path
    immutable_manifest = root / manifest["manifest_path"]
    archive_file.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(archive_file, archive_raw)
    _atomic_write(immutable_manifest, canonical(manifest) + b"\n")
    _atomic_write(root / "state_journal" / "ARCHIVE_MANIFEST.json", canonical(manifest) + b"\n")
    _atomic_write(root / "state_journal" / "CHECKPOINT.json.gz", checkpoint_raw)

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
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, default=Path("state_journal/out/checkpoint_archive_receipt.json"))
    args = parser.parse_args()
    token = os.environ.get("GITHUB_TOKEN", "")
    require(bool(token), "GITHUB_TOKEN required to create checkpoint/archive candidate")
    result = generate(args.root.resolve(), reader=GitHubReader(token, max_requests=40))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(args.output, canonical(result) + b"\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
