"""A complete core keeps only one durable PASS report while retaining all sources."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from brain.core import Store, BrainError
from brain.__main__ import monitor, research, experiment, doctor
from tests.test_brain_v2 import SHA, payload, NOW, REPOSITORY
from brain.adapters import event


class OneCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root=Path(self.folder.name)
        self.store=Store(self.root/"state.sqlite",visibility="PUBLIC")
        self.addCleanup(self.store.close)

    def reports(self):
        return self.store.db.execute("SELECT count(*) FROM reports").fetchone()[0]

    def test_full_cycle_retains_final_verifiable_report_and_original_artifacts(self):
        class API:
            requests=1
            def observe(self, repo):
                return payload(repo),False
            def discover(self,target,repository=None):
                return []
        api=API()
        monitor(self.store,SHA,self.root/"monitor",api=api)
        self.assertEqual(self.reports(),0)
        with self.assertRaisesRegex(BrainError,"MISSING_REPORT"):
            self.store.read_report(SHA)
        research(self.store,SHA,self.root/"research",api=api)
        self.assertEqual(self.reports(),0)
        result=experiment(self.store,SHA,self.root/"experiment")
        self.assertEqual(result["status"],"PASS")
        self.assertEqual(self.reports(),1)
        self.assertEqual(doctor(self.store,SHA,self.root/"doctor")["status"],"PASS")
        self.assertEqual(self.store.pending(),0)
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM attempts").fetchone()[0],3)
        event_count=self.store.db.execute("SELECT count(*) FROM events").fetchone()[0]
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM ledger").fetchone()[0],
                         event_count)
        for operation in ("monitor","research","experiment"):
            with self.subTest(operation=operation):
                body=json.loads((self.root/operation/"report.json").read_text())
                self.assertEqual(body["source_sha"],SHA)
                self.assertTrue((self.root/operation/"report.html").exists())
        self.assertEqual(self.store.read_report(SHA)["canonical_hash"],
                         result["canonical_hash"])

    def test_adverse_derived_report_is_persisted_even_in_preview(self):
        item=event("repository",REPOSITORY,payload(),SHA,now=NOW)
        self.store.submit([item],now=NOW)
        self.store.drain()
        report=self.store.report(SHA,now="2026-10-10T21:00:00Z",persist=False)
        self.assertNotEqual(report["status"],"PASS")
        self.assertEqual(self.reports(),1)

    def test_failed_monitor_preserves_failure_attempt_and_report(self):
        class API:
            requests=2
            def observe(self,repo):
                if repo.endswith("bad"):
                    raise BrainError("SOURCE_API_503")
                return payload(repo),False
        with self.assertRaisesRegex(BrainError,"MONITOR_INCOMPLETE"):
            monitor(self.store,SHA,self.root/"failed",
                    api=API(),repositories=["example/good","example/bad"])
        self.assertEqual(self.reports(),1)
        self.assertEqual(self.store.pending(),0)
        row=self.store.db.execute("SELECT status FROM attempts WHERE operation='monitor'").fetchone()
        self.assertEqual(row[0],"FAIL")
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM ledger").fetchone()[0],1)

    def test_invalid_persistence_flag_denied_without_state_mutation(self):
        item=event("repository",REPOSITORY,payload(),SHA,now=NOW)
        self.store.submit([item],now=NOW)
        self.store.drain()
        before=self.store.db.execute("SELECT count(*) FROM events").fetchone()[0]
        with self.assertRaisesRegex(BrainError,"report persist flag invalid"):
            self.store.report(SHA,now=NOW,persist=1)
        self.assertEqual(self.reports(),0)
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM events").fetchone()[0],before)


if __name__=="__main__":
    unittest.main()
