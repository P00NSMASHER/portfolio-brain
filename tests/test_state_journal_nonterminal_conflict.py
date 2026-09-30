"""A live producer's partial state artifact must not block legacy parity."""
import io
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from runtime.artifact_restore import InvalidStateArtifact, restore_latest_valid_state
from state_journal.contracts import digest
from state_journal.legacy import restore_domain

ROOT = Path(__file__).resolve().parents[1]


class NonterminalArtifactConflictTests(unittest.TestCase):
    def test_conflict_retries_after_excluding_only_nonterminal_producer(self):
        state = json.loads((ROOT / "dashboard/HISTORY_STATE_SEED.json").read_text())
        calls = []

        def restore(output, metadata):
            run_id = os.environ.get("GITHUB_RUN_ID")
            calls.append(run_id)
            if len(calls) == 1:
                archives = {}
                for candidate_run, marker in ((200, "in-progress"), (100, "completed")):
                    body = json.dumps({
                        "schema_version": "1.0.0",
                        "state_id": "fixture-state",
                        "sequence": 4,
                        "marker": marker,
                    }).encode()
                    archive = io.BytesIO()
                    with zipfile.ZipFile(archive, "w") as bundle:
                        bundle.writestr("state.json", body)
                    archives[str(candidate_run)] = archive.getvalue()
                restore_latest_valid_state(
                    {"artifacts": [
                        {
                            "id": candidate_run,
                            "created_at": f"2026-09-30T{candidate_run % 24:02d}:00:00Z",
                            "archive_download_url": str(candidate_run),
                            "workflow_run": {"id": candidate_run, "head_branch": "main"},
                        }
                        for candidate_run in (200, 100)
                    ]},
                    current_run=run_id,
                    expected_head_branch="main",
                    download=archives.__getitem__,
                    output=output,
                    member_name="state.json",
                    expected_state_id="fixture-state",
                    max_archive_bytes=10000,
                    max_state_bytes=1000,
                )
                raise AssertionError("divergent highest-sequence states should conflict")
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(state))
            metadata.write_text(json.dumps({
                "artifact_id": 1100,
                "source_run_id": 100,
                "source_head_sha": "a" * 40,
                "source_sequence": state["sequence"],
                "source_state_hash": digest(state),
                "artifact_created_at": "2026-09-30T09:00:00Z",
            }))
            return "RESTORED"

        class Reader:
            def __init__(self, *_args, **_kwargs):
                pass

            def get(self, suffix):
                run_id = int(suffix.rsplit("/", 1)[1])
                if run_id == 200:
                    return {"status": "in_progress", "conclusion": None}
                return {"status": "completed", "conclusion": "success"}

        with tempfile.TemporaryDirectory() as td, \
             patch.dict(os.environ, {
                 "GITHUB_TOKEN": "token",
                 "GITHUB_RUN_ID": "999",
                 "GITHUB_REF_NAME": "main",
             }, clear=False), \
             patch("state_journal.legacy.GitHubReader", Reader), \
             patch.dict("state_journal.legacy.RESTORERS", {"history": restore}, clear=False):
            restored, _ = restore_domain(ROOT, "history", Path(td))
            self.assertEqual(restored, state)
            self.assertEqual(calls, ["999", "200"])
            self.assertEqual(os.environ["GITHUB_RUN_ID"], "999")

    def test_terminal_divergent_artifacts_still_fail_closed(self):
        def restore(_output, _metadata):
            raise InvalidStateArtifact(
                "conflicting state artifacts at highest sequence",
                conflicting_run_ids=(100, 101),
            )

        class Reader:
            def __init__(self, *_args, **_kwargs):
                pass

            def get(self, _suffix):
                return {"status": "completed", "conclusion": "success"}

        with tempfile.TemporaryDirectory() as td, \
             patch.dict(os.environ, {
                 "GITHUB_TOKEN": "token",
                 "GITHUB_RUN_ID": "999",
                 "GITHUB_REF_NAME": "main",
             }, clear=False), \
             patch("state_journal.legacy.GitHubReader", Reader), \
             patch.dict("state_journal.legacy.RESTORERS", {"history": restore}, clear=False):
            with self.assertRaisesRegex(InvalidStateArtifact, "conflicting state artifacts"):
                restore_domain(ROOT, "history", Path(td))


if __name__ == "__main__":
    unittest.main()
