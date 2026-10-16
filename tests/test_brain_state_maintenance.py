import hashlib
from pathlib import Path
import sqlite3
import tempfile
import unittest
from brain.core import BrainError, digest
from brain.state_maintenance import compact_snapshot
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
