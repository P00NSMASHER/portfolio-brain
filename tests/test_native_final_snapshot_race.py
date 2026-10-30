"""Synthetic validation/copy race; no real provider or approval is used."""
import unittest
from unittest.mock import patch

from verification import native_final_approval as mod
from test_native_final_approval import Provider, ticket, fingerprint, SOURCE, POLICY, NOW


class FinalSnapshotRaceTests(unittest.TestCase):
    def test_ticket_is_copied_before_validation_not_after_it(self):
        original_validator = mod._ticket
        original_ticket = ticket()
        provider = Provider()

        def after_validation(observed, *args):
            original_validator(observed, *args)
            # Deterministic interleaving: another owner mutates caller input
            # after validation but before the first external GET.
            original_ticket['head_ref'] = 'canary/replacement'
            provider.pr['head']['ref'] = original_ticket['head_ref']
            provider.approval['external_id'] = fingerprint(original_ticket)
            provider.checks['check_runs'][1]['external_id'] = fingerprint(original_ticket)

        with patch.object(mod, '_ticket', side_effect=after_validation):
            result = mod.verify_final_approval(
                provider, original_ticket, expected_source_sha=SOURCE,
                expected_policy_sha=POLICY, now=NOW)
        self.assertEqual(result.status, 'HOLD')
        self.assertEqual(result.reason, 'PR_HEAD_OR_BASE_DRIFT')
        self.assertEqual(result.provider_writes, 0)
        self.assertFalse(result.merge_authorized)
        self.assertFalse(result.protected_check_issued)


if __name__ == '__main__':
    unittest.main()
