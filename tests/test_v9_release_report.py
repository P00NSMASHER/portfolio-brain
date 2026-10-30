"""Adversarial, offline tests of v9's non-authoritative report compiler."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from verification import v9_release_report as report


SRC = "4" * 40


def census():
    return {
        "production_source": SRC,
        "status": "WINDOW_RUNNING_NOT_ACCEPTED",
        "acceptance_pass": False,
        "release_or_merge_authorized": False,
        "external_cloudflare_provider_accepted": False,
        "verified_original_cores": 3,
        "completion_span_seconds": 3766,
        "maximum_gap_seconds": 1967,
        "seconds_remaining_minimum": 39434,
        "anchor_run": 39347813668,
        "latest_run": 39353850712,
        "last_sequence": 3425,
        "last_state_commit": "a" * 40,
        "last_raw_sha256": "b" * 64,
        "last_canonical_hash": "c" * 64,
        "historical_adverse_automatic_cores": [],
        "superseded_earlier_successful_cores": 0,
        "anchor_completion_utc": "2026-10-20T00:29:27+00:00",
        "latest_completion_utc": "2026-10-20T01:32:13+00:00",
    }


def provisional():
    return {
        "status": "PRELIMINARY_RAW_SQLITE_REPLAY_PASSED_NOT_ACCEPTANCE",
        "reviewed_source": SRC,
        "state_commit": "a" * 40,
        "sequence": 3425,
        "raw_sqlite_sha256": "b" * 64,
        "pending_events": 0,
        "source_released": False,
        "merge_authorized": False,
        "external_provider_complete": False,
    }


class ReleaseDigestTests(unittest.TestCase):
    def test_original_early_window_never_certifies_even_with_clean_sqlite(self):
        found = report.compile_report(census(), provisional(), source_sha=SRC)
        self.assertEqual(found["completed_span_seconds"], 3766)
        self.assertEqual(found["state_replay_result"],
                         "PRELIMINARY_RAW_SQLITE_REPLAY_PASSED_NOT_ACCEPTANCE")
        self.assertEqual(found["seconds_remaining_minimum"], 39434)
        self.assertFalse(found["production_accepted"])
        self.assertFalse(found["merge_authorized"])
        self.assertFalse(found["auto_merge_enrollment_authorized"])
        self.assertFalse(found["external_provider_authenticated_by_this_module"])

    def test_technical_window_later_still_requires_separate_cloudflare_and_owner(self):
        proof = census()
        proof.update(status="TWELVE_HOUR_ORIGINAL_GITHUB_EVIDENCE_VERIFIED",
                     completion_span_seconds=43260, maximum_gap_seconds=2000,
                     verified_original_cores=25,latest_completion_utc="2026-10-20T12:30:27+00:00")
        proof.pop("seconds_remaining_minimum")
        proof["terminal_replay"] = {
            "status": "ORIGINAL_TERMINAL_RAW_SQLITE_REPLAY_VERIFIED",
            "terminal_source_sha": SRC,
            "terminal_state_commit": "a" * 40,
            "sequence": 3425,
            "pending_events": 0,
            "restored_sqlite_sha256": "b" * 64,
            "authorizes_production_release": False,
        }
        result = report.compile_report(proof, source_sha=SRC)
        self.assertEqual(result["seconds_remaining_minimum"], 0)
        self.assertIn("INDEPENDENT_CLOUDFLARE_ORIGINAL_PROVIDER_CORRELATION",
                      result["review_queue"])
        self.assertFalse(result["owner_governance_approved_by_this_module"])
        self.assertFalse(result["production_accepted"])
        self.assertFalse(result["merge_authorized"])

    def test_six_hour_historical_status_is_not_current_readiness(self):
        x = census()
        x.update(status="SIX_HOUR_ORIGINAL_GITHUB_EVIDENCE_VERIFIED",
                 completion_span_seconds=22000, maximum_gap_seconds=2000,
                 verified_original_cores=12,
                 latest_completion_utc="2026-10-20T06:36:07+00:00")
        x.pop("seconds_remaining_minimum")
        with self.assertRaisesRegex(report.EvidenceError,
                                    "CENSUS_STATUS_UNTRUSTED"):
            report.compile_report(x, source_sha=SRC)

    def test_forced_pass_status_without_seconds_is_denied(self):
        x = census()
        x["status"] = "TWELVE_HOUR_ORIGINAL_GITHUB_EVIDENCE_VERIFIED"
        with self.assertRaisesRegex(report.EvidenceError,
                                    "WINDOW_STATUS_CONTRADICTION"):
            report.compile_report(x, source_sha=SRC)

    def test_backdated_or_bogus_remaining_seconds_fails(self):
        x = census()
        x["seconds_remaining_minimum"] = 0
        with self.assertRaisesRegex(report.EvidenceError,
                                    "REMAINING_WINDOW_INCONSISTENT"):
            report.compile_report(x, source_sha=SRC)

    def test_wrong_source_bad_original_state_and_corrupted_gap_fail(self):
        for key, value in (
            ("production_source", "b" * 40),
            ("last_state_commit", "not a SHA"),
            ("last_raw_sha256", "b" * 63),
            ("maximum_gap_seconds", 5401),
            ("verified_original_cores", True),
        ):
            with self.subTest(key=key):
                x = census()
                x[key] = value
                with self.assertRaises(report.EvidenceError):
                    report.compile_report(x, source_sha=SRC)

    def test_forged_approval_and_missing_negative_flags_fail(self):
        for key in ("acceptance_pass", "release_or_merge_authorized",
                    "external_cloudflare_provider_accepted"):
            for value in (True, None, "false"):
                with self.subTest(key=key, value=value):
                    x = census()
                    x[key] = value
                    with self.assertRaisesRegex(report.EvidenceError,
                                                "TECHNICAL_REPORT_MUST_NOT_SELF_APPROVE"):
                        report.compile_report(x, source_sha=SRC)

    def test_replay_cannot_borrow_another_source_or_committed_state(self):
        for key, value in (
            ("reviewed_source", "f" * 40),
            ("state_commit", "f" * 40),
            ("sequence", 999),
            ("pending_events", 1),
            ("pending_events", False),
            ("raw_sqlite_sha256", "e" * 64),
        ):
            with self.subTest(key=key):
                v = provisional()
                v[key] = value
                with self.assertRaises(report.EvidenceError):
                    report.compile_report(census(), v, source_sha=SRC)

    def test_synthetic_provider_flags_never_establish_true_acceptance(self):
        for key in ("source_released", "merge_authorized",
                    "external_provider_complete"):
            v = provisional()
            v[key] = True
            with self.assertRaisesRegex(report.EvidenceError,
                                        "REPLAY_CANNOT_CLAIM_EXTERNAL_APPROVAL"):
                report.compile_report(census(), v, source_sha=SRC)

    def test_source_artifacts_duplicate_keys_and_nan_denied(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            for payload in ('{"key":1,"key":2}', '{"value":NaN}', "{broken}"):
                path.write_text(payload)
                with self.assertRaises(report.EvidenceError):
                    report.read_json(path)

    def test_contradictory_timing_and_adverse_evidence_fail(self):
        for key,value in [('anchor_completion_utc','bad'),('latest_completion_utc','2026-10-19T00:00:00Z'),('verified_original_cores',2),('historical_adverse_automatic_cores',[123]),('superseded_earlier_successful_cores',-1)]:
            x=census();x[key]=value
            with self.subTest(key=key),self.assertRaises(report.EvidenceError):
                report.compile_report(x,source_sha=SRC)

    def test_output_is_deterministic_and_non_authorizing(self):
        first = report.compile_report(census(), provisional(), source_sha=SRC)
        second = report.compile_report(copy.deepcopy(census()),
                                       copy.deepcopy(provisional()), source_sha=SRC)
        self.assertEqual(json.dumps(first, sort_keys=True),
                         json.dumps(second, sort_keys=True))
        self.assertRegex(first["census_sha256"], "^[0-9a-f]{64}$")
        self.assertEqual(first["schema_version"], 1)
        self.assertTrue(first["kind"].startswith("REVIEW_ONLY"))


if __name__ == "__main__":
    unittest.main()
