import copy
import unittest
from verification.protection import inspect_main_protection


def protection_fixture(repository='owner/brain', main_sha='b'*40):
    """Simulated provider configuration, never real enforcement evidence."""
    rules = [
        {'type': 'deletion'}, {'type': 'non_fast_forward'},
        {'type': 'pull_request', 'parameters': {
            'required_approving_review_count': 0, 'dismiss_stale_reviews_on_push': False,
            'required_review_thread_resolution': True, 'require_code_owner_review': False,
            'require_last_push_approval': False,
        }},
        {'type': 'required_status_checks', 'parameters': {
            'strict_required_status_checks_policy': True,
            'required_status_checks': [
                {'context': 'validate', 'integration_id': 100},
                {'context': 'portfolio-phase1-gate', 'integration_id': 900},
            ],
        }},
    ]
    detail = {'id': 55, 'name': 'test-ruleset', 'source_type': 'Repository',
              'source': repository, 'target': 'branch', 'enforcement': 'active',
              'bypass_actors': [], 'rules': copy.deepcopy(rules)}
    active = [{**copy.deepcopy(row), 'ruleset_id': 55, 'ruleset_source': repository,
               'ruleset_source_type': 'Repository'} for row in rules]
    base = f'https://api.github.com/repos/{repository}'
    return {
        f'{base}/branches/main': {'protected': True, 'commit': {'sha': main_sha}},
        f'{base}/rules/branches/main?per_page=100&page=1': active,
        f'{base}/rulesets/55': detail,
    }


