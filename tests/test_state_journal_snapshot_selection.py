import unittest

from state_journal.contracts import JournalError
from state_journal.github_reducer import _latest_snapshot_artifact
from state_journal.transport import SNAPSHOT_ARTIFACT


def snapshot(artifact_id, run_id, expired=False):
    return {
        "id": artifact_id,
        "name": SNAPSHOT_ARTIFACT,
        "expired": expired,
        "workflow_run": {
            "id": run_id,
            "head_sha": f"{run_id:040x}"[-40:],
            "head_branch": "main",
        },
    }


class SnapshotSelectionTests(unittest.TestCase):
    def test_more_than_twenty_snapshots_select_latest_live_reducer_run(self):
        rows = [snapshot(i, 1000 + i) for i in range(1, 26)]
        self.assertEqual(
            _latest_snapshot_artifact(list(reversed(rows)), current_run="9999")["id"],
            25,
        )

    def test_expired_newer_snapshot_is_ignored(self):
        live = snapshot(20, 1020)
        expired = snapshot(21, 1021, True)
        self.assertEqual(_latest_snapshot_artifact([expired, live], current_run="9999"), live)

    def test_duplicate_latest_run_fails_closed(self):
        one = snapshot(20, 1020)
        two = snapshot(21, 1020)
        with self.assertRaisesRegex(JournalError, "ambiguous"):
            _latest_snapshot_artifact([one, two], current_run="9999")

    def test_current_run_is_excluded(self):
        older = snapshot(20, 1020)
        current = snapshot(21, 1021)
        self.assertEqual(_latest_snapshot_artifact([current, older], current_run="1021"), older)


if __name__ == "__main__":
    unittest.main()
