#!/usr/bin/env python3
import unittest
from pathlib import Path

from verification.step24_security_review import (
    ALLOWED_VERIFIER_PERMISSIONS,
    combine,
    live_review,
    static_review,
)

ROOT = Path(__file__).resolve().parents[1]
TEST_SHA = "a" * 40


def good_live_evidence():
    return {
        "observed_main_sha": TEST_SHA,
        "ruleset": {
            "id": 24182301,
            "name": "portfolio-main-protection",
            "target": "branch",
            "source_type": "Repository",
            "source": "P00NSMASHER/portfolio-brain",
            "enforcement": "active",
            "bypass_actors": [],
            "current_user_can_bypass": "never",
            "rules": [
                {"type": "deletion"},
                {"type": "non_fast_forward"},
                {"type": "pull_request", "parameters": {
                    "required_approving_review_count": 0,
                    "required_review_thread_resolution": True,
                }},
                {"type": "required_status_checks", "parameters": {
                    "strict_required_status_checks_policy": True,
                    "required_status_checks": [
                        {"context": "validate", "integration_id": 15368},
                        {"context": "portfolio-phase1-gate", "integration_id": 5121826},
                    ],
                }},
            ],
        },
        "verifier_app": {
            "id": 5121826,
            "permissions": dict(ALLOWED_VERIFIER_PERMISSIONS),
        },
        "artifact_probe": {
            "run_id": 36728065423,
            "artifact_id": 11103642737,
            "head_sha": TEST_SHA,
            "provider_digest": "sha256:" + "a" * 64,
            "downloaded_zip_digest": "sha256:" + "a" * 64,
            "expired": False,
        },
    }


class Step24SecurityReviewTests(unittest.TestCase):
    def test_static_review_never_completes_step24(self):
        result = static_review(ROOT)
        self.assertFalse(result["step24_complete"])
        self.assertFalse(result["authority_granted"])
        self.assertFalse(result["evidence_upgraded"])
        self.assertIn(result["status"], {"BLOCKED", "READY_FOR_INDEPENDENT_SIGNOFF"})

    def test_current_repo006_binding_is_fail_closed(self):
        result = static_review(ROOT)
        self.assertTrue(result["observed"]["repo006_access_fail_closed"])
        self.assertEqual(result["observed"]["repo006_binding"]["integration_status"], "BLOCKED")

    def test_live_evidence_accepts_exact_rules_app_scope_and_artifact_identity(self):
        result = live_review(good_live_evidence(), TEST_SHA)
        self.assertEqual(result["status"], "READY_FOR_INDEPENDENT_SIGNOFF")
        self.assertEqual(result["finding_counts"]["CRITICAL"], 0)
        self.assertEqual(result["finding_counts"]["UNKNOWN"], 0)
        self.assertFalse(result["step24_complete"])

    def test_matching_ruleset_is_not_enough_when_verifier_scope_widens(self):
        evidence = good_live_evidence()
        evidence["verifier_app"]["permissions"]["contents"] = "write"
        result = live_review(evidence, TEST_SHA)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("VERIFIER_APP_SCOPE_WIDENED", {x["code"] for x in result["findings"]})

    def test_matching_app_and_rules_are_not_enough_when_artifact_head_drifts(self):
        evidence = good_live_evidence()
        evidence["artifact_probe"]["head_sha"] = "0" * 40
        result = live_review(evidence, TEST_SHA)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("ARTIFACT_IDENTITY_UNTRACEABLE", {x["code"] for x in result["findings"]})

    def test_artifact_digest_mismatch_is_blocked(self):
        evidence = good_live_evidence()
        evidence["artifact_probe"]["downloaded_zip_digest"] = "sha256:" + "b" * 64
        result = live_review(evidence, TEST_SHA)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("ARTIFACT_IDENTITY_UNTRACEABLE", {x["code"] for x in result["findings"]})

    def test_expired_artifact_is_not_tamper_resistance_proof(self):
        evidence = good_live_evidence()
        evidence["artifact_probe"]["expired"] = True
        result = live_review(evidence, TEST_SHA)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("ARTIFACT_IDENTITY_UNTRACEABLE", {x["code"] for x in result["findings"]})

    def test_missing_live_evidence_remains_unknown_and_blocked(self):
        static = static_review(ROOT)
        result = combine(static, None)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertGreater(result["finding_counts"]["UNKNOWN"], 0)
        self.assertIn("LIVE_SECURITY_EVIDENCE_NOT_SUPPLIED", {x["code"] for x in result["findings"]})

    def test_ruleset_without_no_bypass_proof_is_blocked(self):
        evidence = good_live_evidence()
        del evidence["ruleset"]["bypass_actors"]
        result = live_review(evidence, TEST_SHA)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("MAIN_RULESET_INSUFFICIENT", {x["code"] for x in result["findings"]})


if __name__ == "__main__":
    unittest.main()
