import json,unittest
from action_engine.action_executor import ActionEngineError,load_ledger,make_email_request,preflight,record_gmail_send
AT="2026-09-26T12:00:00Z"
def req(target="buyer@example.com",subject="Free audit",body="Would you like a bounded review?",campaign="test-campaign",project="PRJ-001",at=AT,target_classification=None,approved=False):
    return make_email_request(project_id=project,target=target,subject=subject,body=body,campaign_id=campaign,evidence_refs=["test:gmail"],target_classification=target_classification,requested_at=at,human_approval_ref="human-approval:test" if approved else None)
class GmailGatewayTests(unittest.TestCase):
    def test_unapproved_email_fails_closed(self):
        d=preflight(load_ledger(),req(),at=AT);self.assertEqual(d["status"],"HUMAN_APPROVAL_REQUIRED");self.assertFalse(d["can_execute"])
    def test_explicitly_approved_email_may_pass_other_gates(self):
        d=preflight(load_ledger(),req(approved=True),at=AT);self.assertTrue(d["can_execute"]);self.assertIn("EXPLICIT_HUMAN_APPROVAL",d["reason_codes"])
    def test_education_requires_verified_adult(self):
        with self.assertRaises(ActionEngineError):req(project="PRJ-005",approved=True)
        d=preflight(load_ledger(),req(project="PRJ-005",target_classification="VERIFIED_ADULT_STAKEHOLDER",approved=True),at=AT);self.assertTrue(d["can_execute"])
    def test_nonadult_education_target_rejected(self):
        with self.assertRaises(ActionEngineError):req(project="PRJ-006",target_classification="BUSINESS_CONTACT",approved=True)
    def test_education_daily_limit(self):
        a=req(project="PRJ-005",target_classification="VERIFIED_ADULT_STAKEHOLDER",approved=True);ledger,_=record_gmail_send(load_ledger(),a,gmail_message_id="edu-m1",gmail_thread_id="edu-t1",sent_at=AT)
        b=req(target="another-adult@example.com",campaign="education-second",project="PRJ-005",target_classification="VERIFIED_ADULT_STAKEHOLDER",approved=True);self.assertEqual(preflight(ledger,b,at="2026-09-26T13:00:00Z")["status"],"BLOCKED_RATE_LIMIT")
    def test_receipt_persists_hashes_only(self):
        ledger,row=record_gmail_send(load_ledger(),req(approved=True),gmail_message_id="msg-private",gmail_thread_id="thread-private",sent_at=AT);raw=json.dumps(ledger)
        for v in ["buyer@example.com","Would you like","Free audit","test-campaign","msg-private","thread-private","human-approval:test"]:self.assertNotIn(v,raw)
        for k in ["target_hash","payload_hash","campaign_hash","gmail_message_hash","gmail_thread_hash"]:self.assertTrue(row[k].startswith("sha256:"))
    def test_direct_record_without_approval_rejected(self):
        with self.assertRaises(ActionEngineError):record_gmail_send(load_ledger(),req(),gmail_message_id="m",gmail_thread_id="t",sent_at=AT)
    def test_duplicate_suppressed(self):
        a=req(approved=True);ledger,_=record_gmail_send(load_ledger(),a,gmail_message_id="m1",gmail_thread_id="t1",sent_at=AT);self.assertEqual(preflight(ledger,a,at="2026-09-26T13:00:00Z")["status"],"DUPLICATE_SUPPRESSED")
    def test_rate_limits(self):
        self.assertEqual(preflight(load_ledger(),req(approved=True),at=AT,gmail_sent_today_count=25)["status"],"BLOCKED_RATE_LIMIT")
        self.assertEqual(preflight(load_ledger(),req(approved=True),at=AT,gmail_target_sent_today_count=1)["status"],"BLOCKED_RATE_LIMIT")
    def test_raw_email_cannot_enter_evidence_ref(self):
        with self.assertRaises(ActionEngineError):make_email_request(project_id="PRJ-001",target="buyer@example.com",subject="x",body="y",campaign_id="c",evidence_refs=["email:buyer@example.com"],requested_at=AT)
if __name__=="__main__":unittest.main()
