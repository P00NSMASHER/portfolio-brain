"""Fail-closed, chunked durable SQLite transport for the public Brain state branch.

Git preserves the entire event ledger; no event, report, or history is pruned.
Every chunk is smaller than GitHub's single-file limit. Existing raw SQLite
state remains readable for a one-time, nonforce migration.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import zlib

FORMAT = "sqlite-zlib-chunks-v1"
MANIFEST = "state-manifest.json"
PARTS = "state-chunks"
RAW = "state.sqlite"
CHUNK_BYTES = 8 * 1024 * 1024
MAX_DB_BYTES = 64 * 1024 * 1024 * 1024
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
PART_NAME = re.compile(r"part-[0-9]{6}[.]z\Z")
HEX = re.compile(r"[0-9a-f]{64}\Z")


class StateArchiveError(RuntimeError):
    """An invalid state archive must never be published or restored."""


def reject(message):
    raise StateArchiveError(message)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def _database_ok(path):
    if path.is_symlink() or not path.is_file():
        reject("STATE_DATABASE_MISSING_OR_UNSAFE")
    try:
        with sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True) as db:
            if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                reject("STATE_DATABASE_INTEGRITY_FAILED")
            if db.execute("PRAGMA foreign_key_check").fetchone() is not None:
                reject("STATE_DATABASE_FOREIGN_KEYS_FAILED")
    except sqlite3.Error as exc:
        raise StateArchiveError("STATE_DATABASE_SQLITE_UNREADABLE") from exc


def _read_manifest(root):
    path = root / MANIFEST
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_MANIFEST_BYTES:
        reject("STATE_MANIFEST_MISSING_OR_UNSAFE")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError, OSError) as exc:
        raise StateArchiveError("STATE_MANIFEST_INVALID_JSON") from exc
    if type(document) is not dict or set(document) != {
        "schema_version", "format", "raw_size", "raw_sha256",
        "compressed_size", "compressed_sha256", "chunks"
    }:
        reject("STATE_MANIFEST_SCHEMA")
    if document["schema_version"] != 1 or document["format"] != FORMAT:
        reject("STATE_MANIFEST_FORMAT")
    raw_size = document["raw_size"]
    comp_size = document["compressed_size"]
    if type(raw_size) is not int or not 0 < raw_size <= MAX_DB_BYTES:
        reject("STATE_MANIFEST_RAW_SIZE")
    if type(comp_size) is not int or not 0 < comp_size <= MAX_DB_BYTES:
        reject("STATE_MANIFEST_COMPRESSED_SIZE")
    if any(type(document[key]) is not str or not HEX.fullmatch(document[key])
           for key in ("raw_sha256", "compressed_sha256")):
        reject("STATE_MANIFEST_HASH")
    chunks = document["chunks"]
    if type(chunks) is not list or not 0 < len(chunks) <= (MAX_DB_BYTES // CHUNK_BYTES) + 1:
        reject("STATE_MANIFEST_CHUNK_COUNT")
    total_raw = total_comp = 0
    for i, chunk in enumerate(chunks):
        if type(chunk) is not dict or set(chunk) != {
            "name", "raw_size", "raw_sha256", "size", "sha256"
        }:
            reject("STATE_MANIFEST_CHUNK_SCHEMA")
        if type(chunk["name"]) is not str or not PART_NAME.fullmatch(chunk["name"]) or (
            chunk["name"] != f"part-{i:06d}.z"
        ):
            reject("STATE_MANIFEST_CHUNK_NAME")
        if type(chunk["raw_size"]) is not int or not 0 < chunk["raw_size"] <= CHUNK_BYTES:
            reject("STATE_MANIFEST_CHUNK_RAW_SIZE")
        if type(chunk["size"]) is not int or not 0 < chunk["size"] <= CHUNK_BYTES + 32768:
            reject("STATE_MANIFEST_CHUNK_SIZE")
        if any(type(chunk[key]) is not str or not HEX.fullmatch(chunk[key])
               for key in ("raw_sha256", "sha256")):
            reject("STATE_MANIFEST_CHUNK_HASH")
        total_raw += chunk["raw_size"]
        total_comp += chunk["size"]
    if total_raw != raw_size or total_comp != comp_size:
        reject("STATE_MANIFEST_TOTAL_MISMATCH")
    if any(c["raw_size"] != CHUNK_BYTES for c in chunks[:-1]):
        reject("STATE_MANIFEST_CHUNK_ALIGNMENT")
    return document


def _extract(root, target):
    manifest = _read_manifest(root)
    folder = root / PARTS
    if folder.is_symlink() or not folder.is_dir():
        reject("STATE_PART_DIRECTORY_MISSING_OR_UNSAFE")
    expected = {chunk["name"] for chunk in manifest["chunks"]}
    if {p.name for p in folder.iterdir()} != expected:
        reject("STATE_CHUNK_SET_MISMATCH")
    raw_hash = hashlib.sha256()
    comp_hash = hashlib.sha256()
    raw_len = comp_len = 0
    with target.open("xb") as out:
        os.chmod(target, 0o600)
        for chunk in manifest["chunks"]:
            part = folder / chunk["name"]
            if part.is_symlink() or not part.is_file() or part.stat().st_size != chunk["size"]:
                reject("STATE_CHUNK_MISSING_OR_UNSAFE")
            packed = part.read_bytes()
            if sha256(packed) != chunk["sha256"]:
                reject("STATE_CHUNK_DIGEST_MISMATCH")
            comp_len += len(packed)
            comp_hash.update(packed)
            try:
                inflater = zlib.decompressobj()
                raw = inflater.decompress(packed, CHUNK_BYTES + 1)
                if (inflater.unconsumed_tail or inflater.unused_data or
                        not inflater.eof or len(raw) != chunk["raw_size"]):
                    reject("STATE_CHUNK_DECOMPRESSION_BOUNDARY")
            except zlib.error as exc:
                raise StateArchiveError("STATE_CHUNK_DECOMPRESSION_FAILED") from exc
            if sha256(raw) != chunk["raw_sha256"]:
                reject("STATE_CHUNK_RAW_DIGEST_MISMATCH")
            out.write(raw)
            raw_hash.update(raw)
            raw_len += len(raw)
        out.flush()
        os.fsync(out.fileno())
    if (raw_len != manifest["raw_size"] or comp_len != manifest["compressed_size"] or
            raw_hash.hexdigest() != manifest["raw_sha256"] or
            comp_hash.hexdigest() != manifest["compressed_sha256"]):
        reject("STATE_ARCHIVE_WHOLE_FILE_MISMATCH")
    _database_ok(target)
    return manifest


def restore(root):
    root = Path(root)
    raw = root / RAW
    manifest = root / MANIFEST
    if raw.exists() or raw.is_symlink():
        if manifest.exists() or manifest.is_symlink():
            reject("STATE_ARCHIVE_AMBIGUOUS_DUAL_FORMAT")
        _database_ok(raw)
        return {"storage_format": "legacy_sqlite", "raw_size": raw.stat().st_size,
                "restored": True}
    if not manifest.exists():
        reject("STATE_UNAVAILABLE")
    with tempfile.TemporaryDirectory(prefix=".restore-", dir=root) as staging:
        temporary = Path(staging) / RAW
        document = _extract(root, temporary)
        os.replace(temporary, raw)
    return {"storage_format": FORMAT, "raw_size": document["raw_size"],
            "raw_sha256": document["raw_sha256"], "chunks": len(document["chunks"]),
            "restored": True}


def pack(root):
    root = Path(root)
    raw_path = root / RAW
    _database_ok(raw_path)
    raw_size = raw_path.stat().st_size
    if not 0 < raw_size <= MAX_DB_BYTES:
        reject("STATE_DATABASE_SIZE_UNSUPPORTED")
    with tempfile.TemporaryDirectory(prefix=".pack-", dir=root) as staging:
        tmp = Path(staging)
        folder = tmp / PARTS
        folder.mkdir()
        raw_hash = hashlib.sha256()
        comp_hash = hashlib.sha256()
        raw_len = comp_len = 0
        chunks = []
        with raw_path.open("rb") as source:
            for i in range((raw_size + CHUNK_BYTES - 1) // CHUNK_BYTES):
                raw = source.read(CHUNK_BYTES)
                if not raw:
                    reject("STATE_DATABASE_CHANGED_DURING_PACK")
                raw_len += len(raw)
                raw_hash.update(raw)
                packed = zlib.compress(raw, level=6)
                comp_hash.update(packed)
                comp_len += len(packed)
                name = f"part-{i:06d}.z"
                part = folder / name
                part.write_bytes(packed)
                os.chmod(part, 0o600)
                chunks.append({"name": name, "raw_size": len(raw),
                               "raw_sha256": sha256(raw), "size": len(packed),
                               "sha256": sha256(packed)})
            if source.read(1) or raw_len != raw_size:
                reject("STATE_DATABASE_CHANGED_DURING_PACK")
        manifest = {
            "schema_version": 1, "format": FORMAT, "raw_size": raw_size,
            "raw_sha256": raw_hash.hexdigest(), "compressed_size": comp_len,
            "compressed_sha256": comp_hash.hexdigest(), "chunks": chunks,
        }
        (tmp / MANIFEST).write_text(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        # Verify reconstructed bytes and SQLite integrity BEFORE replacing any
        # checkout files. The protected Git parent is never modified by this step.
        _extract(tmp, tmp / "verified.sqlite")
        if sha256(raw_path.read_bytes()) != manifest["raw_sha256"]:
            reject("STATE_DATABASE_CHANGED_DURING_VERIFICATION")
        destination = root / PARTS
        if destination.is_symlink() or (destination.exists() and not destination.is_dir()):
            reject("STATE_PART_DESTINATION_UNSAFE")
        destination.mkdir(exist_ok=True)
        for part in folder.iterdir():
            target = destination / part.name
            if target.is_symlink() or (target.exists() and not target.is_file()):
                reject("STATE_PART_DESTINATION_UNSAFE")
            os.replace(part, target)
        active = {chunk["name"] for chunk in chunks}
        for stale in destination.iterdir():
            if stale.name not in active:
                if stale.is_symlink() or not stale.is_file():
                    reject("STATE_PART_DESTINATION_UNSAFE")
                stale.unlink()
        if (root / MANIFEST).is_symlink():
            reject("STATE_MANIFEST_DESTINATION_UNSAFE")
        os.replace(tmp / MANIFEST, root / MANIFEST)
        raw_path.unlink()
    return {"storage_format": FORMAT, "raw_size": raw_size,
            "compressed_size": comp_len, "chunks": len(chunks),
            "raw_sha256": manifest["raw_sha256"],
            "state_warning": "GROWTH_EXCEEDS_80_MIB" if raw_size >= 80 * 1024 * 1024 else None,
            "published": False}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("restore", "pack"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--status", type=Path)
    args = parser.parse_args(argv)
    result = restore(args.root) if args.operation == "restore" else pack(args.root)
    body = json.dumps(result, sort_keys=True, indent=2) + "\n"
    if args.status:
        if args.status.is_symlink():
            reject("STATE_STATUS_DESTINATION_UNSAFE")
        args.status.parent.mkdir(parents=True, exist_ok=True)
        args.status.write_text(body, encoding="utf-8")
    print(body, end="")


if __name__ == "__main__":
    main()
