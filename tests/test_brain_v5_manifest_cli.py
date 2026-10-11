"""V5-only strict manifest intake, never an original provider/terminal receipt.

Tests are synthetic. V3 CLI's historical permissive decoder must remain
unchanged while all three V5 modes reject conflicting JSON and oversized data.
"""
from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from soak_v3.__main__ import V5_MANIFEST_MAX_BYTES, main

SHA = "a" * 40
PARENT = "b" * 40


class StrictV5ManifestCliTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="brain-v5-manifest-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / "evidence.json"

    def empty_window(self):
        return {
            "runs": [],
            "inventory": {
                "coverage_complete": True,
                "provenance": "GITHUB_API_PROVIDER_METADATA",
                "soak_pass": False,
                "core_runs": [],
            },
            "source_sha": SHA,
            "current_main": SHA,
            "first_state_parent": PARENT,
            "started_at": "2026-10-11T00:00:00Z",
            "deadline_at": "2026-10-11T08:00:00Z",
            "now": "2026-10-11T01:00:00Z",
        }

    def invoke(self, mode="window-v5"):
        printed = io.StringIO()
        with redirect_stdout(printed):
            status = main([mode, "--manifest", str(self.path)])
        return status, json.loads(printed.getvalue())

    def write(self, content):
        self.path.write_bytes(
            content.encode("utf-8") if isinstance(content, str) else content
        )
        return self.invoke()

    def test_valid_v5_census_still_waits_without_terminal_acceptance(self):
        self.path.write_text(json.dumps(self.empty_window()))
        status, result = self.invoke()
        self.assertEqual(status, 0)
        self.assertEqual(result["scope"], "NONAUTHORITATIVE_EVIDENCE_INSPECTION")
        self.assertEqual(result["result"]["status"], "WAITING")
        self.assertEqual(result["result"]["reason"], "NO_CYCLES")
        self.assertNotIn("terminal_acceptance", result)
        self.assertEqual(V5_MANIFEST_MAX_BYTES, 8_000_000)

    def test_duplicate_root_keys_do_not_overwrite_original_source(self):
        valid = json.dumps(self.empty_window())
        forged = '{"source_sha":"' + "f" * 40 + '",' + valid[1:]
        status, result = self.write(forged)
        self.assertEqual(status, 1)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["reason"], "V5_JSON_DUPLICATE_KEY")
        # The historical V3 reader retains its last-key-wins behavior.
        legacy_code, legacy = self.invoke("window")
        self.assertEqual(legacy_code, 0)
        self.assertEqual(legacy["result"]["reason"], "NO_CYCLES")

    def test_duplicate_nested_inventory_fields_cannot_hide_census(self):
        original = json.dumps(self.empty_window())
        self.assertEqual(original.count('"coverage_complete": true'), 1)
        conflicting = original.replace(
            '"coverage_complete": true',
            '"coverage_complete": false, "coverage_complete": true',
            1,
        )
        status, result = self.write(conflicting)
        self.assertEqual(status, 1)
        self.assertEqual(result["reason"], "V5_JSON_DUPLICATE_KEY")
        legacy_code, legacy = self.invoke("window")
        self.assertEqual(legacy_code, 0)
        self.assertEqual(legacy["result"]["status"], "WAITING")

    def test_duplicate_runs_member_cannot_drop_failed_records(self):
        original = json.dumps(self.empty_window())
        forged = original.replace(
            '"runs": []',
            '"runs": [{"run_id": 100, "status": "completed",'
            ' "conclusion": "failure"}], "runs": []',
            1,
        )
        status, result = self.write(forged)
        self.assertEqual(status, 1)
        self.assertEqual(result["reason"], "V5_JSON_DUPLICATE_KEY")

    def test_nonfinite_json_rejected_at_any_nested_position(self):
        source = json.dumps(self.empty_window())
        for number in ("NaN", "Infinity", "-Infinity", "1e999"):
            with self.subTest(number=number):
                injected = source.replace(
                    '"soak_pass": false',
                    '"probe": ' + number + ', "soak_pass": false',
                    1,
                )
                status, result = self.write(injected)
                self.assertEqual(status, 1)
                self.assertEqual(result["reason"], "V5_JSON_NONFINITE_NUMBER")

    def test_all_three_v5_modes_reject_duplicate_fields_before_file_io(self):
        forged = '{"path":"/not-real-A","path":"/not-real-B"}'
        self.path.write_text(forged)
        for mode in ("window-v5", "state-v5", "artifact-v5"):
            with self.subTest(mode=mode):
                status, result = self.invoke(mode)
                self.assertEqual(status, 1)
                self.assertEqual(result["reason"], "V5_JSON_DUPLICATE_KEY")

    def test_oversized_v5_manifest_fails_before_opening(self):
        with self.path.open("wb") as file:
            file.truncate(V5_MANIFEST_MAX_BYTES + 1)
        with patch.object(
            Path, "open",
            side_effect=AssertionError("oversized V5 manifest was opened"),
        ):
            status, result = self.invoke()
        self.assertEqual(status, 1)
        self.assertEqual(result["reason"], "V5_MANIFEST_SIZE_INVALID")

    def test_short_local_read_cannot_enter_v5_evaluator(self):
        self.path.write_text(json.dumps(self.empty_window()))
        with patch.object(Path, "open", return_value=io.BytesIO(b"short")):
            status, result = self.invoke()
        self.assertEqual(status, 1)
        self.assertEqual(
            result["reason"], "V5_MANIFEST_SIZE_CHANGED_DURING_READ"
        )

    def test_invalid_or_nonobject_v5_manifest_is_blocked(self):
        for payload, reason in (
            ("[]", "MANIFEST_NOT_OBJECT"),
            ('{"runs": [}', "Expecting value"),
            ("", "V5_MANIFEST_SIZE_INVALID"),
        ):
            with self.subTest(payload=payload):
                status, result = self.write(payload)
                self.assertEqual(status, 1)
                self.assertIn(reason, result["reason"])

    def test_external_cli_v5_output_remains_non_authoritative(self):
        self.path.write_text(json.dumps(self.empty_window()))
        call = subprocess.run(
            [sys.executable, "-m", "soak_v3", "window-v5",
             "--manifest", str(self.path)],
            capture_output=True, text=True, check=False, timeout=15,
        )
        self.assertEqual(call.returncode, 0, call.stderr)
        result = json.loads(call.stdout)
        self.assertEqual(
            result["scope"], "NONAUTHORITATIVE_EVIDENCE_INSPECTION"
        )
        self.assertEqual(result["result"]["status"], "WAITING")
        self.assertNotIn("PASS", call.stdout)


if __name__ == "__main__":
    unittest.main()
