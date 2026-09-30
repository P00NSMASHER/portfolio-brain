"""Reducer replay may resolve a legacy artifact fork only by exact state match."""
import hashlib
import json
import tempfile
import unittest
import zipfile
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from runtime.artifact_restore import InvalidStateArtifact, restore_latest_valid_state
from state_journal.contracts import DOMAINS
from state_journal.legacy_parity import ROOT, verify


def state_hash(state):
    canonical = json.dumps(state, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def archive(state):
    result = BytesIO()
    with zipfile.ZipFile(result, "w") as output:
        output.writestr("runtime_state.json", json.dumps(state).encode())
    return result.getvalue()


class VerifiedLegacyConflictTests(unittest.TestCase):
    def setUp(self):
        self.data = {
            "artifacts": [
                {
                    "id": 2, "created_at": "2026-09-30T12:02:00Z",
                    "archive_download_url": "new",
                    "workflow_run": {"id": 102, "head_branch": "main"},
                },
                {
                    "id": 1, "created_at": "2026-09-30T12:01:00Z",
                    "archive_download_url": "old",
                    "workflow_run": {"id": 101, "head_branch": "main"},
                },
            ]
        }
        self.states = {
            "new": {"schema_version": "1.0.0", "state_id": "portfolio-runtime-state",
                    "sequence": 9, "value": "stale"},
            "old": {"schema_version": "1.0.0", "state_id": "portfolio-runtime-state",
                    "sequence": 9, "value": "replayed"},
        }

    def restore(self, output, *, preferred_state_hash=None):
        return restore_latest_valid_state(
            self.data,
            current_run="999",
            expected_head_branch="main",
            download=lambda url: archive(self.states[url]),
            output=output,
            member_name="runtime_state.json",
            expected_state_id="portfolio-runtime-state",
            max_archive_bytes=10000,
            max_state_bytes=1000,
            preferred_state_hash=preferred_state_hash,
        )

    def test_exact_reducer_replay_match_resolves_highest_sequence_fork(self):
        expected = self.states["old"]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "runtime_state.json"
            status = self.restore(output, preferred_state_hash=state_hash(expected))
            self.assertEqual(status, "RESTORED_REDUCER_VERIFIED_STATE_AFTER_CONFLICT")
            self.assertEqual(json.loads(output.read_text()), expected)

    def test_reducer_state_that_matches_no_fork_branch_still_fails_closed(self):
        expected = {"schema_version": "1.0.0", "state_id": "portfolio-runtime-state",
                    "sequence": 9, "value": "not-replayed"}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "runtime_state.json"
            with self.assertRaisesRegex(InvalidStateArtifact, "conflicting state artifacts"):
                self.restore(output, preferred_state_hash=state_hash(expected))
            self.assertFalse(output.exists())

    def test_legacy_parity_supplies_replayed_domain_states_as_exact_fork_evidence(self):
        projected = {domain: {"domain": domain} for domain in DOMAINS}
        refs = {domain: "fixture:provider-state" for domain in DOMAINS}
        with tempfile.TemporaryDirectory() as directory, patch(
            "state_journal.legacy_parity.restore_all", return_value=(projected, refs)
        ) as restore_all:
            verify(projected, Path(directory))
        restore_all.assert_called_once_with(
            ROOT, Path(directory), expected_states=projected
        )


if __name__ == "__main__":
    unittest.main()
