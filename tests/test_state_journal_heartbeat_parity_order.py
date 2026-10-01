"""Keep equal-time heartbeat replay ordering consistent with legacy restoration."""
import unittest

from agents.heartbeat_state import heartbeat, seed_state
from state_journal.contracts import canonical, digest
from state_journal.events import make_change, make_event, replay_heartbeat_batch
from state_journal.reducer import checkpoint, replay


SHA = "a" * 40
AT = "2026-10-01T06:00:00Z"
AGENTS = ("AGT-DATA-STEWARD", "AGT-HUNTER")


class HeartbeatParityOrderTests(unittest.TestCase):
    def test_equal_time_fork_uses_canonical_batch_order(self):
        initial = seed_state()
        branches = []
        for run_id in map(str, range(1, 40)):
            for agent_id in AGENTS:
                after = heartbeat(
                    initial,
                    agent_ids=[agent_id],
                    activity_kind="HEALTH_CHECK",
                    source_workflow="agent-heartbeat-sweep",
                    source_run_id=run_id,
                    at=AT,
                )
                change = make_change("heartbeat", initial, after)
                branches.append((run_id, change, change["batches"][0]))

        pair = next(
            (
                (left, right)
                for index, left in enumerate(branches)
                for right in branches[index + 1 :]
                if left[0] != right[0]
                and left[2]["work_ids_by_agent"].keys().isdisjoint(
                    right[2]["work_ids_by_agent"].keys()
                )
                and (digest(left[2]) < digest(right[2]))
                != (canonical(left[2]) < canonical(right[2]))
            ),
            None,
        )
        self.assertIsNotNone(pair, "fixture must distinguish digest and canonical ordering")
        left, right = pair
        events = [
            make_event(
                "agent-heartbeat-sweep",
                run_id,
                SHA,
                [change],
            )
            for run_id, change, _batch in pair
        ]
        actual = replay(
            checkpoint({"heartbeat": initial}, {"heartbeat": "fixture:heartbeat"}),
            events,
        )["states"]["heartbeat"]

        expected = initial
        for batch in sorted((left[2], right[2]), key=canonical):
            expected = replay_heartbeat_batch(expected, batch)

        self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
