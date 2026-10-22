"""Hostile publication evidence. Fixtures are synthetic, never deployment proof."""
from __future__ import annotations
import base64
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from brain.v9.batch_queue import BatchFault
from brain.v9 import publication_reader as module
from brain.v9.clipboard_recipe import prepare

CANDIDATE = 'a'*40
MERGE = 'b'*40
ORIGINAL = 'c'*40
RAW = b'synthetic corrected browser asset'
HASH = hashlib.sha256(RAW).hexdigest()
REPO = module.REPO

def specification():
    return dict(schema_version=1, repository=REPO, source_branch='gh-pages', path=module.ASSET,
        original_source_sha=ORIGINAL, original_asset_sha256=module.ORIGINAL_HASH,
        candidate_sha=CANDIDATE, pr_number=75, expected_asset_sha256=HASH,
        fingerprint='d'*64, recipe='CAPTUREBRIEF_CLIPBOARD_RECOVERY_V1', public_url=module.LIVE)

def provider_documents():
    checks = [dict(name=name, head_sha=CANDIDATE, status='completed', conclusion='success', app={'id':15368})
              for name in sorted(module.REQUIRED_JOBS)]
    steps = [dict(name=name, status='completed', conclusion='success') for name in
             (module.LIVE_STEP, 'Wait for GitHub Pages to publish this exact release', 'Verify the public deployment')]
    jobs = [dict(name=name, head_sha=MERGE, status='completed', conclusion='success', steps=deepcopy(steps))
            for name in sorted(module.REQUIRED_JOBS)]
    common = dict(head_sha=MERGE, head_branch='gh-pages', repository={'full_name':REPO},
                  status='completed', conclusion='success')
    runs = [dict(common, id=11, name='Website quality', event='push', path='.github/workflows/site-quality.yml'),
            dict(common, id=12, name='pages build and deployment', event='dynamic', path='dynamic/pages/pages-build-deployment')]
    return {
        'pulls/75': dict(number=75, merged=True, state='closed', merge_commit_sha=MERGE,
            head={'sha':CANDIDATE,'repo':{'full_name':REPO}},
            base={'ref':'gh-pages','repo':{'full_name':REPO}}),
        'commits/'+CANDIDATE+'/check-runs?per_page=100': dict(total_count=2,check_runs=checks),
        'branches/gh-pages': {'commit':{'sha':MERGE}},
        'actions/runs?head_sha='+MERGE+'&per_page=100': dict(total_count=2,workflow_runs=runs),
        'actions/runs/11/jobs?per_page=100': dict(total_count=2,jobs=jobs),
        'contents/'+module.ASSET+'?ref='+MERGE: dict(type='file', encoding='base64', size=len(RAW),
            content=base64.b64encode(RAW).decode())}

class PublicationReaderTests(unittest.TestCase):
    def verify(self, documents=None, live=RAW, drift=False):
        docs = provider_documents() if documents is None else documents
        reader = module.PublicationReader(max_gets=10)
        reads = []
        def get(route):
            reader.used_gets += 1
            reads.append(route)
            if drift and route == 'branches/gh-pages' and reads.count(route) > 1:
                return {'commit': {'sha':'f'*40}}
            return deepcopy(docs[route])
        def body(url, *, authenticated, maximum):
            self.assertFalse(authenticated, 'Never forward API credentials to the live website')
            self.assertEqual(url, module.LIVE+'?brain-repair='+MERGE)
            reader.used_gets += 1
            return live
        with patch.object(module, 'CORRECTED_HASH', HASH), patch.object(reader, '_get', side_effect=get), patch.object(reader, '_bytes', side_effect=body):
            return reader.verify(specification())
    def test_source_issuer_deploy_live_bytes_and_step_proof_agree(self):
        result = self.verify()
        self.assertEqual(result['status'], 'ORIGINAL_PUBLISHED_REPAIR_LIVE_VERIFIED')
        self.assertEqual(result['deployed_sha'], MERGE)
        self.assertEqual(result['provider_gets'], 8)
        self.assertFalse(result['production_accepted'])
        self.assertFalse(result['six_hour_acceptance_passed'])
    def test_changed_candidate_and_wrong_check_publisher_are_refused(self):
        for attack in ('candidate','issuer','pending','missing','duplicate'):
            docs = provider_documents()
            checks = docs['commits/'+CANDIDATE+'/check-runs?per_page=100']
            if attack == 'candidate': docs['pulls/75']['head']['sha'] = ORIGINAL
            if attack == 'issuer': checks['check_runs'][0]['app']['id'] = 123
            if attack == 'pending': checks['check_runs'][0]['status'] = 'in_progress'
            if attack == 'missing': checks['check_runs'].pop()
            if attack == 'duplicate':
                checks['check_runs'].append(deepcopy(checks['check_runs'][0]));checks['total_count']=3
            with self.subTest(attack=attack), self.assertRaises(BatchFault):
                self.verify(docs)
    def test_live_step_skip_and_failed_newer_deployment_are_refused(self):
        for attack in ('skip','different_source','failed_newest','truncated'):
            docs = provider_documents()
            if attack == 'skip': docs['actions/runs/11/jobs?per_page=100']['jobs'][0]['steps'][0]['conclusion']='skipped'
            if attack == 'different_source': docs['actions/runs/11/jobs?per_page=100']['jobs'][1]['head_sha']=ORIGINAL
            run_page = docs['actions/runs?head_sha='+MERGE+'&per_page=100']
            if attack == 'failed_newest':
                failed = dict(run_page['workflow_runs'][0],id=13,conclusion='failure')
                run_page['workflow_runs'].append(failed);run_page['total_count']=3
            if attack == 'truncated': run_page['total_count']=101
            with self.subTest(attack=attack), self.assertRaises(BatchFault):
                self.verify(docs)
    def test_live_byte_mismatch_and_branch_race_are_refused(self):
        with self.assertRaisesRegex(BatchFault, 'PUBLICATION_LIVE_BYTES_MISMATCH'):
            self.verify(live=b'old asset')
        with self.assertRaisesRegex(BatchFault, 'PUBLICATION_SOURCE_MOVED'):
            self.verify(drift=True)
    def test_spec_cannot_expand_host_repository_or_paths(self):
        with patch.object(module, 'CORRECTED_HASH', HASH):
            for key, value in (('public_url','https://example.org/'),('repository','unknown/repo'),
                               ('path','../secrets'),('pr_number',True),('candidate_sha','short')):
                spec=specification();spec[key]=value
                with self.subTest(key=key),self.assertRaises(BatchFault):
                    module.validate_spec(spec)
    def test_route_and_budget_fail_before_network(self):
        reader=module.PublicationReader(max_gets=1)
        with self.assertRaisesRegex(BatchFault, 'PUBLICATION_ROUTE_REFUSED'):
            reader._get('secrets')
        with patch.object(module, 'CORRECTED_HASH', HASH),self.assertRaisesRegex(BatchFault, 'READBACK_BUDGET_EXHAUSTED'):
            reader.verify(specification())
        self.assertEqual(reader.used_gets,0)
    def test_recipe_refuses_unreviewed_or_reapplied_bytes(self):
        for source in (b'anything else', b'', 'not bytes'):
            with self.assertRaisesRegex(ValueError,'CLIPBOARD_ORIGINAL_SOURCE_NOT_REVIEWED'):
                prepare(source)

if __name__=='__main__':
    unittest.main()
