import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from runtime.artifact_restore import InvalidStateArtifact, restore_latest_valid_state
from state_journal import legacy_parity
from state_journal.contracts import DOMAINS, digest


def archive(state):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as bundle:
        bundle.writestr("state.json", json.dumps(state).encode())
    return output.getvalue()


class ExpectedArtifactParityTests(unittest.TestCase):
    def test_replayed_state_resolves_only_a_matching_highest_sequence_fork(self):
        expected = {
            "schema_version": "1.0.0",
            "state_id": "parity-fixture",
            "sequence": 12,
            "value": "replayed",
        }
        divergent = {**expected, "value": "unverified-branch"}
        data = {
            "artifacts": [
                {
                    "id": 2,
                    "created_at": "2026-09-30T12:00:00Z",
                    "archive_download_url": "divergent",
                    "workflow_run": {"id": 22, "head_branch": "main"},
                },
                {
                    "id": 1,
                    "created_at": "2026-09-30T11:00:00Z",
                    "archive_download_url": "replayed",
                    "workflow_run": {"id": 11, "head_branch": "main"},
                },
            ]
        }

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "state.json"
            metadata = Path(directory) / "restore.json"
            status = restore_latest_valid_state(
                data,
                current_run="99",
                expected_head_branch="main",
                download={"divergent": archive(divergent), "replayed": archive(expected)}.__getitem__,
                output=output,
                member_name="state.json",
                expected_state_id="parity-fixture",
                max_archive_bytes=10_000,
                max_state_bytes=1_000,
                metadata_output=metadata,
                expected_state_hash=digest(expected),
            )
            self.assertEqual(status, "RESTORED_EXPECTED_STATE_AFTER_CONFLICT")
            self.assertEqual(json.loads(output.read_text()), expected)
            receipt = json.loads(metadata.read_text())
            self.assertEqual(receipt["artifact_id"], 1)
            self.assertEqual(receipt["source_state_hash"], digest(expected))

    def test_unmatched_projection_does_not_resolve_a_highest_sequence_fork(self):
        first = {
            "schema_version": "1.0.0",
            "state_id": "parity-fixture",
            "sequence": 12,
            "value": "first",
        }
        second = {**first, "value": "second"}
        data = {
            "artifacts": [
                {
                    "id": 2,
                    "created_at": "2026-09-30T12:00:00Z",
                    "archive_download_url": "first",
                    "workflow_run": {"id": 22, "head_branch": "main"},
                },
                {
                    "id": 1,
                    "created_at": "2026-09-30T11:00:00Z",
                    "archive_download_url": "second",
                    "workflow_run": {"id": 11, "head_branch": "main"},
                },
            ]
        }
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "state.json"
            with self.assertRaisesRegex(
                InvalidStateArtifact,
                "conflicting state artifacts at highest sequence",
            ):
                restore_latest_valid_state(
                    data,
                    current_run="99",
                    expected_head_branch="main",
                    download={"first": archive(first), "second": archive(second)}.__getitem__,
                    output=output,
                    member_name="state.json",
                    expected_state_id="parity-fixture",
                    max_archive_bytes=10_000,
                    max_state_bytes=1_000,
                    expected_state_hash=digest({**first, "value": "missing"}),
                )
            self.assertFalse(output.exists())

    def test_parity_supplies_the_replayed_projection_as_restore_authority(self):
        projected = {
            domain: {"state_id": domain, "sequence": 1}
            for domain in DOMAINS
        }
        refs = {domain: f"fixture:{domain}" for domain in DOMAINS}
        with patch.object(
            legacy_parity,
            "restore_all",
            return_value=(projected, refs),
        ) as restore_all:
            result = legacy_parity.verify(projected, Path("unused"))
        restore_all.assert_called_once_with(
            legacy_parity.ROOT,
            Path("unused"),
            expected_states=projected,
        )
        self.assertEqual(result["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
