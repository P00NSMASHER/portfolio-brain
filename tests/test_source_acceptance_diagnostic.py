"""Adversarial unit tests for the read-only original source diagnostic.

These tests use synthetic fixtures only, never source acceptance evidence.
"""
from contextlib import ExitStack
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from verification import source_acceptance_diagnostic as diag

SOURCE = "a" * 40
SECRET_MARKER = "PRIVATE_GITHUB_TOKEN_MUST_NEVER_LEAK"


class FakeAPI:
    def __init__(self, main=SOURCE):
        self.main = main
        self.calls = 2

    def json(self, route):
        if route == "/branches/main":
            return {"commit": {"sha": self.main}}
        raise AssertionError("Unexpected read: " + route)


def successful_summary():
    return {
        "span": 45_000,
        "maximum_gap": 1_800,
        "automatic": [{"id": 100}, {"id": 101}],
        "terminal": {
            "id": 101,
            "state_commit": "c" * 40,
            "state_parent": "b" * 40,
            "sequence": 7,
            "canonical_hash": "d" * 64,
        },
    }


class DiagnosticControlsTests(unittest.TestCase):
    def test_diagnostic_never_reports_release_authority(self):
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(diag, "inventory", return_value=[1, 2, 3]))
            stack.enter_context(mock.patch.object(diag, "window", return_value=[1, 2, 3]))
            stack.enter_context(mock.patch.object(
                diag, "collect_original_runs", return_value=successful_summary(),
            ))
            repair = stack.enter_context(mock.patch.object(
                diag, "verify_terminal_repair_follow_through",
            ))
            replay = stack.enter_context(mock.patch.object(
                diag, "verify_source_state", return_value={
                    "status": "ORIGINAL_BINARY_AND_PROJECTION_VERIFIED_NOT_SOAK_PASS",
                },
            ))
            foundation = stack.enter_context(mock.patch.object(
                diag, "_foundation_run", return_value=42,
            ))
            report = diag.run_probe(FakeAPI(), SOURCE)
        self.assertEqual(report["status"], "DIAGNOSTIC_PREREQUISITES_VERIFIED")
        self.assertEqual(report["stage"], "READONLY_DIAGNOSTIC_COMPLETE")
        self.assertTrue(report["read_only"])
        self.assertIs(report["independent_release_authority"], False)
        self.assertIs(report["owner_aborted_observation_is_not_accepted"], True)
        self.assertIs(report["source_acceptance_receipt_issued"], False)
        self.assertEqual(report["source_history_seconds"], 45_000)
        repair.assert_called_once()
        replay.assert_called_once()
        foundation.assert_called_once()

    def test_main_source_drift_rejected_prior_to_evidence_reads(self):
        with mock.patch.object(diag, "inventory") as inventory:
            result = diag.run_probe(FakeAPI(main="b" * 40), SOURCE)
        inventory.assert_not_called()
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["stage"], "MAIN_EXACT_SOURCE")
        self.assertEqual(result["error_code"], "ORIGINAL_PROOF_NOT_VERIFIED")

    def test_all_stages_reject_private_exception_contents(self):
        scenarios = [
            ("inventory", "SOURCE_CORE_INVENTORY"),
            ("window", "SOURCE_CORE_INVENTORY"),
            ("collect_original_runs", "ORIGINAL_CORE_ARTIFACTS"),
            ("verify_terminal_repair_follow_through", "TERMINAL_REPAIR_FOLLOW_THROUGH"),
            ("verify_source_state", "TERMINAL_SQLITE_REPORT_REPLAY"),
            ("_foundation_run", "ORIGINAL_MAIN_FOUNDATION"),
        ]
        for method, expected_stage in scenarios:
            with self.subTest(method=method), ExitStack() as stack:
                patches = {
                    "inventory": [1, 2, 3],
                    "window": [1, 2, 3],
                    "collect_original_runs": successful_summary(),
                    "verify_terminal_repair_follow_through": None,
                    "verify_source_state": {
                        "status": "ORIGINAL_BINARY_AND_PROJECTION_VERIFIED_NOT_SOAK_PASS",
                    },
                    "_foundation_run": 42,
                }
                for name, value in patches.items():
                    m = stack.enter_context(mock.patch.object(diag, name, return_value=value))
                    if name == method:
                        m.side_effect = RuntimeError(SECRET_MARKER)
                report = diag.run_probe(FakeAPI(), SOURCE)
                self.assertEqual(report["stage"], expected_stage)
                self.assertEqual(report["status"], "BLOCKED")
                self.assertEqual(report["error_code"], "ORIGINAL_PROOF_NOT_VERIFIED")
                self.assertNotIn(SECRET_MARKER, json.dumps(report))
                self.assertIs(report["independent_release_authority"], False)

    def test_insufficient_source_span_fails_before_receipt_or_replay(self):
        summary = successful_summary()
        summary["span"] = 43_199
        with mock.patch.object(diag, "inventory", return_value=[1, 2, 3]), \
             mock.patch.object(diag, "window", return_value=[1, 2, 3]), \
             mock.patch.object(diag, "collect_original_runs", return_value=summary), \
             mock.patch.object(diag, "verify_terminal_repair_follow_through") as repair:
            result = diag.run_probe(FakeAPI(), SOURCE)
        self.assertEqual(result["stage"], "ORIGINAL_TWELVE_HOUR_SPAN")
        self.assertEqual(result["status"], "BLOCKED")
        repair.assert_not_called()

    def test_only_allowlisted_failure_code_can_reach_public_result(self):
        self.assertEqual(diag.error_code(RuntimeError("API_CALL_BUDGET")), "API_CALL_BUDGET")
        self.assertEqual(diag.error_code(RuntimeError(SECRET_MARKER)), "ORIGINAL_PROOF_NOT_VERIFIED")
        self.assertEqual(diag.error_code(RuntimeError("https://private/path?token=secret")),
                         "ORIGINAL_PROOF_NOT_VERIFIED")
        self.assertNotIn("RELEASED", diag.STAGES)
        self.assertNotIn("CERTIFIED", diag.STAGES)

    def test_cli_creates_single_nonacceptance_file_and_never_exposes_token(self):
        fake = FakeAPI()
        result = {"status": "BLOCKED", "stage": "SOURCE_CORE_INVENTORY",
                  "read_only": True, "independent_release_authority": False,
                  "error_code": "API_CALL_BUDGET"}
        with tempfile.TemporaryDirectory() as temp:
            output_path = Path(temp) / "forensics.json"
            output = io.StringIO()
            with mock.patch.object(diag, "GitHubReadOnly", return_value=fake) as transport, \
                 mock.patch.object(diag, "run_probe", return_value=result), \
                 mock.patch.dict(diag.os.environ, {"GITHUB_TOKEN": SECRET_MARKER}), \
                 mock.patch("sys.stdout", output):
                self.assertEqual(diag.main([
                    "--source-sha", SOURCE, "--max-calls", "256",
                    "--output", str(output_path),
                ]), 0)
            self.assertEqual(json.loads(output_path.read_text())["read_limit"], 256)
            self.assertNotIn(SECRET_MARKER, output.getvalue())
            transport.assert_called_once_with(SECRET_MARKER, max_calls=256)
            with self.assertRaises(SystemExit):
                diag.main(["--source-sha", SOURCE, "--output", str(output_path)])

    def test_invalid_source_rejected_without_provider_calls(self):
        with mock.patch.object(diag, "GitHubReadOnly") as connection:
            with self.assertRaises(SystemExit):
                diag.main(["--source-sha", "not-a-sha"])
            connection.assert_not_called()


if __name__ == "__main__":
    unittest.main()
