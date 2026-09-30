"""Legacy parity retries only transient highest-sequence artifact conflicts."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agents.heartbeat_state import seed_state
from runtime.artifact_restore import InvalidStateArtifact
from state_journal.contracts import digest
from state_journal.legacy import RESTORERS, restore_domain


class LegacyParityArtifactRaceTests(unittest.TestCase):
    def test_restore_retries_conflicting_artifacts_and_validates_stable_state(self):
        state = seed_state()
        calls = []

        def restore(output, metadata):
            calls.append(None)
            if len(calls) == 1:
                raise InvalidStateArtifact(
                    "conflicting state artifacts at highest sequence"
                )
            output.write_text(json.dumps(state))
            metadata.write_text(json.dumps({
                "source_state_hash": digest(state),
                "artifact_id": 12,
                "source_run_id": 34,
                "source_head_sha": "a" * 40,
                "source_sequence": state["sequence"],
                "artifact_created_at": "2026-09-30T16:00:00Z",
            }))
            return "RESTORED"

        with tempfile.TemporaryDirectory() as td, \
             patch.dict(os.environ, {"GITHUB_RUN_ID": "99"}, clear=True), \
             patch.dict(RESTORERS, {"heartbeat": restore}), \
             patch("state_journal.legacy.time.sleep") as sleep:
            restored, _source = restore_domain(Path(td), "heartbeat", Path(td) / "work")

        self.assertEqual(restored, state)
        self.assertEqual(len(calls), 2)
        sleep.assert_called_once_with(1)

    def test_persistent_conflict_still_fails_closed_after_bounded_retries(self):
        calls = []

        def restore(_output, _metadata):
            calls.append(None)
            raise InvalidStateArtifact(
                "conflicting state artifacts at highest sequence"
            )

        with tempfile.TemporaryDirectory() as td, \
             patch.dict(os.environ, {"GITHUB_RUN_ID": "99"}, clear=True), \
             patch.dict(RESTORERS, {"heartbeat": restore}), \
             patch("state_journal.legacy.time.sleep"):
            with self.assertRaisesRegex(
                InvalidStateArtifact,
                "conflicting state artifacts at highest sequence",
            ):
                restore_domain(Path(td), "heartbeat", Path(td) / "work")

        self.assertEqual(len(calls), 5)


if __name__ == "__main__":
    unittest.main()
