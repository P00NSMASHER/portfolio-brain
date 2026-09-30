#!/usr/bin/env python3
import copy
import unittest

from runtime.provider_usability_acceptance import build_receipt


SHA = "a" * 40


def ready_health():
    return {
        "schema_version": "1.1.0",
        "state_id": "portfolio-provider-readiness-state",
        "sequence": 8,
        "updated_at": "2026-09-30T17:30:00Z",
        "mode": "daily",
        "status": "READY",
        "source_analysis_status": "SUCCESS",
        "provider_id": "openai",
        "model_id": "gpt-5.6-terra",
        "configured": True,
        "enabled": True,
        "credential_ready": True,
        "call_verified": True,
        "last_successful_at": "2026-09-30T17:30:00Z",
        "cost_gate_status": "COMMITTED",
        "retryable": False,
        "provider_attempt": 1,
        "authority_granted": False,
        "evidence_upgraded": False,
    }


def ready_analysis():
    return {
        "schema_version": "1.0.0",
        "mode": "daily",
        "status": "SUCCESS",
        "packet_hash": "sha256:" + ("1" * 64),
        "route": {
            "tier": "TIER_2",
            "provider_id": "openai",
            "model_id": "gpt-5.6-terra",
            "route_id": "ROUTE-TEST",
        },
        "receipt": {
            "provider_id": "openai",
            "model_id": "gpt-5.6-terra",
        },
        "analysis_text": "{}",
        "authority_granted": False,
        "evidence_upgraded": False,
    }


class ProviderUsabilityAcceptanceTests(unittest.TestCase):
    def receipt(self, health=None, analysis=None, *, observed=SHA):
        return build_receipt(
            ready_health() if health is None else health,
            ready_analysis() if analysis is None else analysis,
            source_run_id=12345,
            source_head_sha=SHA,
            observed_main_sha=observed,
        )

    def test_verified_exact_main_canary_passes(self):
        receipt = self.receipt()
        self.assertEqual(receipt["status"], "PASS")
        self.assertEqual(receipt["reason_codes"], [])
        self.assertTrue(receipt["configured"])
        self.assertTrue(receipt["enabled"])
        self.assertTrue(receipt["credential_ready"])
        self.assertTrue(receipt["call_verified"])
        self.assertTrue(receipt["last_successful_at"])
        self.assertEqual(receipt["cost_gate_status"], "COMMITTED")
        self.assertEqual(receipt["model_analysis_status"], "SUCCESS")
        self.assertTrue(receipt["model_analysis_hash"].startswith("sha256:"))
        self.assertFalse(receipt["authority_granted"])
        self.assertFalse(receipt["evidence_upgraded"])

    def test_missing_credential_is_blocked_never_green(self):
        health = ready_health()
        health.update({
            "status": "MISSING_CREDENTIAL",
            "source_analysis_status": "BLOCKED_MISSING_CREDENTIAL",
            "credential_ready": False,
            "call_verified": False,
            "last_successful_at": None,
            "cost_gate_status": None,
            "provider_attempt": None,
        })
        receipt = self.receipt(health)
        self.assertEqual(receipt["status"], "BLOCKED")
        self.assertIn("CREDENTIAL_NOT_READY", receipt["reason_codes"])
        self.assertIn("CALL_NOT_VERIFIED", receipt["reason_codes"])

    def test_provider_failure_is_blocked_even_with_ready_credential(self):
        health = ready_health()
        health.update({
            "status": "RATE_LIMITED",
            "source_analysis_status": "DEFERRED_PROVIDER_RETRY",
            "call_verified": False,
            "retryable": True,
            "provider_attempt": 2,
        })
        receipt = self.receipt(health)
        self.assertEqual(receipt["status"], "BLOCKED")
        self.assertIn("CALL_NOT_VERIFIED", receipt["reason_codes"])
        self.assertIn("PROVIDER_STATUS_NOT_READY", receipt["reason_codes"])

    def test_config_only_or_legacy_ready_does_not_pass(self):
        legacy = {
            "schema_version": "1.0.0",
            "state_id": "portfolio-provider-readiness-state",
            "sequence": 1,
            "updated_at": "2026-09-30T17:30:00Z",
            "mode": "daily",
            "status": "READY",
            "source_analysis_status": "SUCCESS",
            "provider_id": "openai",
            "model_id": "gpt-5.6-terra",
            "cost_gate_status": "COMMITTED",
            "retryable": False,
            "provider_attempt": 1,
            "authority_granted": False,
            "evidence_upgraded": False,
        }
        receipt = self.receipt(legacy)
        self.assertEqual(receipt["status"], "BLOCKED")
        self.assertIn("USABILITY_SCHEMA_NOT_CURRENT", receipt["reason_codes"])
        self.assertIn("CALL_NOT_VERIFIED", receipt["reason_codes"])

    def test_main_advancing_during_canary_blocks_receipt(self):
        receipt = self.receipt(observed="b" * 40)
        self.assertEqual(receipt["status"], "BLOCKED")
        self.assertFalse(receipt["exact_main_identity"])
        self.assertIn("MAIN_ADVANCED_DURING_CANARY", receipt["reason_codes"])

    def test_missing_provider_health_artifact_is_blocked(self):
        receipt = build_receipt(
            None,
            ready_analysis(),
            source_run_id=12345,
            source_head_sha=SHA,
            observed_main_sha=SHA,
        )
        self.assertEqual(receipt["status"], "BLOCKED")
        self.assertIn("PROVIDER_HEALTH_ARTIFACT_MISSING", receipt["reason_codes"])
        self.assertIsNone(receipt["provider_health_hash"])

    def test_stale_health_without_current_analysis_artifact_cannot_pass(self):
        receipt = build_receipt(
            ready_health(),
            None,
            source_run_id=12345,
            source_head_sha=SHA,
            observed_main_sha=SHA,
        )
        self.assertEqual(receipt["status"], "BLOCKED")
        self.assertIn("MODEL_ANALYSIS_ARTIFACT_MISSING", receipt["reason_codes"])
        self.assertIsNone(receipt["model_analysis_hash"])

    def test_model_analysis_provider_identity_must_match_health(self):
        analysis = ready_analysis()
        analysis["route"]["model_id"] = "other-model"
        receipt = self.receipt(analysis=analysis)
        self.assertEqual(receipt["status"], "BLOCKED")
        self.assertIn("MODEL_ANALYSIS_MODEL_MISMATCH", receipt["reason_codes"])

    def test_invalid_health_cannot_be_rescued_by_boolean_flags(self):
        health = ready_health()
        health["authority_granted"] = True
        receipt = self.receipt(health)
        self.assertEqual(receipt["status"], "BLOCKED")
        self.assertIn("PROVIDER_HEALTH_INVALID", receipt["reason_codes"])
        self.assertIn("AUTHORITY_OR_EVIDENCE_WIDENED", receipt["reason_codes"])

    def test_health_hash_changes_when_evidence_changes(self):
        first = self.receipt()
        changed = copy.deepcopy(ready_health())
        changed["last_successful_at"] = "2026-09-30T17:31:00Z"
        second = self.receipt(changed)
        self.assertNotEqual(first["provider_health_hash"], second["provider_health_hash"])


if __name__ == "__main__":
    unittest.main()
