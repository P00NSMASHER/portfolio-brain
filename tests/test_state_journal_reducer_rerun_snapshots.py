"""Regression tests for reducer snapshots retained across workflow reruns."""
import hashlib
import io
import json
import unittest
import zipfile
from types import SimpleNamespace
from unittest.mock import patch

from agents.heartbeat_state import seed_state
from state_journal.checkpoint_archive import latest_canonical
from state_journal.reducer import checkpoint, make_snapshot, set_authority
from state_journal.transport import SNAPSHOT_ARTIFACT, GitHubReader


def run(run_id, created_at):
    return {
        "id": run_id,
        "created_at": created_at,
        "updated_at": created_at,
        "head_branch": "main",
        "status": "completed",
        "conclusion": "success",
    }


def artifact(artifact_id, run_id, created_at):
    return {
        "id": artifact_id,
        "name": SNAPSHOT_ARTIFACT,
        "created_at": created_at,
        "expired": False,
        "workflow_run": {
            "id": run_id,
            "head_branch": "main",
            "head_sha": "a" * 40,
        },
    }


def canonical_state(sequence):
    base = checkpoint({"heartbeat": seed_state()}, {"heartbeat": "fixture:heartbeat"})
    return set_authority(
        make_snapshot(base, [], sequence=sequence, evidence={}),
        mode="CANONICAL",
        production_authority=True,
    )


def snapshot_archive(state):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("snapshot.json", json.dumps(state, sort_keys=True))
    return stream.getvalue()


class ReducerRerunSnapshotTests(unittest.TestCase):
    def test_discovery_keeps_snapshots_from_reruns_but_counts_distinct_reducer_runs(self):
        reader = object.__new__(GitHubReader)
        latest_attempt_snapshot = artifact(12, 202, "2026-10-01T22:02:00Z")
        earlier_attempt_snapshot = artifact(11, 202, "2026-10-01T22:01:00Z")
        predecessor_snapshot = artifact(9, 201, "2026-10-01T21:01:00Z")
        calls = []

        def get(suffix):
            calls.append(suffix)
            if suffix.startswith("/actions/workflows/portfolio-state-reducer.yml/runs?"):
                return {"workflow_runs": [
                    run(202, "2026-10-01T22:00:00Z"),
                    run(201, "2026-10-01T21:00:00Z"),
                    run(200, "2026-10-01T20:00:00Z"),
                ]}
            if suffix == "/actions/runs/202/artifacts?per_page=100":
                return {"total_count": 2, "artifacts": [
                    earlier_attempt_snapshot, latest_attempt_snapshot,
                ]}
            if suffix == "/actions/runs/201/artifacts?per_page=100":
                return {"total_count": 1, "artifacts": [predecessor_snapshot]}
            raise AssertionError("unexpected GitHub request: " + suffix)

        reader.get = get
        with patch("state_journal.transport.WORKFLOW_PRODUCERS", {}):
            rows = reader.list_recent_journal_artifacts("2026-10-01T16:00:00Z")

        self.assertEqual([row["id"] for row in rows], [12, 11, 9])
        self.assertIn("/actions/runs/201/artifacts?per_page=100", calls)
        self.assertNotIn("/actions/runs/200/artifacts?per_page=100", calls)

    def test_checkpoint_rollover_uses_newest_snapshot_from_successful_rerun(self):
        reader = SimpleNamespace()
        older = artifact(11, 202, "2026-10-01T22:01:00Z")
        newer = artifact(12, 202, "2026-10-01T22:02:00Z")
        archives = {11: snapshot_archive(canonical_state(8)), 12: snapshot_archive(canonical_state(9))}
        for meta in (older, newer):
            archives_meta = archives[meta["id"]]
            meta["digest"] = "sha256:" + hashlib.sha256(archives_meta).hexdigest()

        reader.get = lambda suffix: (
            {"workflow_runs": [{
                **run(202, "2026-10-01T22:00:00Z"),
                "name": "portfolio-state-reducer",
                "path": ".github/workflows/portfolio-state-reducer.yml",
                "head_sha": "a" * 40,
            }]}
            if suffix.startswith("/actions/workflows/portfolio-state-reducer.yml/runs?")
            else {"total_count": 2, "artifacts": [older, newer]}
        )
        reader.archive = lambda artifact_id: archives[artifact_id]

        state, selected_run, selected_artifact = latest_canonical(reader)

        self.assertEqual(state["sequence"], 9)
        self.assertEqual(selected_run["id"], 202)
        self.assertEqual(selected_artifact["id"], 12)


if __name__ == "__main__":
    unittest.main()
