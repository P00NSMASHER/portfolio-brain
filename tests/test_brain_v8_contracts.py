"""Catch source substitution, malformed identity and premature release claims."""
import copy
import hashlib
import json
import unittest
from brain.core import BrainError
try:
    from brain.v8.contracts import validate_work, validate_capability, advance, parse_utc
except ImportError:
    validate_work = validate_capability = advance = parse_utc = None

NOW = '2026-10-15T20:00:00Z'
LATER = '2026-10-15T20:01:00Z'


def work(project='abvm', **changes):
    row = dict(schema_version=1, project_id=project,
        repository='P00NSMASHER/abvmschoolstarworld', source_sha='a'*40,
        fingerprint='b'*64, owner='school-owner', resource='c'*64,
        state='OBSERVED', priority_tier=1, evidence_ids=['d'*64], dependencies=[],
        created_at=NOW, updated_at=NOW, attempts=0, blocker=None)
    row.update(changes)
    identity = {k: row[k] for k in ('project_id','repository','source_sha','fingerprint')}
    raw = json.dumps(identity, sort_keys=True, separators=(',',':')).encode()
    row['work_id'] = 'work:' + hashlib.sha256(raw).hexdigest()
    return row


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(callable(validate_work), 'v8 strict work validation is missing')

    def test_work_identity_and_unknown_authority_rejected(self):
        row = work()
        self.assertEqual(validate_work(row), row)
        changed = copy.deepcopy(row)
        changed['source_sha'] = 'f'*40
        with self.assertRaises(BrainError): validate_work(changed)
        with self.assertRaises(BrainError): validate_work(dict(row, auto_approve=True))
        result = validate_work(row)
        result['evidence_ids'].append('e'*64)
        self.assertEqual(row['evidence_ids'], ['d'*64])

    def test_strict_scalars_identity_and_lists(self):
        bad = [('schema_version',True),('priority_tier',True),('attempts',False),
               ('attempts',101),('source_sha','a'*39),('owner','../owner'),
               ('resource','run shell'),('evidence_ids',['d'*64]*2),
               ('dependencies',['work:'+'1'*64]*33),('repository','https://evil/owner/repo')]
        for key,value in bad:
            with self.subTest(key=key,value=value), self.assertRaises(BrainError):
                validate_work(dict(work(), **{key:value}))

    def test_bad_utc_and_chronology(self):
        for value in ['2026-10-15Z',NOW+'junk','2026-10-15T20:00:00+00:00',
                      '2026-02-30T20:00:00Z',True,'2026-10-15T20:00:00.1234567Z']:
            with self.subTest(value=value), self.assertRaises(BrainError): parse_utc(value)
        self.assertEqual(parse_utc(NOW), parse_utc('2026-10-15T20:00:00.000000Z'))
        with self.assertRaises(BrainError): validate_work(work(updated_at='2026-10-14T20:00:00Z'))

    def test_sequential_transition_and_evidence(self):
        row = advance(work(), 'DIAGNOSED', evidence_ids=['e'*64], now=LATER)
        self.assertEqual(row['state'], 'DIAGNOSED')
        self.assertEqual(row['updated_at'], LATER)
        self.assertEqual(work()['state'], 'OBSERVED')
        with self.assertRaises(BrainError): advance(work(),'PATCHED',evidence_ids=['e'*64],now=LATER)
        with self.assertRaises(BrainError): advance(work(),'DIAGNOSED',evidence_ids=[],now=LATER)
        with self.assertRaises(BrainError): advance(work(),'DIAGNOSED',evidence_ids=['e'*64],now='2026-10-14T20:00:00Z')

    def test_green_local_tests_cannot_claim_release(self):
        row = work(state='TESTED')
        for target in ['RELEASED','INDEPENDENTLY_VERIFIED','LIVE_VERIFIED','LEARNED']:
            with self.subTest(target=target), self.assertRaisesRegex(BrainError,'V8_INDEPENDENT_ADAPTER_REQUIRED'):
                advance(row,target,evidence_ids=['e'*64],now=LATER)
        with self.assertRaises(BrainError): advance(work(state='FAILED'),'DIAGNOSED',evidence_ids=['e'*64],now=LATER)

    def test_blocker_is_bounded_and_not_a_command(self):
        with self.assertRaises(BrainError): validate_work(work(state='BLOCKED'))
        with self.assertRaises(BrainError): validate_work(work(blocker={'code':'curl secret'}))
        blocker = dict(code='CAPABILITY_UNAVAILABLE',retry_condition='CAPABILITY_CHANGED',last_operation_id='a'*64)
        self.assertEqual(validate_work(work(state='BLOCKED',blocker=blocker))['blocker'],blocker)

    def test_capability_read_is_not_write(self):
        row = dict(schema_version=1,executor='chat-owner',repository=work()['repository'],
            resource='c'*64,action='READ',status='READ_CONFIRMED',evidence_id='d'*64,
            observed_at=NOW,expires_at=LATER)
        result=validate_capability(row,now=NOW)
        self.assertEqual(result['effective_status'],'READ_CONFIRMED')
        self.assertEqual(validate_capability(row,now=LATER)['effective_status'],'STALE')
        with self.assertRaises(BrainError): validate_capability(dict(row,action='PATCH_BRANCH'),now=NOW)
        with self.assertRaises(BrainError): validate_capability(dict(row,observed_at=LATER),now=NOW)
