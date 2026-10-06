"""Restore production state exclusively from the reducer-owned canonical snapshot."""
from __future__ import annotations
import argparse, os, time
from datetime import datetime
from pathlib import Path

from runtime.artifact_restore import _atomic_write
from state_journal.archive import archived_artifact_ids, load_active_manifest
from state_journal.contracts import DOMAINS, canonical, digest, require, strict_load, validate_domain
from state_journal.github_reducer import latest_snapshot_artifact, restore_snapshot
from state_journal.reducer import validate_snapshot
from state_journal.transport import EVENT_PREFIX, SNAPSHOT_ARTIFACT, GitHubReader

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CACHE = ROOT / "state_journal/live/canonical_restore_cache.json"


def _cache_payload(state: dict, snapshot_meta: dict, *, current_run: str, waited_for_reducer: bool) -> dict:
    require(isinstance(current_run, str) and current_run, "Canonical cache requires run identity")
    meta = {
        "artifact_id": snapshot_meta["id"],
        "artifact_name": SNAPSHOT_ARTIFACT,
        "artifact_created_at": snapshot_meta.get("created_at"),
        "artifact_expires_at": snapshot_meta.get("expires_at"),
        "source_run_id": (snapshot_meta.get("workflow_run") or {}).get("id"),
        "source_head_sha": (snapshot_meta.get("workflow_run") or {}).get("head_sha"),
    }
    core = {
        "schema_version": "1.0.0", "run_id": current_run,
        "state": state, "snapshot_meta": meta,
        "waited_for_reducer": bool(waited_for_reducer),
    }
    return {**core, "cache_hash": digest(core)}


def _load_cache(path: Path, *, current_run: str) -> dict | None:
    if not path.exists():
        return None
    doc = strict_load(path.read_bytes())
    required = {"schema_version","run_id","state","snapshot_meta","waited_for_reducer","cache_hash"}
    require(set(doc) == required and doc["schema_version"] == "1.0.0", "Canonical cache fields changed")
    core = {key: doc[key] for key in required if key != "cache_hash"}
    require(doc["cache_hash"] == digest(core), "Canonical cache hash mismatch")
    require(doc["run_id"] == current_run and bool(current_run), "Canonical cache belongs to another run")
    validate_snapshot(doc["state"])
    require(doc["state"]["mode"] == "CANONICAL" and doc["state"]["production_authority"] is True,
            "Cached snapshot is not production-authoritative")
    return doc


def _known_event_artifact_ids(state: dict) -> set[int]:
    return {
        ref["artifact_id"]
        for refs in state["evidence"].values()
        for ref in refs
        if ref.get("kind") == "GITHUB_ACTIONS"
    }


def _pending_events(state: dict, artifacts: list[dict], *, archived_ids: set[int] | None = None) -> list[dict]:
    known = _known_event_artifact_ids(state)
    known.update(archived_ids or set())
    return [
        artifact for artifact in artifacts
        if artifact.get("name", "").startswith(EVENT_PREFIX)
        and artifact.get("workflow_run", {}).get("head_branch") == "main"
        and artifact.get("expired") is False
        and artifact.get("id") not in known
    ]


def _provider_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _wait_for_reduction(token: str, policy: dict, pending: list[dict], *, current_run: str,
                        archived_ids: set[int] | None = None,
                        timeout_seconds: int = 300, poll_seconds: float = 5.0,
                        clock=time.monotonic, sleep=time.sleep) -> tuple[GitHubReader, dict, list[dict]]:
    require(pending, "Pending-event wait requires at least one event")
    event_times = [_provider_time(row.get("created_at")) for row in pending]
    require(all(at is not None for at in event_times), "Pending-event creation time missing or invalid")
    latest_event_time = max(event_times)
    pending_ids = {row["id"] for row in pending}
    deadline = clock() + timeout_seconds
    seen_reducers: set[int] = set()
    poller = GitHubReader(token, max_requests=policy["limits"]["max_read_requests"])
    while clock() < deadline:
        # Any genuine reducer completion can unblock the production reader.
        # A queued reducer may be created before events it later incorporates.
        # Its completion/update time bounds relevance; verified snapshot coverage
        # remains the proof that every pending event was actually reduced.
        # Scheduled evidence still has its separate, strict acceptance gate.
        # Snapshot validation and pending-artifact coverage remain mandatory.
        runs = poller.get("/actions/runs?branch=main&per_page=50").get("workflow_runs", [])
        require(isinstance(runs, list), "Reducer run listing malformed")
        successes = [
            row for row in runs
            if row.get("name") == "portfolio-state-reducer"
            and row.get("head_branch") == "main"
            and row.get("status") == "completed"
            and row.get("conclusion") == "success"
            and (completed_at := _provider_time(row.get("updated_at"))) is not None
            and completed_at >= latest_event_time
            and type(row.get("id")) is int
        ]
        for reducer_run in sorted(successes, key=lambda row: row["id"]):
            if reducer_run["id"] in seen_reducers:
                continue
            seen_reducers.add(reducer_run["id"])
            fresh = GitHubReader(token, max_requests=policy["limits"]["max_read_requests"])
            artifacts = getattr(fresh, "list_recent_journal_artifacts", fresh.list_recent_artifacts)(
                policy["artifact_scan_start"], max_pages=policy["limits"]["max_artifact_pages"]
            )
            state = restore_snapshot(fresh, artifacts, current_run=current_run)
            known = _known_event_artifact_ids(state) if state is not None else set()
            known.update(archived_ids or set())
            if state is not None and pending_ids <= known:
                return fresh, state, artifacts
        sleep(poll_seconds)
    require(False, "STALE_CANONICAL_STATE_REDUCTION_TIMEOUT")


