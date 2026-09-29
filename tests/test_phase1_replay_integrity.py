import copy
import hashlib
import json
import unittest

from policy_replay.policy_backtester import replay, validate_replay_receipt
from test_policy_backtester import cycle


def rehash(receipt):
    body = {k: v for k, v in receipt.items() if k != 'replay_hash'}
    receipt['replay_hash'] = 'sha256:' + hashlib.sha256(json.dumps(body, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
    return receipt


class Phase1ReplayIntegrityTests(unittest.TestCase):
    def rows(self):
        return [cycle('1'), cycle('2'), cycle('3')]

    def test_incomplete_self_hashed_receipt_rejected(self):
        malformed = rehash({'mode': 'SHADOW_ONLY', 'promotion_allowed': False, 'forward_canary_required': True})
        with self.assertRaises(ValueError):
            validate_replay_receipt(malformed)

    def test_repeated_cycle_cannot_meet_minimum_sample(self):
        with self.assertRaises(ValueError):
            replay([cycle('one')] * 3, {'candidate_id': 'test'})

    def test_rehashed_million_outcome_contradiction_rejected(self):
        receipt = replay(self.rows(), {'candidate_id': 'test'})
        receipt['comparison']['verified_outcomes']['candidate'] = 1000000
        with self.assertRaises(ValueError):
            validate_replay_receipt(rehash(receipt))

    def test_rehashed_consistent_summary_still_recomputed_from_rows(self):
        receipt = replay(self.rows(), {'candidate_id': 'test'})
        receipt['candidate']['verified_outcomes'] = 1000000
        receipt['comparison']['verified_outcomes']['candidate'] = 1000000
        with self.assertRaises(ValueError):
            validate_replay_receipt(rehash(receipt))

    def test_no_work_rates_unknown_and_opportunities_retained(self):
        receipt = replay(self.rows(), {'candidate_id': 'none', 'include_agents': []})
        self.assertIsNone(receipt['candidate']['deferred_work_rate'])
        self.assertIsNone(receipt['candidate']['inconclusive_rate'])
        self.assertEqual(receipt['opportunity_count'], 3)
        self.assertEqual(receipt['excluded_cycle_count'], 3)
        self.assertEqual(receipt['admission_coverage'], 0)
        self.assertEqual(receipt['exclusion_rate'], 1)

    def test_nonfinite_money_rejected(self):
        for value in (float('inf'), float('nan'), float('-inf'), True):
            with self.subTest(value=value):
                rows = self.rows(); rows[0]['cost_usd'] = value
                with self.assertRaises(ValueError):
                    replay(rows, {'candidate_id': 'test'})

    def test_boolean_counters_rejected(self):
        rows = self.rows(); rows[0]['model_calls'] = True
        with self.assertRaises(ValueError):
            replay(rows, {'candidate_id': 'test'})

    def test_invalid_candidate_filter_types_rejected(self):
        for candidate in ({'include_agents': 'Hunter'}, {'max_planned_api_calls': True}, {'max_estimated_cost_usd': float('inf')}, {'suppress_duplicate_candidates': 'yes'}):
            with self.subTest(candidate=candidate):
                with self.assertRaises(ValueError):
                    replay(self.rows(), {'candidate_id': 'test', **candidate})

    def test_unknown_fields_even_when_rehashed_rejected(self):
        receipt = replay(self.rows(), {'candidate_id': 'test'}); receipt['trusted'] = True
        with self.assertRaises(ValueError):
            validate_replay_receipt(rehash(receipt))

    def test_excluded_incidents_stay_in_historical_record(self):
        rows = self.rows(); rows[0]['authority_violations'] = 1
        receipt = replay(rows, {'candidate_id': 'none', 'include_agents': []})
        self.assertEqual(receipt['historical_authority_violations'], 1)
        self.assertEqual(receipt['unexecuted_alternative_outcomes'], 'UNKNOWN')

    def test_policy_bytes_are_bound_not_only_candidate_name(self):
        receipt = replay(self.rows(), {'candidate_id': 'test'})
        receipt['candidate_policy'] = {'candidate_id': 'test', 'include_agents': []}
        with self.assertRaises(ValueError):
            validate_replay_receipt(rehash(receipt))

    def test_timezone_order_is_chronological_not_lexical(self):
        rows = self.rows()
        rows[0]['started_at'] = '2026-09-20T08:00:00+09:00'
        rows[0]['completed_at'] = '2026-09-20T10:00:00+09:00'
        rows[1]['started_at'] = '2026-09-20T08:00:00+00:00'
        rows[1]['completed_at'] = '2026-09-20T09:00:00+00:00'
        receipt = replay(rows, {'candidate_id': 'test'})
        self.assertEqual([d['cycle_id'] for d in receipt['decisions']], ['1', '2', '3'])

    def test_input_mutation_does_not_mutate_receipt(self):
        rows = self.rows(); candidate = {'candidate_id': 'test'}
        receipt = replay(rows, candidate); before = copy.deepcopy(receipt)
        rows[0]['cost_usd'] = 999; candidate['candidate_id'] = 'other'
        self.assertEqual(receipt, before)
        validate_replay_receipt(receipt)
