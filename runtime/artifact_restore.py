#!/usr/bin/env python3
"""Shared fail-closed helpers for durable GitHub Actions state restore."""
from __future__ import annotations

import json
import hashlib
import os
import tempfile
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any, Callable


class InvalidStateArtifact(ValueError):
    pass


def _validated_payload(
    raw: bytes,
    *,
    member_name: str,
    expected_state_id: str,
    max_archive_bytes: int,
    max_state_bytes: int,
    validator: Callable[[dict[str, Any]], None] | None,
) -> tuple[bytes, int, str]:
    if len(raw) > max_archive_bytes:
        raise InvalidStateArtifact("artifact archive exceeds byte budget")
    try:
        with zipfile.ZipFile(BytesIO(raw)) as archive:
            matches = [info for info in archive.infolist() if info.filename == member_name]
            if len(matches) != 1:
                raise InvalidStateArtifact(f"artifact must contain exactly one {member_name}")
            info = matches[0]
            if info.is_dir() or info.file_size > max_state_bytes:
                raise InvalidStateArtifact("state member exceeds byte budget")
            body = archive.read(info)
    except (zipfile.BadZipFile, RuntimeError, OSError) as exc:
        raise InvalidStateArtifact("artifact is not a readable zip archive") from exc
    if len(body) != info.file_size or len(body) > max_state_bytes:
        raise InvalidStateArtifact("state member size mismatch")
    try:
        state = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InvalidStateArtifact("state member is not valid UTF-8 JSON") from exc
    if not isinstance(state, dict):
        raise InvalidStateArtifact("state payload must be an object")
    if state.get("schema_version") != "1.0.0" or state.get("state_id") != expected_state_id:
        raise InvalidStateArtifact("state identity mismatch")
    if type(state.get("sequence")) is not int or state["sequence"] < 0:
        raise InvalidStateArtifact("state sequence invalid")
    if validator is not None:
        try:
            validator(state)
        except Exception as exc:
            raise InvalidStateArtifact("state payload failed subsystem validation") from exc
    canonical = json.dumps(state, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    state_hash = "sha256:" + hashlib.sha256(canonical).hexdigest()
    return body, state["sequence"], state_hash


def _atomic_write(output: Path, payload: bytes) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=output.parent, prefix=f".{output.name}.", suffix=".tmp", delete=False
        ) as handle:
            temporary = handle.name
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, output)
        temporary = None
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass


def restore_latest_valid_state(
    data: dict[str, Any],
    *,
    current_run: str | None,
    expected_head_branch: str | None = None,
    download: Callable[[str], bytes],
    output: Path,
    member_name: str,
    expected_state_id: str,
    max_archive_bytes: int,
    max_state_bytes: int,
    validator: Callable[[dict[str, Any]], None] | None = None,
    metadata_output: Path | None = None,
    max_candidates: int = 5,
) -> str:
    if type(max_candidates) is not int or max_candidates < 1:
        raise ValueError("max_candidates must be a positive integer")
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
    if not candidates:
        if metadata_output is not None:
            _atomic_write(metadata_output, (json.dumps({
                "schema_version":"1.0.0",
                "restore_status":"NO_PRIOR_ARTIFACT",
                "artifact_id":None,
                "artifact_name":None,
                "artifact_created_at":None,
                "artifact_expires_at":None,
                "source_run_id":None,
                "source_head_sha":None,
            },sort_keys=True)+"\n").encode("utf-8"))
        return "NO_PRIOR_ARTIFACT"
    candidates.sort(key=lambda item: (item.get("created_at", ""), item.get("id", 0)), reverse=True)
    rejected = 0
    valid: list[tuple[int, dict[str, Any], bytes, str]] = []
    for item in candidates[:max_candidates]:
        url = item.get("archive_download_url")
        if not isinstance(url, str) or not url:
            rejected += 1
            continue
        try:
            raw = download(url)
        except Exception:
            # GitHub can briefly retain an unexpired artifact record after its
            # archive becomes unavailable. Treat that candidate exactly like
            # an invalid archive and continue to the next validated
            # predecessor. If every candidate is unavailable, restoration
            # still fails closed below.
            rejected += 1
            continue
        try:
            payload, sequence, state_hash = _validated_payload(
                raw,
                member_name=member_name,
                expected_state_id=expected_state_id,
                max_archive_bytes=max_archive_bytes,
                max_state_bytes=max_state_bytes,
                validator=validator,
            )
        except InvalidStateArtifact:
            rejected += 1
            continue
        valid.append((sequence, item, payload, state_hash))
    if not valid:
        raise InvalidStateArtifact("no valid prior state artifact found")

    # Upload completion time is not a state-version clock. Concurrent or retried
    # workflows can upload a stale snapshot after a more advanced predecessor.
    # Choose the greatest validated sequence within the bounded restore window;
    # creation time remains the deterministic tie-breaker because ``valid``
    # preserves the newest-first candidate order.
    highest_sequence = max(entry[0] for entry in valid)
    highest = [entry for entry in valid if entry[0] == highest_sequence]
    if len({entry[3] for entry in highest}) != 1:
        # A sequence is a durable-state version, not merely an ordering hint.
        # Divergent payloads claiming the same latest version are an ambiguous
        # fork caused by a race or corruption. Upload time cannot safely decide
        # which branch contains every committed mutation, so fail closed.
        raise InvalidStateArtifact("conflicting state artifacts at highest sequence")
    sequence, item, payload, state_hash = highest[0]
    selected_newest_valid = item is valid[0][1]
    status = "RESTORED" if selected_newest_valid else "RESTORED_HIGHEST_SEQUENCE"
    if rejected:
        status += f"_AFTER_REJECTING_{rejected}_INVALID"
    _atomic_write(output, payload)
    if metadata_output is not None:
        workflow_run=item.get("workflow_run") or {}
        _atomic_write(metadata_output, (json.dumps({
            "schema_version":"1.0.0",
            "restore_status":status,
            "artifact_id":item.get("id"),
            "artifact_name":item.get("name"),
            "artifact_created_at":item.get("created_at"),
            "artifact_expires_at":item.get("expires_at"),
            "source_run_id":workflow_run.get("id"),
            "source_head_sha":workflow_run.get("head_sha"),
            "source_sequence":sequence,
            "source_state_hash":state_hash,
            "candidates_inspected":min(len(candidates), max_candidates),
        },sort_keys=True)+"\n").encode("utf-8"))
    return status
