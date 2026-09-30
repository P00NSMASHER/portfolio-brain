import json
import tempfile
import unittest
import zipfile
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from runtime.artifact_restore import InvalidStateArtifact, restore_latest_valid_state
from state_journal.contracts import digest
from state_journal.legacy import restore_domain


ROOT = Path(__file__).resolve().parents[1]


def state_archive(sequence, branch):
    payload = json.dumps({
        "schema_version": "1.0.0",
        "state_id": "test-state",
        "sequence": sequence,
        "branch": branch,
    }).encode()
    archive = BytesIO()
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("state.json", payload)
    return archive.getvalue()


class StateJournalLiveArtifactRaceTests(unittest.TestCase):
    def test_conflict_reports_the_source_runs_needed_to_resolve_a_live_restore_race(self):
        data = {"artifacts": [
            {
                "id": 2,
                "created_at": "2026-09-30T15:00:00Z",
                "archive_download_url": "second",
                "workflow_run": {"id": 202, "head_branch": "main"},
            },
            {
                "id": 1,
                "created_at": "2026-09-30T14:59:00Z",
                "archive_download_url": "first",
                "workflow_run": {"id": 201, "head_branch": "main"},
            },
        ]}
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(
                InvalidStateArtifact, "conflicting state artifacts at highest sequence"
            ) as raised:
                restore_latest_valid_state(
                    data,
                    current_run="999",
                    expected_head_branch="main",
                    download=lambda url: state_archive(7, url),
                    output=Path(directory) / "state.json",
                    member_name="state.json",
                    expected_state_id="test-state",
                    max_archive_bytes=10000,
                    max_state_bytes=1000,
                )
        self.assertEqual(raised.exception.source_run_ids, (201, 202))

    def test_legacy_parity_retries_after_conflicting_writer_runs_finish(self):
        seed = json.loads((ROOT / "scheduler/SCHEDULER_STATE_SEED.json").read_text())
        restore_calls = []
        run_checks = {}

        class Reader:
            def __init__(self, *_args, **_kwargs):
                pass

            def get(self, suffix):
                if suffix == "/actions/runs?branch=main&per_page=100":
                    runs = []
                    for run_id in (201, 202):
                        run_checks[run_id] = run_checks.get(run_id, 0) + 1
                        if run_checks[run_id] == 1:
                            runs.append({"id": run_id, "status": "in_progress", "conclusion": None})
                        else:
                            runs.append({"id": run_id, "status": "completed", "conclusion": "success"})
                    return {"workflow_runs": runs}
                run_id = int(suffix.rsplit("/", 1)[1])
                if run_id == 301:
                    return {"status": "completed", "conclusion": "success"}
                raise AssertionError(f"Unexpected run status lookup: {run_id}")

        def restore(output, metadata):
            restore_calls.append(True)
            if len(restore_calls) == 1:
                raise InvalidStateArtifact(
                    "conflicting state artifacts at highest sequence",
                    source_run_ids=(201, 202),
                )
            output.write_text(json.dumps(seed))
            metadata.write_text(json.dumps({
                "source_state_hash": digest(seed),
                "artifact_id": 301,
                "source_run_id": 301,
                "source_head_sha": "a" * 40,
                "source_sequence": seed["sequence"],
                "artifact_created_at": "2026-09-30T15:00:00Z",
            }))
            return "RESTORED"

        with tempfile.TemporaryDirectory() as directory, \
             patch.dict("os.environ", {"GITHUB_TOKEN": "token", "GITHUB_RUN_ID": "999"}, clear=False), \
             patch("state_journal.legacy.GitHubReader", Reader), \
             patch.dict("state_journal.legacy.RESTORERS", {"scheduler": restore}), \
             patch("state_journal.legacy.time.sleep"):
            state, _reference = restore_domain(ROOT, "scheduler", Path(directory))

        self.assertEqual(state, seed)
        self.assertEqual(len(restore_calls), 2)
        self.assertEqual(run_checks, {201: 2, 202: 2})


if __name__ == "__main__":
    unittest.main()
