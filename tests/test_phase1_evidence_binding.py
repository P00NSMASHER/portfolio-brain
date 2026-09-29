import copy
from datetime import datetime, timedelta, timezone
import unittest

from verification.evidence import EvidenceError, ResolvedEvidence, digest
from policy_replay.policy_backtester import replay
from challenger.champion_challenger import assess_candidate, validate_assessment
from attribution.attribution_engine import allocator_dimensions, build_attribution_snapshot, validate_snapshot
import test_champion_challenger as challenger_fixtures
import test_attribution_engine as attribution_fixtures


class FixtureResolver:
    """Explicit synthetic data: it can never produce production eligibility."""
    def __init__(self, records):
        self.records = records

    def resolve(self, reference):
        if reference not in self.records:
            raise EvidenceError('evidence reference does not resolve')
        return ResolvedEvidence(copy.deepcopy(self.records[reference]), 'SYNTHETIC_FIXTURE', reference)


def bound_fixture():
    d, adapter, r, canary = challenger_fixtures.ChampionChallengerTests().happy_inputs()
    subject = {k: canary[k] for k in ('candidate_id', 'candidate_policy_hash', 'source_revision_sha', 'evaluator_revision_sha')}
    clock = datetime.now(timezone.utc)
    def envelope(kind, measurements):
        return {'schema_version':'1.0.0', 'kind':kind, 'subject':subject,
                'producer_id':'fixture-producer', 'verifier_id':'fixture-independent-verifier',
                'verified_at':(clock-timedelta(seconds=30)).isoformat(),
                'expires_at':(clock+timedelta(hours=1)).isoformat(), 'measurements':measurements}
    fields = ('cycle_id','proposal_id','project_id','source_id','agent_id','estimated_cost_usd','planned_model_calls','planned_api_calls','planned_github_jobs','duplicate_candidate')
    decisions = {c['cycle_id']:{'recorded_at':c['started_at'], 'input_hash':digest({k:c[k] for k in fields})} for c in r['input_cycles']}
    records = {'fixture:replay':envelope('REPLAY_INPUTS', {'cycles':r['input_cycles'], 'candidate_policy':r['candidate_policy'], 'decision_inputs':decisions})}
    m = {k:adapter[k] for k in ('adapter_id','isolated','network_mode','downstream_writes','authority_violations','third_party_code_execution')}
    m.update({'executed':True, 'result':'PASS', 'behavior_checks':{'action_result':True, 'isolation':True}})
    records['test-receipt:A'] = envelope('ADAPTER_RESULT',m)
    for i, reference in enumerate(canary['evidence_refs']):
        records[reference] = envelope('FORWARD_CYCLE', {'cycle_id':f'F{i}', 'executed':True, 'result':'PASS', 'authority_violations':0, 'forbidden_actions_attempted':0, 'active_policy_changed':False, 'checks':{'behavior_result':True, 'replay_binding':True, 'policy_unchanged':True}})
    inputs = dict(discovery=d, rights_record=challenger_fixtures.permissive_rights(d), adapter_receipt=adapter, replay_receipt=r, forward_canary_receipt=canary)
    return inputs, FixtureResolver(records)


def rehash(receipt, key):
    receipt[key] = digest({k:v for k,v in receipt.items() if k != key})


