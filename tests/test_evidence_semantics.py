import unittest
from pathlib import Path

from dashboard.live_state_bridge import EVIDENCE_SEMANTICS
from notifications.notification_engine import _delivery

ROOT=Path(__file__).resolve().parents[1]

class EvidenceSemanticsTests(unittest.TestCase):
    def test_heartbeat_notification_and_pages_grant_no_verification_credit(self):
        self.assertEqual(EVIDENCE_SEMANTICS,{
          "heartbeat":"LIVENESS_CONNECTIVITY_ONLY",
          "notification":"ALERT_ONLY",
          "pages":"PUBLICATION_ONLY",
          "technical_verification_credit":False,
          "market_verification_credit":False,
          "revenue_verification_credit":False,
        })

    def test_notification_delivery_is_alert_only_and_grants_no_authority(self):
        record={
          "alert_id":"ALT-TEST","fingerprint":"sha256:"+"1"*64,"kind":"OPEN_HUMAN_BLOCKERS","severity":"HIGH",
          "project_ids":["PRJ-000"],"entity_refs":["BLK-TEST"],"evidence_refs":["test:evidence"],
          "title_code":"OPEN_HUMAN_BLOCKERS","summary_code":"OPEN_HUMAN_BLOCKERS:COUNT_1",
          "status":"ACTIVE","first_seen_at":"2026-09-30T14:00:00Z","last_seen_at":"2026-09-30T14:00:00Z",
          "seen_count":1,"last_emitted_at":None,"emission_count":0
        }
        delivery=_delivery(record,"2026-09-30T14:00:01Z")
        self.assertFalse(delivery["authority_granted"])
        self.assertNotIn("verification_state",delivery)
        self.assertNotIn("value_verified",delivery)

    def test_dashboard_renders_lineage_and_explicit_nonverification_semantics(self):
        source=(ROOT/"dashboard/command_center.py").read_text(encoding="utf-8")
        self.assertIn('src.get("source_state_hash")',source)
        self.assertIn('src.get("restore_status")',source)
        self.assertIn('src.get("error_class")',source)
        self.assertIn("heartbeats prove liveness/connectivity only",source)
        self.assertIn("None grants technical, market, or revenue verification credit",source)

    def test_pages_publication_has_no_production_deploy_authority(self):
        import json
        policy=json.loads((ROOT/"governance/boundaries.json").read_text())
        pages=policy["actions"]["PAGES_PUBLICATION"]
        self.assertTrue(pages["publication_only"])
        self.assertFalse(pages["production_deploy_authority"])

if __name__=="__main__":unittest.main()
