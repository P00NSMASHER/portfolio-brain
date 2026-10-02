"""Validated durable checkpoint/archive lineage for the canonical state journal."""
from __future__ import annotations

import gzip
import hashlib
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from state_journal.contracts import MAX_SNAPSHOT_BYTES, JournalError, canonical, digest, fields, require, strict_load
from state_journal.reducer import checkpoint, validate_checkpoint, validate_snapshot

ROOT = Path(__file__).resolve().parents[1]
ACTIVE_MANIFEST = ROOT / "state_journal" / "ARCHIVE_MANIFEST.json"
ARCHIVE_SCHEMA_LEGACY = "1.0.0"
ARCHIVE_SCHEMA = "1.1.0"
CHECKPOINT_PATH = "state_journal/CHECKPOINT.json.gz"
REPLAY_OVERLAP_SECONDS = 6 * 60 * 60
SECRET_RE = re.compile(
    rb"(?:github_pat_[A-Za-z0-9_]{20,}|gh[pousr]_[A-Za-z0-9_]{20,}|"
    rb"sk-[A-Za-z0-9_-]{20,}|-----BEGIN [A-Z ]*PRIVATE KEY-----)",
    re.I,
)


def _require_sanitized_archive(raw: bytes) -> None:
    require(isinstance(raw, bytes), "Archive sanitization input must be bytes")
    require(SECRET_RE.search(raw) is None, "Credential-like material prohibited from public archive")


def _utc(value: str) -> datetime:
    require(isinstance(value, str) and value.endswith("Z"), "Archive time must be UTC ISO-8601")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError("Archive time invalid") from exc
    require(parsed.tzinfo is not None, "Archive time requires timezone")
    return parsed


