import io
import json
import unittest
import zipfile

from agents.artifact_state import _merge_commuting_heartbeat_fork, _canonical_bytes
from agents.heartbeat_state import heartbeat, seed_state
from state_journal.contracts import digest
from state_journal.events import make_change, make_event
from state_journal.reducer import checkpoint, replay


def artifact(artifact_id, state):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("agent_heartbeat_state.json", json.dumps(state))
    return {
        "id": artifact_id,
        "name": "portfolio-agent-heartbeat-state",
        "created_at": f"2026-10-01T13:30:0{artifact_id}Z",
        "expires_at": "2026-10-28T00:00:00Z",
        "archive_download_url": str(artifact_id),
        "expired": False,
        "workflow_run": {
            "id": artifact_id + 100,
            "head_branch": "main",
            "head_sha": str(artifact_id).zfill(40),
        },
    }, output.getvalue()


class StateJournalHeartbeatParityTests(unittest.TestCase):
    def test_merged_heartbeat_fork_uses_canonical_reducer_batch_order(self):
        at = "2026-10-01T13:30:00Z"
        base = seed_state()
        possible_batches = []
        for agent_id, workflow in (
            ("AGT-HUNTER", "hunter-autonomous-cycle"),
            ("AGT-DATA-STEWARD", "runtime-worker"),
        ):
            for run_id in range(1, 41):
                possible_batches.append({
                    "at": at,
                    "activity_kind": "PARITY_TEST",
                    "source_workflow": workflow,
                    "source_run_id": str(run_id),
                    "work_ids_by_agent": {agent_id: []},
                })
        pair = next(
            (
                (left, right)
                for left in possible_batches
                if left["source_workflow"] == "hunter-autonomous-cycle"
                for right in possible_batches
                if right["source_workflow"] == "runtime-worker"
                and (
                    (_canonical_bytes(left) < _canonical_bytes(right))
                    != (digest(left) < digest(right))
                )
            ),
            None,
        )
        self.assertIsNotNone(pair, "test fixtures must cover differing lexical/hash order")

        branches = []
        events = []
        for batch in pair:
            agent_id = next(iter(batch["work_ids_by_agent"]))
            after = heartbeat(
                base,
                agent_ids=[agent_id],
                activity_kind=batch["activity_kind"],
                source_workflow=batch["source_workflow"],
                source_run_id=batch["source_run_id"],
                work_ids_by_agent=batch["work_ids_by_agent"],
                at=batch["at"],
            )
            branches.append(after)
            event = make_event(
                batch["source_workflow"],
                batch["source_run_id"],
                "a" * 40,
                [make_change("heartbeat", base, after)],
            )
            events.append(event)

        base_artifact, base_archive = artifact(1, base)
        first_artifact, first_archive = artifact(2, branches[0])
        second_artifact, second_archive = artifact(3, branches[1])
        archives = {"1": base_archive, "2": first_archive, "3": second_archive}
        merged, _, _ = _merge_commuting_heartbeat_fork(
            {"artifacts": [second_artifact, first_artifact, base_artifact]},
            current_run="999",
            expected_head_branch="main",
            download=archives.__getitem__,
        )
        reduced = replay(
            checkpoint({"heartbeat": base}, {"heartbeat": "fixture:heartbeat"}),
            events,
        )["states"]["heartbeat"]

        self.assertEqual(merged, reduced)


if __name__ == "__main__":
    unittest.main()
