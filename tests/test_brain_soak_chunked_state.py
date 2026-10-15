"""Adversarial original Git chunk manifest and binary replay tests.

All GitHub responses are synthetic and independent of the production codec.
Green tests do not establish unattended production or commercial outcomes.
"""
import base64
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zlib

from soak_v3.audit import EvidenceError
from soak_v3 import chunked_evidence as audit

COMMIT = "a"*40
PARENT = "b"*40
TREE = "c"*40


class MockOriginalGit:
    def __init__(self):
        self.calls = []
        self.raw = b"SQLite format 3\x00" + bytes(range(256)) * 2
        self.original_hash = hashlib.sha256(self.raw).hexdigest()
        self.chunks = []
        self.blobs = {}
        with patch.object(audit, "CHUNK_BYTES", 128):
            for i in range(0, len(self.raw), 128):
                block = self.raw[i:i+128]
                packed = zlib.compress(block, 6)
                name = f"part-{i//128:06d}.z"
                blob_id = audit.git_hash(packed)
                self.blobs[blob_id] = packed
                self.chunks.append({
                    "name": name, "raw_size": len(block),
                    "raw_sha256": hashlib.sha256(block).hexdigest(),
                    "size": len(packed),
                    "sha256": hashlib.sha256(packed).hexdigest(),
                    "git_sha": blob_id,
                })
        self.manifest = {
            "schema_version": 1, "format": audit.FORMAT,
            "raw_size": len(self.raw), "raw_sha256": self.original_hash,
            "compressed_size": sum(x["size"] for x in self.chunks),
            "compressed_sha256": hashlib.sha256(b"".join(
                self.blobs[x["git_sha"]] for x in self.chunks
            )).hexdigest(),
            "chunks": [{k:v for k,v in x.items() if k != "git_sha"}
                       for x in self.chunks],
        }
        self.refresh()

    def refresh(self):
        blob = (json.dumps(self.manifest, sort_keys=True, separators=(",", ":"))
                + "\n").encode()
        self.manifest_sha = audit.git_hash(blob)
        self.blobs[self.manifest_sha] = blob
        self.entries = [
            {"path": "README.md", "type": "blob", "mode": "100644",
             "sha": "d"*40},
            {"path": "state-manifest.json", "type": "blob", "mode": "100644",
             "sha": self.manifest_sha},
            {"path": "state-chunks", "type": "tree", "mode": "040000",
             "sha": "e"*40},
        ] + [{"path": "state-chunks/"+x["name"], "type": "blob",
              "mode": "100644", "sha": x["git_sha"]} for x in self.chunks]

    def json(self, path):
        self.calls.append(path)
        if path == f"/git/commits/{COMMIT}":
            return {"sha": COMMIT, "tree": {"sha": TREE},
                    "parents": [{"sha": PARENT}]}
        if path == f"/git/trees/{TREE}?recursive=1":
            return {"sha": TREE, "truncated": False,
                    "tree": copy.deepcopy(self.entries)}
        raise AssertionError("unexpected read")

    def get(self, path, *, limit=2_000_000):
        self.calls.append(path)
        if not path.startswith("/git/blobs/"):
            raise AssertionError("nonblob read")
        sha = path.rsplit("/", 1)[-1]
        binary = self.blobs.get(sha)
        if binary is None:
            raise EvidenceError("MISSING_ORIGINAL_GIT_BLOB")
        payload = json.dumps({
            "sha": sha, "encoding": "base64", "size": len(binary),
            "content": base64.b64encode(binary).decode(),
        }).encode()
        if len(payload) > limit:
            raise EvidenceError("SIMULATED_JSON_RESPONSE_TOO_LARGE")
        return payload


