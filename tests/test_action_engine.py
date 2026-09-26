import json,unittest
from action_engine.action_executor import ActionEngineError,load_ledger,make_email_request,preflight,record_gmail_send

AT="2026-09-26T12:00:00Z"

def req(target="buyer@example.com",subject="Free audit",body="Would you like a bounded review?",campaign="test-campaign",project="PRJ-001",at=AT,target_classification=None):
    return make_email_request(project_id=project,target=target,subject=subject,body=body,campaign_id=campaign,evidence_refs=["test:gmail"],target_classification=target_classification,requested_at=at)

class GmailGatewayTests(unittest.TestCase):
    def test_commercial_email_preflight_is_allowed(self):
        d=preflight(load_ledger(),req(),at=AT)
        self.assertEqual(d["status"],"APPROVED_GMAIL_CONNECTOR_ACTION")
        self.assertTrue(d["can_execute"])

    def test_education_project_requires_verified_adult_target(self):
        with self.assertRaises(ActionEngineError):req(project="PRJ-005")
        d=preflight(load_ledger(),req(project="PRJ-005",target_classification="VERIFIED_ADULT_STAKEHOLDER"),at=AT)
        self.assertTrue(d["can_execute"])
        self.assertIn("VERIFIED_ADULT_STAKEHOLDER_ONLY",d["reason_codes"])

    def test_education_project_rejects_nonadult_target_classification(self):
        with self.assertRaises(ActionEngineError):
            req(project="PRJ-006",target_classification="BUSINESS_CONTACT")

    def test_education_project_daily_limit_is_one(self):
        education=req(project="PRJ-005",target_classification="VERIFIED_ADULT_STAKEHOLDER")
        ledger,row=record_gmail_send(load_ledger(),education,gmail_message_id="edu-m1",gmail_thread_id="edu-t1",sent_at=AT)
        second=req(target="another-adult@example.com",campaign="education-second",project="PRJ-005",target_classification="VERIFIED_ADULT_STAKEHOLDER")
        d=preflight(ledger,second,at="2026-09-26T13:00:00Z")
        self.assertEqual(d["status"],"BLOCKED_RATE_LIMIT")
        self.assertIn("PROJECT_DAILY_ACTION_LIMIT",d["reason_codes"])

    def test_success_receipt_persists_hashes_only(self):
        ledger,row=record_gmail_send(load_ledger(),req(),gmail_message_id="msg-private",gmail_thread_id="thread-private",sent_at=AT)
        raw=json.dumps(ledger)
        for forbidden in ["buyer@example.com","Would you like","Free audit","test-campaign","msg-private","thread-private"]:
            self.assertNotIn(forbidden,raw)
        for key in ["target_hash","payload_hash","campaign_hash","gmail_message_hash","gmail_thread_hash"]:
            self.assertTrue(row[key].startswith("sha256:"))

    def test_successful_duplicate_is_suppressed(self):
        ledger,_=record_gmail_send(load_ledger(),req(),gmail_message_id="m1",gmail_thread_id="t1",sent_at=AT)
        d=preflight(ledger,req(),at="2026-09-26T13:00:00Z")
        self.assertEqual(d["status"],"DUPLICATE_SUPPRESSED")

    def test_gmail_daily_count_is_fail_closed_input(self):
        d=preflight(load_ledger(),req(),at=AT,gmail_sent_today_count=25)
        self.assertEqual(d["status"],"BLOCKED_RATE_LIMIT")
        self.assertIn("DAILY_ACTION_LIMIT",d["reason_codes"])

    def test_gmail_recipient_count_is_fail_closed_input(self):
        d=preflight(load_ledger(),req(),at=AT,gmail_target_sent_today_count=1)
        self.assertEqual(d["status"],"BLOCKED_RATE_LIMIT")
        self.assertIn("RECIPIENT_DAILY_LIMIT",d["reason_codes"])

    def test_evidence_refs_cannot_contain_raw_email(self):
        with self.assertRaises(ActionEngineError):
            make_email_request(project_id="PRJ-001",target="buyer@example.com",subject="x",body="y",campaign_id="c",evidence_refs=["email:buyer@example.com"],requested_at=AT)

if __name__=="__main__":unittest.main()
