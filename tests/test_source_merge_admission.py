"""Hostile acceptance-census and manual merge-path tests; no network or App writes."""
import base64
import copy
import hashlib
import json
import unittest
import urllib.error
from unittest.mock import patch

from brain.v9.guarded_merge import REPO, git_blob_sha
from verification import independent_verifier as independent
from verification.source_admission import (
    SourceAdmissionError, verify_predecessor_acceptance,
)
from test_source_acceptance_verifier import valid_receipt

SOURCE = "a" * 40
TIP = "b" * 40
DATE = "20261024"
BRANCH = "auto-repair/pb-01-acceptance-receipt-" + SOURCE[:8] + "-" + DATE
PATH = "acceptance/finish-soak-" + SOURCE[:8] + "-" + DATE + ".json"


def authentic_receipt():
    receipt = valid_receipt()
    receipt["source_sha"] = SOURCE
    receipt["decision_date_utc"] = "2026-10-25"
    run = receipt["original_run_evidence"]
    run.update(
        completed_span_seconds=43201, maximum_gap_seconds=1800,
        original_qualifying_cores=24, original_signed_cloudflare_dispatched_cores=24,
        original_github_native_schedule_cores=0, source_run_census_count=24,
        first_original_run_id=101, terminal_original_run_id=125,
        terminal_original_monitor_completed_utc="2026-10-25T00:31:01Z",
    )
    terminal = receipt["terminal_state_replay"]
    terminal.update(
        source_sha=SOURCE, pending_events=0, sqlite_integrity="PASS",
        foreign_keys="PASS", strict_event_ledger_replay="PASS",
        deterministic_report_reproduction="PASS",
        terminal_replay_status="ORIGINAL_TERMINAL_RAW_SQLITE_REPLAY_VERIFIED",
    )
    external = receipt["external_cloudflare_provider"]
    external.update(
        signed_dispatch_count=24,
        signed_dispatch_timestamps_utc=["2026-10-24T10:31:00Z"],
        all_signed_origin_records_source_bound=True,
        all_origin_verification_steps_success=True,
    )
    proof = receipt["proof"]
    proof.update(
        technical_workflow_run_id=42,
        technical_workflow_run_attempt=1,
        technical_workflow_conclusion="success",
        technical_audit_url="https://github.com/" + REPO + "/actions/runs/42",
        hosted_review_result_source_bound=True,
    )
    return receipt


class OriginalProvider:
    """Faithful canonical producer ref, bytes and independent App attestation."""
    def __init__(self):
        self.receipt = authentic_receipt()
        self.refs = [{"ref": "refs/heads/" + BRANCH,
                      "object": {"sha": TIP, "type": "commit"}}]
        self.commit = {"sha": TIP, "parents": [{"sha": SOURCE}]}
        self.compare = {
            "ahead_by": 1, "behind_by": 0,
            "merge_base_commit": {"sha": SOURCE},
            "files": [{"filename": PATH, "status": "added"}],
        }
        self.main = {"protected": True, "commit": {"sha": SOURCE}}
        self.issuer = 5121826
        self.binding_override = None
        self.paid = False
        self.calls = []

    def get(self, route):
        self.calls.append(route)
        raw = (json.dumps(self.receipt, indent=2, sort_keys=True,
                          allow_nan=False) + "\n").encode()
        if route == "/git/matching-refs/heads/auto-repair/pb-01-acceptance-receipt-" + SOURCE[:8] + "-":
            return copy.deepcopy(self.refs)
        if route == "/git/commits/" + TIP:
            return copy.deepcopy(self.commit)
        if route == "/compare/" + SOURCE + "..." + TIP:
            return copy.deepcopy(self.compare)
        if route == "/contents/" + PATH + "?ref=" + TIP:
            return {"type": "file", "encoding": "base64", "size": len(raw),
                    "sha": git_blob_sha(raw),
                    "content": base64.b64encode(raw).decode()}
        if route == "/commits/" + TIP + "/check-runs?per_page=100":
            binding = "source-acceptance:" + SOURCE + ":" + hashlib.sha256(raw).hexdigest()
            return {"total_count": 1, "check_runs": [{
                "id": 700, "head_sha": TIP, "name": "portfolio-source-acceptance",
                "app": {"id": self.issuer},
                "external_id": self.binding_override or binding,
                "status": "completed", "conclusion": "success",
            }]}
        if route == "/branches/main":
            return copy.deepcopy(self.main)
        raise AssertionError("unexpected provider endpoint: " + route)


