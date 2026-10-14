"""V7 strict read-only original-provider inventory: never release authority."""
import contextlib
import copy
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from brain.core import BrainError
from brain.soak_inventory import audit_run_inventory, main

SHA = "f39a8b2ad88b6e1f0db246b586c89a9d611a566c"
OLD = "a" * 40
CHECKED = "2026-10-14T00:10:00Z"


def run(number, *, event="workflow_dispatch", conclusion="success",
        status="completed", sha=SHA, when="2026-10-13T13:00:00Z",
        created="2026-10-13T12:59:00Z", attempt=1):
    return {
        "run_id": number, "run_attempt": attempt,
        "workflow": "brain-cycle-v2", "head_sha": sha,
        "event": event, "status": status, "conclusion": conclusion,
        "created_at": created, "updated_at": when,
    }


def assess(*rows, complete=False):
    return audit_run_inventory(list(rows), expected_sha=SHA,
                               checked_at=CHECKED,
                               provider_pagination_complete=complete)


class SoakInventoryTests(unittest.TestCase):
    def test_all_dispatch_successes_never_certify_six_hour_native_origin(self):
        records = [
            run(101, when="2026-10-13T13:00:00Z"),
            run(102, when="2026-10-13T17:00:00Z",
                created="2026-10-13T16:59:00Z"),
            run(103, when="2026-10-13T23:05:00Z",
                created="2026-10-13T23:04:00Z"),
        ]
        report = assess(*records, complete=True)
        self.assertEqual(report["status"],
                         "ORIGINAL_SIGNED_AND_BINARY_EVIDENCE_REQUIRED")
        self.assertEqual(report["category_counts"],
                         {"DISPATCH_ORIGIN_NOT_AUTHENTICATED": 3})
        self.assertEqual(report["native_schedule_success_candidates"], 0)
        self.assertIsNone(report["provider_update_span_seconds_NOT_COMPLETION_PROOF"])
        self.assertFalse(report["six_hour_source_window_verified"])
        self.assertFalse(report["production_accepted"])
        self.assertFalse(report["release_authority"])
        self.assertTrue(report["caller_claims_pagination_complete_NOT_AUTHENTICATED"])

    def test_original_push_is_nonqualifying_even_when_green(self):
        data = assess(run(1, event="push"))
        self.assertEqual(data["category_counts"], {"PUSH_SMOKE_NONQUALIFYING": 1})
        self.assertFalse(data["original_github_zip_verified_here"])

    def test_native_schedules_longer_than_six_hours_still_need_signed_original_artifacts(self):
        first = run(1, event="schedule", when="2026-10-13T15:00:00Z")
        second = run(2, event="schedule",
                     created="2026-10-13T22:02:00Z",
                     when="2026-10-13T22:03:00Z")
        data = assess(second, first)
        self.assertEqual(data["native_schedule_success_candidates"], 2)
        self.assertEqual(data["provider_update_span_seconds_NOT_COMPLETION_PROOF"],
                         7*3600+180)
        self.assertEqual(data["provider_update_max_gap_seconds_NOT_COMPLETION_PROOF"],
                         7*3600+180)
        self.assertFalse(data["six_hour_source_window_verified"])
        self.assertFalse(data["independent_sqlite_replay_verified_here"])
        self.assertNotEqual(data["status"], "PASS")
        self.assertFalse(data["production_accepted"])

    def test_one_failed_native_schedule_blocks_clean_story(self):
        result = assess(
            run(1, event="schedule"),
            run(2, event="schedule", conclusion="failure",
                when="2026-10-13T16:00:00Z",
                created="2026-10-13T15:59:00Z"),
            run(3, event="workflow_dispatch",
                when="2026-10-13T17:00:00Z",
                created="2026-10-13T16:59:00Z"),
        )
        self.assertEqual(result["exact_source_failures_observed"], 1)
        self.assertEqual(result["category_counts"], {
            "NATIVE_SCHEDULE_SUCCESS_ARTIFACT_NOT_VERIFIED": 1,
            "EXACT_SOURCE_FAILED": 1,
            "DISPATCH_ORIGIN_NOT_AUTHENTICATED": 1,
        })
        self.assertEqual(result["status"], "EXACT_SOURCE_FAILURES_REVIEW_REQUIRED")
        self.assertFalse(result["release_authority"])

    def test_original_source_mismatch_cannot_substitute_for_v6_progress(self):
        report = assess(run(1, sha=OLD), run(2, sha=SHA))
        self.assertEqual(report["category_counts"], {
            "OTHER_SOURCE_EXCLUDED": 1,
            "DISPATCH_ORIGIN_NOT_AUTHENTICATED": 1,
        })
        self.assertEqual(report["native_schedule_success_candidates"], 0)

    def test_unfinished_cancelled_and_failed_attempts_remain_visible(self):
        report = assess(
            run(1, status="in_progress", conclusion=None),
            run(2, status="completed", conclusion="cancelled",
                when="2026-10-13T14:00:00Z",
                created="2026-10-13T13:59:00Z"),
            run(3, status="completed", conclusion="success",
                when="2026-10-13T15:00:00Z",
                created="2026-10-13T14:59:00Z"),
        )
        self.assertEqual(report["exact_source_failures_observed"], 1)
        self.assertEqual(report["exact_source_nonterminal_observed"], 1)
        self.assertEqual(report["observed_run_attempts"], 3)
        self.assertEqual(report["status"], "EXACT_SOURCE_FAILURES_REVIEW_REQUIRED")

    def test_rerun_attempt_does_not_erase_failed_original_attempt(self):
        report = assess(
            run(5, attempt=1, conclusion="failure"),
            run(5, attempt=2, conclusion="success"),
        )
        self.assertEqual(report["exact_source_failures_observed"], 1)
        self.assertEqual(report["observed_run_attempts"], 2)
        self.assertFalse(report["production_accepted"])

    def test_duplicate_provider_attempt_rejected_even_if_one_row_different(self):
        a = run(5)
        b = {**run(5), "event": "schedule"}
        with self.assertRaises(BrainError):
            assess(a, b)

    def test_untrusted_conclusion_status_pairings_fail_closed(self):
        for update in (
            {"status":"in_progress", "conclusion":"success"},
            {"status":"completed", "conclusion":None},
            {"status":"pending", "conclusion":"failure"},
            {"status":"completed", "conclusion":"UNKNOWN"},
            {"status":"green", "conclusion":"success"},
            {"event":"SCHEDULE", "conclusion":"success"},
        ):
            with self.subTest(update=update), self.assertRaises(BrainError):
                assess({**run(1), **update})

    def test_unknown_fields_are_not_copied_into_private_report_or_html(self):
        forged = run(1)
        forged["private_token"] = "SECRET_SENTINEL"
        with self.assertRaises(BrainError):
            assess(forged)
        legitimate = assess(run(1))
        self.assertNotIn("SECRET_SENTINEL", json.dumps(legitimate))
        self.assertEqual(legitimate["github_mutations"], 0)
        self.assertEqual(legitimate["provider_calls_added"], 0)

    def test_bool_int_wrong_sha_bad_attempt_and_noncore_workflow_rejected(self):
        bad = (
            {"run_id":True}, {"run_attempt":False}, {"run_attempt":0},
            {"head_sha":"short"}, {"head_sha":None},
            {"workflow":"foundation-ci"}, {"created_at":"bad"},
            {"updated_at":"2026-10-10T00:00:00Z"},
            {"updated_at":"2027-01-01T00:00:00Z"},
        )
        for patch in bad:
            with self.subTest(patch=patch), self.assertRaises(
                (BrainError, ValueError)
            ):
                assess({**run(1), **patch})

    def test_bad_top_level_and_untrusted_pagination_claims_rejected(self):
        for rows, complete in (
            ({}, False), (None, False), ([run(1)]*251, False),
            ([run(1)], 1), ([run(1)], None),
        ):
            with self.subTest(complete=complete, size=len(rows) if rows else 0):
                with self.assertRaises(BrainError):
                    audit_run_inventory(rows, expected_sha=SHA,
                                        checked_at=CHECKED,
                                        provider_pagination_complete=complete)
        for sha in (None, "x"*40):
            with self.assertRaises(BrainError):
                audit_run_inventory([], expected_sha=sha,
                                    checked_at=CHECKED)

    def test_order_independent_source_facts_and_chronology(self):
        first = run(1)
        second = run(2, when="2026-10-13T13:30:00Z",
                     created="2026-10-13T13:29:00Z")
        self.assertEqual(assess(second, first), assess(first, second))
        self.assertEqual(
            [r["run_id"] for r in assess(second, first)["run_rows"]],
            [1,2],
        )

    def test_fractional_second_provider_updates_sort_by_actual_instant(self):
        older = run(1, when="2026-10-13T13:00:00Z",
                    created="2026-10-13T12:59:00Z")
        newer = run(2, when="2026-10-13T13:00:00.9Z",
                    created="2026-10-13T12:59:00Z")
        self.assertEqual(
            [r["run_id"] for r in assess(newer, older)["run_rows"]],
            [1,2],
        )

    @unittest.skipUnless(os.name=="posix", "private output permissions on POSIX")
    def test_cli_new_private_advisory_does_not_modify_input(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root/"raw.json"
            output = root/"soak-inventory-advisory.json"
            raw = {"workflow_runs":[run(1)], "provider_pagination_complete":False}
            source.write_text(json.dumps(raw))
            before = source.read_bytes()
            with contextlib.redirect_stdout(io.StringIO()):
                code = main(["--input", str(source), "--output",str(output),
                             "--expected-sha",SHA, "--checked-at", CHECKED])
            self.assertEqual(code, 0)
            self.assertEqual(source.read_bytes(), before)
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            data = json.loads(output.read_text())
            self.assertFalse(data["production_accepted"])
            self.assertEqual(data["observed_run_attempts"],1)
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertNotEqual(main([
                    "--input",str(source),"--output",str(output),
                    "--expected-sha",SHA,"--checked-at",CHECKED]),0)
            self.assertEqual(source.read_bytes(),before)

    @unittest.skipUnless(os.name=="posix", "symlink safety requires POSIX")
    def test_cli_input_output_alias_and_symlink_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            source=root/"raw.json"
            source.write_text(json.dumps({
                "workflow_runs":[run(1)],"provider_pagination_complete":False,
            }))
            target=root/"soak-inventory-advisory.json"
            target.symlink_to(source)
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main([
                    "--input",str(source),"--output",str(target),
                    "--expected-sha",SHA,"--checked-at",CHECKED]),1)
            self.assertTrue(target.is_symlink())
            self.assertFalse(json.loads(source.read_text()).get("production_accepted",False))


if __name__ == "__main__":
    unittest.main()
