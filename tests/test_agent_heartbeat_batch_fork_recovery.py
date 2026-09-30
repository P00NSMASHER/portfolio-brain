import io
import json
import unittest
import zipfile

from agents.artifact_state import _resolve_equivalent_heartbeat_fork
from agents.heartbeat_state import heartbeat, seed_state


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
        "workflow_run": {
            "id": artifact_id + 100,
            "head_branch": "main",
            "head_sha": str(artifact_id).zfill(40),
        },
    }


class AgentHeartbeatBatchForkRecoveryTests(unittest.TestCase):
    def test_later_equivalent_partial_multi_agent_batch_wins(self):
        base = seed_state()
        agents = ["AGT-DATA-STEWARD", "AGT-HUNTER"]
        first = heartbeat(
            base,
            agent_ids=agents,
            activity_kind="RUNTIME_OBSERVATION",
            source_workflow="runtime-worker",
            source_run_id="observe-run",
            at="2026-09-28T13:50:55Z",
        )
        later = heartbeat(
            base,
            agent_ids=agents,
            activity_kind="RUNTIME_OBSERVATION",
            source_workflow="runtime-worker",
            source_run_id="sync-run",
            at="2026-09-28T13:51:03Z",
        )
        data = {
            "artifacts": [
                candidate(2, "2026-09-28T13:51:05Z", "later"),
                candidate(1, "2026-09-28T13:50:57Z", "first"),
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


if __name__ == "__main__":
    unittest.main()