class SourceMergeAdmissionTests(unittest.TestCase):
    def verify(self, provider):
        return verify_predecessor_acceptance(SOURCE, provider.get)

    def test_canonical_producer_branch_with_real_app_receipt_is_admitted(self):
        provider = OriginalProvider()
        proof = self.verify(provider)
        self.assertEqual(proof["acceptance_ref"], BRANCH)
        self.assertEqual(proof["acceptance_commit"], TIP)
        self.assertEqual(len(provider.calls), 6)
        self.assertEqual(provider.calls[-1], "/branches/main")

    def test_legacy_branch_must_not_substitute_for_canonical_producer(self):
        provider = OriginalProvider()
        provider.refs[0]["ref"] = "refs/heads/brain-acceptance-" + SOURCE[:8] + "-" + DATE
        with self.assertRaisesRegex(SourceAdmissionError, "ACCEPTANCE_BRANCH_IDENTITY"):
            self.verify(provider)

    def test_no_receipt_and_no_fabricated_producer_branch(self):
        provider = OriginalProvider()
        provider.refs = []
        with self.assertRaisesRegex(SourceAdmissionError, "SOURCE_ACCEPTANCE_NOT_YET_RECORDED"):
            self.verify(provider)
        self.assertEqual(len(provider.calls), 1)

    def test_missing_ref_provider_404_is_not_accepted(self):
        def missing(_):
            raise urllib.error.HTTPError(
                "https://api.github.com", 404, "Not Found", {}, None)
        with self.assertRaisesRegex(SourceAdmissionError, "SOURCE_ACCEPTANCE_NOT_YET_RECORDED"):
            verify_predecessor_acceptance(SOURCE, missing)

    def test_duplicate_receipt_refs_are_denied(self):
        provider = OriginalProvider()
        provider.refs.append(copy.deepcopy(provider.refs[0]))
        with self.assertRaisesRegex(SourceAdmissionError, "ACCEPTANCE_BRANCH_NOT_UNIQUE"):
            self.verify(provider)

    def test_wrong_source_ancestry_and_bogus_changed_file_denied(self):
        for mutant, code in [
            (lambda p: p.commit["parents"][0].update(sha="f" * 40), "ACCEPTANCE_COMMIT_ANCESTRY"),
            (lambda p: p.compare["files"][0].update(filename=".github/override.yml"), "ACCEPTANCE_BRANCH_SCOPE"),
            (lambda p: p.compare.update(ahead_by=2), "ACCEPTANCE_BRANCH_SCOPE"),
            (lambda p: p.main["commit"].update(sha="f" * 40), "ACCEPTANCE_MAIN_MOVED"),
            (lambda p: p.main.update(protected=False), "ACCEPTANCE_MAIN_MOVED"),
        ]:
            p = OriginalProvider()
            mutant(p)
            with self.subTest(code=code), self.assertRaisesRegex(SourceAdmissionError, code):
                self.verify(p)

    def test_less_than_twelve_completed_hours_denied(self):
        p = OriginalProvider()
        p.receipt["original_run_evidence"]["completed_span_seconds"] = 43199
        with self.assertRaisesRegex(SourceAdmissionError, "ACCEPTANCE_ORIGINAL_EVIDENCE_MISSING"):
            self.verify(p)

    def test_discarded_six_hour_contract_denied(self):
        p = OriginalProvider()
        p.receipt["criteria"]["minimum_completed_span_seconds"] = 21600
        with self.assertRaisesRegex(SourceAdmissionError, "ACCEPTANCE_RECEIPT_INVALID"):
            self.verify(p)

    def test_missing_terminal_followthrough_contract_denied(self):
        p = OriginalProvider()
        p.receipt["criteria"]["requires_terminal_30_minute_repair_follow_through"] = False
        with self.assertRaisesRegex(SourceAdmissionError, "ACCEPTANCE_RECEIPT_INVALID"):
            self.verify(p)

    def test_bad_gap_missing_original_step_and_nonzero_backlog_denied(self):
        for group, key, value in [
            ("original_run_evidence", "maximum_gap_seconds", 5401),
            ("original_run_evidence", "all_success_attempt_one", False),
            ("original_run_evidence", "all_required_original_job_steps_success", False),
            ("original_run_evidence", "all_original_core_state_parent_child_links_contiguous", False),
            ("external_cloudflare_provider", "all_signed_origin_records_source_bound", False),
            ("terminal_state_replay", "pending_events", 1),
            ("terminal_state_replay", "strict_event_ledger_replay", "FAIL"),
        ]:
            p = OriginalProvider()
            p.receipt[group][key] = value
            with self.subTest(group=group, key=key), self.assertRaises(SourceAdmissionError):
                self.verify(p)

    def test_wrong_issuer_or_receipt_hash_cannot_authorize(self):
        p = OriginalProvider()
        p.issuer = 15368
        with self.assertRaisesRegex(SourceAdmissionError, "ACCEPTANCE_ATTESTATION_UNVERIFIED"):
            self.verify(p)
        p = OriginalProvider()
        p.binding_override = "source-acceptance:" + SOURCE + ":" + "f" * 64
        with self.assertRaisesRegex(SourceAdmissionError, "ACCEPTANCE_ATTESTATION_UNVERIFIED"):
            self.verify(p)

    def test_source_specific_receipt_cannot_certify_another_main_sha(self):
        p = OriginalProvider()
        p.receipt["source_sha"] = "f" * 40
        with self.assertRaisesRegex(SourceAdmissionError, "ACCEPTANCE_STATUS_OR_SOURCE"):
            self.verify(p)

    def test_invalid_or_extra_receipt_claim_denied(self):
        p = OriginalProvider()
        p.receipt["proof"]["revenue_verified"] = True
        with self.assertRaisesRegex(SourceAdmissionError, "ACCEPTANCE_RECEIPT_INVALID"):
            self.verify(p)

    def test_transient_provider_error_denies_without_retry(self):
        for status in (403, 429, 500, 502, 503, 504):
            def fail(_):
                raise urllib.error.HTTPError(
                    "https://api.github.com", status, "unavailable", {}, None)
            with self.subTest(status=status), self.assertRaisesRegex(
                SourceAdmissionError, "SOURCE_API_UNAVAILABLE"
            ):
                verify_predecessor_acceptance(SOURCE, fail)

    def test_any_write_or_unreviewed_read_is_denied(self):
        p = OriginalProvider()
        with self.assertRaisesRegex(SourceAdmissionError, "SOURCE_API_ROUTE_DENIED"):
            # Only GET routes from the reviewed source-specific proof are permitted.
            verify_predecessor_acceptance(SOURCE, lambda path:
                p.get(path) if path.startswith("/git/matching-refs/") else 1)
        # The original real branch identity is independent of any fake 2xx.

    def test_independent_gate_blocks_owner_manual_merge_without_source_acceptance(self):
        responses = [
            {"head": {"repo": {"full_name": REPO}, "sha": "c" * 40},
             "base": {"repo": {"full_name": REPO}, "ref": "main"}},
            {"commit": {"sha": SOURCE}},
            {"merge_base_commit": {"sha": SOURCE}, "files": []},
        ]
        with patch.object(independent, "_api", side_effect=responses), patch.object(
            independent, "verify_predecessor_acceptance",
            side_effect=SourceAdmissionError("SOURCE_ACCEPTANCE_NOT_YET_RECORDED"),
        ):
            with self.assertRaisesRegex(SourceAdmissionError, "SOURCE_ACCEPTANCE_NOT_YET_RECORDED"):
                independent.verify_exact_head(
                    token="independent-token", pr_number=804,
                    expected_head_sha="c" * 40,
                    full_exit=0, phase1_exit=0, operating_exit=0,
                )

    def test_verifier_and_receipt_source_are_immutable_trust_anchors(self):
        for name in ("verification/independent_verifier.py",
                     "verification/source_admission.py",
                     "brain/v9/guarded_merge.py"):
            self.assertIn(name, independent.IMMUTABLE_TRUST_ANCHORS)


if __name__ == "__main__":
    unittest.main()
