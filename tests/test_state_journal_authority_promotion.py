import hashlib
import io
import json
import unittest
import zipfile

from agents.heartbeat_state import seed_state
from state_journal.contracts import JournalError, REPOSITORY
from state_journal.github_reducer import restore_snapshot
from state_journal.reducer import checkpoint, make_snapshot, set_authority

SHA = "a" * 40


def packed(state):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("snapshot.json", json.dumps(state))
    return output.getvalue()


def inputs(states):
    raws = {}
    artifacts = []
    runs = {}
    for run_id, state in zip(range(101, 101 + len(states)), states):
        raw = packed(state)
        raws[run_id] = raw
        artifacts.append({
            "id": run_id,
            "name": "portfolio-canonical-shadow-state",
            "expired": False,
            "digest": "sha256:" + hashlib.sha256(raw).hexdigest(),
            "workflow_run": {"id": run_id, "head_sha": SHA, "head_branch": "main"},
        })
        runs[run_id] = {
            "id": run_id,
            "path": ".github/workflows/portfolio-state-reducer.yml",
            "head_sha": SHA,
            "head_branch": "main",
            "status": "completed",
            "conclusion": "success",
            "repository": {"full_name": REPOSITORY},
            "head_repository": {"full_name": REPOSITORY},
        }

    class Reader:
        def archive(self, artifact_id):
            return raws[artifact_id]

        def get(self, suffix):
            return runs[int(suffix.rsplit("/", 1)[1])]

    return Reader(), artifacts


class AuthorityPromotionRestoreTests(unittest.TestCase):
    def test_metadata_only_promotion_supersedes_shadow_at_same_sequence(self):
        base = checkpoint({"heartbeat": seed_state()}, {"heartbeat": "fixture:heartbeat"})
        shadow = make_snapshot(base, [], sequence=5, evidence={})
        promoted = set_authority(shadow, mode="CANONICAL", production_authority=True)
        reader, artifacts = inputs([shadow, promoted])
        self.assertEqual(restore_snapshot(reader, artifacts, current_run="999"), promoted)

    def test_payload_divergence_at_same_sequence_is_rejected(self):
        one = checkpoint({"heartbeat": seed_state()}, {"heartbeat": "fixture:one"})
        two = checkpoint({"heartbeat": seed_state()}, {"heartbeat": "fixture:two"})
        reader, artifacts = inputs([
            make_snapshot(one, [], sequence=5, evidence={}),
            make_snapshot(two, [], sequence=5, evidence={}),
        ])
        with self.assertRaisesRegex(JournalError, "Conflicting canonical snapshots"):
            restore_snapshot(reader, artifacts, current_run="999")


if __name__ == "__main__":
    unittest.main()
