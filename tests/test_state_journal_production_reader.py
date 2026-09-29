import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agents.heartbeat_state import seed_state
from state_journal.contracts import JournalError, digest
from state_journal.reducer import checkpoint, make_snapshot, set_authority
from state_journal.transport import EVENT_PREFIX, SNAPSHOT_ARTIFACT
from state_journal.production_reader import restore_domain

ROOT = Path(__file__).resolve().parents[1]


def canonical_snapshot():
    base = checkpoint({"heartbeat": seed_state()}, {"heartbeat": "fixture:heartbeat"})
    state = make_snapshot(base, [], sequence=5, evidence={})
    return set_authority(state, mode="CANONICAL", production_authority=True)


def snapshot_meta():
    return {
        "id": 11,
        "name": SNAPSHOT_ARTIFACT,
        "expired": False,
        "created_at": "2026-09-29T18:42:59Z",
        "expires_at": "2026-10-29T18:42:59Z",
        "workflow_run": {"id": 101, "head_branch": "main", "head_sha": "a" * 40},
    }

class FakeReader:
    def __init__(self, artifacts):
        self.artifacts = artifacts
    def list_recent_artifacts(self, *args, **kwargs):
        return self.artifacts
    def archive(self, artifact_id):
        return b"snapshot-bytes"


class CanonicalProductionReaderTests(unittest.TestCase):
    def run_restore(self, artifacts):
        state = canonical_snapshot()
        fake = FakeReader(artifacts)
        with tempfile.TemporaryDirectory() as td, \
             patch.dict(os.environ, {"GITHUB_TOKEN": "token", "GITHUB_RUN_ID": "999"}, clear=False), \
             patch("state_journal.production_reader.GitHubReader", return_value=fake), \
             patch("state_journal.production_reader.restore_snapshot", return_value=state), \
             patch("state_journal.production_reader.artifact_digest"), \
             patch("state_journal.production_reader.extract_json", return_value=state):
            output = Path(td) / "heartbeat.json"
            metadata = Path(td) / "meta.json"
            status = restore_domain("heartbeat", output, metadata)
            return status, json.loads(output.read_text()), json.loads(metadata.read_text())

    def test_restores_exact_domain_from_authoritative_snapshot(self):
        status, state, meta = self.run_restore([snapshot_meta()])
        self.assertEqual(status, "RESTORED_CANONICAL")
        self.assertEqual(state, seed_state())
        self.assertEqual(meta["artifact_id"], 11)
        self.assertEqual(meta["source_run_id"], 101)
        self.assertEqual(meta["source_head_sha"], "a" * 40)
        self.assertEqual(meta["domain_state_hash"], digest(seed_state()))
    def test_pending_event_blocks_stale_reader(self):
        pending = {
            "id": 12,
            "name": EVENT_PREFIX + "123-runtime-worker-" + "b" * 40 + "-1",
            "expired": False,
            "created_at": "2026-09-29T18:43:10Z",
            "workflow_run": {"id": 123, "head_branch": "main", "head_sha": "b" * 40},
        }
        with self.assertRaisesRegex(JournalError, "STALE_CANONICAL_STATE_PENDING_REDUCTION"):
            self.run_restore([snapshot_meta(), pending])

    def test_all_state_mutators_use_canonical_reader(self):
        names = [
            "agent-heartbeat-sweep.yml",
            "command-center-pages.yml",
            "continuous-learning-bootstrap.yml",
            "hunter-autonomous-cycle.yml",
            "model-value-proof.yml",
            "operator-console.yml",
            "portfolio-autonomous-scheduler.yml",
            "portfolio-notification-cycle.yml",
            "runtime-worker.yml",
            "software-factory-candidate.yml",
            "verified-feedback-bootstrap.yml",
        ]
        for name in names:
            with self.subTest(workflow=name):
                text = (ROOT / ".github/workflows" / name).read_text()
                self.assertIn("state_journal.production_reader", text)

    def test_reducer_remains_only_canonical_snapshot_publisher(self):
        publishers = []
        for workflow in (ROOT / ".github/workflows").glob("*.yml"):
            if "name: portfolio-canonical-shadow-state" in workflow.read_text():
                publishers.append(workflow.name)
        self.assertEqual(publishers, ["portfolio-state-reducer.yml"])


if __name__ == "__main__":
    unittest.main()