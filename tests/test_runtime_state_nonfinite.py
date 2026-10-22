import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from runtime.artifact_restore import InvalidStateArtifact, restore_latest_valid_state
from runtime.artifact_state import validate_runtime_artifact_bundle
from runtime.state import RuntimeStateError, canonical_hash, validate_state


def valid_state():
    repositories = {}
    for index in range(1, 9):
        repositories[f"REPO-{index:03d}"] = {
            "source_ref": "refs/heads/main",
            "cursor_sha": f"{index:040x}",
            "status": "BLOCKED_HISTORICAL_ONLY" if index == 6 else "CURRENT",
            "observed_at": None,
        }
    return {
        "schema_version": "1.0.0",
        "state_id": "portfolio-runtime-state",
        "sequence": 0,
        "updated_at": "2026-10-22T22:00:00Z",
        "last_cycle_id": None,
        "repositories": repositories,
        "recent_cycles": [],
        "daily_learning_state": None,
        "weekly_synthesis": None,
    }


def archive(members):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as zipped:
        for name, payload in members.items():
            zipped.writestr(name, payload)
    return out.getvalue()


def state_archive(state):
    return archive({
        "runtime_state.json": json.dumps(
            state, allow_nan=True, separators=(",", ":")
        ).encode(),
    })


class RuntimeStateNonfiniteTests(unittest.TestCase):
    def probes(self):
        return {
            "daily_nan": ("daily_learning_state", float("nan")),
            "daily_pos_inf": ("daily_learning_state", float("inf")),
            "daily_neg_inf": ("daily_learning_state", float("-inf")),
            "weekly_nested_nan": ("weekly_synthesis", {"score": float("nan")}),
        }

    def test_runtime_validator_rejects_nonfinite_learning_and_synthesis(self):
        for name, (field, value) in self.probes().items():
            with self.subTest(name=name):
                state = valid_state()
                state[field] = value
                with self.assertRaisesRegex(RuntimeStateError, "finite canonical JSON"):
                    validate_state(state)

    def test_runtime_bundle_strict_decoder_rejects_nonfinite_member(self):
        receipt = {
            "schema_version": "1.0.0",
            "cycle_id": "disabled",
            "mode": "sync",
            "started_at": "2026-10-22T22:00:00Z",
            "finished_at": "2026-10-22T22:00:00Z",
            "status": "DISABLED",
            "reason": "test",
            "observations": [],
            "api_requests": 0,
        }
        receipt["receipt_hash"] = canonical_hash(receipt)
        for name, (field, value) in self.probes().items():
            with self.subTest(name=name):
                state = valid_state()
                state[field] = value
                raw = archive({
                    "runtime_state.json": json.dumps(
                        state, allow_nan=True, separators=(",", ":")
                    ).encode(),
                    "cycle_receipt.json": json.dumps(receipt).encode(),
                })
                with self.assertRaisesRegex(InvalidStateArtifact, "non-finite JSON"):
                    validate_runtime_artifact_bundle(
                        raw,
                        max_archive_bytes=100000,
                        max_member_bytes=50000,
                    )

    def test_invalid_newest_state_falls_back_without_overwriting_history(self):
        bad = valid_state()
        bad["daily_learning_state"] = float("nan")
        good = valid_state()
        data = {"artifacts": [
            {
                "id": 2,
                "created_at": "2026-10-22T22:01:00Z",
                "archive_download_url": "bad",
                "workflow_run": {"id": 2, "head_branch": "main"},
            },
            {
                "id": 1,
                "created_at": "2026-10-22T22:00:00Z",
                "archive_download_url": "good",
                "workflow_run": {"id": 1, "head_branch": "main"},
            },
        ]}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "runtime_state.json"
            status = restore_latest_valid_state(
                data,
                current_run="99",
                expected_head_branch="main",
                download={
                    "bad": state_archive(bad),
                    "good": state_archive(good),
                }.__getitem__,
                output=output,
                member_name="runtime_state.json",
                expected_state_id="portfolio-runtime-state",
                max_archive_bytes=100000,
                max_state_bytes=50000,
                validator=validate_state,
            )
            self.assertEqual(status, "RESTORED_AFTER_REJECTING_1_INVALID")
            self.assertEqual(json.loads(output.read_text())["sequence"], 0)

    def test_finite_state_hash_is_unchanged(self):
        state = valid_state()
        self.assertEqual(
            canonical_hash(state),
            "sha256:6f13ed551bc1c7637632e44224c41ebce1a56ef4b2fbbcc954d02f6ed9f1f8f6",
        )


if __name__ == "__main__":
    unittest.main()
