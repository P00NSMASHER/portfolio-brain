import unittest

from agents.heartbeat_state import heartbeat, seed_state
from state_journal.contracts import canonical, digest
from state_journal.events import make_change, make_event, replay_heartbeat_batch
from state_journal.reducer import checkpoint, replay


class HeartbeatParityOrderTests(unittest.TestCase):
    def test_same_time_commuting_batches_follow_legacy_canonical_order(self):
        base = seed_state()
        at = "2026-09-30T12:00:00Z"
        agents = sorted(base["agents"])
        candidates = []
        for agent_index, agent_id in enumerate(agents):
            for run_number in range(1, 25):
                run_id = agent_index * 24 + run_number
                after = heartbeat(
                    base,
                    agent_ids=[agent_id],
                    activity_kind="PARITY_ORDER_TEST",
                    source_workflow="runtime-worker",
                    source_run_id=str(run_id),
                    at=at,
                )
                change = make_change("heartbeat", base, after)
                batch = change["batches"][0]
                event = make_event(
                    "runtime-worker",
                    str(run_id),
                    "a" * 40,
                    [change],
                )
                candidates.append((agent_index, batch, event))

        pair = next((
            (first_event, second_event)
            for first_index, first_batch, first_event in candidates
            for second_index, second_batch, second_event in candidates
            if first_index < second_index
            if (canonical(first_batch) < canonical(second_batch))
            != (digest(first_batch) < digest(second_batch))
        ), None)
        if pair is None:
            self.fail("fixture must exercise differing legacy and journal tie-breakers")
        first_event, second_event = pair
        first_batch = first_event["changes"][0]["batches"][0]
        second_batch = second_event["changes"][0]["batches"][0]

        expected = base
        for batch in sorted((first_batch, second_batch), key=canonical):
            expected = replay_heartbeat_batch(expected, batch)

        base_checkpoint = checkpoint(
            {"heartbeat": base},
            {"heartbeat": "fixture:heartbeat"},
        )
        projection = replay(base_checkpoint, [first_event, second_event])
        self.assertEqual(projection["states"]["heartbeat"], expected)


if __name__ == "__main__":
    unittest.main()
