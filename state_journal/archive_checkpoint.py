#!/usr/bin/env python3
"""Build and validate durable, lineage-linked canonical journal archives."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from state_journal.contracts import canonical, digest, require, strict_load
from state_journal.reducer import validate_snapshot

ARCHIVE_BRANCH = "archive/state-journal"
ARCHIVE_SCHEMA = "1.0.0"
OVERLAP_MINUTES = 30
SECRET_RE = re.compile(
    rb"(?:github_pat_[A-Za-z0-9_]{20,}|gh[pousr]_[A-Za-z0-9_]{20,}|"
    rb"sk-[A-Za-z0-9_-]{20,}|-----BEGIN [A-Z ]*PRIVATE KEY-----)",
    re.I,
)


def _utc(value: str) -> datetime:
    require(isinstance(value, str) and value.endswith("Z"), "archive timestamp must be UTC ISO-8601")
    try:
        dt = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError("archive timestamp invalid") from exc
    return dt.astimezone(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _manifest_body(manifest: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in manifest.items() if k != "manifest_hash"}


def validate_manifest(manifest: dict[str, Any], *, previous: dict[str, Any] | None = None) -> None:
    required = {
        "schema_version", "archive_id", "archive_branch", "snapshot_member", "archived_at",
        "canonical_sequence", "canonical_state_hash", "checkpoint_hash", "event_count",
        "source_reducer_run_id", "source_head_sha", "source_artifact_id",
        "source_artifact_digest", "source_artifact_created_at", "source_artifact_expires_at",
        "snapshot_gzip_sha256", "snapshot_json_sha256", "replay_scan_start",
        "previous_manifest_hash", "previous_checkpoint_hash", "previous_canonical_state_hash",
        "previous_sequence", "sanitized", "manifest_hash",
    }
    require(isinstance(manifest, dict) and set(manifest) == required, "archive manifest fields changed")
    require(manifest["schema_version"] == ARCHIVE_SCHEMA, "archive manifest schema changed")
    require(manifest["archive_branch"] == ARCHIVE_BRANCH, "archive branch changed")
    require(manifest["snapshot_member"] == "snapshot.json.gz", "archive snapshot member changed")
    require(type(manifest["canonical_sequence"]) is int and manifest["canonical_sequence"] >= 0, "archive sequence invalid")
    require(type(manifest["event_count"]) is int and manifest["event_count"] >= 0, "archive event count invalid")
    require(type(manifest["source_reducer_run_id"]) is int and manifest["source_reducer_run_id"] > 0, "archive source run invalid")
    require(type(manifest["source_artifact_id"]) is int and manifest["source_artifact_id"] > 0, "archive source artifact invalid")
    require(re.fullmatch(r"[0-9a-f]{40}", str(manifest["source_head_sha"])) is not None, "archive source SHA invalid")
    for key in ("canonical_state_hash", "checkpoint_hash", "source_artifact_digest",
                "snapshot_gzip_sha256", "snapshot_json_sha256", "manifest_hash"):
        require(re.fullmatch(r"sha256:[0-9a-f]{64}", str(manifest[key])) is not None, f"archive {key} invalid")
    _utc(manifest["archived_at"]); _utc(manifest["source_artifact_created_at"]); _utc(manifest["replay_scan_start"])
    if manifest["source_artifact_expires_at"] is not None:
        _utc(manifest["source_artifact_expires_at"])
    require(manifest["sanitized"] is True, "archive must be explicitly sanitized")
    expected = digest(_manifest_body(manifest))
    require(manifest["manifest_hash"] == expected, "archive manifest hash mismatch")
    expected_id = "PARCH-" + expected.split(":", 1)[1][:24].upper()
    require(manifest["archive_id"] == expected_id, "archive id mismatch")
    if previous is None:
        require(manifest["previous_manifest_hash"] is None, "first archive has previous manifest")
        require(manifest["previous_checkpoint_hash"] is None, "first archive has previous checkpoint")
        require(manifest["previous_canonical_state_hash"] is None, "first archive has previous state")
        require(manifest["previous_sequence"] is None, "first archive has previous sequence")
    else:
        validate_manifest(previous)
        require(manifest["previous_manifest_hash"] == previous["manifest_hash"], "archive manifest lineage mismatch")
        require(manifest["previous_checkpoint_hash"] == previous["checkpoint_hash"], "archive checkpoint lineage mismatch")
        require(manifest["previous_canonical_state_hash"] == previous["canonical_state_hash"], "archive state lineage mismatch")
        require(manifest["previous_sequence"] == previous["canonical_sequence"], "archive sequence lineage mismatch")
        require(manifest["canonical_sequence"] >= previous["canonical_sequence"], "archive sequence regressed")


def build_archive(
    snapshot: dict[str, Any],
    *,
    source_reducer_run_id: int,
    source_head_sha: str,
    source_artifact_id: int,
    source_artifact_digest: str,
    source_artifact_created_at: str,
    source_artifact_expires_at: str | None,
    archived_at: str,
    previous: dict[str, Any] | None = None,
) -> tuple[bytes, dict[str, Any]]:
    validate_snapshot(snapshot)
    require(snapshot["mode"] == "CANONICAL" and snapshot["production_authority"] is True,
            "only production-authoritative canonical snapshots may be archived")
    raw = canonical(snapshot) + b"\n"
    require(SECRET_RE.search(raw) is None, "credential-like material cannot enter public archive")
    gz = gzip.compress(raw, compresslevel=9, mtime=0)
    created = _utc(source_artifact_created_at)
    body = {
        "schema_version": ARCHIVE_SCHEMA,
        "archive_id": "",
        "archive_branch": ARCHIVE_BRANCH,
        "snapshot_member": "snapshot.json.gz",
        "archived_at": archived_at,
        "canonical_sequence": snapshot["sequence"],
        "canonical_state_hash": snapshot["state_hash"],
        "checkpoint_hash": snapshot["checkpoint"]["checkpoint_hash"],
        "event_count": snapshot["event_count"],
        "source_reducer_run_id": source_reducer_run_id,
        "source_head_sha": source_head_sha,
        "source_artifact_id": source_artifact_id,
        "source_artifact_digest": source_artifact_digest,
        "source_artifact_created_at": source_artifact_created_at,
        "source_artifact_expires_at": source_artifact_expires_at,
        "snapshot_gzip_sha256": _sha256(gz),
        "snapshot_json_sha256": _sha256(raw),
        "replay_scan_start": _iso(created - timedelta(minutes=OVERLAP_MINUTES)),
        "previous_manifest_hash": None if previous is None else previous["manifest_hash"],
        "previous_checkpoint_hash": None if previous is None else previous["checkpoint_hash"],
        "previous_canonical_state_hash": None if previous is None else previous["canonical_state_hash"],
        "previous_sequence": None if previous is None else previous["canonical_sequence"],
        "sanitized": True,
    }
    manifest_hash = digest(body)
    body["archive_id"] = "PARCH-" + manifest_hash.split(":", 1)[1][:24].upper()
    body["manifest_hash"] = digest({k: v for k, v in body.items() if k != "manifest_hash"})
    # archive_id participates in the final manifest hash, so bind it to that hash.
    body["archive_id"] = "PARCH-" + body["manifest_hash"].split(":", 1)[1][:24].upper()
    body["manifest_hash"] = digest({k: v for k, v in body.items() if k != "manifest_hash"})
    body["archive_id"] = "PARCH-" + body["manifest_hash"].split(":", 1)[1][:24].upper()
    # One final pass reaches a stable ID/hash pair because ID is derived only from hash.
    body["manifest_hash"] = digest({k: v for k, v in body.items() if k != "manifest_hash"})
    body["archive_id"] = "PARCH-" + body["manifest_hash"].split(":", 1)[1][:24].upper()
    body["manifest_hash"] = digest({k: v for k, v in body.items() if k != "manifest_hash"})
    validate_manifest(body, previous=previous)
    return gz, body


def verify_archive(snapshot_gz: bytes, manifest: dict[str, Any], *, previous: dict[str, Any] | None = None) -> dict[str, Any]:
    validate_manifest(manifest, previous=previous)
    require(_sha256(snapshot_gz) == manifest["snapshot_gzip_sha256"], "archive gzip digest mismatch")
    try:
        raw = gzip.decompress(snapshot_gz)
    except (OSError, EOFError) as exc:
        raise ValueError("archive gzip invalid") from exc
    require(_sha256(raw) == manifest["snapshot_json_sha256"], "archive JSON digest mismatch")
    require(SECRET_RE.search(raw) is None, "credential-like material detected in archive")
    snapshot = strict_load(raw)
    validate_snapshot(snapshot)
    require(snapshot["state_hash"] == manifest["canonical_state_hash"], "archive state hash mismatch")
    require(snapshot["sequence"] == manifest["canonical_sequence"], "archive sequence mismatch")
    require(snapshot["checkpoint"]["checkpoint_hash"] == manifest["checkpoint_hash"], "archive checkpoint mismatch")
    return snapshot


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    build = sub.add_parser("build")
    build.add_argument("--snapshot", type=Path, required=True)
    build.add_argument("--previous-manifest", type=Path)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--manifest", type=Path, required=True)
    build.add_argument("--source-run-id", type=int, required=True)
    build.add_argument("--source-head-sha", required=True)
    build.add_argument("--source-artifact-id", type=int, required=True)
    build.add_argument("--source-artifact-digest", required=True)
    build.add_argument("--source-artifact-created-at", required=True)
    build.add_argument("--source-artifact-expires-at")
    build.add_argument("--archived-at", required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("--snapshot", type=Path, required=True)
    verify.add_argument("--manifest", type=Path, required=True)
    verify.add_argument("--previous-manifest", type=Path)
    args = ap.parse_args()

    previous = json.loads(args.previous_manifest.read_text()) if getattr(args, "previous_manifest", None) and args.previous_manifest.exists() else None
    if args.cmd == "build":
        snapshot = strict_load(args.snapshot.read_bytes())
        gz, manifest = build_archive(
            snapshot,
            source_reducer_run_id=args.source_run_id,
            source_head_sha=args.source_head_sha,
            source_artifact_id=args.source_artifact_id,
            source_artifact_digest=args.source_artifact_digest,
            source_artifact_created_at=args.source_artifact_created_at,
            source_artifact_expires_at=args.source_artifact_expires_at,
            archived_at=args.archived_at,
            previous=previous,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(gz)
        args.manifest.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
        print(json.dumps({"status": "PASS", "archive_id": manifest["archive_id"], "canonical_sequence": manifest["canonical_sequence"], "manifest_hash": manifest["manifest_hash"]}, sort_keys=True))
    else:
        snapshot = verify_archive(args.snapshot.read_bytes(), json.loads(args.manifest.read_text()), previous=previous)
        print(json.dumps({"status": "PASS", "canonical_sequence": snapshot["sequence"], "state_hash": snapshot["state_hash"]}, sort_keys=True))


if __name__ == "__main__":
    main()
