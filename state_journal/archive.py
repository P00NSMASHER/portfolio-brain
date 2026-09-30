"""Validated durable checkpoint/archive lineage for the canonical state journal."""
from __future__ import annotations

import gzip
import hashlib
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from state_journal.contracts import JournalError, canonical, digest, fields, require, strict_load
from state_journal.reducer import checkpoint, make_snapshot, validate_checkpoint, validate_snapshot

ROOT = Path(__file__).resolve().parents[1]
ACTIVE_MANIFEST = ROOT / "state_journal" / "ARCHIVE_MANIFEST.json"
ARCHIVE_SCHEMA = "1.1.0"
LEGACY_ARCHIVE_SCHEMA = "1.0.0"
CHECKPOINT_PATH = "state_journal/CHECKPOINT.json.gz"
REPLAY_OVERLAP_MINUTES = 30
SECRET_RE = re.compile(
    rb"(?:github_pat_[A-Za-z0-9_]{20,}|gh[pousr]_[A-Za-z0-9_]{20,}|"
    rb"sk-[A-Za-z0-9_-]{20,}|-----BEGIN [A-Z ]*PRIVATE KEY-----)",
    re.I,
)

LEGACY_FIELDS = {
    "schema_version", "archive_id", "manifest_path", "archive_path", "archive_file_sha256",
    "checkpoint_path", "previous_manifest_hash", "archived_sequence", "archived_state_hash",
    "archived_projection_hash", "archived_checkpoint_hash", "archived_event_count",
    "archived_event_hashes", "archived_provider_artifacts", "new_checkpoint_hash",
    "checkpoint_sequence", "source_reducer_run_id", "source_artifact_id", "source_head_sha",
    "source_artifact_digest", "source_artifact_created_at", "artifact_scan_start", "manifest_hash",
}
CURRENT_FIELDS = LEGACY_FIELDS | {
    "archive_created_at", "replay_overlap_seconds", "previous_manifest_path",
    "previous_archive_id", "previous_archived_sequence", "previous_archived_state_hash",
    "previous_checkpoint_hash", "archived_source_run_ids", "archived_source_attempts",
    "checkpoint_state_hash",
}


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


def _iso(value: datetime) -> str:
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


def _archived_source_run_ids(state: dict) -> list[int]:
    runs = {
        ref["source_run_id"]
        for refs in state["evidence"].values()
        for ref in refs
        if ref.get("kind") == "GITHUB_ACTIONS"
    }
    require(all(type(value) is int and value > 0 for value in runs), "Archived source run identity invalid")
    return sorted(runs)


def _archived_source_attempts(state: dict) -> list[str]:
    attempts = {
        f"{ref['source_run_id']}:{ref['source_run_attempt']}"
        for refs in state["evidence"].values()
        for ref in refs
        if ref.get("kind") == "GITHUB_ACTIONS"
    }
    require(
        all(re.fullmatch(r"[1-9][0-9]*:[1-9][0-9]*", value) is not None for value in attempts),
        "Archived source run/attempt identity invalid",
    )
    return sorted(attempts, key=lambda value: tuple(int(part) for part in value.split(":")))


def _checkpoint_ref(*, archive_path: str, archive_file_sha256: str, state_hash: str) -> str:
    return f"repo-archive:{archive_path}:{archive_file_sha256}:state={state_hash}"


def _archive_identity(sequence: int, state_hash: str) -> str:
    return f"canonical-archive-seq-{sequence:08d}-{state_hash.removeprefix('sha256:')[:16]}"


def _manifest_fields(manifest: dict) -> set[str]:
    schema = manifest.get("schema_version")
    if schema == ARCHIVE_SCHEMA:
        return CURRENT_FIELDS
    if schema == LEGACY_ARCHIVE_SCHEMA:
        return LEGACY_FIELDS
    raise JournalError("CORRUPTED_CHECKPOINT: unsupported archive manifest schema")


def _manifest_core(manifest: dict) -> dict:
    required = _manifest_fields(manifest)
    return {key: manifest[key] for key in required if key != "manifest_hash"}


