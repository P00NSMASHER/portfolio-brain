from legacy.workflow_archive import legacy_workflow_path
#!/usr/bin/env python3
import unittest
from pathlib import Path
from unittest.mock import patch

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
            "conditions": {
                "ref_name": {
                    "exclude": [],
                    "include": ["refs/heads/main"],
                },
            },
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
            "slug": "portfolio-brain-522",
            "permissions": dict(ALLOWED_VERIFIER_PERMISSIONS),
            "events": [],
            "source_pr_number": 306,
            "source_head_sha": "c" * 40,
            "source_merge_sha": TEST_SHA,
            "source_check_run_id": 110038864379,
            "source_check_name": "portfolio-phase1-gate",
            "source_check_conclusion": "success",
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

    def test_static_review_covers_required_workflow_permissions(self):
        result = static_review(ROOT)
        self.assertTrue(result["observed"]["workflow_permissions_exact"])
        self.assertIn("WORKFLOW_PERMISSIONS", result["covered_domains"])

    def test_static_review_accepts_canonical_governance_and_bounded_gmail_gateway(self):
        result = static_review(ROOT)
        observed = result["observed"]
        self.assertTrue(observed["governance_canonical_action_schema"])
        self.assertTrue(observed["governance_authority_matrix_fail_closed"])
        self.assertTrue(observed["governance_email_policy_bounded"])
        self.assertTrue(observed["chatgpt_gmail_customer_email_gateway_present"])
        self.assertTrue(observed["chatgpt_gmail_customer_email_policy_bounded"])
        codes = {item["code"] for item in result["findings"]}
        self.assertNotIn("GOVERNANCE_AUTHORITY_MATRIX_NOT_FAIL_CLOSED", codes)
        self.assertNotIn("CHATGPT_GMAIL_CUSTOMER_EMAIL_AUTHORITY_PRESENT", codes)

    def test_static_review_blocks_unbounded_gmail_daily_limit(self):
        target = ROOT / "action_engine" / "ACTION_POLICY.json"
        original_read_text = Path.read_text

        def drifted_read_text(path, *args, **kwargs):
            value = original_read_text(path, *args, **kwargs)
            if path == target:
                return value.replace('"max_per_utc_day": 25', '"max_per_utc_day": 250', 1)
            return value

        with patch.object(Path, "read_text", new=drifted_read_text):
            result = static_review(ROOT)
        self.assertFalse(result["observed"]["chatgpt_gmail_customer_email_policy_bounded"])
        self.assertIn(
            "CHATGPT_GMAIL_CUSTOMER_EMAIL_AUTHORITY_PRESENT",
            {item["code"] for item in result["findings"]},
        )

    def test_static_review_accepts_permission_narrowing_job_override(self):
        result = static_review(ROOT)
        repair = result["observed"]["workflow_permissions"][".github/workflows/portfolio-autonomous-repair.yml"]
        self.assertTrue(repair["job_level_overrides_bounded"])
        self.assertTrue(repair["exact"])
        self.assertEqual(repair["job_level_overrides"], [{
            "actions": "write",
            "contents": "read",
            "pull-requests": "write",
        }])

    def test_static_review_blocks_job_level_permission_widening(self):
        target = legacy_workflow_path(ROOT / ".github" / "workflows" / "portfolio-autonomous-repair.yml")
        original_read_text = Path.read_text

        def drifted_read_text(path, *args, **kwargs):
            value = original_read_text(path, *args, **kwargs)
            if path == target:
                return value.replace(
                    "      pull-requests: write",
                    "      pull-requests: write\\n      checks: write",
                    1,
                )
            return value

        with patch.object(Path, "read_text", new=drifted_read_text):
            result = static_review(ROOT)
        repair = result["observed"]["workflow_permissions"][".github/workflows/portfolio-autonomous-repair.yml"]
        self.assertFalse(repair["job_level_overrides_bounded"])
        self.assertIn("WORKFLOW_PERMISSION_SCOPE_DRIFT", {x["code"] for x in result["findings"]})

    def test_static_review_blocks_sensitive_workflow_permission_drift(self):
        target = legacy_workflow_path(ROOT / ".github" / "workflows" / "portfolio-autonomous-scheduler.yml")
        original_read_text = Path.read_text

        def drifted_read_text(path, *args, **kwargs):
            value = original_read_text(path, *args, **kwargs)
            if path == target:
                return value.replace("  contents: read", "  contents: write", 1)
            return value

        with patch.object(Path, "read_text", new=drifted_read_text):
            result = static_review(ROOT)
        self.assertFalse(result["observed"]["workflow_permissions_exact"])
        self.assertIn("WORKFLOW_PERMISSION_SCOPE_DRIFT", {x["code"] for x in result["findings"]})

    def test_combined_review_rejects_missing_required_domain_coverage(self):
        static = static_review(ROOT)
        static["covered_domains"] = [
            domain for domain in static["covered_domains"]
            if domain != "WORKFLOW_PERMISSIONS"
        ]
        result = combine(static, live_review(good_live_evidence(), TEST_SHA))
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("WORKFLOW_PERMISSIONS", result["observed"]["required_domain_coverage"]["missing"])
        self.assertIn("REQUIRED_DOMAIN_EVIDENCE_MISSING", {x["code"] for x in result["findings"]})

    def test_live_evidence_accepts_exact_rules_app_scope_and_artifact_identity(self):
        result = live_review(good_live_evidence(), TEST_SHA)
        self.assertEqual(result["status"], "READY_FOR_INDEPENDENT_SIGNOFF")
        self.assertEqual(result["finding_counts"]["CRITICAL"], 0)
        self.assertEqual(result["finding_counts"]["UNKNOWN"], 0)
        self.assertFalse(result["step24_complete"])

    def test_ruleset_must_explicitly_cover_main(self):
        evidence = good_live_evidence()
        evidence["ruleset"]["conditions"]["ref_name"]["include"] = ["refs/heads/release"]
        result = live_review(evidence, TEST_SHA)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertFalse(result["observed"]["ruleset_covers_main"])
        self.assertIn("MAIN_RULESET_INSUFFICIENT", {x["code"] for x in result["findings"]})

    def test_verifier_app_scope_must_bind_to_exact_protected_merge(self):
        evidence = good_live_evidence()
        evidence["verifier_app"]["source_merge_sha"] = "d" * 40
        result = live_review(evidence, TEST_SHA)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertFalse(result["observed"]["verifier_app_source_binding"])
        self.assertIn("VERIFIER_APP_SCOPE_WIDENED", {x["code"] for x in result["findings"]})

    def test_ruleset_exclusions_covering_main_are_blocked(self):
        for pattern in ("refs/heads/main", "refs/heads/*", "refs/heads/m*", "~ALL", "~DEFAULT_BRANCH", None):
            with self.subTest(pattern=pattern):
                evidence = good_live_evidence()
                evidence["ruleset"]["conditions"]["ref_name"]["exclude"] = [pattern]
                result = live_review(evidence, TEST_SHA)
                self.assertEqual(result["status"], "BLOCKED")
                self.assertFalse(result["observed"]["ruleset_covers_main"])
                self.assertIn("MAIN_RULESET_INSUFFICIENT", {x["code"] for x in result["findings"]})

    def test_unrelated_ruleset_exclusion_preserves_main_coverage(self):
        evidence = good_live_evidence()
        evidence["ruleset"]["conditions"]["ref_name"]["exclude"] = ["refs/heads/release/*"]
        result = live_review(evidence, TEST_SHA)
        self.assertEqual(result["status"], "READY_FOR_INDEPENDENT_SIGNOFF")
        self.assertTrue(result["observed"]["ruleset_covers_main"])

    def test_verifier_app_event_subscription_widening_is_blocked(self):
        evidence = good_live_evidence()
        evidence["verifier_app"]["events"] = ["pull_request"]
        result = live_review(evidence, TEST_SHA)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("VERIFIER_APP_SCOPE_WIDENED", {x["code"] for x in result["findings"]})

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
