"""Regression coverage for deterministic same-time heartbeat fork replay."""
import io
import json
import unittest
import zipfile

from agents.artifact_state import _merge_commuting_heartbeat_fork
from agents.heartbeat_state import heartbeat, seed_state
from state_journal.contracts import canonical, digest
from state_journal.events import heartbeat_batches, make_change, make_event
from state_journal.reducer import checkpoint, replay

SHA = "a" * 40
AT = "2026-10-02T09:00:00Z"


def archive(state):
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as bundle:
        bundle.writestr("agent_heartbeat_state.json", json.dumps(state))
    return payload.getvalue()


def artifact(artifact_id, created_at, url):
    return {
        "id": artifact_id,
        "created_at": created_at,
        "expires_at": "2026-10-28T00:00:00Z",
        "archive_download_url": url,
        "expired": False,
        "workflow_run": {"id": artifact_id + 100, "head_branch": "main"},
    }


class HeartbeatTieOrderRegressionTests(unittest.TestCase):
    def test_same_time_disjoint_updates_match_legacy_fork_merge_order(self):
        base = seed_state()
        branches = None
        agent_ids = sorted(base["agents"])
        for first_index, first_agent in enumerate(agent_ids):
            for second_agent in agent_ids[first_index + 1:]:
                first = heartbeat(
                    base,
                    agent_ids=[first_agent],
                    activity_kind="RUNTIME_OBSERVATION",
                    source_workflow="runtime-worker",
                    source_run_id="101",
                    at=AT,
                )
                second = heartbeat(
                    base,
                    agent_ids=[second_agent],
                    activity_kind="RUNTIME_OBSERVATION",
                    source_workflow="runtime-worker",
                    source_run_id="102",
                    at=AT,
                )
                batches = heartbeat_batches(base, first) + heartbeat_batches(base, second)
                if sorted(batches, key=canonical) != sorted(batches, key=digest):
                    branches = (first_agent, first, second_agent, second)
                    break
            if branches is not None:
                break
        self.assertIsNotNone(branches, "fixture must distinguish canonical and digest tie-breakers")
        first_agent, first_state, second_agent, second_state = branches

        first_event = make_event(
            "runtime-worker", "101", SHA,
            [make_change("heartbeat", base, first_state)],
        )
        second_event = make_event(
            "runtime-worker", "102", SHA,
            [make_change("heartbeat", base, second_state)],
        )
        payloads = {
            "first": archive(first_state),
            "second": archive(second_state),
            "base": archive(base),
        }
        legacy_state, _sources, _fork_ids = _merge_commuting_heartbeat_fork(
            {
                "artifacts": [
                    artifact(1, "2026-10-02T09:01:00Z", "first"),
                    artifact(2, "2026-10-02T09:02:00Z", "second"),
                    artifact(3, "2026-10-02T08:59:00Z", "base"),
                ]
            },
            current_run="999",
            expected_head_branch="main",
            download=payloads.__getitem__,
        )
        base_checkpoint = checkpoint({"heartbeat": base}, {"heartbeat": "fixture:heartbeat"})

        projected = replay(base_checkpoint, [first_event, second_event])["states"]["heartbeat"]

        self.assertEqual(projected, legacy_state)
        self.assertEqual(
            {event["agent_id"] for event in projected["recent_events"][-2:]},
            {first_agent, second_agent},
        )


if __name__ == "__main__":
    unittest.main()