class Phase1EvidenceBindingTests(unittest.TestCase):
    def test_source_bound_synthetic_positive_is_not_production_review(self):
        inputs, resolver = bound_fixture()
        result = assess_candidate(**inputs, resolver=resolver)
        validate_assessment(result, resolver=resolver)
        self.assertTrue(result['technical_checks_pass'])
        self.assertEqual(result['evidence_scope'],'SYNTHETIC_FIXTURE')
        self.assertFalse(result['eligible_for_human_promotion_review'])
        self.assertFalse(result['automatic_promotion_allowed'])
        self.assertFalse(result['forward_performance_improvement_established'])

    def test_source_bound_fixture_cannot_validate_without_resolver(self):
        inputs, resolver = bound_fixture()
        result = assess_candidate(**inputs, resolver=resolver)
        with self.assertRaises(ValueError):
            validate_assessment(result)

    def test_adapter_helper_only_prepares_a_claim(self):
        inputs, _ = bound_fixture()
        self.assertEqual(inputs['adapter_receipt']['status'],'CLAIM_ONLY')
        self.assertEqual(inputs['forward_canary_receipt']['status'],'CLAIM_ONLY')
        self.assertFalse(assess_candidate(**inputs)['eligible_for_human_promotion_review'])

    def test_cross_candidate_replay_rejected(self):
        inputs, resolver = bound_fixture()
        r = inputs['replay_receipt']; policy=copy.deepcopy(r['candidate_policy']);policy['candidate_id']='another-candidate'
        inputs['replay_receipt']=replay(r['input_cycles'],policy,provenance=r['provenance'])
        with self.assertRaises(ValueError):
            assess_candidate(**inputs,resolver=resolver)

    def test_changed_policy_same_candidate_rejected(self):
        inputs, resolver=bound_fixture();r=inputs['replay_receipt'];p=copy.deepcopy(r['candidate_policy']);p['max_estimated_cost_usd']=3.0
        inputs['replay_receipt']=replay(r['input_cycles'],p,provenance=r['provenance'])
        with self.assertRaises(ValueError):
            assess_candidate(**inputs,resolver=resolver)

    def test_fabricated_reference_rejected(self):
        inputs,resolver=bound_fixture(); del resolver.records['test-receipt:A']
        with self.assertRaises(ValueError):
            assess_candidate(**inputs,resolver=resolver)

    def test_self_hashed_pass_is_not_execution_evidence(self):
        inputs,resolver=bound_fixture();a=inputs['adapter_receipt'];a['status']='PASS';rehash(a,'adapter_hash')
        with self.assertRaises(ValueError):
            assess_candidate(**inputs,resolver=resolver)

    def test_adapter_requires_observed_action_result(self):
        inputs,resolver=bound_fixture();resolver.records['test-receipt:A']['measurements']['behavior_checks']['action_result']=False
        with self.assertRaises(ValueError):
            assess_candidate(**inputs,resolver=resolver)

    def test_duplicate_canary_cycle_not_counted_twice(self):
        inputs,resolver=bound_fixture();resolver.records['canary:C2']['measurements']['cycle_id']='F0'
        with self.assertRaises(ValueError):
            assess_candidate(**inputs,resolver=resolver)

    def test_cycle_count_without_measurements_rejected(self):
        inputs,resolver=bound_fixture();c=inputs['forward_canary_receipt'];c['observed_cycles']=30;rehash(c,'canary_hash')
        with self.assertRaises(ValueError):
            assess_candidate(**inputs,resolver=resolver)

    def test_expired_and_future_evidence_rejected(self):
        for key,value in [('expires_at','2000-01-01T00:00:00Z'),('verified_at','2099-01-01T00:00:00Z')]:
            with self.subTest(key=key):
                inputs,resolver=bound_fixture();resolver.records['canary:C1'][key]=value
                with self.assertRaises(ValueError):
                    assess_candidate(**inputs,resolver=resolver)

    def test_same_producer_verifier_principal_rejected(self):
        inputs,resolver=bound_fixture();r=resolver.records['test-receipt:A'];r['verifier_id']=r['producer_id']
        with self.assertRaises(ValueError):
            assess_candidate(**inputs,resolver=resolver)

    def test_wrong_source_revision_rejected(self):
        inputs,resolver=bound_fixture();resolver.records['test-receipt:A']['subject']=dict(resolver.records['test-receipt:A']['subject'],source_revision_sha='f'*40)
        with self.assertRaises(ValueError):
            assess_candidate(**inputs,resolver=resolver)

    def test_post_execution_decision_inputs_rejected(self):
        inputs,resolver=bound_fixture();resolver.records['fixture:replay']['measurements']['decision_inputs']['1']['recorded_at']='2026-09-25T12:00:00Z'
        with self.assertRaises(ValueError):
            assess_candidate(**inputs,resolver=resolver)

    def test_source_rows_not_replaced_by_rehashed_claim(self):
        inputs,resolver=bound_fixture();resolver.records['fixture:replay']['measurements']['cycles']=copy.deepcopy(inputs['replay_receipt']['input_cycles']);resolver.records['fixture:replay']['measurements']['cycles'][0]['cost_usd']=99
        with self.assertRaises(ValueError):
            assess_candidate(**inputs,resolver=resolver)

    def test_rehashed_eligible_assessment_rejected(self):
        inputs,resolver=bound_fixture();r=assess_candidate(**inputs,resolver=resolver);r['eligible_for_human_promotion_review']=True;r['decision']='ELIGIBLE_FOR_HUMAN_PROMOTION_REVIEW';rehash(r,'assessment_hash')
        with self.assertRaises(ValueError):
            validate_assessment(r,resolver=resolver)

    def test_attribution_allocator_rejects_unresolved_input(self):
        r=build_attribution_snapshot(attribution_fixtures.AttributionEngineTests().fixture())
        with self.assertRaises(ValueError):
            allocator_dimensions(r)

    def test_rehashed_attribution_inflation_rejected(self):
        r=build_attribution_snapshot(attribution_fixtures.AttributionEngineTests().fixture());r['global_profile']['verified_outcomes']=999;rehash(r,'attribution_hash')
        with self.assertRaises(ValueError):
            validate_snapshot(r)
        with self.assertRaises(ValueError):
            allocator_dimensions(r)

    def test_attribution_boolean_money_rejected(self):
        rows=attribution_fixtures.AttributionEngineTests().fixture();rows[0]['cost_usd']=True
        with self.assertRaises(ValueError):
            build_attribution_snapshot(rows)