def _iso_utc(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _sha256_bytes(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _gzip_json(document: dict) -> bytes:
    raw = canonical(document) + b"\n"
    _require_sanitized_archive(raw)
    return gzip.compress(raw, compresslevel=9, mtime=0)


def _archived_provider_artifacts(state: dict) -> dict[str, str]:
    result: dict[str, str] = {}
    for refs in state["evidence"].values():
        for ref in refs:
            if ref.get("kind") != "GITHUB_ACTIONS":
                continue
            artifact_id = str(ref["artifact_id"])
            archive_digest = ref["archive_digest"]
            old = result.get(artifact_id)
            require(old is None or old == archive_digest, "Archived provider identity changed")
            result[artifact_id] = archive_digest
    return dict(sorted(result.items(), key=lambda item: int(item[0])))


def _archived_event_hashes(state: dict) -> dict[str, str]:
    return {event["event_id"]: event["event_hash"] for event in state["events"]}


def _checkpoint_ref(*, archive_path: str, archive_file_sha256: str, state_hash: str) -> str:
    return f"repo-archive:{archive_path}:{archive_file_sha256}:state={state_hash}"


def _manifest_required(schema_version: str) -> set[str]:
    common = {
        "schema_version", "archive_id", "manifest_path", "archive_path", "archive_file_sha256",
        "checkpoint_path", "previous_manifest_hash", "archived_sequence", "archived_state_hash",
        "archived_projection_hash", "archived_checkpoint_hash", "archived_event_count",
        "archived_event_hashes", "archived_provider_artifacts", "new_checkpoint_hash",
        "checkpoint_sequence", "source_reducer_run_id", "source_artifact_id", "source_head_sha",
        "source_artifact_digest", "source_artifact_created_at", "artifact_scan_start", "manifest_hash",
    }
    if schema_version == ARCHIVE_SCHEMA_LEGACY:
        return common
    require(schema_version == ARCHIVE_SCHEMA, "Archive manifest schema mismatch")
    return common | {
        "checkpoint_id", "checkpoint_freshness_at", "previous_manifest_path",
        "previous_checkpoint_hash", "replay_overlap_seconds",
    }


def _validate_manifest_envelope(manifest: dict) -> set[str]:
    require(isinstance(manifest, dict), "Archive manifest must be an object")
    required = _manifest_required(manifest.get("schema_version"))
    fields(manifest, required, "Archive manifest")
    core = {key: manifest[key] for key in required if key != "manifest_hash"}
    require(manifest["manifest_hash"] == digest(core), "Archive manifest hash mismatch")
    return required


def build_rollover(
    state: dict,
    *,
    source_reducer_run_id: int,
    source_artifact_id: int,
    source_head_sha: str,
    source_artifact_digest: str,
    source_artifact_created_at: str,
    previous_manifest: dict | None = None,
) -> tuple[dict, bytes, dict, bytes, str]:
    """Return manifest, archived snapshot gzip, checkpoint, checkpoint gzip, archive path."""
    validate_snapshot(state)
    require(state["mode"] == "CANONICAL" and state["production_authority"] is True,
            "Only production-authoritative canonical state may be archived")
    require(type(source_reducer_run_id) is int and source_reducer_run_id > 0, "Reducer run id invalid")
    require(type(source_artifact_id) is int and source_artifact_id > 0, "Snapshot artifact id invalid")
    require(isinstance(source_head_sha, str) and len(source_head_sha) == 40, "Snapshot source SHA invalid")
    require(isinstance(source_artifact_digest, str) and source_artifact_digest.startswith("sha256:"),
            "Snapshot artifact digest invalid")
    source_created_at = _utc(source_artifact_created_at)
    sequence = state["sequence"]
    previous_manifest_hash = None
    previous_manifest_path = None
    previous_checkpoint_hash = None
    if previous_manifest is not None:
        _validate_manifest_envelope(previous_manifest)
        previous_manifest_hash = previous_manifest["manifest_hash"]
        previous_manifest_path = previous_manifest["manifest_path"]
        previous_checkpoint_hash = previous_manifest["new_checkpoint_hash"]
        require(state["checkpoint"]["checkpoint_hash"] == previous_checkpoint_hash,
                "Archived checkpoint predecessor hash mismatch")
        require(sequence >= previous_manifest["checkpoint_sequence"],
                "Archived sequence regressed behind predecessor checkpoint")

    archive_path = (
        f"state_journal/archive/canonical-seq-{sequence:08d}-"
        f"{state['state_hash'].removeprefix('sha256:')[:16]}.json.gz"
    )
    archive_raw = _gzip_json(state)
    archive_file_sha256 = _sha256_bytes(archive_raw)
    source_ref = _checkpoint_ref(
        archive_path=archive_path,
        archive_file_sha256=archive_file_sha256,
        state_hash=state["state_hash"],
    )
    source_refs = {domain: source_ref for domain in sorted(state["projection"]["states"])}
    compacted = checkpoint(state["projection"]["states"], source_refs)
    validate_checkpoint(compacted)
    checkpoint_raw = _gzip_json(compacted)
    manifest_path = archive_path.removesuffix(".json.gz") + ".manifest.json"

    core = {
        "schema_version": ARCHIVE_SCHEMA,
        "archive_id": f"canonical-archive-seq-{sequence:08d}",
        "checkpoint_id": (
            f"canonical-checkpoint-seq-{sequence + 1:08d}-"
            f"{compacted['checkpoint_hash'].removeprefix('sha256:')[:16]}"
        ),
        "manifest_path": manifest_path,
        "archive_path": archive_path,
        "archive_file_sha256": archive_file_sha256,
        "checkpoint_path": CHECKPOINT_PATH,
        "previous_manifest_hash": previous_manifest_hash,
        "previous_manifest_path": previous_manifest_path,
        "previous_checkpoint_hash": previous_checkpoint_hash,
        "archived_sequence": sequence,
        "archived_state_hash": state["state_hash"],
        "archived_projection_hash": state["projection"]["projection_hash"],
        "archived_checkpoint_hash": state["checkpoint"]["checkpoint_hash"],
        "archived_event_count": state["event_count"],
        "archived_event_hashes": _archived_event_hashes(state),
        "archived_provider_artifacts": _archived_provider_artifacts(state),
        "new_checkpoint_hash": compacted["checkpoint_hash"],
        "checkpoint_sequence": sequence + 1,
        "source_reducer_run_id": source_reducer_run_id,
        "source_artifact_id": source_artifact_id,
        "source_head_sha": source_head_sha,
        "source_artifact_digest": source_artifact_digest,
        "source_artifact_created_at": source_artifact_created_at,
        "checkpoint_freshness_at": source_artifact_created_at,
        "replay_overlap_seconds": REPLAY_OVERLAP_SECONDS,
        "artifact_scan_start": _iso_utc(source_created_at - timedelta(seconds=REPLAY_OVERLAP_SECONDS)),
    }
    manifest = {**core, "manifest_hash": digest(core)}
    validate_manifest(
        manifest, root=None, archived_state=state, checkpoint_doc=compacted,
        previous_manifest=previous_manifest,
    )
    return manifest, archive_raw, compacted, checkpoint_raw, archive_path


def validate_manifest(
    manifest: dict,
    *,
    root: Path | None = ROOT,
    archived_state: dict | None = None,
    checkpoint_doc: dict | None = None,
    previous_manifest: dict | None = None,
) -> tuple[dict, dict]:
    required = _validate_manifest_envelope(manifest)
    schema_version = manifest["schema_version"]
    require(manifest["checkpoint_path"] == CHECKPOINT_PATH, "Archive checkpoint path changed")
    require(
        isinstance(manifest["archive_path"], str)
        and manifest["archive_path"].startswith("state_journal/archive/")
        and manifest["archive_path"].endswith(".json.gz")
        and ".." not in manifest["archive_path"],
        "Archive path invalid",
    )
    require(
        manifest["manifest_path"] == manifest["archive_path"].removesuffix(".json.gz") + ".manifest.json",
        "Archive manifest path mismatch",
    )
    require(type(manifest["archived_sequence"]) is int and manifest["archived_sequence"] >= 0,
            "Archived sequence invalid")
    require(manifest["checkpoint_sequence"] == manifest["archived_sequence"] + 1,
            "Checkpoint sequence must advance exactly once")
    require(type(manifest["archived_event_count"]) is int and manifest["archived_event_count"] >= 0,
            "Archived event count invalid")
    require(type(manifest["source_reducer_run_id"]) is int and manifest["source_reducer_run_id"] > 0,
            "Archive reducer run identity invalid")
    require(type(manifest["source_artifact_id"]) is int and manifest["source_artifact_id"] > 0,
            "Archive source artifact identity invalid")
    require(isinstance(manifest["source_head_sha"], str) and len(manifest["source_head_sha"]) == 40,
            "Archive source SHA invalid")
    require(isinstance(manifest["source_artifact_digest"], str)
            and manifest["source_artifact_digest"].startswith("sha256:"),
            "Archive source artifact digest invalid")
    require(isinstance(manifest["archive_file_sha256"], str)
            and manifest["archive_file_sha256"].startswith("sha256:"),
            "Archive file digest invalid")
    require(isinstance(manifest["archived_state_hash"], str)
            and manifest["archived_state_hash"].startswith("sha256:"),
            "Archived state hash invalid")
    require(isinstance(manifest["archived_projection_hash"], str)
            and manifest["archived_projection_hash"].startswith("sha256:"),
            "Archived projection hash invalid")
    require(isinstance(manifest["new_checkpoint_hash"], str)
            and manifest["new_checkpoint_hash"].startswith("sha256:"),
            "New checkpoint hash invalid")
    require(manifest["previous_manifest_hash"] is None or (
        isinstance(manifest["previous_manifest_hash"], str)
        and manifest["previous_manifest_hash"].startswith("sha256:")
    ), "Previous archive manifest hash invalid")
    source_created_at = _utc(manifest["source_artifact_created_at"])
    scan_start = _utc(manifest["artifact_scan_start"])
    if schema_version == ARCHIVE_SCHEMA:
        require(
            isinstance(manifest["checkpoint_id"], str)
            and manifest["checkpoint_id"].startswith("canonical-checkpoint-seq-"),
            "Checkpoint identity invalid",
        )
        require(manifest["checkpoint_freshness_at"] == manifest["source_artifact_created_at"],
                "Checkpoint freshness timestamp changed")
        require((manifest["previous_manifest_hash"] is None) == (manifest["previous_manifest_path"] is None),
                "Previous archive manifest hash/path must move together")
        require((manifest["previous_manifest_hash"] is None) == (manifest["previous_checkpoint_hash"] is None),
                "Previous archive checkpoint lineage must move with manifest lineage")
        require(manifest["previous_manifest_path"] is None or (
            isinstance(manifest["previous_manifest_path"], str)
            and manifest["previous_manifest_path"].startswith("state_journal/archive/")
            and manifest["previous_manifest_path"].endswith(".manifest.json")
            and ".." not in manifest["previous_manifest_path"]
        ), "Previous archive manifest path invalid")
        require(type(manifest["replay_overlap_seconds"]) is int
                and 60 <= manifest["replay_overlap_seconds"] <= 7 * 24 * 60 * 60,
                "Replay overlap bound invalid")
        require(scan_start < source_created_at, "Replay overlap must begin before checkpoint publication")
        require(int((source_created_at - scan_start).total_seconds()) == manifest["replay_overlap_seconds"],
                "Replay overlap duration does not match manifest")
        if previous_manifest is not None:
            _validate_manifest_envelope(previous_manifest)
            require(manifest["previous_manifest_hash"] == previous_manifest["manifest_hash"],
                    "Previous archive manifest hash lineage mismatch")
            require(manifest["previous_manifest_path"] == previous_manifest["manifest_path"],
                    "Previous archive manifest path lineage mismatch")
            require(manifest["previous_checkpoint_hash"] == previous_manifest["new_checkpoint_hash"],
                    "Previous checkpoint hash lineage mismatch")
            require(manifest["archived_checkpoint_hash"] == manifest["previous_checkpoint_hash"],
                    "Archived checkpoint predecessor hash mismatch")
            require(manifest["archived_sequence"] >= previous_manifest["checkpoint_sequence"],
                    "Archived sequence regressed behind predecessor checkpoint")
        elif root is None:
            require(manifest["previous_manifest_hash"] is None,
                    "Previous archive lineage was declared but not validated")

    if root is not None:
        archive_file = root / manifest["archive_path"]
        checkpoint_file = root / manifest["checkpoint_path"]
        immutable_manifest_file = root / manifest["manifest_path"]
        require(archive_file.is_file(), "Archived canonical snapshot missing from repository")
        require(checkpoint_file.is_file(), "Compacted checkpoint missing from repository")
        require(immutable_manifest_file.is_file(), "Immutable archive manifest missing from repository")
        immutable = strict_load(immutable_manifest_file.read_bytes())
        require(immutable == manifest, "Active and immutable archive manifests differ")
        if schema_version == ARCHIVE_SCHEMA and manifest["previous_manifest_hash"] is not None:
            previous_file = root / manifest["previous_manifest_path"]
            require(previous_file.is_file(), "Previous immutable archive manifest missing")
            predecessor = strict_load(previous_file.read_bytes())
            _validate_manifest_envelope(predecessor)
            require(predecessor["manifest_hash"] == manifest["previous_manifest_hash"],
                    "Previous archive manifest lineage mismatch")
            require(predecessor["manifest_path"] == manifest["previous_manifest_path"],
                    "Previous archive manifest path lineage mismatch")
            require(predecessor["new_checkpoint_hash"] == manifest["previous_checkpoint_hash"],
                    "Previous checkpoint hash lineage mismatch")
            require(manifest["archived_checkpoint_hash"] == manifest["previous_checkpoint_hash"],
                    "Archived checkpoint predecessor hash mismatch")
            require(manifest["archived_sequence"] >= predecessor["checkpoint_sequence"],
                    "Archived sequence regressed behind predecessor checkpoint")
        archive_raw = archive_file.read_bytes()
        require(_sha256_bytes(archive_raw) == manifest["archive_file_sha256"],
                "Archived canonical snapshot file digest mismatch")
        try:
            archived_json = gzip.decompress(archive_raw)
            checkpoint_json = gzip.decompress(checkpoint_file.read_bytes())
            _require_sanitized_archive(archived_json)
            _require_sanitized_archive(checkpoint_json)
            archived_state = strict_load(archived_json, max_bytes=MAX_SNAPSHOT_BYTES)
            checkpoint_doc = strict_load(checkpoint_json)
        except (OSError, EOFError) as exc:
            raise ValueError("Archive/checkpoint gzip invalid") from exc

    require(archived_state is not None and checkpoint_doc is not None, "Archive validation inputs missing")
    validate_snapshot(archived_state)
    validate_checkpoint(checkpoint_doc)
    require(archived_state["sequence"] == manifest["archived_sequence"], "Archived sequence mismatch")
    require(archived_state["state_hash"] == manifest["archived_state_hash"], "Archived state hash mismatch")
    require(archived_state["projection"]["projection_hash"] == manifest["archived_projection_hash"],
            "Archived projection hash mismatch")
    require(archived_state["checkpoint"]["checkpoint_hash"] == manifest["archived_checkpoint_hash"],
            "Archived predecessor checkpoint mismatch")
    require(archived_state["event_count"] == manifest["archived_event_count"], "Archived event count mismatch")
    require(_archived_event_hashes(archived_state) == manifest["archived_event_hashes"],
            "Archived event identity set mismatch")
    require(_archived_provider_artifacts(archived_state) == manifest["archived_provider_artifacts"],
            "Archived provider evidence set mismatch")
    require(checkpoint_doc["checkpoint_hash"] == manifest["new_checkpoint_hash"],
            "Compacted checkpoint hash mismatch")
    if schema_version == ARCHIVE_SCHEMA:
        expected_checkpoint_id = (
            f"canonical-checkpoint-seq-{manifest['checkpoint_sequence']:08d}-"
            f"{manifest['new_checkpoint_hash'].removeprefix('sha256:')[:16]}"
        )
        require(manifest["checkpoint_id"] == expected_checkpoint_id, "Checkpoint identity mismatch")
    require(checkpoint_doc["states"] == archived_state["projection"]["states"],
            "Compacted checkpoint state differs from archived projection")
    expected_ref = _checkpoint_ref(
        archive_path=manifest["archive_path"],
        archive_file_sha256=manifest["archive_file_sha256"],
        state_hash=manifest["archived_state_hash"],
    )
    require(set(checkpoint_doc["source_refs"].values()) == {expected_ref},
            "Compacted checkpoint provenance does not bind archive")
    return archived_state, checkpoint_doc


def load_active_manifest(root: Path = ROOT) -> dict | None:
    path = root / "state_journal" / "ARCHIVE_MANIFEST.json"
    if not path.exists():
        return None
    try:
        manifest = strict_load(path.read_bytes())
        validate_manifest(manifest, root=root)
        return manifest
    except Exception as exc:
        if isinstance(exc, JournalError) and str(exc).startswith("CORRUPTED_CHECKPOINT:"):
            raise
        raise JournalError("CORRUPTED_CHECKPOINT: " + str(exc)) from exc


def archived_artifact_ids(manifest: dict | None) -> set[int]:
    if manifest is None:
        return set()
    return {int(value) for value in manifest["archived_provider_artifacts"]}


def archived_event_hashes(manifest: dict | None) -> dict[str, str]:
    return {} if manifest is None else dict(manifest["archived_event_hashes"])


def archived_provider_artifacts(manifest: dict | None) -> dict[int, str]:
    if manifest is None:
        return {}
    return {int(key): value for key, value in manifest["archived_provider_artifacts"].items()}
