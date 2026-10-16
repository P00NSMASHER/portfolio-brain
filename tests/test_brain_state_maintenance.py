import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from brain.core import BrainError, digest
from brain.state_maintenance import (compact_snapshot,
    main as maintenance_main,maintain_within_verified_capacity,
    storage_pressure,validate_publication_receipt)
from tests import test_brain_soak_v3 as fixture_module

class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixture_module.StateTests();self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.source=self.fixture.path;self.target=self.source.with_name('compacted.sqlite')
        with sqlite3.connect(self.source) as db:
            for i in range(2,12):
                report=dict(status='FAIL' if i==3 else 'PASS',padding='x'*10000)
                db.execute('INSERT INTO reports VALUES(?,?,?,?,?,?,?)',(i,1,self.fixture.chain,'b'*40 if i==2 else fixture_module.SHA,'2026-10-08T02:00:00Z',__import__('json').dumps(report),digest(report)))
        self.original=hashlib.sha256(self.source.read_bytes()).hexdigest()
    def test_compaction_preserves_latest_per_source_failure_and_canonical_history(self):
        result=compact_snapshot(self.source,self.target,keep_recent=2)
        self.assertEqual(result['kept_reports'],4)
        self.assertLess(result['target_bytes'],result['source_bytes'])
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(),self.original)
        with sqlite3.connect(self.target) as db:
            self.assertEqual([r[0] for r in db.execute('SELECT id FROM reports ORDER BY id')],[2,3,10,11])
            self.assertEqual(db.execute('SELECT count(*) FROM events').fetchone()[0],1)
    def test_existing_destination_is_never_overwritten(self):
        self.target.write_text('keep')
        with self.assertRaises(BrainError):compact_snapshot(self.source,self.target)
        self.assertEqual(self.target.read_text(),'keep')
    def test_corrupt_report_refused_without_creating_destination(self):
        with sqlite3.connect(self.source) as db:db.execute("UPDATE reports SET hash='bad' WHERE id=2")
        with self.assertRaises(BrainError):compact_snapshot(self.source,self.target)
        self.assertFalse(self.target.exists())
    def test_live_wal_snapshot_refused(self):
        Path(str(self.source)+'-wal').touch()
        with self.assertRaises(BrainError):compact_snapshot(self.source,self.target)
        self.assertFalse(self.target.exists())

    def test_trigger_cannot_silently_alter_retained_report(self):
        with sqlite3.connect(self.source) as db:
            db.execute("CREATE TRIGGER change_report AFTER DELETE ON reports BEGIN UPDATE reports SET body='{}' WHERE id=11; END")
        with self.assertRaises(BrainError): compact_snapshot(self.source,self.target,keep_recent=2)
        self.assertFalse(self.target.exists())

    def test_working_copy_is_atomically_compacted_inside_verified_capacity(self):
        before=self.source.stat().st_size
        result=maintain_within_verified_capacity(
            self.source,trigger_bytes=1,verified_raw_bytes=before,keep_recent=2)
        self.assertEqual(result['status'],'COMPACTED_TO_VERIFIED_PRODUCTION_CAPACITY')
        self.assertTrue(result['compacted'])
        self.assertLess(self.source.stat().st_size,before)
        with sqlite3.connect(self.source) as db:
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone(),('ok',))
            self.assertEqual(db.execute('SELECT count(*) FROM events').fetchone()[0],1)

    def test_working_copy_below_trigger_is_unchanged(self):
        result=maintain_within_verified_capacity(
            self.source,trigger_bytes=self.source.stat().st_size,
            verified_raw_bytes=self.source.stat().st_size+1)
        self.assertEqual(result['status'],'WITHIN_VERIFIED_PRODUCTION_CAPACITY')
        self.assertFalse(result['compacted'])
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(),self.original)

    def test_packed_pressure_compacts_before_raw_trigger(self):
        with patch('brain.state_maintenance.COMPACTION_TRIGGER_COMPRESSED_BYTES',1):
            result=maintain_within_verified_capacity(self.source,keep_recent=2)
        self.assertEqual(result['compaction_reasons'],['COMPRESSED_SIZE'])
        self.assertLess(result['target_bytes'],result['source_bytes'])

    def test_report_growth_compacts_before_size_triggers(self):
        with patch('brain.state_maintenance.COMPACTION_TRIGGER_REPORTS',10):
            result=maintain_within_verified_capacity(self.source,keep_recent=2)
        self.assertEqual(result['compaction_reasons'],['REPORT_COUNT'])
        self.assertEqual(result['storage_pressure']['reports'],4)

    def test_packed_capacity_failure_preserves_original(self):
        with patch('brain.state_maintenance.COMPACTION_TRIGGER_COMPRESSED_BYTES',1), \
             patch('brain.state_maintenance.VERIFIED_PRODUCTION_COMPRESSED_BYTES',1):
            with self.assertRaisesRegex(BrainError,'exceeds verified compressed capacity'):
                maintain_within_verified_capacity(self.source,keep_recent=2)
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(),self.original)
        self.assertEqual(list(self.source.parent.glob('.capacity-*.sqlite')),[])

    def test_pressure_matches_actual_production_codec(self):
        from brain.state_archive import pack
        pressure=storage_pressure(self.source)
        root=self.source.parent/'archive';root.mkdir()
        (root/'state.sqlite').write_bytes(self.source.read_bytes())
        receipt=pack(root)
        self.assertEqual(pressure['raw_bytes'],receipt['raw_size'])
        self.assertEqual(pressure['compressed_bytes'],receipt['compressed_size'])

    def test_pressure_refuses_live_journal_even_below_trigger(self):
        Path(str(self.source)+'-journal').touch()
        with self.assertRaises(BrainError): maintain_within_verified_capacity(self.source)

    def test_unachievable_capacity_leaves_source_untouched(self):
        before=self.source.read_bytes()
        with self.assertRaisesRegex(BrainError,'exceeds verified production capacity'):
            maintain_within_verified_capacity(
                self.source,trigger_bytes=1,verified_raw_bytes=2)
        self.assertEqual(self.source.read_bytes(),before)
        self.assertEqual(list(self.source.parent.glob('.capacity-*.sqlite')),[])

    def test_packed_publication_must_fit_both_verified_bounds(self):
        valid=dict(raw_size=100,compressed_size=50,chunks=1,published=False)
        self.assertEqual(validate_publication_receipt(valid)['status'],
                         'VERIFIED_PRODUCTION_CAPACITY_ENVELOPE_PASS')
        for field,value in (('raw_size',120_512_513),
                            ('compressed_size',20_602_942),('chunks',False)):
            with self.subTest(field=field),self.assertRaises(BrainError):
                validate_publication_receipt(dict(valid,**{field:value}))

    def test_capacity_cli_writes_new_auditable_receipt(self):
        receipt=self.source.with_name('capacity-receipt.json')
        maintenance_main(['--source',str(self.source),'--apply-capacity-bound',
                          '--receipt',str(receipt)])
        body=json.loads(receipt.read_text())
        self.assertEqual(body['status'],'WITHIN_VERIFIED_PRODUCTION_CAPACITY')
        self.assertFalse(body['published'])
        with self.assertRaises(BrainError):
            maintenance_main(['--source',str(self.source),'--apply-capacity-bound',
                              '--receipt',str(receipt)])
