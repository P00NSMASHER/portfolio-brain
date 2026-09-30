import io
import json
import unittest
import zipfile

from agents.artifact_state import _resolve_equivalent_heartbeat_fork
from agents.heartbeat_state import heartbeat, seed_state
from runtime.artifact_restore import InvalidStateArtifact


def bundle(state):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr("agent_heartbeat_state.json", json.dumps(state).encode())
    return out.getvalue()


def candidate(artifact_id, created_at, url):
    return {
        "id": artifact_id,
        "name": "portfolio-agent-heartbeat-state",
        "created_at": created_at,
        "expires_at": "2026-10-28T00:00:00Z",
        "archive_download_url": url,
        "expired": False,
        "workflow_run": {"id": artifact_id + 100, "head_branch": "main"},
    }


class AgentHeartbeatBatchForkRecoveryTests(unittest.TestCase):
    def test_later_equivalent_multi_agent_batch_wins(self):
        base = heartbeat(
            seed_state(),
            agent_ids=["AGT-HUNTER"],
            activity_kind="HUNTER_CYCLE",
            source_workflow="hunter-autonomous-cycle",
            source_run_id="prior-run",
            at="2026-09-29T13:00:00Z",
        )
        agents = ["AGT-DATA-STEWARD", "AGT-PORTFOLIO-MANAGER"]
        first = heartbeat(
            base,
            agent_ids=agents,
            activity_kind="SCHEDULED_WORK",
            source_workflow="portfolio-autonomous-scheduler",
            source_run_id="scheduler-run-1",
            work_ids_by_agent={"AGT-DATA-STEWARD": ["SWORK-1"]},
            at="2026-09-29T13:50:55Z",
        )
        later = heartbeat(
            base,
            agent_ids=agents,
            activity_kind="SCHEDULED_WORK",
            source_workflow="portfolio-autonomous-scheduler",
            source_run_id="scheduler-run-2",
            work_ids_by_agent={"AGT-DATA-STEWARD": ["SWORK-1"]},
            at="2026-09-29T13:51:03Z",
        )
        data = {
            "artifacts": [
                candidate(2, "2026-09-29T13:51:05Z", "later"),
                candidate(1, "2026-09-29T13:50:57Z", "first"),
            ]
        }
        payloads = {"later": bundle(later), "first": bundle(first)}

        selected, fork_ids = _resolve_equivalent_heartbeat_fork(
            data,
            current_run="999",
            expected_head_branch="main",
            download=payloads.__getitem__,
        )

        self.assertEqual(selected["artifacts"][0]["id"], 2)
        self.assertEqual(fork_ids, [2, 1])

    def test_batch_with_different_work_is_still_rejected(self):
        base = heartbeat(
            seed_state(),
            agent_ids=["AGT-HUNTER"],
            activity_kind="HUNTER_CYCLE",
            source_workflow="hunter-autonomous-cycle",
            source_run_id="prior-run",
            at="2026-09-29T13:00:00Z",
        )
        agents = ["AGT-DATA-STEWARD", "AGT-PORTFOLIO-MANAGER"]
        first = heartbeat(
            base,
            agent_ids=agents,
            activity_kind="SCHEDULED_WORK",
            source_workflow="portfolio-autonomous-scheduler",
            source_run_id="scheduler-run-1",
            work_ids_by_agent={"AGT-DATA-STEWARD": ["SWORK-1"]},
            at="2026-09-29T13:50:55Z",
        )
        later = heartbeat(
            base,
            agent_ids=agents,
            activity_kind="SCHEDULED_WORK",
            source_workflow="portfolio-autonomous-scheduler",
            source_run_id="scheduler-run-2",
            work_ids_by_agent={"AGT-DATA-STEWARD": ["SWORK-2"]},
            at="2026-09-29T13:51:03Z",
        )
        data = {
            "artifacts": [
                candidate(2, "2026-09-29T13:51:05Z", "later"),
                candidate(1, "2026-09-29T13:50:57Z", "first"),
            ]
        }
        payloads = {"later": bundle(later), "first": bundle(first)}

        with self.assertRaisesRegex(
            InvalidStateArtifact, "no unique later equivalent update"
        ):
            _resolve_equivalent_heartbeat_fork(
                data,
                current_run="999",
                expected_head_branch="main",
                download=payloads.__getitem__,
            )


if __name__ == "__main__":
    unittest.main()
