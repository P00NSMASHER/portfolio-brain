import unittest
from datetime import datetime, timezone, timedelta
from brain.clock import validate

class ClockTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 8, 1, 30, tzinfo=timezone.utc)
        self.sha = 'a' * 40
        self.receipt = dict(schema_version=1, source_sha=self.sha, issued_at=self.now.isoformat(), slot='20261008T01', producer='6ac323fee9c88191bd31e9d4cfc554f8', kind='scheduled')
    def test_valid_clock_and_manual_provenance(self):
        self.assertEqual(validate(self.receipt,self.sha,self.now)['kind'],'scheduled')
        self.receipt['kind']='manual_probe'
        self.assertEqual(validate(self.receipt,self.sha,self.now)['kind'],'manual_probe')
    def test_stale_future_and_naive_time(self):
        for timestamp in [self.now-timedelta(seconds=1201),self.now+timedelta(seconds=1),self.now.replace(tzinfo=None)]:
            with self.subTest(timestamp=timestamp), self.assertRaises(ValueError):
                validate(dict(self.receipt,issued_at=timestamp.isoformat()),self.sha,self.now)
    def test_drift_wrong_slot_unknown_producer_and_extra_fields(self):
        for change in [{'source_sha':'b'*40},{'slot':'20261008T02'},{'producer':'unknown'},{'kind':'fake_success'},{'unexpected':True}]:
            with self.subTest(change=change),self.assertRaises(ValueError):
                validate(dict(self.receipt,**change),self.sha,self.now)
