import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from brain import state_capacity_probe as probe
from brain import state_archive
from brain.validate import validate_policy


class CapacityProbeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_small_equivalent_pack_transfer_restore_and_strict_replay(self):
        with patch.object(state_archive, "CHUNK_BYTES", 64 * 1024):
            receipt = probe.build(self.root, target_bytes=2 * 1024 * 1024,
                                  padding_bytes=128 * 1024)
            self.assertGreaterEqual(receipt["raw_size"], 2 * 1024 * 1024)
            self.assertFalse(receipt["production_capacity_verified"])
            result = probe.verify(self.root, minimum_bytes=2 * 1024 * 1024)
        self.assertEqual(result["status"],
                         "5GB_ARCHIVE_TRANSFER_AND_REPLAY_VERIFIED")
        self.assertEqual(result["reason"], "DURABLE_PRODUCTION_BACKEND_NOT_VERIFIED")
        self.assertFalse(result["production_capacity_verified"])

    def test_below_target_and_modified_receipt_fail_closed(self):
        with patch.object(state_archive, "CHUNK_BYTES", 64 * 1024):
            probe.build(self.root, target_bytes=1024 * 1024, padding_bytes=128 * 1024)
            with self.assertRaisesRegex(probe.CapacityProbeError, "TARGET_NOT_REACHED"):
                probe.verify(self.root, minimum_bytes=2 * 1024 * 1024)
            path = self.root / "capacity-receipt.json"
            receipt = json.loads(path.read_text())
            receipt["production_capacity_verified"] = True
            path.write_text(json.dumps(receipt))
            with self.assertRaisesRegex(probe.CapacityProbeError, "RECEIPT_SCHEMA"):
                probe.verify(self.root, minimum_bytes=1024 * 1024)

    def test_existing_database_and_oversized_target_are_rejected(self):
        (self.root / "state.sqlite").write_bytes(b"existing")
        with self.assertRaisesRegex(probe.CapacityProbeError, "DATABASE_EXISTS"):
            probe.build(self.root, target_bytes=1024 * 1024)
        (self.root / "state.sqlite").unlink()
        with self.assertRaisesRegex(probe.CapacityProbeError, "TARGET_INVALID"):
            probe.build(self.root, target_bytes=probe.TARGET_BYTES + 1)

    def test_verification_uses_five_gib_audit_bound_and_exact_source(self):
        with patch.object(state_archive, "CHUNK_BYTES", 64 * 1024):
            probe.build(self.root, target_bytes=1024 * 1024, padding_bytes=128 * 1024)
            with self.assertRaisesRegex(probe.CapacityProbeError, "SOURCE_SHA_MISMATCH"):
                probe.verify(self.root, minimum_bytes=1024 * 1024,
                             expected_code_source="b" * 40)
            result = probe.verify(self.root, minimum_bytes=1024 * 1024)
        self.assertEqual(result["state_sequence"], 1)
        self.assertEqual(result["code_source_sha"], probe.FIXTURE_SOURCE_SHA)
        self.assertEqual(result["fixture_source_sha"], probe.FIXTURE_SOURCE_SHA)

    def test_receipt_metadata_types_fail_closed(self):
        with patch.object(state_archive, "CHUNK_BYTES", 64 * 1024):
            probe.build(self.root, target_bytes=1024 * 1024,
                        padding_bytes=128 * 1024)
        path = self.root / "capacity-receipt.json"
        original = json.loads(path.read_text())
        for field, value in (
            ("schema_version", True),
            ("target_bytes", False),
            ("compressed_size", -1),
            ("chunks", "NOT_A_VERIFIED_CHUNK_COUNT"),
        ):
            receipt = dict(original)
            receipt[field] = value
            path.write_text(json.dumps(receipt))
            with self.subTest(field=field), self.assertRaisesRegex(
                    probe.CapacityProbeError, "RECEIPT_SCHEMA|TARGET_NOT_REACHED"):
                probe.verify(self.root, minimum_bytes=1024 * 1024)

    def test_receipt_archive_metadata_must_match_restored_manifest(self):
        with patch.object(state_archive, "CHUNK_BYTES", 64 * 1024):
            receipt = probe.build(self.root, target_bytes=1024 * 1024,
                                  padding_bytes=128 * 1024)
        restored = {
            "raw_size": receipt["raw_size"],
            "raw_sha256": receipt["raw_sha256"],
            "compressed_size": receipt["compressed_size"],
            "chunks": receipt["chunks"],
        }
        for field in ("compressed_size", "chunks"):
            changed = dict(restored)
            changed[field] += 1
            with self.subTest(field=field), patch.object(
                    probe, "restore", return_value=changed), self.assertRaisesRegex(
                        probe.CapacityProbeError, "RESTORE_MISMATCH"):
                probe.verify(self.root, minimum_bytes=1024 * 1024)

    def test_nonrecurring_capacity_gate_is_in_active_workflow_inventory(self):
        self.assertEqual(validate_policy()["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
