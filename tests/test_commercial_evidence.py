import copy
import unittest
from datetime import datetime, timedelta

from commercial_evidence.state import (
    CommercialEvidenceError,
    hashv,
    load_current,
    policy,
    project_current,
    validate_observation,
)


class CommercialEvidenceTests(unittest.TestCase):
    def _rehash(self,observation):
        out=copy.deepcopy(observation)
        body={key:value for key,value in out.items() if key not in {"observation_id","observation_hash"}}
        digest=hashv(body)
        out["observation_hash"]=digest
        out["observation_id"]="CEOBS-"+digest.split(":",1)[1][:20].upper()
        return out

    def test_checked_in_observation_is_sanitized_scoped_and_integrity_bound(self):
        observation=load_current()
        validate_observation(observation)
        self.assertEqual(observation["source_kind"],"CHATGPT_GMAIL_CONNECTOR_SANITIZED_OBSERVATION")
        self.assertEqual(observation["evidence_state"],"OBSERVED")
        self.assertEqual(observation["threads_observed"],19)
        self.assertEqual(observation["outbound_messages_observed"],21)
        self.assertEqual(observation["inbound_messages_observed"],1)
        self.assertEqual(observation["threads_with_auto_response"],1)
        self.assertEqual(observation["threads_with_human_reply"],0)
        self.assertFalse(observation["private_payloads_persisted"])
        self.assertFalse(observation["raw_message_ids_persisted"])
        self.assertFalse(observation["raw_thread_ids_persisted"])
        self.assertFalse(observation["recipient_identifiers_persisted"])

    def test_fresh_scoped_zero_reply_is_observed_not_global_zero_or_definitive_outcome(self):
        observation=load_current()
        captured=datetime.fromisoformat(observation["captured_at"].replace("Z","+00:00"))
        at=(captured+timedelta(minutes=5)).isoformat().replace("+00:00","Z")
        projection=project_current(observation,at=at)
        self.assertEqual(projection["evidence_status"],"CURRENT_SCOPE_OBSERVED")
        self.assertEqual(projection["current_reply_state"],"OBSERVED_NO_HUMAN_REPLY_IN_SCOPE")
        self.assertEqual(projection["current_payment_state"],"UNKNOWN")
        self.assertFalse(projection["live_external_evidence_feed"])
        self.assertFalse(projection["authority_granted"])
        self.assertFalse(projection["definitive_outcome_recorded"])
        self.assertIn("explicit Gmail query contract",projection["scope_note"])

    def test_stale_observation_fails_closed_to_unknown(self):
        observation=load_current()
        captured=datetime.fromisoformat(observation["captured_at"].replace("Z","+00:00"))
        at=(captured+timedelta(minutes=float(policy()["max_observation_age_minutes"])+1)).isoformat().replace("+00:00","Z")
        projection=project_current(observation,at=at)
        self.assertEqual(projection["evidence_status"],"STALE_OR_UNAVAILABLE")
        self.assertFalse(projection["fresh"])
        self.assertEqual(projection["current_reply_state"],"UNKNOWN")
        self.assertEqual(projection["current_auto_response_state"],"UNKNOWN")
        self.assertEqual(projection["current_payment_state"],"UNKNOWN")

    def test_tampered_count_without_hash_update_is_rejected(self):
        observation=load_current()
        observation["threads_with_human_reply"]=1
        with self.assertRaisesRegex(CommercialEvidenceError,"hash mismatch"):
            validate_observation(observation)

    def test_mailbox_like_private_value_is_rejected_even_with_valid_hash(self):
        observation=load_current()
        observation["coverage_scope"]="private@example.com"
        observation=self._rehash(observation)
        with self.assertRaisesRegex(CommercialEvidenceError,"mailbox-like"):
            validate_observation(observation)

    def test_raw_private_field_cannot_be_added_to_closed_contract(self):
        observation=load_current()
        observation["message_id"]="raw-provider-id"
        with self.assertRaisesRegex(CommercialEvidenceError,"fields changed"):
            validate_observation(observation)

    def test_privacy_flags_cannot_be_enabled_even_with_valid_hash(self):
        observation=load_current()
        observation["raw_thread_ids_persisted"]=True
        observation=self._rehash(observation)
        with self.assertRaisesRegex(CommercialEvidenceError,"privacy boundary violated"):
            validate_observation(observation)

    def test_policy_does_not_allow_definitive_outcome_authority(self):
        p=policy()
        self.assertEqual(p["authority_class"],"OBSERVE")
        self.assertEqual(p["privacy_boundary"],"SANITIZED_COUNTS_HASHES_AND_SCOPE_ONLY")
        self.assertIn("OBSERVED",p["allowed_evidence_states"])
        self.assertNotIn("PASSED",p["allowed_evidence_states"])
        self.assertNotIn("FAILED",p["allowed_evidence_states"])


if __name__=="__main__":
    unittest.main()
