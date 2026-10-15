"""Regression and adversarial checks for the state-branch 100 MB GitHub limit."""
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from brain import state_archive as archive

ROOT = Path(__file__).resolve().parents[1]


class StateArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.raw = self.root / "state.sqlite"
        with sqlite3.connect(self.raw) as db:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("CREATE TABLE ledger (id INTEGER PRIMARY KEY, evidence BLOB NOT NULL)")
            db.execute("INSERT INTO ledger(evidence) VALUES (?)", (bytes(range(256)) * 400,))
        self.original = self.raw.read_bytes()
        self.original_hash = hashlib.sha256(self.original).hexdigest()
        p = patch.object(archive, "CHUNK_BYTES", 16 * 1024)
        p.start()
        self.addCleanup(p.stop)

    def test_legacy_source_read_is_compatible(self):
        response = archive.restore(self.root)
        self.assertEqual(response["storage_format"], "legacy_sqlite")
        self.assertEqual(self.raw.read_bytes(), self.original)

    def test_roundtrip_integrity_and_deterministic_chunk_layout(self):
        result = archive.pack(self.root)
        self.assertEqual(result["raw_sha256"], self.original_hash)
        self.assertFalse(self.raw.exists())
        manifest = json.loads((self.root / archive.MANIFEST).read_text())
        self.assertGreater(len(manifest["chunks"]), 1)
        self.assertEqual(manifest["raw_size"], len(self.original))
        for part in (self.root / archive.PARTS).iterdir():
            self.assertLess(part.stat().st_size, archive.CHUNK_BYTES + 32769)
        self.assertEqual(archive.restore(self.root)["raw_sha256"], self.original_hash)
        self.assertEqual(self.raw.read_bytes(), self.original)
        self.assertEqual(archive.pack(self.root)["raw_sha256"], self.original_hash)
        self.assertEqual(archive.restore(self.root)["raw_sha256"], self.original_hash)
        with sqlite3.connect(self.raw) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM ledger").fetchone()[0], 1)
        self.assertEqual(self.raw.read_bytes(), self.original)

    def test_missing_or_corrupted_chunk_fails_closed_without_creating_state(self):
        for mutate in ("remove", "tamper"):
            with self.subTest(mutate=mutate):
                if not self.raw.exists():
                    self.raw.write_bytes(self.original)
                archive.pack(self.root)
                part = sorted((self.root / archive.PARTS).iterdir())[0]
                if mutate == "remove":
                    part.unlink()
                else:
                    data = bytearray(part.read_bytes())
                    data[0] ^= 0x80
                    part.write_bytes(data)
                with self.assertRaises(archive.StateArchiveError):
                    archive.restore(self.root)
                self.assertFalse(self.raw.exists())

    def test_ambiguous_dual_format_refused(self):
        archive.pack(self.root)
        self.raw.write_bytes(self.original)
        with self.assertRaisesRegex(archive.StateArchiveError, "AMBIGUOUS"):
            archive.restore(self.root)

    def test_manifest_path_traversal_and_incorrect_checksum_refused(self):
        archive.pack(self.root)
        path = self.root / archive.MANIFEST
        original_doc = json.loads(path.read_text())
        for mutation in ("../state.sqlite", "part-000999.z"):
            with self.subTest(mutation=mutation):
                doc = json.loads(json.dumps(original_doc))
                doc["chunks"][0]["name"] = mutation
                path.write_text(json.dumps(doc))
                with self.assertRaises(archive.StateArchiveError):
                    archive.restore(self.root)
                self.assertFalse(self.raw.exists())

    def test_manifest_whole_file_digest_cannot_be_laundered(self):
        archive.pack(self.root)
        path = self.root / archive.MANIFEST
        doc = json.loads(path.read_text())
        doc["raw_sha256"] = "0" * 64
        path.write_text(json.dumps(doc))
        with self.assertRaisesRegex(archive.StateArchiveError, "WHOLE_FILE"):
            archive.restore(self.root)
        self.assertFalse(self.raw.exists())

    def test_reject_malicious_decompression_bomb_before_allocation(self):
        archive.pack(self.root)
        path = self.root / archive.MANIFEST
        doc = json.loads(path.read_text())
        blob = __import__("zlib").compress(b"A" * (archive.CHUNK_BYTES + 1))
        part = self.root / archive.PARTS / doc["chunks"][0]["name"]
        part.write_bytes(blob)
        doc["chunks"][0]["size"] = len(blob)
        doc["chunks"][0]["sha256"] = hashlib.sha256(blob).hexdigest()
        # Update superficial compressed-envelope hashes so the decode limit,
        # not the first integrity check, rejects this hostile chunk.
        all_blobs = [p.read_bytes() for p in sorted((self.root / archive.PARTS).iterdir())]
        doc["compressed_size"] = sum(map(len, all_blobs))
        doc["compressed_sha256"] = hashlib.sha256(b"".join(all_blobs)).hexdigest()
        path.write_text(json.dumps(doc))
        with self.assertRaisesRegex(archive.StateArchiveError, "DECOMPRESSION_BOUNDARY"):
            archive.restore(self.root)

    def test_failed_pack_leaves_legacy_state_and_no_manifest(self):
        self.raw.write_bytes(b"not sqlite")
        with self.assertRaises(archive.StateArchiveError):
            archive.pack(self.root)
        self.assertEqual(self.raw.read_bytes(), b"not sqlite")
        self.assertFalse((self.root / archive.MANIFEST).exists())

    def test_restore_does_not_accept_missing_data(self):
        self.raw.unlink()
        with self.assertRaisesRegex(archive.StateArchiveError, "STATE_UNAVAILABLE"):
            archive.restore(self.root)

    def test_actual_workflow_restores_archive_and_commits_deletion_atomically(self):
        yaml = (ROOT / ".github" / "workflows" / "brain-cycle.yml").read_text()
        self.assertIn("python -m brain.state_archive restore --root state", yaml)
        self.assertIn("python -m brain.state_archive pack --root state", yaml)
        self.assertIn("git -C state add --all -- .", yaml)
        self.assertIn("push origin HEAD:refs/heads/brain-state-v2", yaml)
        self.assertNotIn("git push --force", yaml)
        self.assertLess(yaml.index("brain.state_archive restore"),
                        yaml.index("Exact-SHA deterministic preflight"))
        self.assertLess(yaml.index("brain.state_archive pack"),
                        yaml.index("Publish one nonsecret state transaction without force"))


if __name__ == "__main__":
    unittest.main()
