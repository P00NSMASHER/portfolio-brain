"""Single shadow reducer workflow entry point. Never changes production readers."""
from __future__ import annotations
import argparse
import gzip
import json
import os
from pathlib import Path

from runtime.artifact_restore import _atomic_write
from state_journal.archive import (
    archived_event_hashes as manifest_event_hashes,
    archived_provider_artifacts as manifest_provider_artifacts,
    load_active_manifest,
)
from state_journal.contracts import (
    REPOSITORY, Conflict, JournalError, MissingPredecessor, canonical, digest, require, strict_load,
)
from state_journal.reducer import make_snapshot, validate_snapshot, validate_checkpoint, advance, set_authority
from state_journal.legacy_parity import verify as verify_legacy_parity
from state_journal.provider_quarantine import reducer_run_is_quarantined
from state_journal.transport import EVENT_PREFIX, SNAPSHOT_ARTIFACT, GitHubReader, artifact_digest, extract_json

ROOT = Path(__file__).resolve().parents[1]


def snapshot_candidates(artifacts: list[dict], *, current_run: str) -> list[dict]:
    candidates = [a for a in artifacts if a.get("name") == SNAPSHOT_ARTIFACT
                  and a.get("workflow_run", {}).get("head_branch") == "main"
                  and not reducer_run_is_quarantined(a.get("workflow_run", {}).get("id"))
                  and str(a.get("workflow_run", {}).get("id")) != current_run]
    if not candidates:
        return []
    require(any(not a.get("expired") for a in candidates), "Canonical journal expired; explicit recovery required")
    active = [a for a in candidates if not a.get("expired")]
    # The sole reducer is serialized and publishes exactly one snapshot only
    # after a successful replay step. Provider creation order therefore is the
    # canonical publication order; historical snapshot count must never become
    # a permanent reader outage.
    return sorted(active, key=lambda a: (str(a.get("created_at") or ""), a.get("id", 0)), reverse=True)


def latest_snapshot_artifact(artifacts: list[dict], *, current_run: str) -> dict | None:
    candidates = snapshot_candidates(artifacts, current_run=current_run)
    return candidates[0] if candidates else None


def _restore_snapshot_artifact(reader: GitHubReader, artifact: dict) -> dict:
    source = artifact.get("workflow_run", {})
    cached_run = getattr(reader, "snapshot_source_run", None)
    run = cached_run(artifact["id"]) if callable(cached_run) else None
    if run is not None:
        require(run.get("id") == source.get("id"), "Snapshot source run identity mismatch")
    else:
        run = reader.get(f"/actions/runs/{source['id']}")
    require(run.get("path") == ".github/workflows/portfolio-state-reducer.yml", "Snapshot did not come from sole reducer workflow")
    require(run.get("head_branch") == "main" and run.get("head_sha") == source.get("head_sha"), "Snapshot source SHA/branch mismatch")
    require(run.get("status") == "completed" and run.get("conclusion") == "success", "Snapshot producer did not succeed")
    require(run.get("repository", {}).get("full_name") == REPOSITORY and run.get("head_repository", {}).get("full_name") == REPOSITORY,
            "Snapshot source fork mismatch")
    raw = reader.archive(artifact["id"]); artifact_digest(artifact, raw)
    state = extract_json(raw, "snapshot.json"); validate_snapshot(state)
    return state


def restore_snapshot(reader: GitHubReader, artifacts: list[dict], *, current_run: str) -> dict | None:
    candidates = snapshot_candidates(artifacts, current_run=current_run)
    if not candidates:
        return None
    latest = _restore_snapshot_artifact(reader, candidates[0])
    if len(candidates) > 1:
        predecessor = _restore_snapshot_artifact(reader, candidates[1])
        require(latest["sequence"] >= predecessor["sequence"], "Canonical snapshot sequence regressed")
        if latest["sequence"] == predecessor["sequence"]:
            selected = select_latest_snapshot([predecessor, latest])
            require(selected["state_hash"] == latest["state_hash"],
                    "Latest snapshot does not preserve same-sequence canonical authority")
    return latest