class IndependentChunkedStateTests(unittest.TestCase):
    def setUp(self):
        self.fake = MockOriginalGit()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)/"original.sqlite"
        self.patch = patch.object(audit, "CHUNK_BYTES", 128)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_original_git_blob_and_whole_archive_replay(self):
        result = audit.verify_original_state(
            self.fake, state_commit=COMMIT, target=self.path
        )
        self.assertEqual(result["status"],
                         "ORIGINAL_GIT_BLOBS_VERIFIED_NOT_SOAK_ACCEPTANCE")
        self.assertFalse(result["soak_pass"])
        self.assertEqual(result["source_state_commit"], COMMIT)
        self.assertEqual(result["state_parent"], PARENT)
        self.assertEqual(result["raw_image_sha256"], self.fake.original_hash)
        self.assertEqual(result["chunk_count"], len(self.fake.chunks))
        self.assertEqual(self.path.read_bytes(), self.fake.raw)
        self.assertLessEqual(len(self.fake.calls), 2+len(self.fake.chunks)+1)
        self.assertFalse(any("/contents/" in p for p in self.fake.calls))

    def test_git_blob_byte_tampering_fails_and_removes_partial_file(self):
        source = self.fake.chunks[1]["git_sha"]
        self.fake.blobs[source] += b"tampering"
        with self.assertRaisesRegex(EvidenceError, "GIT_BLOB_METADATA_INVALID"):
            audit.verify_original_state(self.fake, state_commit=COMMIT,
                                        target=self.path)
        self.assertFalse(self.path.exists())

    def test_whole_image_digest_is_verified_not_only_each_part(self):
        self.fake.manifest["raw_sha256"] = "f"*64
        self.fake.refresh()
        with self.assertRaisesRegex(EvidenceError, "STATE_ORIGINAL_IMAGE_DIGEST_INVALID"):
            audit.verify_original_state(self.fake, state_commit=COMMIT,
                                        target=self.path)
        self.assertFalse(self.path.exists())

    def test_extra_chunk_and_legacy_dual_format_are_rejected(self):
        for variant in ("extra", "dual"):
            with self.subTest(variant=variant):
                fake = MockOriginalGit()
                if variant == "extra":
                    fake.entries.append({
                        "path": "state-chunks/part-999999.z",
                        "type": "blob", "mode": "100644", "sha": "a"*40,
                    })
                else:
                    fake.entries.append({
                        "path": "state.sqlite", "type": "blob",
                        "mode": "100644", "sha": "a"*40,
                    })
                with self.assertRaisesRegex(EvidenceError, "STATE_ORIGINAL"):
                    audit.verify_original_state(fake, state_commit=COMMIT,
                                                target=self.path)
                self.assertFalse(self.path.exists())

    def test_chunk_path_escape_and_missing_tree_entry_fail_closed(self):
        for variant in ("traversal", "missing"):
            with self.subTest(variant=variant):
                fake = MockOriginalGit()
                if variant == "traversal":
                    fake.manifest["chunks"][0]["name"] = "../escape.z"
                    fake.refresh()
                else:
                    fake.entries = [entry for entry in fake.entries
                                    if not entry["path"].endswith("part-000000.z")]
                with self.assertRaises(EvidenceError):
                    audit.verify_original_state(fake, state_commit=COMMIT,
                                                target=self.path)
                self.assertFalse(self.path.exists())

    def test_corrupted_commit_tree_and_manifest_refused(self):
        fake = MockOriginalGit()
        fake.entries[1]["mode"] = "120000"
        with self.assertRaisesRegex(EvidenceError, "GIT_MODE_INVALID"):
            audit.verify_original_state(fake, state_commit=COMMIT, target=self.path)

    def test_manifest_size_bomb_is_rejected_before_decoding(self):
        fake = MockOriginalGit()
        fake.manifest["raw_size"] = 300 * 1024 * 1024
        fake.refresh()
        with self.assertRaisesRegex(EvidenceError, "STATE_MANIFEST_RAW_BOUND"):
            audit.verify_original_state(fake, state_commit=COMMIT, target=self.path)

    def test_hostile_zlib_expansion_cannot_claim_valid_raw(self):
        fake = MockOriginalGit()
        raw_bomb = b"X"*5000
        packed = zlib.compress(raw_bomb)
        sha = audit.git_hash(packed)
        fake.blobs[sha] = packed
        fake.chunks[0]["git_sha"] = sha
        fake.manifest["chunks"][0]["size"] = len(packed)
        fake.manifest["chunks"][0]["sha256"] = hashlib.sha256(packed).hexdigest()
        fake.manifest["compressed_size"] = sum(
            len(fake.blobs[x["git_sha"]]) for x in fake.chunks
        )
        fake.manifest["compressed_sha256"] = hashlib.sha256(b"".join(
            fake.blobs[x["git_sha"]] for x in fake.chunks
        )).hexdigest()
        fake.refresh()
        with self.assertRaisesRegex(EvidenceError, "STATE_ORIGINAL_DECOMPRESSION_BOUND"):
            audit.verify_original_state(fake, state_commit=COMMIT,
                                        target=self.path)
        self.assertFalse(self.path.exists())

    def test_output_must_be_new_not_replaced(self):
        self.path.write_bytes(b"already here")
        with self.assertRaisesRegex(EvidenceError, "EVIDENCE_DESTINATION_UNSAFE"):
            audit.verify_original_state(self.fake, state_commit=COMMIT,
                                        target=self.path)
        self.assertEqual(self.path.read_bytes(), b"already here")


if __name__ == "__main__":
    unittest.main()
