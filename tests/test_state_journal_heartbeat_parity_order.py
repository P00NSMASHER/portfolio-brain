"""Regression coverage for legacy-compatible ordering of concurrent heartbeats."""
import itertools
import unittest

from agents.heartbeat_state import heartbeat, seed_state
from state_journal.contracts import canonical, digest
from state_journal.events import make_change, make_event
from state_journal.reducer import checkpoint, replay, replay_heartbeat_batch


class HeartbeatParityOrderTests(unittest.TestCase):
    def test_equal_time_batches_use_legacy_canonical_order_not_hash_order(self):
        base_state = seed_state()
        batches_and_events = []
        for agent_id in sorted(base_state["agents"]):
            for _ in range(3):
                run_id = str(101 + len(batches_and_events))
                after = heartbeat(
                    base_state,
                    agent_ids=[agent_id],
                    activity_kind="RUNTIME_OBSERVATION",
                    source_workflow="runtime-worker",
                    source_run_id=run_id,
                    at="2026-09-30T12:00:00Z",
                )
                event = make_event(
                    "runtime-worker",
                    run_id,
                    "a" * 40,
                    [make_change("heartbeat", base_state, after)],
                )
                batches_and_events.append((event["changes"][0]["batches"][0], event))

        pair = next(
            (
                (left, left_event, right, right_event)
                for (left, left_event), (right, right_event) in itertools.combinations(batches_and_events, 2)
                if left["work_ids_by_agent"].keys().isdisjoint(right["work_ids_by_agent"].keys())
                and (canonical(left) < canonical(right)) != (digest(left) < digest(right))
            ),
            None,
        )
        self.assertIsNotNone(pair, "fixture must include batches whose canonical and hash orders differ")
        left, left_event, right, right_event = pair

        base = checkpoint({"heartbeat": base_state}, {"heartbeat": "fixture:heartbeat"})
        expected = base_state
        for batch in sorted((left, right), key=canonical):
            expected = replay_heartbeat_batch(expected, batch)

        self.assertEqual(replay(base, [left_event, right_event])["states"]["heartbeat"], expected)


if __name__ == "__main__":
    unittest.main()