class Phase1ProtectionTests(unittest.TestCase):
    def run_case(self, data, **kwargs):
        return inspect_main_protection('owner/brain', [{'name':'validate','app_id':100}],
                    gate_app_id=kwargs.pop('gate_app_id', 900),
                    get_json=lambda url:copy.deepcopy(data[url]), **kwargs)

    def test_positive_is_only_configuration_not_enforcement(self):
        r=self.run_case(protection_fixture())
        self.assertEqual(r['status'],'CONFIGURATION_OBSERVED')
        self.assertFalse(r['enforcement_tested'])
        self.assertFalse(r['production_accepted'])
        self.assertEqual(r['mutation_capability'],'NONE')

    def test_human_approval_is_not_required_when_app_gate_is_independent(self):
        data=protection_fixture()
        r=self.run_case(data)
        self.assertTrue(r['criteria']['pull_request_required'])
        self.assertNotIn('pull_request_review', r['criteria'])

    def test_nonzero_human_approval_requirement_is_rejected_in_solo_mode(self):
        data=protection_fixture()
        for row in data['https://api.github.com/repos/owner/brain/rules/branches/main?per_page=100&page=1']:
            if row['type']=='pull_request': row['parameters']['required_approving_review_count']=1
        data['https://api.github.com/repos/owner/brain/rulesets/55']['rules'][2]['parameters']['required_approving_review_count']=1
        self.assertIn('pull_request_required', self.run_case(data)['missing'])

    def test_main_unprotected_is_blocked(self):
        data=protection_fixture(); data['https://api.github.com/repos/owner/brain/branches/main']['protected']=False
        self.assertIn('branch_reported_protected',self.run_case(data)['missing'])

    def test_no_effective_rules_is_blocked(self):
        data=protection_fixture(); data['https://api.github.com/repos/owner/brain/rules/branches/main?per_page=100&page=1']=[]
        r=self.run_case(data)
        self.assertEqual(r['status'],'BLOCKED')
        self.assertEqual(r['bypass_visibility'],'UNKNOWN')

    def test_missing_app_never_filled_with_candidate_ci(self):
        r=self.run_case(protection_fixture(),gate_app_id=None)
        self.assertIn('gate_issuer_configured',r['missing'])
        self.assertIn('check:portfolio-phase1-gate',r['missing'])

    def test_omitted_bypass_list_is_unknown_not_empty(self):
        data=protection_fixture(); del data['https://api.github.com/repos/owner/brain/rulesets/55']['bypass_actors']
        r=self.run_case(data)
        self.assertEqual(r['bypass_visibility'],'UNKNOWN')
        self.assertFalse(r['production_accepted'])

    def test_explicit_bypass_is_blocked(self):
        data=protection_fixture(); data['https://api.github.com/repos/owner/brain/rulesets/55']['bypass_actors']=[{'actor_type':'RepositoryRole','actor_id':5,'bypass_mode':'always'}]
        self.assertIn('no_visible_bypass',self.run_case(data)['missing'])

    def test_inactive_ruleset_rejected(self):
        for value in ('evaluate','disabled'):
            data=protection_fixture();data['https://api.github.com/repos/owner/brain/rulesets/55']['enforcement']=value
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,'actively enforced'):
                self.run_case(data)

    def test_inconsistent_effective_rule_and_detail_rejected(self):
        data=protection_fixture();data['https://api.github.com/repos/owner/brain/rulesets/55']['rules'][0]['type']='creation'
        with self.assertRaisesRegex(ValueError,'disagree'):self.run_case(data)

    def test_wrong_source_never_silently_treated_as_repository_rule(self):
        data=protection_fixture();data['https://api.github.com/repos/owner/brain/rules/branches/main?per_page=100&page=1'][0]['ruleset_source']='other/repo'
        with self.assertRaisesRegex(ValueError,'source'):self.run_case(data)

    def test_ambiguous_duplicate_rule_rejected(self):
        data=protection_fixture();rows=data['https://api.github.com/repos/owner/brain/rules/branches/main?per_page=100&page=1'];rows.append(copy.deepcopy(rows[0]))
        with self.assertRaisesRegex(ValueError,'duplicate'):self.run_case(data)

    def test_check_issuer_and_strictness_required(self):
        for field,value in [('integration_id',None),('integration_id',True)]:
            data=protection_fixture()
            for row in data['https://api.github.com/repos/owner/brain/rules/branches/main?per_page=100&page=1']:
                if row['type']=='required_status_checks':row['parameters']['required_status_checks'][0][field]=value
            data['https://api.github.com/repos/owner/brain/rulesets/55']['rules'][-1]['parameters']['required_status_checks'][0][field]=value
            self.assertIn('check:validate',self.run_case(data)['missing'])

    def test_check_without_strict_base_is_blocked(self):
        data=protection_fixture()
        data['https://api.github.com/repos/owner/brain/rules/branches/main?per_page=100&page=1'][-1]['parameters']['strict_required_status_checks_policy']=False
        data['https://api.github.com/repos/owner/brain/rulesets/55']['rules'][-1]['parameters']['strict_required_status_checks_policy']=False
        self.assertIn('check:validate',self.run_case(data)['missing'])

    def test_rules_change_during_observation_rejected(self):
        data=protection_fixture(); count=0
        def api(url):
            nonlocal count
            r=copy.deepcopy(data[url])
            if '/rules/branches/' in url:
                count+=1
                if count>1:r=[]
            return r
        with self.assertRaisesRegex(ValueError,'rules changed'):
            inspect_main_protection('owner/brain',[{'name':'validate','app_id':100}],gate_app_id=900,get_json=api)

    def test_details_change_during_observation_rejected(self):
        data=protection_fixture();count=0
        def api(url):
            nonlocal count
            r=copy.deepcopy(data[url])
            if url.endswith('/rulesets/55'):
                count+=1
                if count>1:r['bypass_actors']=[{'actor_id':5}]
            return r
        with self.assertRaisesRegex(ValueError,'ruleset changed'):
            inspect_main_protection('owner/brain',[{'name':'validate','app_id':100}],gate_app_id=900,get_json=api)

    def test_truncated_effective_rules_fail_closed(self):
        data=protection_fixture(); row=data['https://api.github.com/repos/owner/brain/rules/branches/main?per_page=100&page=1'][0]
        def api(url):
            if '/rules/branches/' in url:return [copy.deepcopy(row)]*100
            return data[url]
        with self.assertRaisesRegex(ValueError,'pagination bound'):
            inspect_main_protection('owner/brain',[{'name':'validate','app_id':100}],gate_app_id=900,get_json=api)

    def test_invalid_repository_rejected_before_read(self):
        with self.assertRaises(ValueError):
            inspect_main_protection('owner/repo/../../secrets',[{'name':'validate','app_id':100}],gate_app_id=900,get_json=lambda _:self.fail('network'))
