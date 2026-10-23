"""Fail-closed JSON and schema checks for persisted runtime learning state."""
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from runtime.artifact_restore import InvalidStateArtifact, _validated_payload, restore_latest_valid_state
from runtime.continuous_runtime import load_runtime_state
from runtime.state import (
    RuntimeStateError,
    advance_cycle,
    bootstrap_state,
    canonical_hash,
    cycle_id_for,
    validate_state,
)


def artifact(body: bytes) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("runtime_state.json", body)
    return output.getvalue()


def encoded_state(*, field: str, value) -> bytes:
    state = bootstrap_state(now="2026-10-22T23:00:00Z")
    state[field] = value
    return json.dumps(state, separators=(",", ":")).encode("utf-8")


def validate_artifact(body: bytes):
    return _validated_payload(
        artifact(body),
        member_name="runtime_state.json",
        expected_state_id="portfolio-runtime-state",
        max_archive_bytes=20_000,
        max_state_bytes=10_000,
        validator=validate_state,
    )


def state_after_one_cycle():
    state = bootstrap_state(now="2026-10-22T23:00:00Z")
    cursor = state["repositories"]["REPO-001"]["cursor_sha"]
    observations = [{
        "repository_id": "REPO-001",
        "status": "UNCHANGED",
        "source_ref": "main",
        "prior_sha": cursor,
        "current_sha": cursor,
        "observed_at": "2026-10-22T23:01:00Z",
    }]
    receipt = {
        "schema_version": "1.0.0",
        "cycle_id": cycle_id_for(
            state,
            mode="observe",
            target_repository_id="REPO-001",
            observations=observations,
        ),
        "mode": "observe",
        "started_at": "2026-10-22T23:01:00Z",
        "finished_at": "2026-10-22T23:01:00Z",
        "status": "PASS",
        "reason": None,
        "observations": observations,
        "api_requests": 1,
    }
    receipt["receipt_hash"] = canonical_hash(receipt)
    return advance_cycle(state, receipt)


class RuntimeStateFiniteJSONTests(unittest.TestCase):
    def test_direct_loader_and_artifact_restore_reject_boolean_sequences(self):
        valid_states = [
            bootstrap_state(now="2026-10-22T23:00:00Z"),
            state_after_one_cycle(),
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runtime_state.json"
            for sequence, valid in enumerate(valid_states):
                with self.subTest(control=sequence):
                    path.write_text(json.dumps(valid), encoding="utf-8")
                    self.assertEqual(
                        load_runtime_state(path, now="2026-10-22T23:02:00Z")["sequence"],
                        sequence,
                    )

                malformed = dict(valid)
                malformed["sequence"] = bool(sequence)
                malformed_body = json.dumps(malformed).encode("utf-8")
                with self.subTest(boolean=bool(sequence), path="direct"):
                    path.write_bytes(malformed_body)
                    with self.assertRaises(RuntimeStateError):
                        load_runtime_state(path, now="2026-10-22T23:02:00Z")
                with self.subTest(boolean=bool(sequence), path="artifact"):
                    with self.assertRaises(InvalidStateArtifact):
                        validate_artifact(malformed_body)

    def test_four_reproduced_nonfinite_payloads_are_rejected(self):
        probes = [
            ("daily_learning_state", float("nan")),
            ("daily_learning_state", float("inf")),
            ("daily_learning_state", float("-inf")),
            ("weekly_synthesis", {"score": float("nan")}),
        ]
        for field, value in probes:
            with self.subTest(field=field, value=value):
                with self.assertRaises(InvalidStateArtifact):
                    validate_artifact(encoded_state(field=field, value=value))

    def test_nested_nonfinite_values_in_both_subtrees_are_rejected(self):
        probes = [
            ("daily_learning_state", {"nested": [{"score": float("nan")}]}),
            ("weekly_synthesis", {"nested": [{"score": float("inf")}]}),
        ]
        for field, value in probes:
            with self.subTest(field=field):
                with self.assertRaises(InvalidStateArtifact):
                    validate_artifact(encoded_state(field=field, value=value))

    def test_learning_subtree_schemas_reject_opaque_scalars(self):
        for field, value in [("daily_learning_state", True), ("weekly_synthesis", "opaque")]:
            with self.subTest(field=field):
                state = bootstrap_state(now="2026-10-22T23:00:00Z")
                state[field] = value
                with self.assertRaises(RuntimeStateError):
                    validate_state(state)

    def test_invalid_newest_artifact_falls_back_to_valid_predecessor(self):
        invalid = encoded_state(field="daily_learning_state", value=float("nan"))
        valid_state = bootstrap_state(now="2026-10-22T23:00:00Z")
        valid_body = (json.dumps(valid_state, indent=2) + "\n").encode("utf-8")
        candidates = {"artifacts": [
            {"id": 2, "created_at": "2026-10-22T23:02:00Z", "archive_download_url": "new",
             "workflow_run": {"id": 20, "head_branch": "main"}},
            {"id": 1, "created_at": "2026-10-22T23:01:00Z", "archive_download_url": "old",
             "workflow_run": {"id": 10, "head_branch": "main"}},
        ]}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "runtime_state.json"
            status = restore_latest_valid_state(
                candidates,
                current_run="99",
                expected_head_branch="main",
                download={"new": artifact(invalid), "old": artifact(valid_body)}.__getitem__,
                output=output,
                member_name="runtime_state.json",
                expected_state_id="portfolio-runtime-state",
                max_archive_bytes=20_000,
                max_state_bytes=10_000,
                validator=validate_state,
            )
            self.assertEqual(status, "RESTORED_AFTER_REJECTING_1_INVALID")
            self.assertEqual(output.read_bytes(), valid_body)

    def test_valid_seed_bytes_and_hash_are_unchanged(self):
        state = bootstrap_state(now="2026-10-22T23:00:00Z")
        body = (json.dumps(state, indent=2) + "\n").encode("utf-8")
        restored, sequence, state_hash = validate_artifact(body)
        self.assertEqual(restored, body)
        self.assertEqual(sequence, 0)
        self.assertEqual(state_hash, "sha256:b02fc1e5a808f0a057565a40f302020ee2e4334d9a2b1d0738d6ddc510bb6967")
        self.assertEqual(canonical_hash(state), state_hash)


if __name__ == "__main__":
    unittest.main()
