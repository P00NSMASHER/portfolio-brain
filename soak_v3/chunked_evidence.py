"""Independent, read-only verification of original Git chunked Brain SQLite bytes.

Does not import the production codec and cannot certify automatic six-hour soak.
Git object identity, manifest, each chunk and whole database are distinct gates.
"""
from __future__ import annotations
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import zlib
from soak_v3.audit import EvidenceError, require, sha40, sha64

CHUNK_BYTES = 8 * 1024 * 1024
MAX_RAW_BYTES = 256 * 1024 * 1024
MAX_CHUNKS = MAX_RAW_BYTES // CHUNK_BYTES
MAX_JSON_BYTES = 4_000_000
PART = re.compile(r"part-[0-9]{6}\.z\Z")
MANIFEST = "state-manifest.json"
FORMAT = "sqlite-zlib-chunks-v1"


def git_hash(contents):
    return hashlib.sha1(
        b"blob " + str(len(contents)).encode("ascii") + b"\0" + contents
    ).hexdigest()


def _get_blob(api, blob_sha, *, max_size):
    sha40(blob_sha)
    require(type(max_size) is int
            and 0 < max_size <= max(CHUNK_BYTES + 32768, 2_000_000),
            "EVIDENCE_BLOB_BOUND_INVALID")
    raw_response = api.get(
        f"/git/blobs/{blob_sha}",
        limit=min(MAX_JSON_BYTES, (max_size * 4 // 3) + 131072),
    )
    require(len(raw_response) <= MAX_JSON_BYTES, "GIT_BLOB_JSON_TOO_LARGE")
    try:
        data = json.loads(raw_response)
    except (ValueError, TypeError) as exc:
        raise EvidenceError("GIT_BLOB_JSON_INVALID") from exc
    require(type(data) is dict and data.get("sha") == blob_sha
            and data.get("encoding") == "base64"
            and type(data.get("content")) is str
            and type(data.get("size")) is int
            and 0 <= data["size"] <= max_size,
            "GIT_BLOB_METADATA_INVALID")
    try:
        binary = base64.b64decode("".join(data["content"].split()), validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise EvidenceError("GIT_BLOB_BASE64_INVALID") from exc
    require(len(binary) == data["size"] and len(binary) <= max_size,
            "GIT_BLOB_SIZE_MISMATCH")
    require(git_hash(binary) == blob_sha, "GIT_BLOB_IDENTITY_INVALID")
    return binary


def _manifest(doc):
    require(type(doc) is dict and set(doc) == {
        "schema_version", "format", "raw_size", "raw_sha256",
        "compressed_size", "compressed_sha256", "chunks",
    }, "STATE_MANIFEST_FIELDS")
    require(doc["schema_version"] == 1 and doc["format"] == FORMAT,
            "STATE_MANIFEST_FORMAT")
    raw_size = doc["raw_size"]
    compressed_size = doc["compressed_size"]
    require(type(raw_size) is int and CHUNK_BYTES < raw_size <= MAX_RAW_BYTES,
            "STATE_MANIFEST_RAW_BOUND")
    require(type(compressed_size) is int
            and 0 < compressed_size <= MAX_RAW_BYTES + 1024 * 1024,
            "STATE_MANIFEST_COMPRESSED_BOUND")
    sha64(doc["raw_sha256"])
    sha64(doc["compressed_sha256"])
    chunks = doc["chunks"]
    require(type(chunks) is list
            and len(chunks) == (raw_size + CHUNK_BYTES - 1) // CHUNK_BYTES
            and 1 < len(chunks) <= MAX_CHUNKS,
            "STATE_MANIFEST_CHUNK_COUNT")
    cumulative_raw = cumulative_packed = 0
    for index, chunk in enumerate(chunks):
        require(type(chunk) is dict and set(chunk) == {
            "name", "raw_size", "raw_sha256", "size", "sha256",
        }, "STATE_MANIFEST_PART_FIELDS")
        require(type(chunk["name"]) is str and PART.fullmatch(chunk["name"])
                and chunk["name"] == f"part-{index:06d}.z",
                "STATE_MANIFEST_PART_NAME")
        require(type(chunk["raw_size"]) is int
                and 0 < chunk["raw_size"] <= CHUNK_BYTES
                and (index == len(chunks)-1 or chunk["raw_size"] == CHUNK_BYTES),
                "STATE_MANIFEST_PART_RAW_BOUND")
        require(type(chunk["size"]) is int
                and 0 < chunk["size"] <= CHUNK_BYTES+32768,
                "STATE_MANIFEST_PART_PACKED_BOUND")
        sha64(chunk["sha256"])
        sha64(chunk["raw_sha256"])
        cumulative_raw += chunk["raw_size"]
        cumulative_packed += chunk["size"]
    require(cumulative_raw == raw_size and cumulative_packed == compressed_size,
            "STATE_MANIFEST_TOTALS_MISMATCH")
    return doc


def verify_original_state(api, *, state_commit, target):
    """Verify an original Git state commit into a new private temporary filename.

    The caller MUST separately verify SQLite integrity, event IDs, canonical
    ledger, source-pinned report and artifact receipt. No remote writes occur.
    """
    sha40(state_commit)
    target = Path(target)
    require(not target.exists() and not target.is_symlink()
            and target.parent.is_dir() and not target.parent.is_symlink(),
            "EVIDENCE_DESTINATION_UNSAFE")
    commit = api.json(f"/git/commits/{state_commit}")
    require(commit.get("sha") == state_commit
            and type(commit.get("tree")) is dict
            and type(commit["tree"].get("sha")) is str
            and re.fullmatch("[0-9a-f]{40}", commit["tree"]["sha"])
            and type(commit.get("parents")) is list
            and len(commit["parents"]) == 1,
            "STATE_ORIGINAL_COMMIT_INVALID")
    parent = sha40(commit["parents"][0].get("sha"))
    tree_sha = commit["tree"]["sha"]
    inventory = api.json(f"/git/trees/{tree_sha}?recursive=1")
    require(inventory.get("sha") == tree_sha
            and inventory.get("truncated") is False
            and type(inventory.get("tree")) is list
            and len(inventory["tree"]) <= 100,
            "STATE_ORIGINAL_TREE_INVALID")
    rows = {}
    for entry in inventory["tree"]:
        require(type(entry) is dict and type(entry.get("path")) is str
                and type(entry.get("type")) is str
                and entry["path"] not in rows,
                "STATE_ORIGINAL_TREE_ENTRY_INVALID")
        rows[entry["path"]] = entry
    require("state.sqlite" not in rows and MANIFEST in rows,
            "STATE_ORIGINAL_TREE_FORMAT_INVALID")
    entry = rows[MANIFEST]
    require(entry.get("type") == "blob" and entry.get("mode") == "100644",
            "STATE_MANIFEST_GIT_MODE_INVALID")
    manifest_sha = sha40(entry.get("sha"))
    raw_manifest = _get_blob(api, manifest_sha, max_size=2_000_000)
    try:
        document = _manifest(json.loads(raw_manifest))
    except (ValueError, TypeError) as exc:
        raise EvidenceError("STATE_MANIFEST_JSON_INVALID") from exc
    paths = {f"state-chunks/{c['name']}" for c in document["chunks"]}
    actual = {name for name in rows if name.startswith("state-chunks/")}
    require(paths == {name for name in actual if rows[name].get("type") == "blob"},
            "STATE_ORIGINAL_CHUNK_SET_INVALID")
    require(not (actual - paths - {"state-chunks"}),
            "STATE_ORIGINAL_UNEXPECTED_CHUNK")
    for name in paths:
        require(rows[name].get("mode") == "100644"
                and rows[name].get("type") == "blob"
                and type(rows[name].get("sha")) is str
                and re.fullmatch("[0-9a-f]{40}", rows[name]["sha"]),
                "STATE_ORIGINAL_CHUNK_GIT_MODE_INVALID")

    packed_hash = hashlib.sha256()
    restored_hash = hashlib.sha256()
    written_raw = written_packed = 0
    try:
        with target.open("xb") as output:
            os.chmod(target, 0o600)
            for part in document["chunks"]:
                name = f"state-chunks/{part['name']}"
                packed = _get_blob(api, rows[name]["sha"], max_size=part["size"])
                require(len(packed) == part["size"]
                        and hashlib.sha256(packed).hexdigest() == part["sha256"],
                        "STATE_ORIGINAL_PART_DIGEST_INVALID")
                packed_hash.update(packed)
                written_packed += len(packed)
                try:
                    inflater = zlib.decompressobj()
                    raw = inflater.decompress(packed, part["raw_size"] + 1)
                except zlib.error as exc:
                    raise EvidenceError("STATE_ORIGINAL_PART_DECODE_FAILED") from exc
                require(inflater.eof and not inflater.unused_data
                        and not inflater.unconsumed_tail
                        and len(raw) == part["raw_size"],
                        "STATE_ORIGINAL_DECOMPRESSION_BOUND")
                require(hashlib.sha256(raw).hexdigest() == part["raw_sha256"],
                        "STATE_ORIGINAL_RAW_PART_DIGEST_INVALID")
                restored_hash.update(raw)
                written_raw += len(raw)
                output.write(raw)
            output.flush()
            os.fsync(output.fileno())
        require(written_packed == document["compressed_size"]
                and packed_hash.hexdigest() == document["compressed_sha256"]
                and written_raw == document["raw_size"]
                and restored_hash.hexdigest() == document["raw_sha256"],
                "STATE_ORIGINAL_IMAGE_DIGEST_INVALID")
        with target.open("rb") as image:
            require(image.read(16) == b"SQLite format 3\x00",
                    "STATE_ORIGINAL_SQLITE_HEADER_INVALID")
    except BaseException:
        if target.exists() and not target.is_symlink():
            target.unlink()
        raise
    return {
        "status": "ORIGINAL_GIT_BLOBS_VERIFIED_NOT_SOAK_ACCEPTANCE",
        "source_state_commit": state_commit,
        "state_parent": parent,
        "manifest_git_blob_sha": manifest_sha,
        "raw_image_sha256": restored_hash.hexdigest(),
        "raw_size": written_raw,
        "compressed_size": written_packed,
        "chunk_count": len(document["chunks"]),
        "soak_pass": False,
    }
