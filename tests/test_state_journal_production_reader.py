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
from state_journal.production_reader import restore_domain, _wait_for_reduction

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
    def test_default_reducer_wait_covers_real_queue_pressure(self):
        source=(ROOT/"state_journal/production_reader.py").read_text()
        self.assertIn("timeout_seconds: int = 300",source)
        self.assertIn("poll_seconds: float = 5.0",source)
        self.assertIn('max_requests=policy["limits"]["max_read_requests"]',source)

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

    def test_second_restore_in_same_run_uses_validated_local_cache(self):
        state = canonical_snapshot()
        fake = FakeReader([snapshot_meta()])
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cache = root / "canonical-cache.json"
            first = root / "first.json"
            second = root / "second.json"
            first_meta = root / "first-meta.json"
            second_meta = root / "second-meta.json"
            env = {
                "GITHUB_TOKEN": "token", "GITHUB_RUN_ID": "999",
                "PORTFOLIO_CANONICAL_CACHE": str(cache),
            }
            with patch.dict(os.environ, env, clear=False), \
                 patch("state_journal.production_reader.GitHubReader", return_value=fake) as reader_cls, \
                 patch("state_journal.production_reader.restore_snapshot", return_value=state), \
                 patch("state_journal.production_reader.artifact_digest"), \
                 patch("state_journal.production_reader.extract_json", return_value=state):
                self.assertEqual(restore_domain("heartbeat", first, first_meta), "RESTORED_CANONICAL")
                self.assertTrue(cache.exists())
                calls_after_first = reader_cls.call_count
                self.assertEqual(restore_domain("heartbeat", second, second_meta), "RESTORED_CANONICAL_CACHED")
                self.assertEqual(reader_cls.call_count, calls_after_first)
            self.assertEqual(json.loads(first.read_text()), json.loads(second.read_text()))
            self.assertEqual(json.loads(second_meta.read_text())["restore_status"], "RESTORED_CANONICAL_CACHED")

    def test_cache_is_bound_to_exact_github_run(self):
        state = canonical_snapshot()
        fake = FakeReader([snapshot_meta()])
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cache = root / "canonical-cache.json"
            with patch.dict(os.environ, {
                "GITHUB_TOKEN": "token", "GITHUB_RUN_ID": "999",
                "PORTFOLIO_CANONICAL_CACHE": str(cache),
            }, clear=False), \
                 patch("state_journal.production_reader.GitHubReader", return_value=fake), \
                 patch("state_journal.production_reader.restore_snapshot", return_value=state), \
                 patch("state_journal.production_reader.artifact_digest"), \
                 patch("state_journal.production_reader.extract_json", return_value=state):
                restore_domain("heartbeat", root / "first.json")
            with patch.dict(os.environ, {
                "GITHUB_TOKEN": "token", "GITHUB_RUN_ID": "1000",
                "PORTFOLIO_CANONICAL_CACHE": str(cache),
            }, clear=False), self.assertRaisesRegex(JournalError, "another run"):
                restore_domain("heartbeat", root / "second.json")
    def test_pending_event_waits_for_successful_reducer_evidence(self):
        pending = {
            "id": 12,
            "name": EVENT_PREFIX + "123-runtime-worker-" + "b" * 40 + "-1",
            "expired": False,
            "created_at": "2026-09-29T18:43:10Z",
            "workflow_run": {"id": 123, "head_branch": "main", "head_sha": "b" * 40},
        }
        fresh = canonical_snapshot()
        fresh["evidence"] = {"event": [{"kind": "GITHUB_ACTIONS", "artifact_id": 12}]}
        class PollReader:
            def get(self, _suffix):
                return {"workflow_runs": [{
                    "id": 900, "name": "portfolio-state-reducer", "head_branch": "main",
                    "status": "completed", "conclusion": "success",
                    "created_at": "2026-09-29T18:43:11Z",
                }]}
        class FreshReader:
            def list_recent_artifacts(self, *args, **kwargs):
                return [snapshot_meta(), pending]
        policy = json.loads((ROOT / "state_journal/POLICY.json").read_text())
        with patch("state_journal.production_reader.GitHubReader", side_effect=[PollReader(), FreshReader()]), \
             patch("state_journal.production_reader.restore_snapshot", return_value=fresh):
            reader, state, artifacts = _wait_for_reduction(
                "token", policy, [pending], current_run="999",
                timeout_seconds=1, poll_seconds=0, clock=lambda: 0, sleep=lambda _: None,
            )
        self.assertIsInstance(reader, FreshReader)
        self.assertEqual(state, fresh)
        self.assertEqual(artifacts[-1]["id"], 12)

    def test_pending_event_timeout_fails_closed(self):
        pending = {
            "id": 12, "name": EVENT_PREFIX + "123-runtime-worker-" + "b" * 40 + "-1",
            "expired": False, "created_at": "2026-09-29T18:43:10Z",
            "workflow_run": {"id": 123, "head_branch": "main", "head_sha": "b" * 40},
        }
        policy = json.loads((ROOT / "state_journal/POLICY.json").read_text())
        class PollReader:
            def get(self, _suffix): return {"workflow_runs": []}
        with patch("state_journal.production_reader.GitHubReader", return_value=PollReader()), \
             self.assertRaisesRegex(JournalError, "STALE_CANONICAL_STATE_REDUCTION_TIMEOUT"):
            _wait_for_reduction("token", policy, [pending], current_run="999", timeout_seconds=0)

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