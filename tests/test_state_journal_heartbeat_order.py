"""Regression coverage for canonical ordering of same-time heartbeat batches."""
import unittest

from agents.heartbeat_state import seed_state
from state_journal.contracts import canonical, digest
from state_journal.events import make_change, make_event, replay_heartbeat_batch
from state_journal.reducer import checkpoint, replay


class HeartbeatReplayOrderingTests(unittest.TestCase):
    def test_same_time_disjoint_updates_use_canonical_batch_order(self):
        base = seed_state()
        at = "2026-09-30T12:00:00Z"
        agent_ids = ("AGT-DATA-STEWARD", "AGT-HUNTER")

        # Find a small, deterministic pair whose byte and hash order disagree.
        # This reproduces the case where hash ordering diverges from legacy fork
        # recovery's canonical-byte ordering.
        batches = None
        for left in range(20):
            for right in range(20):
                candidate = [
                    {
                        "at": at,
                        "activity_kind": f"ACTIVITY-{left}",
                        "source_workflow": "runtime-worker",
                        "source_run_id": "101",
                        "work_ids_by_agent": {agent_ids[0]: [f"WORK-{left}"]},
                    },
                    {
                        "at": at,
                        "activity_kind": f"ACTIVITY-{right}",
                        "source_workflow": "hunter-autonomous-cycle",
                        "source_run_id": "102",
                        "work_ids_by_agent": {agent_ids[1]: [f"WORK-{right}"]},
                    },
                ]
                if [canonical(batch) for batch in sorted(candidate, key=canonical)] != [
                    canonical(batch) for batch in sorted(candidate, key=digest)
                ]:
                    batches = candidate
                    break
            if batches is not None:
                break
        self.assertIsNotNone(batches)

        events = []
        for batch in batches:
            after = replay_heartbeat_batch(base, batch)
            events.append(make_event(
                batch["source_workflow"],
                batch["source_run_id"],
                "a" * 40,
                [make_change("heartbeat", base, after)],
            ))

        expected = base
        for batch in sorted(batches, key=canonical):
            expected = replay_heartbeat_batch(expected, batch)
        checkpoint_doc = checkpoint(
            {"heartbeat": base}, {"heartbeat": "fixture:heartbeat"}
        )

        actual = replay(checkpoint_doc, events)["states"]["heartbeat"]
        self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
