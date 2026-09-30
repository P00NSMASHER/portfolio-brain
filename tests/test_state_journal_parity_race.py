"""Regression tests for producer completion racing reducer parity restoration."""
import unittest
from pathlib import Path
from unittest.mock import patch

from state_journal.contracts import JournalError
from state_journal.github_reducer import reduce_and_verify_legacy_parity


class LegacyParityRaceTests(unittest.TestCase):
    def test_rediscovery_reduces_a_producer_that_finished_during_parity_restore(self):
        first_state = {"projection": {"states": {"cost": {"sequence": 1}}}}
        refreshed_state = {"projection": {"states": {"cost": {"sequence": 2}}}}
        first_receipt = {"new_deliveries": 0}
        refreshed_receipt = {"new_deliveries": 1}
        parity = {"status": "PASS", "domains": {"cost": {}}}

        with patch(
            "state_journal.github_reducer.reduce_from_provider",
            side_effect=[(first_state, first_receipt), (refreshed_state, refreshed_receipt)],
        ) as reduce, patch(
            "state_journal.github_reducer.verify_legacy_parity",
            side_effect=[JournalError("LEGACY_PARITY_MISMATCH:cost"), parity],
        ) as verify:
            state, receipt, result = reduce_and_verify_legacy_parity(
                object(), since="2026-09-30T00:00:00Z", current_run="900",
                upload_steps={}, work=Path("unused"),
            )

        self.assertEqual(state, refreshed_state)
        self.assertEqual(receipt, refreshed_receipt)
        self.assertEqual(result, parity)
        self.assertEqual(reduce.call_count, 2)
        self.assertEqual(verify.call_count, 2)

    def test_only_a_legacy_domain_mismatch_triggers_rediscovery(self):
        with patch(
            "state_journal.github_reducer.reduce_from_provider",
            return_value=({"projection": {"states": {}}}, {}),
        ) as reduce, patch(
            "state_journal.github_reducer.verify_legacy_parity",
            side_effect=JournalError("Other parity validation error"),
        ):
            with self.assertRaisesRegex(JournalError, "Other parity validation error"):
                reduce_and_verify_legacy_parity(
                    object(), since="2026-09-30T00:00:00Z", current_run="900",
                    upload_steps={}, work=Path("unused"),
                )

        self.assertEqual(reduce.call_count, 1)

    def test_persistent_legacy_mismatch_still_blocks_publication(self):
        with patch(
            "state_journal.github_reducer.reduce_from_provider",
            return_value=({"projection": {"states": {}}}, {}),
        ) as reduce, patch(
            "state_journal.github_reducer.verify_legacy_parity",
            side_effect=JournalError("LEGACY_PARITY_MISMATCH:cost"),
        ):
            with self.assertRaisesRegex(JournalError, "LEGACY_PARITY_MISMATCH:cost"):
                reduce_and_verify_legacy_parity(
                    object(), since="2026-09-30T00:00:00Z", current_run="900",
                    upload_steps={}, work=Path("unused"),
                )

        self.assertEqual(reduce.call_count, 2)


if __name__ == "__main__":
    unittest.main()
