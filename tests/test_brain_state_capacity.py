"""Capacity expansion retains bounded, independent verification."""
import copy
import unittest
from soak_v3 import chunked_evidence as audit
from soak_v3.audit import EvidenceError, verify_sqlite
from tests import test_brain_soak_v3 as fixture_module

class CapacityTests(unittest.TestCase):
    def test_five_gib_manifest_and_overflow(self):
        size=5*1024*1024*1024
        part=dict(raw_size=8*1024*1024,raw_sha256='a'*64,size=8*1024*1024+3000,sha256='b'*64)
        doc=dict(schema_version=1,format=audit.FORMAT,raw_size=size,
                 raw_sha256='c'*64,compressed_size=640*(8*1024*1024+3000),
                 compressed_sha256='d'*64,chunks=[dict(part,name=f'part-{i:06d}.z') for i in range(640)])
        self.assertEqual(audit._manifest(doc)['raw_size'],size)
        bad=copy.deepcopy(doc);bad['raw_size']+=1
        with self.assertRaisesRegex(EvidenceError,'STATE_MANIFEST_RAW_BOUND'): audit._manifest(bad)

    def test_sqlite_replay_can_explicitly_use_five_gib_bound(self):
        fixture=fixture_module.StateTests();fixture.setUp()
        try:
            self.assertEqual(verify_sqlite(fixture.path,expected_sequence=1,
                expected_chain=fixture.chain,expected_source=fixture_module.SHA,
                max_bytes=5*1024*1024*1024)['status'],'PASS')
        finally: fixture.doCleanups()
