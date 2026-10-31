"""Adversarial read-only checks for predecessor-source branch-policy admission."""
import copy
import io
import unittest
import urllib.error
from unittest.mock import patch

from brain.v9 import guarded_merge as gm
from verification.source_admission import (
    SourceAdmissionError,
    verify_predecessor_acceptance,
)
from verification import independent_verifier as verifier
from test_brain_v9_guarded_merge import BASE, REVIEW_TIP, FakeProvider


class SourceMergeAdmissionTests(unittest.TestCase):
    def observe(self, provider, *, calls=None):
        def read(path):
            if calls is not None:
                calls.append(path)
            return provider.get("repos/" + gm.REPO + path)
        return verify_predecessor_acceptance(BASE, read)

    def test_real_source_specific_attestation_passes_only_exact_main(self):
        provider = FakeProvider()
        calls = []
        proof = self.observe(provider, calls=calls)
        self.assertEqual(proof["acceptance_commit"], REVIEW_TIP)
        self.assertIn("brain-acceptance-" + BASE[:8], proof["acceptance_ref"])
        self.assertEqual(len(calls), 5)
        self.assertTrue(all(path.startswith("/") for path in calls))
        self.assertTrue(all("/repos/" not in path for path in calls))

    def test_missing_predecessor_acceptance_does_not_invent_one(self):
        provider = FakeProvider()
        provider.no_acceptance = True
        with self.assertRaisesRegex(SourceAdmissionError, "SOURCE_ACCEPTANCE_NOT_YET_RECORDED"):
            self.observe(provider)

    def test_wrong_source_and_forged_receipt_rejected(self):
        for field, value in (
            ("source_sha", "f" * 40),
            ("decision", "RELEASED_WITHOUT_EVIDENCE"),
            ("status", "COLLECTING"),
        ):
            provider = FakeProvider()
            provider.record[field] = value
            with self.subTest(field=field), self.assertRaises(SourceAdmissionError):
                self.observe(provider)

    def test_six_hour_window_is_not_twelve_hour_acceptance(self):
        provider = FakeProvider()
        provider.record["criteria"]["minimum_completed_span_seconds"] = 21600
        with self.assertRaisesRegex(SourceAdmissionError, "ACCEPTANCE_CURRENT_CONTRACT_REQUIRED"):
            self.observe(provider)

    def test_underlength_repair_interval_is_not_acceptance(self):
        provider = FakeProvider()
        provider.record["criteria"]["requires_terminal_30_minute_repair_follow_through"] = False
        with self.assertRaisesRegex(SourceAdmissionError, "ACCEPTANCE_CURRENT_CONTRACT_REQUIRED"):
            self.observe(provider)

    def test_wrong_attestation_issuer_is_denied(self):
        provider = FakeProvider()
        original = provider.get

        def mutated(path):
            value = original(path)
            if path.endswith("commits/" + REVIEW_TIP + "/check-runs?per_page=100"):
                value["check_runs"][0]["app"]["id"] = 15368
            return value

        provider.get = mutated
        with self.assertRaisesRegex(SourceAdmissionError, "ACCEPTANCE_ATTESTATION_UNVERIFIED"):
            self.observe(provider)

    def test_wrong_attestation_receipt_digest_is_denied(self):
        provider = FakeProvider()
        original = provider.get

        def mutated(path):
            value = original(path)
            if path.endswith("commits/" + REVIEW_TIP + "/check-runs?per_page=100"):
                value["check_runs"][0]["external_id"] = "source-acceptance:" + BASE + ":" + ("f" * 64)
            return value

        provider.get = mutated
        with self.assertRaisesRegex(SourceAdmissionError, "ACCEPTANCE_ATTESTATION_UNVERIFIED"):
            self.observe(provider)

    def test_nonchild_acceptance_commit_is_denied(self):
        provider = FakeProvider()
        provider.commit["parents"][0]["sha"] = "f" * 40
        with self.assertRaisesRegex(SourceAdmissionError, "ACCEPTANCE_COMMIT_ANCESTRY"):
            self.observe(provider)

    def test_ambiguous_multiple_refs_are_denied(self):
        provider = FakeProvider()
        provider.refs.append(copy.deepcopy(provider.refs[0]))
        with self.assertRaisesRegex(SourceAdmissionError, "ACCEPTANCE_BRANCH_NOT_UNIQUE"):
            self.observe(provider)

    def test_wrong_provider_scope_is_denied_without_any_read(self):
        invoked = []
        with patch.object(gm, "accepted_source"):
            with self.assertRaisesRegex(SourceAdmissionError, "SOURCE_SHA_INVALID"):
                verify_predecessor_acceptance("unknown", lambda path: invoked.append(path))
        self.assertEqual(invoked, [])
        with self.assertRaisesRegex(SourceAdmissionError, "SOURCE_READ_PRINCIPAL_MISSING"):
            verify_predecessor_acceptance(BASE, None)

    def test_404_is_a_missing_receipt_not_a_positive_signal(self):
        def read(path):
            raise urllib.error.HTTPError("https://api.github.com", 404, "Not Found", {}, io.BytesIO())
        with self.assertRaisesRegex(SourceAdmissionError, "SOURCE_ACCEPTANCE_NOT_YET_RECORDED"):
            verify_predecessor_acceptance(BASE, read)

    def test_transient_provider_failure_never_becomes_green(self):
        for status in (403, 429, 500, 502, 503, 504):
            def read(path):
                raise urllib.error.HTTPError("https://api.github.com", status, "Service Unavailable", {}, io.BytesIO())
            with self.subTest(status=status), self.assertRaisesRegex(
                SourceAdmissionError, "SOURCE_API_UNAVAILABLE"
            ):
                verify_predecessor_acceptance(BASE, read)

    def test_manual_protected_pr_still_requires_predecessor_attestation(self):
        # No optional v9 enrollment or label is involved: this is the one
        # issuer-pinned independent check GitHub requires on *every* PR merge.
        records = [
            {"head": {"repo": {"full_name": gm.REPO}, "sha": "c" * 40},
             "base": {"repo": {"full_name": gm.REPO}, "ref": "main"}},
            {"commit": {"sha": "b" * 40}},
            {"merge_base_commit": {"sha": "b" * 40}, "files": []},
        ]
        routes = []
        def api(token, path, **kwargs):
            routes.append(path)
            return records.pop(0)
        with patch.object(verifier, "_api", side_effect=api), patch.object(
            verifier, "verify_predecessor_acceptance",
            side_effect=SourceAdmissionError("SOURCE_ACCEPTANCE_NOT_YET_RECORDED"),
        ):
            with self.assertRaisesRegex(SourceAdmissionError, "SOURCE_ACCEPTANCE_NOT_YET_RECORDED"):
                verifier.verify_exact_head(
                    token="independent-verifier-token", pr_number=901,
                    expected_head_sha="c" * 40, full_exit=0,
                    phase1_exit=0, operating_exit=0,
                )
        self.assertFalse(any("/check-runs?" in path for path in routes))
        self.assertEqual(len(routes), 3)

    def test_trusted_verifier_change_remains_self_protected(self):
        self.assertIn("verification/independent_verifier.py", verifier.IMMUTABLE_TRUST_ANCHORS)
        self.assertIn("verification/source_admission.py", verifier.IMMUTABLE_TRUST_ANCHORS)
        self.assertIn("brain/v9/guarded_merge.py", verifier.IMMUTABLE_TRUST_ANCHORS)


if __name__ == "__main__":
    unittest.main()
