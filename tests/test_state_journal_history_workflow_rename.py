import unittest

from state_journal.contracts import REPOSITORY, validate_source_evidence


class HistoryWorkflowRenameTests(unittest.TestCase):
    def test_historical_command_center_workflow_evidence_remains_authorized(self):
        event = {
            "event_hash": "sha256:" + "a" * 64,
            "producer": "command-center-pages",
            "run_id": "101",
            "source_sha": "b" * 40,
        }
        evidence = {
            "kind": "GITHUB_ACTIONS",
            "repository": REPOSITORY,
            "artifact_id": 12,
            "archive_digest": "sha256:" + "c" * 64,
            "source_run_id": 101,
            "source_run_attempt": 1,
            "source_sha": "b" * 40,
            "workflow_id": 45,
            "workflow_path": ".github/workflows/command-center.yml",
            "source_conclusion": "success",
            "event_hash": event["event_hash"],
            "job_id": 20,
        }

        validate_source_evidence(evidence, event)


if __name__ == "__main__":
    unittest.main()
