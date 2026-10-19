"""Adversarial injected-provider unit tests; not live execution evidence."""
import base64
import copy
import hashlib
import json
import unittest
from unittest.mock import Mock
from brain.core import BrainError, digest
from brain.v9.reconciliation import observe_draft, validate_intent

REPO = 'Owner/project'
BASE, HEAD, TREE = 'a'*40, 'b'*40, 'c'*40
RAW = b'hello\n'
BLOB = hashlib.sha1(b'blob 6\0' + RAW).hexdigest()
NOW = '2026-10-18T08:00:00Z'


class DraftReconciliationTests(unittest.TestCase):
    def intent(self):
        return dict(schema_version=1, repository=REPO, base_sha=BASE, head_sha=HEAD,
                    pull_number=42, actor_login='repair[bot]', expected_files={'README.md': BLOB})

    def responses(self):
        metadata = dict(full_name=REPO, default_branch='main', permissions={'pull': True})
        ref = dict(ref='refs/heads/main', object={'type': 'commit', 'sha': BASE})
        pr = dict(number=42, state='open', draft=True, merged=False, merged_at=None,
                  user={'login': 'repair[bot]'}, head=dict(sha=HEAD, ref='repair', repo={'full_name': REPO}),
                  base=dict(sha=BASE, ref='main', repo={'full_name': REPO}))
        candidate = dict(ref='refs/heads/repair', object={'type': 'commit', 'sha': HEAD})
        return [metadata, ref, pr, candidate,
                dict(sha=HEAD, parents=[{'sha': BASE}], tree={'sha': TREE}),
                dict(ahead_by=1, behind_by=0, merge_base_commit={'sha': BASE},
                     files=[dict(filename='README.md', status='modified', sha=BLOB)]),
                dict(sha=TREE, truncated=False, tree=[dict(path='README.md', type='blob', mode='100644', sha=BLOB)]),
                dict(type='file', path='README.md', sha=BLOB, encoding='base64', size=len(RAW), content=base64.b64encode(RAW).decode()),
                copy.deepcopy(pr), copy.deepcopy(candidate), copy.deepcopy(ref), copy.deepcopy(metadata)]

    def run_fake(self, responses=None):
        records = iter(self.responses() if responses is None else responses)
        calls = []
        def transport(path, token):
            calls.append(path)
            value = next(records)
            if isinstance(value, Exception):
                raise value
            return value if type(value) is bytes else json.dumps(value).encode()
        result = observe_draft(self.intent(), token='test-token', now=NOW, transport=transport)
        return result, calls

    def test_exact_draft_receipt_is_sanitized_and_has_no_authority(self):
        result, calls = self.run_fake()
        self.assertEqual(result['intent_digest'], digest(self.intent()))
        self.assertEqual(result['outcome'], 'EXACT_DRAFT_OBSERVED')
        self.assertEqual(result['evidence_kind'], 'INJECTED_TRANSPORT_OBSERVATION')
        for key in ('write_authority', 'independent_acceptance', 'production_accepted', 'release_authority'):
            self.assertIs(result[key], False)
        self.assertNotIn('test-token', json.dumps(result))
        self.assertNotIn('hello', json.dumps(result))
        self.assertEqual(len(calls), 12)
        self.assertIn('?ref=' + HEAD, calls[7])
        for status in ('added', 'modified'):
            responses = self.responses()
            responses[5]['files'][0]['status'] = status
            self.run_fake(responses)

    def test_validation_before_transport_and_copy(self):
        intent = self.intent()
        copied = validate_intent(intent)
        copied['expected_files']['README.md'] = BASE
        self.assertEqual(intent['expected_files']['README.md'], BLOB)
        for key, value in [('schema_version', True), ('pull_number', True), ('pull_number', 0),
                           ('repository', 'https://evil.test'), ('actor_login', 'x/y'),
                           ('head_sha', BASE), ('base_sha', 'x'*40), ('expected_files', {}),
                           ('expected_files', {'../secret': BLOB}), ('expected_files', {'a\\b': BLOB}),
                           ('expected_files', {str(i): BLOB for i in range(17)}), ('extra', 1)]:
            bad = self.intent(); bad[key] = value
            transport = Mock()
            with self.subTest(key=key, value=value), self.assertRaises((BrainError, ValueError)):
                observe_draft(bad, token='test-token', now=NOW, transport=transport)
            transport.assert_not_called()

    def test_identity_ancestry_change_and_source_drift_fail_closed(self):
        cases = [(3, ('object', 'sha'), BASE), (9, ('object', 'sha'), BASE),
                 (11, ('permissions', 'pull'), False), (0, ('permissions', 'pull'), 1), (0, ('full_name',), 'other/repo'),
                 (1, ('object', 'sha'), HEAD), (10, ('object', 'sha'), HEAD),
                 (11, ('default_branch',), 'other'), (2, ('user', 'login'), 'attacker'),
                 (2, ('number',), True), (2, ('draft',), False), (2, ('merged',), True),
                 (2, ('state',), 'closed'), (8, ('draft',), False), (8, ('head', 'ref'), 'changed'),
                 (2, ('base', 'repo', 'full_name'), 'fork/repo'), (2, ('head', 'repo', 'full_name'), 'fork/repo'),
                 (2, ('base', 'ref'), 'other'), (2, ('head', 'sha'), BASE),
                 (4, ('parents',), []), (4, ('parents',), [{'sha': BASE}, {'sha': HEAD}]),
                 (4, ('parents',), [{'sha': HEAD}]), (5, ('ahead_by',), True),
                 (5, ('ahead_by',), 2), (5, ('behind_by',), 1),
                 (5, ('merge_base_commit', 'sha'), HEAD), (5, ('files',), []),
                 (6, ('truncated',), True), (7, ('size',), True), (7, ('content',), 'AAAA'),
                 (7, ('target',), 'elsewhere'), (7, ('submodule_git_url',), 'https://evil'),
                 (7, ('encoding',), 'none'), (7, ('sha',), BASE)]
        for index, keys, value in cases:
            rows = self.responses(); target = rows[index]
            for key in keys[:-1]: target = target[key]
            target[keys[-1]] = value
            with self.subTest(index=index, keys=keys), self.assertRaises((BrainError, ValueError)):
                self.run_fake(rows)

    def test_unapproved_files_and_special_tree_modes_rejected(self):
        for key, value in [('status', 'removed'), ('status', 'renamed'), ('previous_filename', 'old'),
                           ('filename', 'other'), ('sha', BASE)]:
            rows = self.responses(); rows[5]['files'][0][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(BrainError): self.run_fake(rows)
        for mode in ('120000', '160000', '040000'):
            rows = self.responses(); rows[6]['tree'][0]['mode'] = mode
            with self.subTest(mode=mode), self.assertRaises(BrainError): self.run_fake(rows)
        for index, key in [(5, 'files'), (6, 'tree')]:
            rows = self.responses(); rows[index][key] *= 2
            with self.assertRaises(BrainError): self.run_fake(rows)

    def test_uncertain_and_malformed_responses_never_prove_absence(self):
        for value in (OSError('unavailable'), ValueError('404'), b'{"a":1,"a":2}', b'[]', b'NaN', b'\xff'):
            with self.subTest(value=value), self.assertRaises((BrainError, ValueError, OSError)):
                self.run_fake([value])


if __name__ == '__main__':
    unittest.main()
