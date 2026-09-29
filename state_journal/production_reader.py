"""Restore production state exclusively from the reducer-owned canonical snapshot."""
from __future__ import annotations
import argparse, os
from pathlib import Path

from runtime.artifact_restore import _atomic_write
from state_journal.contracts import DOMAINS, canonical, digest, require, strict_load, validate_domain
from state_journal.github_reducer import restore_snapshot
from state_journal.reducer import validate_snapshot
from state_journal.transport import EVENT_PREFIX, SNAPSHOT_ARTIFACT, GitHubReader, artifact_digest, extract_json

ROOT = Path(__file__).resolve().parents[1]


def restore_domain(domain: str, output: Path, metadata_output: Path | None = None) -> str:
    require(domain in DOMAINS, "Unknown canonical domain")
    policy = strict_load((ROOT / "state_journal/POLICY.json").read_bytes())
    require(policy["mode"] == "CANONICAL", "Production canonical mode is not active")
    require(policy["canonical_snapshot_authorized"] is True, "Canonical snapshot is not authorized")
    require(policy["production_readers_enabled"] is True and policy["production_cutover_complete"] is True,
            "Production canonical readers are not enabled")
    token = os.environ.get("GITHUB_TOKEN", "")
    require(bool(token), "GITHUB_TOKEN required for canonical restore")
    reader = GitHubReader(token, max_requests=policy["limits"]["max_read_requests"])
    artifacts = reader.list_recent_artifacts(
        policy["artifact_scan_start"], max_pages=policy["limits"]["max_artifact_pages"]
    )
    current_run = os.environ.get("GITHUB_RUN_ID", "")
    state = restore_snapshot(reader, artifacts, current_run=current_run)
    require(state is not None, "CANONICAL_SNAPSHOT_REQUIRED")
    require(state["mode"] == "CANONICAL" and state["production_authority"] is True,
            "Latest reducer snapshot is not production-authoritative")
    matching_snapshot_artifacts = []
    for artifact in artifacts:
        if artifact.get("name") != SNAPSHOT_ARTIFACT:
            continue
        source = artifact.get("workflow_run", {})
        if source.get("head_branch") != "main" or str(source.get("id")) == str(current_run) or artifact.get("expired"):
            continue
        raw = reader.archive(artifact["id"])
        artifact_digest(artifact, raw)
        candidate = extract_json(raw, "snapshot.json")
        validate_snapshot(candidate)
        if candidate["state_hash"] == state["state_hash"]:
            matching_snapshot_artifacts.append(artifact)
    require(matching_snapshot_artifacts, "Canonical snapshot provider metadata missing")
    snapshot_meta = max(
        matching_snapshot_artifacts,
        key=lambda row: (row.get("created_at", ""), row.get("id", 0)),
    )
    known_artifacts = {
        ref["artifact_id"]
        for refs in state["evidence"].values()
        for ref in refs
        if ref.get("kind") == "GITHUB_ACTIONS"
    }
    pending = [
        a for a in artifacts
        if a.get("name", "").startswith(EVENT_PREFIX)
        and a.get("workflow_run", {}).get("head_branch") == "main"
        and a.get("id") not in known_artifacts
    ]
    require(not pending, "STALE_CANONICAL_STATE_PENDING_REDUCTION")
    projected = state["projection"]["states"]
    require(domain in projected, "Canonical projection missing domain")
    value = projected[domain]
    validate_domain(domain, value)
    _atomic_write(output, canonical(value) + b"\n")
    if metadata_output is not None:
        meta = {
            "schema_version": "1.0.0",
            "restore_status": "RESTORED_CANONICAL",
            "domain": domain,
            "canonical_sequence": state["sequence"],
            "canonical_state_hash": state["state_hash"],
            "domain_state_hash": digest(value),
            "event_count": state["event_count"],
            "artifact_id": snapshot_meta["id"],
            "artifact_name": SNAPSHOT_ARTIFACT,
            "artifact_created_at": snapshot_meta.get("created_at"),
            "artifact_expires_at": snapshot_meta.get("expires_at"),
            "source_run_id": (snapshot_meta.get("workflow_run") or {}).get("id"),
            "source_head_sha": (snapshot_meta.get("workflow_run") or {}).get("head_sha"),
            "source_sequence": value["sequence"],
            "source_state_hash": digest(value),
        }
        _atomic_write(metadata_output, canonical(meta) + b"\n")
    return "RESTORED_CANONICAL"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--domain", choices=sorted(DOMAINS), required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--metadata-output", type=Path)
    args = ap.parse_args()
    print(restore_domain(args.domain, args.output, args.metadata_output))


if __name__ == "__main__":
    main()