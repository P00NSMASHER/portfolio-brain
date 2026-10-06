"""Fixed-clock scheduling cannot manufacture native delivery or slide the hour."""
import unittest
from datetime import datetime,timedelta,timezone
from acceptance.step23_delivery_qualification import REQUIRED,pin_requested_start

START=datetime(2026,10,6,3,15,tzinfo=timezone.utc)
HORIZON=datetime(2026,10,6,4,tzinfo=timezone.utc)
REQUEST='2026-10-06T03:15:00Z'

def result():
    return dict(status='QUALIFIED',qualified=True,exact_main_sha='a'*40,
                baseline='2026-10-06T02:40:00Z',missing_workflows=[],
                soak_start='2026-10-06T03:30:00Z',soak_deadline='2026-10-06T04:30:00Z',
                selected={name:dict(run_id=i+1,created_at='2026-10-06T02:45:00Z',
                          completed_at='2026-10-06T02:50:00Z') for i,name in enumerate(REQUIRED)})

class FixedStartTests(unittest.TestCase):
    def test_fixed_start_and_deadline(self):
        got=pin_requested_start(result(),REQUEST,HORIZON,START)
        self.assertTrue(got['qualified'])
        self.assertEqual(got['soak_start'],REQUEST)
        self.assertEqual(got['soak_deadline'],'2026-10-06T04:15:00Z')
        self.assertFalse(got['acceptance_complete'])
    def test_missing_readiness_blocks_not_reschedules(self):
        value=result();value['selected'].pop(next(iter(REQUIRED)))
        for now in (START,START+timedelta(minutes=20)):
            got=pin_requested_start(value,REQUEST,HORIZON,now)
            self.assertEqual(got['status'],'REQUESTED_START_BLOCKED')
            self.assertFalse(got['qualified']);self.assertNotIn('soak_start',got)
    def test_readiness_after_start_cannot_backdate(self):
        value=result();value['selected'][next(iter(REQUIRED))]['completed_at']='2026-10-06T03:16:00Z'
        self.assertFalse(pin_requested_start(value,REQUEST,HORIZON,START+timedelta(minutes=2))['qualified'])
    def test_registration_buffer_remains_required(self):
        value=result();value['baseline']='2026-10-06T03:17:00Z'
        self.assertEqual(pin_requested_start(value,REQUEST,HORIZON,START)['status'],'REQUESTED_START_BLOCKED_REGISTRATION')
    def test_before_start_shows_prequalification(self):
        value=result();value['selected']={};value['missing_workflows']=list(REQUIRED)
        self.assertEqual(pin_requested_start(value,REQUEST,HORIZON,START-timedelta(minutes=1))['status'],'PREQUALIFYING_FIXED_START')
    def test_expired_window_never_restarts(self):
        self.assertEqual(pin_requested_start(result(),REQUEST,HORIZON,START+timedelta(hours=1))['status'],'REQUESTED_WINDOW_EXPIRED')
    def test_unrequested_auto_mode_unchanged(self):
        value=result();self.assertIs(pin_requested_start(value,None,HORIZON,START),value)
    def test_horizon_is_not_extended(self):
        with self.assertRaisesRegex(RuntimeError,'OUTSIDE_HORIZON'):
            pin_requested_start(result(),REQUEST,START+timedelta(minutes=59),START)

if __name__=='__main__':unittest.main()
