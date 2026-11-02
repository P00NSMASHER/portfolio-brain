"""V11 protected native enrollment, fail-shut readback and uncertain write tests."""
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from brain.v11 import verified_delivery as d
from test_brain_v11_delivery import Fake, BASE, HEAD


class NativeEnrollmentTests(unittest.TestCase):
    def setUp(self):
        self.provider = Fake()
        self.plan = {
            "status": "V10_REPAIR_ELIGIBLE_FOR_NATIVE_PROTECTION",
            "pr_number": 777, "pr_node": "PR_some_exact_node_777",
            "head_sha": HEAD, "base_sha": BASE,
        }
        self.calls = []

    def mark_ready(self, args, **_):
        self.calls.append(("ready", args))
        self.provider.pr["draft"] = False
        return {"data": {"markPullRequestReadyForReview": {
            "pullRequest": {"id": self.plan["pr_node"], "isDraft": False}}}}

    def native_merge(self, args, **_):
        self.calls.append(("native", args))
        self.assertEqual(args[:4], ["gh", "pr", "merge", "777"])
        self.assertIn("--auto", args)
        self.assertIn("--squash", args)
        self.assertNotIn("--admin", args)
        self.assertNotIn("--delete-branch", args)
        self.provider.pr["auto_merge"] = {"merge_method": "squash"}
        return SimpleNamespace(returncode=0, stdout="enrolled", stderr="")

    def test_original_native_enrollment_binds_genuine_pr_and_no_direct_merge(self):
        with patch.object(d, "_gh", side_effect=self.mark_ready), \
             patch.object(d.subprocess, "run", side_effect=self.native_merge):
            result = d.enroll(self.provider, self.plan)
        self.assertEqual(result["status"], "V11_NATIVE_GITHUB_PROTECTION_ENROLLED")
        self.assertEqual(result["pr_number"], 777)
        self.assertTrue(result["requires_independent_check"])
        self.assertFalse(result["merged"])
        self.assertFalse(result["production_deployed"])
        self.assertEqual([x[0] for x in self.calls], ["ready", "native"])

    def test_main_moved_after_mark_ready_denies_before_native_enrollment(self):
        def adversarial_ready(args, **kwargs):
            response = self.mark_ready(args, **kwargs)
            self.provider.main = "e" * 40
            return response
        with patch.object(d, "_gh", side_effect=adversarial_ready), \
             patch.object(d.subprocess, "run", side_effect=AssertionError("no merge")):
            with self.assertRaisesRegex(d.DeliveryDenied, "SOURCE_DRIFT"):
                d.enroll(self.provider, self.plan)
        self.assertEqual(len(self.calls), 1)

    def test_native_enrollment_network_or_cli_failure_does_not_claim_merge(self):
        def uncertain(args, **kwargs):
            self.calls.append(("uncertain", args))
            return SimpleNamespace(returncode=1, stdout="", stderr="transient")
        with patch.object(d, "_gh", side_effect=self.mark_ready), \
             patch.object(d.subprocess, "run", side_effect=uncertain):
            with self.assertRaisesRegex(d.DeliveryDenied, "ENROLLMENT_UNCERTAIN"):
                d.enroll(self.provider, self.plan)
        self.assertEqual(len(self.calls), 2)
        self.assertFalse(self.provider.pr["merged"])
        self.assertIsNone(self.provider.pr["auto_merge"])

    def test_unsafe_plan_has_no_external_effect(self):
        with patch.object(d, "_gh", side_effect=AssertionError("external write")):
            with self.assertRaisesRegex(d.DeliveryDenied, "INELIGIBLE_PLAN"):
                d.enroll(self.provider, {"status": "UNVERIFIED"})


if __name__ == "__main__":
    unittest.main()