def restore_domain(domain: str, output: Path, metadata_output: Path | None = None) -> str:
    require(domain in DOMAINS, "Unknown canonical domain")
    policy = strict_load((ROOT / "state_journal/POLICY.json").read_bytes())
    archive_manifest = load_active_manifest(ROOT)
    archive_ids = archived_artifact_ids(archive_manifest)
    require(policy["mode"] == "CANONICAL", "Production canonical mode is not active")
    require(policy["canonical_snapshot_authorized"] is True, "Canonical snapshot is not authorized")
    require(policy["production_readers_enabled"] is True and policy["production_cutover_complete"] is True,
            "Production canonical readers are not enabled")
    current_run = os.environ.get("GITHUB_RUN_ID", "")
    cache_path = Path(os.environ.get("PORTFOLIO_CANONICAL_CACHE", str(DEFAULT_CACHE)))
    cached = _load_cache(cache_path, current_run=current_run)
    if cached is not None:
        state = cached["state"]
        snapshot_meta = {
            "id": cached["snapshot_meta"]["artifact_id"],
            "name": SNAPSHOT_ARTIFACT,
            "created_at": cached["snapshot_meta"]["artifact_created_at"],
            "expires_at": cached["snapshot_meta"]["artifact_expires_at"],
            "workflow_run": {
                "id": cached["snapshot_meta"]["source_run_id"],
                "head_sha": cached["snapshot_meta"]["source_head_sha"],
            },
        }
        waited_for_reducer = cached["waited_for_reducer"]
        restore_status = "RESTORED_CANONICAL_CACHED"
    else:
        token = os.environ.get("GITHUB_TOKEN", "")
        require(bool(token), "GITHUB_TOKEN required for canonical restore")
        reader = GitHubReader(token, max_requests=policy["limits"]["max_read_requests"])
        artifacts = getattr(reader, "list_recent_journal_artifacts", reader.list_recent_artifacts)(
            policy["artifact_scan_start"], max_pages=policy["limits"]["max_artifact_pages"]
        )
        state = restore_snapshot(reader, artifacts, current_run=current_run)
        require(state is not None, "CANONICAL_SNAPSHOT_REQUIRED")
        require(state["mode"] == "CANONICAL" and state["production_authority"] is True,
                "Latest reducer snapshot is not production-authoritative")
        snapshot_meta = latest_snapshot_artifact(artifacts, current_run=current_run)
        require(snapshot_meta is not None, "Canonical snapshot provider metadata missing")
        pending = _pending_events(state, artifacts, archived_ids=archive_ids)
        waited_for_reducer = bool(pending)
        if pending:
            reader, state, artifacts = _wait_for_reduction(
                token, policy, pending, current_run=current_run, archived_ids=archive_ids
            )
            require(state["mode"] == "CANONICAL" and state["production_authority"] is True,
                    "Reducer catch-up snapshot is not production-authoritative")
            require(not _pending_events(state, artifacts, archived_ids=archive_ids),
                    "STALE_CANONICAL_STATE_PENDING_REDUCTION")
            snapshot_meta = latest_snapshot_artifact(artifacts, current_run=current_run)
            require(snapshot_meta is not None, "Canonical snapshot provider metadata missing after reducer wait")
        restore_status = "RESTORED_CANONICAL_AFTER_REDUCER_WAIT" if waited_for_reducer else "RESTORED_CANONICAL"
        cache = _cache_payload(state, snapshot_meta, current_run=current_run, waited_for_reducer=waited_for_reducer)
        _atomic_write(cache_path, canonical(cache) + b"\n")
    projected = state["projection"]["states"]
    require(domain in projected, "Canonical projection missing domain")
    value = projected[domain]
    validate_domain(domain, value)
    _atomic_write(output, canonical(value) + b"\n")
    if metadata_output is not None:
        meta = {
            "schema_version": "1.0.0",
            "restore_status": restore_status,
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
    return restore_status


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--domain", choices=sorted(DOMAINS), required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--metadata-output", type=Path)
    args = ap.parse_args()
    print(restore_domain(args.domain, args.output, args.metadata_output))


if __name__ == "__main__":
    main()
