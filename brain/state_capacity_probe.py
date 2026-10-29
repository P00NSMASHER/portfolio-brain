"""Build and independently verify a bounded synthetic state-capacity image.

The probe exercises the production archive codec with real SQLite bytes.  It
does not publish state or turn temporary CI storage into a production store.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sqlite3

from brain.core import canonical, digest
from brain.state_archive import MAX_DB_BYTES, pack, restore
from soak_v3.audit import verify_sqlite
from soak_v3.chunked_evidence import MAX_RAW_BYTES as MAX_AUDIT_BYTES


TARGET_BYTES = 5_000_000_000
FIXTURE_SOURCE_SHA = "a" * 40
OBSERVED_AT = "2026-10-16T00:00:00Z"
SHA40 = re.compile(r"[0-9a-f]{40}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class CapacityProbeError(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise CapacityProbeError(message)


def _sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def build(root, *, target_bytes=TARGET_BYTES, padding_bytes=64 * 1024 * 1024,
          code_source_sha=FIXTURE_SOURCE_SHA):
    """Create, pack and receipt a new synthetic image of at least target_bytes."""
    root = Path(root)
    # Keep enough headroom below the 5 GiB replay ceiling for SQLite pages.
    require(type(target_bytes) is int and 0 < target_bytes <= TARGET_BYTES,
            "CAPACITY_TARGET_INVALID")
    require(type(padding_bytes) is int and 4096 <= padding_bytes <= 64 * 1024 * 1024,
            "CAPACITY_PADDING_INVALID")
    require(type(code_source_sha) is str and SHA40.fullmatch(code_source_sha),
            "CAPACITY_SOURCE_SHA_INVALID")
    require(root.is_dir() and not root.is_symlink(), "CAPACITY_ROOT_INVALID")
    database = root / "state.sqlite"
    require(not database.exists() and not database.is_symlink(),
            "CAPACITY_DATABASE_EXISTS")

    event = {
        "id": "", "kind": "repository", "key": "capacity-probe",
        "observed_at": OBSERVED_AT, "source_sha": FIXTURE_SOURCE_SHA,
        "visibility": "PUBLIC", "data_kind": "ACTUAL", "payload": {},
    }
    event["id"] = "repository:" + digest(event)
    event_hash = digest(event)
    chain = digest({"seq": 1, "event_hash": event_hash, "previous": "0" * 64})
    report = {
        "status": "PASS", "source_sha": FIXTURE_SOURCE_SHA, "pending_events": 0,
        "state_sequence": 1, "canonical_hash": chain,
    }

    with sqlite3.connect(database) as db:
        db.executescript("""
        PRAGMA foreign_keys=ON;
        CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE events(seq INTEGER PRIMARY KEY AUTOINCREMENT,
          id TEXT UNIQUE NOT NULL,body TEXT NOT NULL,hash TEXT NOT NULL,
          status TEXT NOT NULL,received_at TEXT NOT NULL);
        CREATE TABLE ledger(seq INTEGER PRIMARY KEY,prev_hash TEXT NOT NULL,
          chain_hash TEXT NOT NULL);
        CREATE TABLE reports(id INTEGER PRIMARY KEY AUTOINCREMENT,
          seq INTEGER NOT NULL,chain_hash TEXT NOT NULL,source_sha TEXT NOT NULL,
          created_at TEXT NOT NULL,body TEXT NOT NULL,hash TEXT NOT NULL);
        CREATE TABLE attempts(id INTEGER PRIMARY KEY AUTOINCREMENT,
          created_at TEXT NOT NULL,operation TEXT NOT NULL,status TEXT NOT NULL,
          error_class TEXT,source_sha TEXT,event_seq INTEGER,details TEXT NOT NULL);
        CREATE TABLE capacity_probe(id INTEGER PRIMARY KEY,payload BLOB NOT NULL);
        """)
        db.executemany("INSERT INTO meta VALUES(?,?)",
                       (("schema_version", "2"), ("visibility", "PUBLIC")))
        db.execute("INSERT INTO events VALUES(?,?,?,?,?,?)",
                   (1, event["id"], canonical(event), event_hash, "APPLIED", OBSERVED_AT))
        db.execute("INSERT INTO ledger VALUES(?,?,?)", (1, "0" * 64, chain))
        db.execute("INSERT INTO reports VALUES(?,?,?,?,?,?,?)",
                   (1, 1, chain, FIXTURE_SOURCE_SHA, OBSERVED_AT,
                    canonical(report), digest(report)))
        while database.stat().st_size < target_bytes:
            remaining = target_bytes - database.stat().st_size
            db.execute("INSERT INTO capacity_probe(payload) VALUES(zeroblob(?))",
                       (min(padding_bytes, max(4096, remaining)),))
            db.commit()
        if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise CapacityProbeError("CAPACITY_FIXTURE_CORRUPT")

    raw_bytes = database.stat().st_size
    raw_sha = _sha256(database)
    packed = pack(root)
    require(packed["raw_size"] == raw_bytes and packed["raw_sha256"] == raw_sha,
            "CAPACITY_PACK_RECEIPT_MISMATCH")
    receipt = {
        "schema_version": 1,
        "status": "PACKED_5GB_CANDIDATE_NOT_PRODUCTION_CAPACITY",
        "target_bytes": target_bytes,
        "raw_size": raw_bytes,
        "raw_sha256": raw_sha,
        "compressed_size": packed["compressed_size"],
        "chunks": packed["chunks"],
        "code_source_sha": code_source_sha,
        "fixture_source_sha": FIXTURE_SOURCE_SHA,
        "state_sequence": 1,
        "canonical_hash": chain,
        "published": False,
        "production_capacity_verified": False,
    }
    (root / "capacity-receipt.json").write_text(
        json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return receipt


def verify(root, *, minimum_bytes=TARGET_BYTES,
           expected_code_source=FIXTURE_SOURCE_SHA):
    """Restore an independently transferred archive and replay its state."""
    root = Path(root)
    require(type(minimum_bytes) is int and 0 < minimum_bytes <= MAX_AUDIT_BYTES,
            "CAPACITY_MINIMUM_INVALID")
    require(type(expected_code_source) is str
            and SHA40.fullmatch(expected_code_source),
            "CAPACITY_SOURCE_SHA_INVALID")
    receipt_path = root / "capacity-receipt.json"
    require(receipt_path.is_file() and not receipt_path.is_symlink(),
            "CAPACITY_RECEIPT_MISSING")
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise CapacityProbeError("CAPACITY_RECEIPT_INVALID") from exc
    required = {
        "schema_version", "status", "target_bytes", "raw_size", "raw_sha256",
        "compressed_size", "chunks", "code_source_sha", "fixture_source_sha",
        "state_sequence", "canonical_hash", "published",
        "production_capacity_verified",
    }
    require(type(receipt) is dict and set(receipt) == required
            and type(receipt["schema_version"]) is int
            and receipt["schema_version"] == 1
            and receipt["status"] == "PACKED_5GB_CANDIDATE_NOT_PRODUCTION_CAPACITY"
            and receipt["published"] is False
            and receipt["production_capacity_verified"] is False,
            "CAPACITY_RECEIPT_SCHEMA")
    require(type(receipt["target_bytes"]) is int
            and minimum_bytes <= receipt["target_bytes"] <= MAX_AUDIT_BYTES
            and type(receipt["raw_size"]) is int
            and receipt["target_bytes"] <= receipt["raw_size"] <= MAX_AUDIT_BYTES,
            "CAPACITY_TARGET_NOT_REACHED")
    require(type(receipt["compressed_size"]) is int
            and 0 < receipt["compressed_size"] <= MAX_DB_BYTES
            and type(receipt["chunks"]) is int and receipt["chunks"] > 0
            and type(receipt["raw_sha256"]) is str
            and SHA256.fullmatch(receipt["raw_sha256"])
            and type(receipt["canonical_hash"]) is str
            and SHA256.fullmatch(receipt["canonical_hash"])
            and type(receipt["state_sequence"]) is int
            and receipt["state_sequence"] == 1
            and type(receipt["code_source_sha"]) is str
            and SHA40.fullmatch(receipt["code_source_sha"])
            and receipt["fixture_source_sha"] == FIXTURE_SOURCE_SHA,
            "CAPACITY_RECEIPT_SCHEMA")
    require(receipt["code_source_sha"] == expected_code_source,
            "CAPACITY_SOURCE_SHA_MISMATCH")
    restored = restore(root)
    database = root / "state.sqlite"
    require(restored["raw_size"] == receipt["raw_size"]
            and restored["raw_sha256"] == receipt["raw_sha256"]
            and restored["compressed_size"] == receipt["compressed_size"]
            and restored["chunks"] == receipt["chunks"]
            and _sha256(database) == receipt["raw_sha256"],
            "CAPACITY_RESTORE_MISMATCH")
    proof = verify_sqlite(
        database, expected_sequence=receipt["state_sequence"],
        expected_chain=receipt["canonical_hash"],
        expected_source=receipt["fixture_source_sha"], max_bytes=MAX_AUDIT_BYTES,
        strict_event_ids=True,
    )
    return {
        "schema_version": 1,
        "status": "5GB_ARCHIVE_TRANSFER_AND_REPLAY_VERIFIED",
        "raw_size": receipt["raw_size"],
        "raw_sha256": proof["sha256"],
        "chunks": receipt["chunks"],
        "compressed_size": receipt["compressed_size"],
        "code_source_sha": receipt["code_source_sha"],
        "fixture_source_sha": receipt["fixture_source_sha"],
        "canonical_hash": proof["canonical_hash"],
        "state_sequence": proof["sequence"],
        "production_capacity_verified": False,
        "reason": "DURABLE_PRODUCTION_BACKEND_NOT_VERIFIED",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("build", "verify"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    args = parser.parse_args(argv)
    result = (build(args.root, code_source_sha=args.source_sha)
              if args.operation == "build"
              else verify(args.root, expected_code_source=args.source_sha))
    args.output.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
