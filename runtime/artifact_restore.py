#!/usr/bin/env python3
"""Shared fail-closed helpers for durable GitHub Actions state restore."""
from __future__ import annotations

import json
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
) -> bytes:
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
    return body


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
    download: Callable[[str], bytes],
    output: Path,
    member_name: str,
    expected_state_id: str,
    max_archive_bytes: int,
    max_state_bytes: int,
    validator: Callable[[dict[str, Any]], None] | None = None,
    metadata_output: Path | None = None,
) -> str:
    candidates = [
        item
        for item in data.get("artifacts", [])
        if not item.get("expired")
        and str((item.get("workflow_run") or {}).get("id")) != str(current_run)
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
    for item in candidates:
        url = item.get("archive_download_url")
        if not isinstance(url, str) or not url:
            rejected += 1
            continue
        raw = download(url)
        try:
            payload = _validated_payload(
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
        _atomic_write(output, payload)
        status="RESTORED" if rejected == 0 else f"RESTORED_AFTER_REJECTING_{rejected}_INVALID"
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
            },sort_keys=True)+"\n").encode("utf-8"))
        return status
    raise InvalidStateArtifact("no valid prior state artifact found")