def _runtime_observation_change(event: dict) -> dict | None:
    if event.get("producer") != "runtime-worker":
        return None
    for change in event.get("changes", []):
        if change.get("domain") != "runtime":
            continue
        receipt = (change.get("proofs") or {}).get("cycle_receipt")
        if isinstance(receipt, dict) and receipt.get("mode") == "observe":
            return change
    return None


def _authority_payload(state: dict) -> dict:
    return {
        key: state[key]
        for key in (
            "schema_version", "state_id", "sequence", "checkpoint", "events",
            "evidence", "projection", "event_count",
        )
    }


def select_latest_snapshot(states: list[dict]) -> dict:
    require(states, "No valid canonical snapshots")
    highest = max(s["sequence"] for s in states)
    latest = [s for s in states if s["sequence"] == highest]
    by_hash = {digest(s): s for s in latest}
    if len(by_hash) == 1:
        return next(iter(by_hash.values()))
    candidates = [
        s for s in by_hash.values()
        if s["mode"] == "CANONICAL" and s["production_authority"] is True
    ]
    if len(candidates) == 1:
        promoted = candidates[0]
        if all(_authority_payload(other) == _authority_payload(promoted) for other in by_hash.values()):
            return promoted
    raise JournalError("Conflicting canonical snapshots; never select an arbitrary winner")


def _roll_checkpoint_forward(state: dict, checkpoint_doc: dict, manifest: dict) -> tuple[dict, int]:
    """Compact an archived prefix while retaining every post-checkpoint event/evidence."""
    validate_snapshot(state)
    validate_checkpoint(checkpoint_doc)
    require(state["checkpoint"]["checkpoint_hash"] == manifest["archived_checkpoint_hash"],
            "CONFLICTING_LINEAGE: live snapshot does not descend from archived checkpoint root")
    require(state["sequence"] >= manifest["archived_sequence"],
            "CONFLICTING_LINEAGE: live canonical sequence regressed behind archived source")
    if state["sequence"] == manifest["archived_sequence"]:
        require(state["state_hash"] == manifest["archived_state_hash"],
                "CONFLICTING_LINEAGE: archived sequence has different canonical state")

    archived_hashes = manifest_event_hashes(manifest)
    live_events = {event["event_id"]: event for event in state["events"]}
    missing_events = sorted(set(archived_hashes) - set(live_events))
    require(not missing_events, "INCOMPLETE_REPLAY: live snapshot dropped archived events")
    for event_id, event_hash in archived_hashes.items():
        require(live_events[event_id]["event_hash"] == event_hash,
                "CONFLICTING_LINEAGE: archived immutable event changed")

    archived_artifacts = manifest_provider_artifacts(manifest)
    live_artifacts: dict[int, str] = {}
    for event_id, refs in state["evidence"].items():
        for ref in refs:
            if ref.get("kind") != "GITHUB_ACTIONS":
                continue
            artifact_id = ref["artifact_id"]
            archive_digest = ref["archive_digest"]
            previous = live_artifacts.get(artifact_id)
            require(previous is None or previous == archive_digest,
                    "CONFLICTING_LINEAGE: provider artifact digest changed inside live snapshot")
            live_artifacts[artifact_id] = archive_digest
            if event_id in archived_hashes:
                require(archived_artifacts.get(artifact_id) == archive_digest,
                        "INCOMPLETE_REPLAY: archived event gained unarchived provider evidence")
    for artifact_id, archive_digest in archived_artifacts.items():
        require(live_artifacts.get(artifact_id) == archive_digest,
                "INCOMPLETE_REPLAY: archived provider evidence disappeared")

    retained_ids = sorted(set(live_events) - set(archived_hashes))
    retained_events = [live_events[event_id] for event_id in retained_ids]
    retained_evidence = {event_id: state["evidence"][event_id] for event_id in retained_ids}
    rolled = make_snapshot(
        checkpoint_doc,
        retained_events,
        sequence=state["sequence"] + 1,
        evidence=retained_evidence,
        mode=state["mode"],
        production_authority=state["production_authority"],
    )
    require(rolled["projection"]["projection_hash"] == state["projection"]["projection_hash"],
            "INCOMPLETE_REPLAY: checkpoint plus retained replay does not reconstruct exact canonical state")
    return rolled, len(retained_events)


