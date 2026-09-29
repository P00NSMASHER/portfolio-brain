"""Single shadow reducer workflow entry point. Never changes production readers."""
from __future__ import annotations
import argparse
import gzip
import json
import os
from pathlib import Path

from runtime.artifact_restore import _atomic_write
from state_journal.contracts import REPOSITORY, JournalError, canonical, digest, require, strict_load
from state_journal.reducer import make_snapshot, validate_snapshot, validate_checkpoint, advance, set_authority
from state_journal.legacy_parity import verify as verify_legacy_parity
from state_journal.transport import EVENT_PREFIX, SNAPSHOT_ARTIFACT, GitHubReader, artifact_digest, extract_json

ROOT = Path(__file__).resolve().parents[1]


def restore_snapshot(reader: GitHubReader, artifacts: list[dict], *, current_run: str) -> dict | None:
    candidates = [a for a in artifacts if a.get("name") == SNAPSHOT_ARTIFACT
                  and a.get("workflow_run", {}).get("head_branch") == "main"
                  and str(a.get("workflow_run", {}).get("id")) != current_run]
    if not candidates:
        return None
    require(any(not a.get("expired") for a in candidates), "Canonical journal expired; explicit recovery required")
    require(len(candidates) <= 20, "Snapshot selection bound reached; no arbitrary truncation")
    states = []
    for a in candidates:
        if a.get("expired"):
            continue
        source = a.get("workflow_run", {})
        run = reader.get(f"/actions/runs/{source['id']}")
        require(run.get("path") == ".github/workflows/portfolio-state-reducer.yml", "Snapshot did not come from sole reducer workflow")
        require(run.get("head_branch") == "main" and run.get("head_sha") == source.get("head_sha"), "Snapshot source SHA/branch mismatch")
        require(run.get("status") == "completed" and run.get("conclusion") == "success", "Snapshot producer did not succeed")
        require(run.get("repository", {}).get("full_name") == REPOSITORY and run.get("head_repository", {}).get("full_name") == REPOSITORY,
                "Snapshot source fork mismatch")
        raw = reader.archive(a["id"]); artifact_digest(a, raw)
        state = extract_json(raw, "snapshot.json"); validate_snapshot(state)
        states.append(state)
    highest = max(s["sequence"] for s in states)
    latest = [s for s in states if s["sequence"] == highest]
    full_digests = {digest(s) for s in latest}
    if len(full_digests) == 1:
        return latest[0]

    # A protected CANONICAL_READY promotion intentionally republishes the exact
    # same immutable journal payload with authority metadata changed from
    # SHADOW/false to CANONICAL/true without advancing the journal sequence.
    # Treat that one proven metadata-only transition as supersession, not a
    # fork. Any payload divergence at the same sequence still fails closed.
    def immutable_lineage(state: dict) -> str:
        return digest({k: state[k] for k in (
            "schema_version", "state_id", "sequence", "checkpoint", "events",
            "evidence", "projection", "event_count",
        )})

    require(len({immutable_lineage(s) for s in latest}) == 1,
            "Conflicting canonical snapshots; never select an arbitrary winner")
    promoted = {digest(s): s for s in latest
                if s["mode"] == "CANONICAL" and s["production_authority"] is True}
    shadow = {digest(s): s for s in latest
              if s["mode"] == "SHADOW" and s["production_authority"] is False}
    require(len(promoted) == 1 and len(shadow) >= 1
            and len(promoted) + len(shadow) == len(full_digests),
            "Conflicting canonical snapshots; never select an arbitrary winner")
    canonical_state = next(iter(promoted.values()))
    shadow_state = next(iter(shadow.values()))
    require(canonical(set_authority(shadow_state, mode="CANONICAL", production_authority=True))
            == canonical(canonical_state),
            "Conflicting canonical snapshots; never select an arbitrary winner")
    return canonical_state


def reduce_from_provider(reader: GitHubReader, *, since: str, current_run: str,
                         upload_steps: dict, explicit_checkpoint: dict | None = None) -> tuple[dict, dict]:
    artifacts = reader.list_recent_artifacts(since)
    state = restore_snapshot(reader, artifacts, current_run=current_run)
    if state is None:
        require(explicit_checkpoint is not None, "CHECKPOINT_REQUIRED: no automatic empty-state reset")
        state = make_snapshot(explicit_checkpoint, [], sequence=0, evidence={})
    elif explicit_checkpoint is not None:
        require(state["checkpoint"]["checkpoint_hash"] == explicit_checkpoint["checkpoint_hash"],
                "Canonical checkpoint root changed")
    known_artifacts = {r["artifact_id"]: r["archive_digest"] for refs in state["evidence"].values()
                       for r in refs if r.get("kind") == "GITHUB_ACTIONS"}
    incoming = []
    excluded = 0
    for a in artifacts:
        if not a.get("name", "").startswith(EVENT_PREFIX):
            continue
        source = a.get("workflow_run", {})
        if source.get("head_branch") != "main":
            excluded += 1; continue
        if a["id"] in known_artifacts:
            require(a.get("digest") == known_artifacts[a["id"]], "Previously ingested provider digest changed")
            continue
        require(a.get("expired") is False, "Unconsumed event artifact expired; no silent evidence loss")
        incoming.append(reader.event(a, upload_steps))
    candidate = advance(state, incoming)
    return candidate, {"status": "PASS", "mode": "SHADOW", "production_authority": False,
                       "canonical_sequence": candidate["sequence"], "events_total": candidate["event_count"],
                       "new_deliveries": len(incoming), "excluded_non_main_artifacts": excluded,
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
        state, receipt = reduce_from_provider(reader, since=policy["artifact_scan_start"],
                                             current_run=os.environ.get("GITHUB_RUN_ID", ""), upload_steps=upload_steps,
                                             explicit_checkpoint=bootstrap)
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