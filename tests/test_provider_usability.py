#!/usr/bin/env python3
import json
import tempfile
import unittest
from pathlib import Path

from runtime.model_analysis import _write_health
from runtime.provider_health import ProviderHealthError, validate_provider_health


ROOT=Path(__file__).resolve().parents[1]


class ProviderUsabilityTests(unittest.TestCase):
    def test_seed_separates_configuration_from_usability(self):
        state=json.loads((ROOT/"runtime"/"PROVIDER_HEALTH_SEED.json").read_text())
        validate_provider_health(state)
        self.assertTrue(state["configured"])
        self.assertTrue(state["enabled"])
        self.assertIsNone(state["credential_ready"])
        self.assertIsNone(state["call_verified"])
        self.assertIsNone(state["last_successful_at"])
        self.assertEqual(state["status"],"UNKNOWN")

    def test_ready_requires_real_verified_call(self):
        state=json.loads((ROOT/"runtime"/"PROVIDER_HEALTH_SEED.json").read_text())
        state.update({
            "mode":"daily","provider_id":"openai","model_id":"gpt-5.6-luna",
            "status":"READY","source_analysis_status":"SUCCESS",
            "credential_ready":True,"call_verified":False,
        })
        with self.assertRaisesRegex(ProviderHealthError,"READY requires verified provider usability"):
            validate_provider_health(state)

    def test_failed_status_cannot_claim_verified_call(self):
        state=json.loads((ROOT/"runtime"/"PROVIDER_HEALTH_SEED.json").read_text())
        state.update({
            "mode":"daily","provider_id":"openai","model_id":"gpt-5.6-luna",
            "status":"RATE_LIMITED","source_analysis_status":"DEFERRED_PROVIDER_RETRY",
            "credential_ready":True,"call_verified":True,
            "last_successful_at":"2026-09-30T13:00:00Z","retryable":True,
            "provider_attempt":2,
        })
        with self.assertRaisesRegex(
            ProviderHealthError,"verified call cannot coexist with a non-READY status"
        ):
            validate_provider_health(state)

    def test_success_timestamp_survives_later_failed_canary(self):
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)
            success=_write_health(
                out,mode="daily",status="READY",source_status="SUCCESS",sequence=4,
                at="2026-09-30T13:00:00Z",provider_id="openai",model_id="gpt-5.6-luna",
                cost_gate_status="COMMITTED",provider_attempt=1,
                credential_ready=True,call_verified=True,
            )
            failed=_write_health(
                out,mode="daily",status="RATE_LIMITED",source_status="DEFERRED_PROVIDER_RETRY",
                sequence=5,at="2026-09-30T13:05:00Z",provider_id="openai",
                model_id="gpt-5.6-luna",provider_attempt=2,
                credential_ready=True,call_verified=False,retryable=True,
            )
            self.assertTrue(success["call_verified"])
            self.assertFalse(failed["call_verified"])
            self.assertEqual(failed["last_successful_at"],"2026-09-30T13:00:00Z")
            self.assertNotEqual(failed["status"],"READY")

    def test_missing_credential_is_blocked_not_green(self):
        with tempfile.TemporaryDirectory() as td:
            state=_write_health(
                Path(td),mode="daily",status="MISSING_CREDENTIAL",
                source_status="BLOCKED_MISSING_CREDENTIAL",sequence=0,
                at="2026-09-30T13:10:00Z",provider_id="openai",
                model_id="gpt-5.6-luna",credential_ready=False,call_verified=False,
            )
            self.assertTrue(state["configured"])
            self.assertTrue(state["enabled"])
            self.assertFalse(state["credential_ready"])
            self.assertFalse(state["call_verified"])
            self.assertIsNone(state["last_successful_at"])
            self.assertNotEqual(state["status"],"READY")

    def test_legacy_artifact_remains_restore_compatible(self):
        legacy={
            "schema_version":"1.0.0","state_id":"portfolio-provider-readiness-state",
            "sequence":1,"updated_at":"2026-09-29T00:00:00Z","mode":"daily",
            "status":"READY","source_analysis_status":"SUCCESS","provider_id":"openai",
            "model_id":"gpt-5.6-luna","cost_gate_status":"COMMITTED","retryable":False,
            "provider_attempt":1,"authority_granted":False,"evidence_upgraded":False,
        }
        validate_provider_health(legacy)


if __name__=="__main__":
    unittest.main()
