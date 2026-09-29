import hashlib
import io
import json
import unittest
import zipfile

from agents.heartbeat_state import seed_state
from state_journal.contracts import JournalError
from state_journal.github_reducer import restore_snapshot
from state_journal.reducer import checkpoint, make_snapshot
from state_journal.transport import SNAPSHOT_ARTIFACT

REPO = "P00NSMASHER/portfolio-brain"
SHA = "a" * 40


def _archive(state):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as bundle:
        bundle.writestr("snapshot.json", json.dumps(state, sort_keys=True, separators=(",", ":")))
    return stream.getvalue()


def _source(artifact_id, run_id, state):
    raw = _archive(state)
    meta = {
        "id": artifact_id,
        "name": SNAPSHOT_ARTIFACT,
        "expired": False,
        "digest": "sha256:" + hashlib.sha256(raw).hexdigest(),
        "workflow_run": {"id": run_id, "head_branch": "main", "head_sha": SHA},
    }
    run = {
        "id": run_id,
        "path": ".github/workflows/portfolio-state-reducer.yml",
        "head_branch": "main",
        "head_sha": SHA,
        "status": "completed",
        "conclusion": "success",
        "repository": {"full_name": REPO},
        "head_repository": {"full_name": REPO},
    }
    return meta, run, raw


class Reader:
    def __init__(self, rows):
        self.runs = {}
        self.archives = {}
        self.artifacts = []
        for artifact_id, run_id, state in rows:
            meta, run, raw = _source(artifact_id, run_id, state)
            self.artifacts.append(meta)
            self.runs[run_id] = run
            self.archives[artifact_id] = raw

    def get(self, path):
        return self.runs[int(path.rsplit("/", 1)[-1])]

    def archive(self, artifact_id):
        return self.archives[artifact_id]


class CanonicalReadyReducerRegressionTests(unittest.TestCase):
    def test_authority_only_ready_snapshot_does_not_block_next_reducer_run(self):
        base = checkpoint({"heartbeat": seed_state()}, {"heartbeat": "fixture:heartbeat"})
        shadow = make_snapshot(base, [], sequence=5, evidence={})
        ready = make_snapshot(
            base, [], sequence=5, evidence={}, mode="CANONICAL", production_authority=True
        )
        reader = Reader([(101, 201, shadow), (102, 202, ready)])
        selected = restore_snapshot(reader, reader.artifacts, current_run="999")
        self.assertEqual(selected, ready)

    def test_real_same_sequence_lineage_conflict_still_fails_closed(self):
        first = checkpoint({"heartbeat": seed_state()}, {"heartbeat": "fixture:first"})
        second = checkpoint({"heartbeat": seed_state()}, {"heartbeat": "fixture:second"})
        shadow = make_snapshot(first, [], sequence=5, evidence={})
        divergent = make_snapshot(
            second, [], sequence=5, evidence={}, mode="CANONICAL", production_authority=True
        )
        reader = Reader([(101, 201, shadow), (102, 202, divergent)])
        with self.assertRaisesRegex(JournalError, "Conflicting canonical snapshots"):
            restore_snapshot(reader, reader.artifacts, current_run="999")


if __name__ == "__main__":
    unittest.main()