def reduce_from_provider(reader: GitHubReader, *, since: str, current_run: str,
                         upload_steps: dict, explicit_checkpoint: dict | None = None,
                         explicit_run_ids: list[int] | tuple[int, ...] = (),
                         archive_manifest: dict | None = None) -> tuple[dict, dict]:
    journal_reader = getattr(reader, "list_recent_journal_artifacts", None)
    artifacts = (
        journal_reader(since, explicit_run_ids=explicit_run_ids)
        if journal_reader is not None
        else reader.list_recent_artifacts(since)
    )
    state = restore_snapshot(reader, artifacts, current_run=current_run)
    archived_events = manifest_event_hashes(archive_manifest)
    archived_artifacts = manifest_provider_artifacts(archive_manifest)
    checkpoint_rollover = False
    checkpoint_rollover_replay_events = 0
    recovered_from_archive_checkpoint = False
    if archive_manifest is not None:
        require(explicit_checkpoint is not None, "Active archive requires compacted checkpoint")
        require(explicit_checkpoint["checkpoint_hash"] == archive_manifest["new_checkpoint_hash"],
                "Active archive/checkpoint binding mismatch")
        if state is None:
            state = make_snapshot(
                explicit_checkpoint, [], sequence=archive_manifest["checkpoint_sequence"], evidence={}
            )
            recovered_from_archive_checkpoint = True
        elif state["checkpoint"]["checkpoint_hash"] != explicit_checkpoint["checkpoint_hash"]:
            state, checkpoint_rollover_replay_events = _roll_checkpoint_forward(
                state, explicit_checkpoint, archive_manifest
            )
            checkpoint_rollover = True
        else:
            require(state["sequence"] >= archive_manifest["checkpoint_sequence"],
                    "Canonical snapshot predates active compacted checkpoint")
    elif state is None:
        require(explicit_checkpoint is not None, "CHECKPOINT_REQUIRED: no automatic empty-state reset")
        state = make_snapshot(explicit_checkpoint, [], sequence=0, evidence={})
    elif explicit_checkpoint is not None:
        require(state["checkpoint"]["checkpoint_hash"] == explicit_checkpoint["checkpoint_hash"],
                "Canonical checkpoint root changed")

    known_artifacts = {r["artifact_id"]: r["archive_digest"] for refs in state["evidence"].values()
                       for r in refs if r.get("kind") == "GITHUB_ACTIONS"}
    known_artifacts.update(archived_artifacts)
    committed_events = {event["event_id"]: event for event in state["events"]}
    incoming = []
    excluded = 0
    rerun_conflicts = []
    for a in artifacts:
        if not a.get("name", "").startswith(EVENT_PREFIX):
            continue
        source = a.get("workflow_run", {})
        if source.get("head_branch") != "main":
            excluded += 1; continue
        if a["id"] in known_artifacts:
            require(a.get("digest") == known_artifacts[a["id"]], "Previously ingested/archived provider digest changed")
            continue
        require(a.get("expired") is False,
                "EXPIRED_EVIDENCE: unconsumed event artifact expired; no silent evidence loss")
        event, provider = reader.event(a, upload_steps)
        archived_hash = archived_events.get(event["event_id"])
        if archived_hash is not None:
            require(event["event_hash"] == archived_hash, "Archived event identity changed")
            continue
        committed = committed_events.get(event["event_id"])
        if committed is not None and committed != event:
            prior_attempts = sorted({
                ref["source_run_attempt"]
                for ref in state["evidence"].get(event["event_id"], [])
                if ref.get("kind") == "GITHUB_ACTIONS"
                and ref.get("source_run_id") == provider.get("source_run_id")
                and ref.get("source_sha") == provider.get("source_sha")
                and type(ref.get("source_run_attempt")) is int
            })
            attempt = provider.get("source_run_attempt")
            if prior_attempts and type(attempt) is int and attempt > min(prior_attempts):
                rerun_conflicts.append({
                    "artifact_id": a["id"],
                    "event_id": event["event_id"],
                    "event_hash": event["event_hash"],
                    "source_run_id": provider["source_run_id"],
                    "source_run_attempt": attempt,
                    "committed_source_run_attempt": min(prior_attempts),
                })
                continue
            raise Conflict("Conflicting event identity is not a later rerun of an already committed source")
        incoming.append((event, provider))

    # A queued push run can become stale while waiting for the global writer
    # lock. If both that stale main observation and the exact-current-main
    # observation were published from the same canonical predecessor, prefer
    # the exact-current-main observation only after proving the stale source SHA
    # is its ancestor. This is source-authority resolution, never upload-time
    # winner selection, and every skipped artifact remains explicit evidence.
    stale_main_observations = []
    current_sha = os.environ.get("GITHUB_SHA", "")
    if current_sha and incoming:
        groups = {}
        for event, provider in incoming:
            change = _runtime_observation_change(event)
            if change is not None:
                groups.setdefault(change["before_hash"], []).append((event, provider, change))
        drop_ids = set()
        for before_hash, rows in groups.items():
            if len({change["after_hash"] for _, _, change in rows}) <= 1:
                continue
            exact = [row for row in rows if row[0].get("source_sha") == current_sha]
            if len(exact) != 1:
                continue
            exact_event = exact[0][0]
            for event, provider, change in rows:
                if event["event_id"] == exact_event["event_id"]:
                    continue
                comparison = reader.get(f"/compare/{event['source_sha']}...{current_sha}")
                require(
                    comparison.get("merge_base_commit", {}).get("sha") == event["source_sha"],
                    "Stale main observation source is not an ancestor of exact current main",
                )
                drop_ids.add(event["event_id"])
                stale_main_observations.append({
                    "artifact_id": provider.get("artifact_id"),
                    "event_id": event["event_id"],
                    "event_hash": event["event_hash"],
                    "source_run_id": provider.get("source_run_id"),
                    "source_sha": event["source_sha"],
                    "superseded_by_event_id": exact_event["event_id"],
                    "superseded_by_source_sha": current_sha,
                    "before_hash": before_hash,
                    "reason": "STALE_MAIN_OBSERVATION_SUPERSEDED_BY_EXACT_MAIN",
                })
        if drop_ids:
            incoming = [(event, provider) for event, provider in incoming if event["event_id"] not in drop_ids]

    try:
        candidate = advance(state, incoming)
    except MissingPredecessor as exc:
        if archive_manifest is not None:
            raise JournalError("MISSING_REPLAY: " + str(exc)) from exc
        raise
    return candidate, {"status": "PASS", "mode": "SHADOW", "production_authority": False,
                       "canonical_sequence": candidate["sequence"], "events_total": candidate["event_count"],
                       "new_deliveries": len(incoming), "excluded_non_main_artifacts": excluded,
                       "quarantined_rerun_conflict_count": len(rerun_conflicts),
                       "quarantined_rerun_conflicts": rerun_conflicts,
                       "superseded_stale_main_observation_count": len(stale_main_observations),
                       "superseded_stale_main_observations": stale_main_observations,
                       "checkpoint_rollover": checkpoint_rollover,
                       "checkpoint_rollover_replay_events": checkpoint_rollover_replay_events,
                       "recovered_from_archive_checkpoint": recovered_from_archive_checkpoint,
                       "checkpoint_recovery_status": (
                           "NO_CHECKPOINT" if archive_manifest is None else "VALID_CHECKPOINT"
                       ),
                       "active_archive_id": None if archive_manifest is None else archive_manifest["archive_id"],
                       "projection_hash": candidate["projection"]["projection_hash"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("state_journal/out/reducer"))
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--initialize", action="store_true")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    try:
        require(os.environ.get("GITHUB_REF") == "refs/heads/main", "Reducer publishes only from main")
        require(os.environ.get("GITHUB_WORKFLOW") == "portfolio-state-reducer", "Only the reducer workflow owns canonical publication")
        policy = strict_load((ROOT / "state_journal/POLICY.json").read_bytes())
        require(policy["mode"] in {"SHADOW", "CANONICAL_READY", "CANONICAL"}, "Unknown state-journal mode")
        require(type(policy.get("canonical_snapshot_authorized")) is bool, "Canonical snapshot authorization flag missing")
        require(type(policy["production_readers_enabled"]) is bool and type(policy["production_cutover_complete"]) is bool,
                "State-journal authority flags invalid")
        require(policy["production_readers_enabled"] == policy["production_cutover_complete"],
                "Reader authority and cutover completion must move together")
        if policy["mode"] == "CANONICAL_READY":
            require(policy["canonical_snapshot_authorized"] is True, "Canonical-ready mode requires explicit snapshot authorization")
            require(policy["production_readers_enabled"] is False and policy["production_cutover_complete"] is False,
                    "Canonical-ready stage may not enable production readers")
        checkpoint_path = args.checkpoint or (ROOT / "state_journal/CHECKPOINT.json.gz")
        require(checkpoint_path.is_file(), "Reviewed source-bound checkpoint is missing")
        raw_checkpoint = checkpoint_path.read_bytes()
        if checkpoint_path.suffix == ".gz":
            try:
                raw_checkpoint = gzip.decompress(raw_checkpoint)
            except (OSError, EOFError) as exc:
                raise JournalError("Reviewed checkpoint gzip is invalid") from exc
        bootstrap = strict_load(raw_checkpoint)
        validate_checkpoint(bootstrap)
        token = os.environ.get("GITHUB_TOKEN", "")
        require(bool(token), "Read-only GitHub token is required")
        reader = GitHubReader(token)
        upload_steps = strict_load((ROOT / "state_journal/UPLOAD_STEPS.json").read_bytes())
        recovery_run_ids = policy.get("recovery_run_ids", [])
        require(isinstance(recovery_run_ids, list), "Recovery run IDs must be a list")
        require(all(type(run_id) is int and run_id > 0 for run_id in recovery_run_ids),
                "Recovery run IDs must be positive integers")
        trigger_run = os.environ.get("TRIGGER_WORKFLOW_RUN_ID", "").strip()
        if trigger_run:
            require(trigger_run.isdigit() and int(trigger_run) > 0, "Trigger workflow run ID invalid")
            recovery_run_ids = [*recovery_run_ids, int(trigger_run)]
        recovery_run_ids = sorted(set(recovery_run_ids))
        archive_manifest = load_active_manifest(ROOT)
        state, receipt = reduce_from_provider(reader, since=policy["artifact_scan_start"],
                                             current_run=os.environ.get("GITHUB_RUN_ID", ""), upload_steps=upload_steps,
                                             explicit_checkpoint=bootstrap, explicit_run_ids=recovery_run_ids,
                                             archive_manifest=archive_manifest)
        receipt["explicit_recovery_run_ids"] = recovery_run_ids
        validate_snapshot(state)
        parity = verify_legacy_parity(state["projection"]["states"], args.output_dir / "legacy-parity-work")
        receipt["legacy_parity"] = parity["status"]
        receipt["legacy_domain_count"] = len(parity["domains"])
        if policy["canonical_snapshot_authorized"] is True and policy["mode"] in {"CANONICAL_READY", "CANONICAL"}:
            state = set_authority(state, mode="CANONICAL", production_authority=True)
        receipt["mode"] = state["mode"]
        receipt["production_authority"] = state["production_authority"]
        _atomic_write(args.output_dir / "legacy_parity.json", canonical(parity) + b"\n")
        _atomic_write(args.output_dir / "snapshot.json", canonical(state) + b"\n")
        _atomic_write(args.output_dir / "receipt.json", canonical(receipt) + b"\n")
        print(json.dumps(receipt))
    except Exception as exc:
        # No snapshot upload on failure. Existing state and source events survive.
        receipt = {"status": "BLOCKED", "mode": "SHADOW", "production_authority": False,
                   "reason_type": type(exc).__name__, "reason": str(exc)}
        _atomic_write(args.output_dir / "receipt.json", canonical(receipt) + b"\n")
        print(json.dumps(receipt))
        raise SystemExit(1) from exc


if __name__ == "__main__": main()