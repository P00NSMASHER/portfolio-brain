import json,os,unittest
from unittest.mock import patch
from action_engine.action_executor import ActionEngineError,execute_email,load_state,make_email_request,preflight

AT="2026-09-26T04:00:00Z"

def req(target="buyer@example.com",subject="Free audit",body="Would you like a bounded review?",campaign="test-campaign",project="PRJ-001",at=AT):
    return make_email_request(project_id=project,target=target,subject=subject,body=body,campaign_id=campaign,evidence_refs=["test:action"],requested_at=at)

ENV={
 "PORTFOLIO_EMAIL_SMTP_HOST":"smtp.example.com",
 "PORTFOLIO_EMAIL_SMTP_PORT":"465",
 "PORTFOLIO_EMAIL_SMTP_USER":"operator@example.com",
 "PORTFOLIO_EMAIL_SMTP_PASSWORD":"secret",
 "PORTFOLIO_EMAIL_FROM":"operator@example.com",
}

class ActionEngineTests(unittest.TestCase):
    def test_commercial_project_email_is_allowed(self):
        r=req()
        _,d=preflight(load_state(),r,at=AT)
        self.assertEqual(d["status"],"APPROVED_BOUNDED_ACTION")
        self.assertTrue(d["can_execute"])

    def test_noncommercial_project_is_rejected(self):
        with self.assertRaises(ActionEngineError):
            req(project="PRJ-005")

    def test_missing_credentials_block_before_transport(self):
        with patch.dict(os.environ,{},clear=True):
            with self.assertRaises(ActionEngineError):
                execute_email(load_state(),req(),at=AT,transport=lambda *a:self.fail("transport called"))

    def test_success_persists_only_hashes_and_sanitized_refs(self):
        with patch.dict(os.environ,ENV,clear=True):
            state,d,row=execute_email(load_state(),req(),at=AT,transport=lambda request,creds:"remote-123")
        self.assertEqual(d["status"],"EXECUTED")
        self.assertEqual(row["status"],"SENT")
        raw=json.dumps(state)
        self.assertNotIn("buyer@example.com",raw)
        self.assertNotIn("Would you like",raw)
        self.assertNotIn("Free audit",raw)
        self.assertNotIn("remote-123",raw)
        self.assertIn("sha256:",row["remote_ref"])
        self.assertNotIn("test-campaign",raw)

    def test_successful_duplicate_is_suppressed(self):
        calls=[]
        with patch.dict(os.environ,ENV,clear=True):
            state,d,_=execute_email(load_state(),req(),at=AT,transport=lambda request,creds:calls.append(1) or "r1")
            state,d2,row2=execute_email(state,req(),at="2026-09-26T05:00:00Z",transport=lambda *a:self.fail("duplicate transport called"))
        self.assertEqual(d2["status"],"DUPLICATE_SUPPRESSED")
        self.assertIsNone(row2)
        self.assertEqual(len(calls),1)

    def test_failed_transport_can_retry_only_twice(self):
        def fail(request,creds): raise RuntimeError("down")
        with patch.dict(os.environ,ENV,clear=True):
            state,d1,_=execute_email(load_state(),req(),at=AT,transport=fail)
            state,d2,_=execute_email(state,req(),at="2026-09-26T04:10:00Z",transport=fail)
            state,d3,row3=execute_email(state,req(),at="2026-09-26T04:20:00Z",transport=fail)
        self.assertEqual(d1["status"],"TRANSPORT_FAILED")
        self.assertEqual(d2["status"],"TRANSPORT_FAILED")
        self.assertEqual(d3["status"],"BLOCKED_RETRY_LIMIT")
        self.assertIsNone(row3)

    def test_same_recipient_daily_limit_applies_across_payloads(self):
        with patch.dict(os.environ,ENV,clear=True):
            state,_,_=execute_email(load_state(),req(body="first"),at=AT,transport=lambda *a:"r1")
            r2=req(body="second",campaign="second-campaign",at="2026-09-26T06:00:00Z")
            state,d,row=execute_email(state,r2,at="2026-09-26T06:00:00Z",transport=lambda *a:self.fail("rate-limited transport called"))
        self.assertEqual(d["status"],"BLOCKED_RATE_LIMIT")
        self.assertIn("RECIPIENT_DAILY_LIMIT",d["reason_codes"])
        self.assertIsNone(row)

    def test_kill_switch_environment_blocks(self):
        with patch.dict(os.environ,{"PORTFOLIO_ACTIONS_DISABLED":"true"}):
            _,d=preflight(load_state(),req(),at=AT)
        self.assertEqual(d["status"],"BLOCKED_KILL_SWITCH")

    def test_evidence_refs_cannot_contain_raw_email(self):
        with self.assertRaises(ActionEngineError):
            make_email_request(project_id="PRJ-001",target="buyer@example.com",subject="x",body="y",campaign_id="c",evidence_refs=["email:buyer@example.com"],requested_at=AT)

if __name__=="__main__":unittest.main()