def _valid_sha256(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", value) is not None


def _validate_manifest_core(manifest: dict) -> None:
    required = _manifest_fields(manifest)
    fields(manifest, required, "Archive manifest")
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
    require(re.fullmatch(r"[0-9a-f]{40}", str(manifest["source_head_sha"])) is not None,
            "Archive source SHA invalid")
    for key in (
        "source_artifact_digest", "archive_file_sha256", "archived_state_hash",
        "archived_projection_hash", "archived_checkpoint_hash", "new_checkpoint_hash",
        "manifest_hash",
    ):
        require(_valid_sha256(manifest[key]), f"Archive {key} invalid")
    require(manifest["previous_manifest_hash"] is None or _valid_sha256(manifest["previous_manifest_hash"]),
            "Previous archive manifest hash invalid")
    source_created = _utc(manifest["source_artifact_created_at"])
    replay_start = _utc(manifest["artifact_scan_start"])
    require(replay_start <= source_created, "Replay scan starts after archived source publication")
    require(manifest["manifest_hash"] == digest(_manifest_core(manifest)), "Archive manifest hash mismatch")

    if manifest["schema_version"] == LEGACY_ARCHIVE_SCHEMA:
        return

    require(manifest["archive_id"] == _archive_identity(
        manifest["archived_sequence"], manifest["archived_state_hash"]
    ), "Immutable archive identity does not bind canonical state")
    require(_valid_sha256(manifest["checkpoint_state_hash"]), "Checkpoint state hash invalid")
    require(
        type(manifest["replay_overlap_seconds"]) is int
        and 0 < manifest["replay_overlap_seconds"] <= 86400,
        "Replay overlap invalid",
    )
    archived_at = _utc(manifest["archive_created_at"])
    require(archived_at >= source_created, "Archive creation predates source reducer artifact")
    expected_start = _iso(source_created - timedelta(seconds=manifest["replay_overlap_seconds"]))
    require(manifest["artifact_scan_start"] == expected_start,
            "Replay scan start does not preserve declared overlap")
    runs = manifest["archived_source_run_ids"]
    require(
        isinstance(runs, list)
        and runs == sorted(set(runs))
        and all(type(value) is int and value > 0 for value in runs),
        "Archived source run coverage invalid",
    )
    attempts = manifest["archived_source_attempts"]
    require(
        isinstance(attempts, list)
        and len(attempts) == len(set(attempts))
        and all(re.fullmatch(r"[1-9][0-9]*:[1-9][0-9]*", value) is not None for value in attempts),
        "Archived source run/attempt coverage invalid",
    )
    require(
        {int(value.split(":", 1)[0]) for value in attempts} <= set(runs),
        "Archived attempt coverage names an unarchived source run",
    )
    previous_values = (
        manifest["previous_manifest_path"], manifest["previous_archive_id"],
        manifest["previous_archived_sequence"], manifest["previous_archived_state_hash"],
        manifest["previous_checkpoint_hash"],
    )
    if manifest["previous_manifest_hash"] is None:
        require(all(value is None for value in previous_values),
                "First archive cannot claim predecessor lineage")
    else:
        require(
            isinstance(manifest["previous_manifest_path"], str)
            and manifest["previous_manifest_path"].startswith("state_journal/archive/")
            and manifest["previous_manifest_path"].endswith(".manifest.json")
            and ".." not in manifest["previous_manifest_path"],
            "Previous manifest path invalid",
        )
        require(isinstance(manifest["previous_archive_id"], str) and manifest["previous_archive_id"],
                "Previous archive identity missing")
        require(type(manifest["previous_archived_sequence"]) is int
                and manifest["previous_archived_sequence"] >= 0,
                "Previous archive sequence invalid")
        require(_valid_sha256(manifest["previous_archived_state_hash"]),
                "Previous archive state hash invalid")
        require(_valid_sha256(manifest["previous_checkpoint_hash"]),
                "Previous checkpoint hash invalid")


def _validate_lineage(manifest: dict, previous: dict) -> None:
    require(manifest["schema_version"] == ARCHIVE_SCHEMA,
            "CONFLICTING_LINEAGE: legacy manifest cannot claim current predecessor fields")
    _validate_manifest_core(previous)
    require(manifest["previous_manifest_hash"] == previous["manifest_hash"],
            "CONFLICTING_LINEAGE: predecessor manifest hash mismatch")
    require(manifest["previous_manifest_path"] == previous["manifest_path"],
            "CONFLICTING_LINEAGE: predecessor manifest path mismatch")
    require(manifest["previous_archive_id"] == previous["archive_id"],
            "CONFLICTING_LINEAGE: predecessor archive identity mismatch")
    require(manifest["previous_archived_sequence"] == previous["archived_sequence"],
            "CONFLICTING_LINEAGE: predecessor sequence mismatch")
    require(manifest["previous_archived_state_hash"] == previous["archived_state_hash"],
            "CONFLICTING_LINEAGE: predecessor state hash mismatch")
    require(manifest["previous_checkpoint_hash"] == previous["new_checkpoint_hash"],
            "CONFLICTING_LINEAGE: predecessor checkpoint hash mismatch")
    require(manifest["archived_sequence"] > previous["archived_sequence"],
            "CHECKPOINT_SEQUENCE_REGRESSION: archive sequence did not advance")
    require(manifest["archived_sequence"] >= previous["checkpoint_sequence"],
            "CHECKPOINT_SEQUENCE_REGRESSION: archive sequence predates predecessor checkpoint")
    require(manifest["archived_checkpoint_hash"] == previous["new_checkpoint_hash"],
            "CONFLICTING_LINEAGE: source canonical root does not descend from predecessor checkpoint")
    require(
        _utc(manifest["source_artifact_created_at"]) >= _utc(previous["source_artifact_created_at"]),
        "CONFLICTING_LINEAGE: source artifact time regressed",
    )


def build_rollover(
    state: dict,
    *,
    source_reducer_run_id: int,
    source_artifact_id: int,
    source_head_sha: str,
    source_artifact_digest: str,
    source_artifact_created_at: str,
    previous_manifest: dict | None = None,
    archive_created_at: str | None = None,
) -> tuple[dict, bytes, dict, bytes, str]:
    """Return manifest, archived snapshot gzip, checkpoint, checkpoint gzip, archive path."""
    validate_snapshot(state)
    require(state["mode"] == "CANONICAL" and state["production_authority"] is True,
            "Only production-authoritative canonical state may be archived")
    require(type(source_reducer_run_id) is int and source_reducer_run_id > 0, "Reducer run id invalid")
    require(type(source_artifact_id) is int and source_artifact_id > 0, "Snapshot artifact id invalid")
    require(re.fullmatch(r"[0-9a-f]{40}", source_head_sha) is not None, "Snapshot source SHA invalid")
    require(_valid_sha256(source_artifact_digest), "Snapshot artifact digest invalid")
    source_created = _utc(source_artifact_created_at)
    archive_created_at = archive_created_at or source_artifact_created_at
    _utc(archive_created_at)
    if previous_manifest is not None:
        _validate_manifest_core(previous_manifest)
        require(state["sequence"] > previous_manifest["archived_sequence"],
                "CHECKPOINT_SEQUENCE_REGRESSION: archive source sequence did not advance")
        require(state["sequence"] >= previous_manifest["checkpoint_sequence"],
                "CHECKPOINT_SEQUENCE_REGRESSION: archive source predates predecessor checkpoint")
        require(state["checkpoint"]["checkpoint_hash"] == previous_manifest["new_checkpoint_hash"],
                "CONFLICTING_LINEAGE: source canonical checkpoint does not descend from active archive")

    sequence = state["sequence"]
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
    checkpoint_sequence = sequence + 1
    checkpoint_state = make_snapshot(
        compacted, [], sequence=checkpoint_sequence, evidence={},
        mode="CANONICAL", production_authority=True,
    )
    manifest_path = archive_path.removesuffix(".json.gz") + ".manifest.json"
    overlap_seconds = REPLAY_OVERLAP_MINUTES * 60

    core = {
        "schema_version": ARCHIVE_SCHEMA,
        "archive_id": _archive_identity(sequence, state["state_hash"]),
        "manifest_path": manifest_path,
        "archive_path": archive_path,
        "archive_file_sha256": archive_file_sha256,
        "checkpoint_path": CHECKPOINT_PATH,
        "previous_manifest_hash": None if previous_manifest is None else previous_manifest["manifest_hash"],
        "previous_manifest_path": None if previous_manifest is None else previous_manifest["manifest_path"],
        "previous_archive_id": None if previous_manifest is None else previous_manifest["archive_id"],
        "previous_archived_sequence": None if previous_manifest is None else previous_manifest["archived_sequence"],
        "previous_archived_state_hash": None if previous_manifest is None else previous_manifest["archived_state_hash"],
        "previous_checkpoint_hash": None if previous_manifest is None else previous_manifest["new_checkpoint_hash"],
        "archived_sequence": sequence,
        "archived_state_hash": state["state_hash"],
        "archived_projection_hash": state["projection"]["projection_hash"],
        "archived_checkpoint_hash": state["checkpoint"]["checkpoint_hash"],
        "archived_event_count": state["event_count"],
        "archived_event_hashes": _archived_event_hashes(state),
        "archived_provider_artifacts": _archived_provider_artifacts(state),
        "archived_source_run_ids": _archived_source_run_ids(state),
        "archived_source_attempts": _archived_source_attempts(state),
        "new_checkpoint_hash": compacted["checkpoint_hash"],
        "checkpoint_state_hash": checkpoint_state["state_hash"],
        "checkpoint_sequence": checkpoint_sequence,
        "source_reducer_run_id": source_reducer_run_id,
        "source_artifact_id": source_artifact_id,
        "source_head_sha": source_head_sha,
        "source_artifact_digest": source_artifact_digest,
        "source_artifact_created_at": source_artifact_created_at,
        "archive_created_at": archive_created_at,
        "replay_overlap_seconds": overlap_seconds,
        "artifact_scan_start": _iso(source_created - timedelta(seconds=overlap_seconds)),
    }
    manifest = {**core, "manifest_hash": digest(core)}
    validate_manifest(
        manifest, root=None, archived_state=state, checkpoint_doc=compacted,
        previous_manifest=previous_manifest,
    )
    return manifest, archive_raw, compacted, checkpoint_raw, archive_path


def _read_archived_state(root: Path, manifest: dict) -> dict:
    archive_file = root / manifest["archive_path"]
    require(archive_file.is_file(), "Archived canonical snapshot missing from repository")
    archive_raw = archive_file.read_bytes()
    require(_sha256_bytes(archive_raw) == manifest["archive_file_sha256"],
            "Archived canonical snapshot file digest mismatch")
    try:
        archived_json = gzip.decompress(archive_raw)
    except (OSError, EOFError) as exc:
        raise ValueError("Archive gzip invalid") from exc
    _require_sanitized_archive(archived_json)
    archived_state = strict_load(archived_json)
    validate_snapshot(archived_state)
    require(archived_state["state_hash"] == manifest["archived_state_hash"],
            "Archived state hash mismatch")
    return archived_state


def validate_manifest(
    manifest: dict,
    *,
    root: Path | None = ROOT,
    archived_state: dict | None = None,
    checkpoint_doc: dict | None = None,
    previous_manifest: dict | None = None,
) -> tuple[dict, dict]:
    _validate_manifest_core(manifest)
    if previous_manifest is not None:
        _validate_lineage(manifest, previous_manifest)

    if root is not None:
        checkpoint_file = root / manifest["checkpoint_path"]
        immutable_manifest_file = root / manifest["manifest_path"]
        require(checkpoint_file.is_file(), "Compacted checkpoint missing from repository")
        require(immutable_manifest_file.is_file(), "Immutable archive manifest missing from repository")
        immutable = strict_load(immutable_manifest_file.read_bytes())
        require(immutable == manifest, "Active and immutable archive manifests differ")
        archived_state = _read_archived_state(root, manifest)
        try:
            checkpoint_json = gzip.decompress(checkpoint_file.read_bytes())
        except (OSError, EOFError) as exc:
            raise ValueError("Checkpoint gzip invalid") from exc
        _require_sanitized_archive(checkpoint_json)
        checkpoint_doc = strict_load(checkpoint_json)
        if (
            manifest["schema_version"] == ARCHIVE_SCHEMA
            and manifest["previous_manifest_hash"] is not None
            and previous_manifest is None
        ):
            previous_path = root / manifest["previous_manifest_path"]
            require(previous_path.is_file(), "CONFLICTING_LINEAGE: predecessor manifest missing")
            previous_manifest = strict_load(previous_path.read_bytes())
            _validate_lineage(manifest, previous_manifest)

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
    require(checkpoint_doc["states"] == archived_state["projection"]["states"],
            "Compacted checkpoint state differs from archived projection")
    expected_ref = _checkpoint_ref(
        archive_path=manifest["archive_path"],
        archive_file_sha256=manifest["archive_file_sha256"],
        state_hash=manifest["archived_state_hash"],
    )
    require(set(checkpoint_doc["source_refs"].values()) == {expected_ref},
            "Compacted checkpoint provenance does not bind archive")
    if manifest["schema_version"] == ARCHIVE_SCHEMA:
        require(_archived_source_run_ids(archived_state) == manifest["archived_source_run_ids"],
                "Archived source run coverage mismatch")
        require(_archived_source_attempts(archived_state) == manifest["archived_source_attempts"],
                "Archived source run/attempt coverage mismatch")
        checkpoint_state = make_snapshot(
            checkpoint_doc, [], sequence=manifest["checkpoint_sequence"], evidence={},
            mode="CANONICAL", production_authority=True,
        )
        require(checkpoint_state["state_hash"] == manifest["checkpoint_state_hash"],
                "Checkpoint replay root hash mismatch")
    return archived_state, checkpoint_doc


def load_active_manifest(root: Path = ROOT) -> dict | None:
    path = root / "state_journal" / "ARCHIVE_MANIFEST.json"
    if not path.exists():
        return None
    manifest = strict_load(path.read_bytes())
    try:
        validate_manifest(manifest, root=root)
    except JournalError as exc:
        message = str(exc)
        if message.startswith(("CONFLICTING_LINEAGE:", "CHECKPOINT_SEQUENCE_REGRESSION:")):
            raise
        raise JournalError("CORRUPTED_CHECKPOINT: " + message) from exc
    except Exception as exc:
        raise JournalError("CORRUPTED_CHECKPOINT: " + str(exc)) from exc
    return manifest


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


def archived_source_run_ids(manifest: dict | None, root: Path = ROOT) -> set[int]:
    if manifest is None:
        return set()
    if "archived_source_run_ids" in manifest:
        return set(manifest["archived_source_run_ids"])
    # v1.0 compatibility: derive coverage from the targeted immutable archive
    # rather than enumerating Actions history or guessing from disappeared artifacts.
    state = _read_archived_state(root, manifest)
    return set(_archived_source_run_ids(state))


def archived_source_attempts(manifest: dict | None, root: Path = ROOT) -> set[tuple[int, int]]:
    if manifest is None:
        return set()
    if "archived_source_attempts" in manifest:
        return {
            tuple(int(part) for part in value.split(":"))
            for value in manifest["archived_source_attempts"]
        }
    # v1.0 compatibility: targeted immutable archive lookup, never Actions enumeration.
    state = _read_archived_state(root, manifest)
    return {
        tuple(int(part) for part in value.split(":"))
        for value in _archived_source_attempts(state)
    }
