"""Independent PB01 receipt-semantics regression gate for issue #689 / PR #751.

Tests are purposely adversarial. No production code, permissions, schedules, or
provider settings are changed by this file. A PASS receipt must substantiate
repository observation work before it can advance durable state.
"""
import copy
import unittest

from runtime.state import (
    RuntimeStateError,
    advance_cycle,
    bootstrap_state,
    canonical_hash,
    cycle_id_for,
    validate_cycle_receipt,
)

BEFORE = "2026-09-25T17:00:00Z"
FINISHED = "2026-09-25T18:00:00Z"


class PB01IndependentObservationGate(unittest.TestCase):
    def setUp(self):
        self.state = bootstrap_state(now=BEFORE)
        self.rid = "REPO-001"
        self.cursor = self.state["repositories"][self.rid]["cursor_sha"]
        self.source_ref = self.state["repositories"][self.rid]["source_ref"]

    def observation(self, status="UNCHANGED", **overrides):
        value = {
            "repository_id": self.rid,
            "status": status,
            "source_ref": self.source_ref,
            "prior_sha": self.cursor,
            "current_sha": self.cursor,
            "observed_at": FINISHED,
        }
        value.update(overrides)
        return value

    def receipt(self, observations, *, mode="observe", status="PASS", reason=None):
        target = (
            observations[0].get("repository_id")
            if mode == "observe" and len(observations) == 1
            else None
        )
        value = {
            "schema_version": "1.0.0",
            "cycle_id": (
                "disabled" if status == "DISABLED"
                else cycle_id_for(
                    self.state, mode=mode,
                    target_repository_id=target, observations=observations
                )
            ),
            "mode": mode,
            "started_at": FINISHED,
            "finished_at": FINISHED,
            "status": status,
            "reason": reason,
            "observations": observations,
            "api_requests": 0 if status == "DISABLED" else len(observations),
        }
        value["receipt_hash"] = canonical_hash(value)
        return value

    def test_positive_unchanged_retains_cursor_and_records_observation(self):
        original = copy.deepcopy(self.state)
        result = advance_cycle(self.state, self.receipt([self.observation()]))
        self.assertEqual(result["sequence"], 1)
        self.assertEqual(result["repositories"][self.rid]["cursor_sha"], self.cursor)
        self.assertEqual(result["repositories"][self.rid]["observed_at"], FINISHED)
        self.assertEqual(self.state, original)

    def test_positive_changed_updates_cursor_and_replay_is_denied(self):
        newer = "f" * 40 if self.cursor != "f" * 40 else "e" * 40
        receipt = self.receipt([self.observation("CHANGED", current_sha=newer)])
        result = advance_cycle(self.state, receipt)
        self.assertEqual(result["repositories"][self.rid]["cursor_sha"], newer)
        with self.assertRaises(RuntimeStateError):
            advance_cycle(result, receipt)

    def test_positive_blocked_is_allowed_without_cursor_advancement(self):
        rid = "REPO-006"
        old = self.state["repositories"][rid]["cursor_sha"]
        blocked = {"repository_id": rid, "status": "BLOCKED",
                   "observed_at": FINISHED, "reason": "historical-only"}
        result = advance_cycle(self.state, self.receipt([blocked]))
        self.assertEqual(result["sequence"], 1)
        self.assertEqual(result["repositories"][rid]["cursor_sha"], old)
        self.assertEqual(result["repositories"][rid]["status"], "BLOCKED_HISTORICAL_ONLY")

    def test_disabled_receipt_remains_explicitly_supported(self):
        receipt = self.receipt([], mode="sync", status="DISABLED",
                               reason="operator kill switch")
        validate_cycle_receipt(receipt, allow_disabled=True)
        with self.assertRaises(RuntimeStateError):
            validate_cycle_receipt(receipt)

    def test_incomplete_success_observation_must_not_advance(self):
        for status in ("UNCHANGED", "CHANGED"):
            for defect in ("absent", "none", "empty"):
                with self.subTest(status=status, current_sha=defect):
                    observation = self.observation(status)
                    if defect == "absent":
                        observation.pop("current_sha")
                    elif defect == "none":
                        observation["current_sha"] = None
                    else:
                        observation["current_sha"] = ""
                    initial = copy.deepcopy(self.state)
                    receipt = self.receipt([observation])
                    with self.assertRaises(RuntimeStateError):
                        advance_cycle(self.state, receipt)
                    self.assertEqual(self.state, initial)

    def test_empty_observe_pass_must_not_advance(self):
        receipt = self.receipt([], mode="observe")
        with self.assertRaises(RuntimeStateError):
            advance_cycle(self.state, receipt)
        self.assertEqual(self.state["sequence"], 0)

    def test_empty_sync_pass_must_not_advance(self):
        receipt = self.receipt([], mode="sync")
        with self.assertRaises(RuntimeStateError):
            advance_cycle(self.state, receipt)
        self.assertEqual(self.state["sequence"], 0)

    def test_unknown_status_and_duplicate_identity_still_rejected(self):
        with self.assertRaises(RuntimeStateError):
            advance_cycle(
                self.state,
                self.receipt([self.observation(status="OBSERVED")]),
            )
        obs = self.observation()
        with self.assertRaises(RuntimeStateError):
            advance_cycle(self.state, self.receipt([obs, copy.deepcopy(obs)],
                                                   mode="sync"))
        self.assertEqual(self.state["sequence"], 0)

    def test_invalid_source_ref_is_rejected_atomically(self):
        initial = copy.deepcopy(self.state)
        bad = self.observation(source_ref="unexpected-branch")
        with self.assertRaises(RuntimeStateError):
            advance_cycle(self.state, self.receipt([bad]))
        self.assertEqual(self.state, initial)


if __name__ == "__main__":
    unittest.main()
