"""Original-run/immutable-state provenance for optional V7 sanitized advice.

Synthetic private source data only. No release, CI writer, network, schedule,
repo mutation or production acceptance authority.
"""
import hashlib
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from brain.sidecar import finalize, main
from test_brain_sidecar import (
    SOURCE, STATE, PARENT, RUN, delivery, observation
)

SUCCESS = ("success",) * 4


def files(folder, *, manifest=None, receipt=None):
    root = Path(folder)
    original = root / "delivery.json"
    investigation = root / "report.json"
    output = root / "sidecar-status.json"
    original.write_text(json.dumps(delivery() if manifest is None else manifest))
    investigation.write_text(json.dumps(observation() if receipt is None else receipt))
    return original, investigation, output


def bound(d, report, output, *, source=SOURCE, run_id=RUN,
          attempt="1", sha=STATE, stages=SUCCESS):
    return finalize(
        report, output, source, *stages,
        original_delivery=d, original_run_id=run_id,
        original_run_attempt=attempt, published_state_sha=sha,
    )


class OriginalCycleBindingTests(unittest.TestCase):
    def test_verified_original_run_and_state_pins_public_advisory(self):
        with tempfile.TemporaryDirectory() as folder:
            d, r, out = files(folder)
            before = (d.read_bytes(), r.read_bytes())
            result = bound(d, r, out)
            self.assertEqual(result["status"], "OBSERVED_READ_ONLY")
            self.assertIs(result["original_delivery_verified"], True)
            self.assertEqual(result["original_core_run_id"], RUN)
            self.assertEqual(result["original_core_run_attempt"], "1")
            self.assertEqual(result["published_state_sha"], STATE)
            self.assertEqual(
                result["original_delivery_sha256"],
                hashlib.sha256(before[0]).hexdigest(),
            )
            self.assertEqual(json.loads(out.read_text()), result)
            self.assertEqual((d.read_bytes(), r.read_bytes()), before)
            self.assertIs(result["root_cause_verified"], False)
            self.assertIs(result["execution_authority"], False)
            self.assertIs(result["production_accepted"], False)
            self.assertEqual(result["events_written"], 0)
            self.assertEqual(result["github_mutations"], 0)
            self.assertEqual(result["paid_calls"], 0)
            self.assertNotIn("script", out.read_text())
            self.assertEqual(out.stat().st_mode & 0o777, 0o600)

    def test_run_id_attempt_published_state_and_source_cannot_be_replayed(self):
        for wrong in (
            {"run_id": "2"}, {"run_id": "0"}, {"run_id": "3"*21},
            {"attempt": "2"}, {"attempt": "0"},
            {"sha": PARENT}, {"sha": "unknown"}, {"sha": ""},
            {"source": PARENT},
        ):
            with self.subTest(wrong=wrong), tempfile.TemporaryDirectory() as folder:
                d, r, out = files(folder)
                result = bound(d, r, out, **wrong)
                self.assertEqual(result["status"], "BLOCKED_NO_VERIFIED_INVESTIGATION")
                self.assertIs(result["original_delivery_verified"], False)
                self.assertIsNone(result["original_core_run_id"])
                self.assertIsNone(result["published_state_sha"])
                self.assertEqual(json.loads(out.read_text()), result)

    def test_modified_and_untrusted_original_core_manifest_rejected(self):
        changes = (
            {"run_id": "50"},
            {"run_attempt": "3"},
            {"source_sha": PARENT},
            {"state_commit": PARENT},
            {"state_commit": "untrusted"},
            {"schema_version": True},
            {"publication_verified": 1},
            {"publication_verified": False},
            {"soak_completed": True},
            {"workflow": "fake-action"},
            {"execution_boundary": "TRADE_WRITE"},
            {"state_parent": None},
            {"added_secret": "UNTRUSTED_SENTINEL"},
        )
        for changed in changes:
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as folder:
                d, r, out = files(folder, manifest=delivery(**changed))
                result = bound(d, r, out)
                self.assertEqual(result["status"], "BLOCKED_NO_VERIFIED_INVESTIGATION")
                self.assertIs(result["original_delivery_verified"], False)
                self.assertNotIn("UNTRUSTED_SENTINEL", out.read_text())

    def test_missing_invalid_or_oversized_original_manifest_blocks_green(self):
        with tempfile.TemporaryDirectory() as folder:
            d, r, out = files(folder)
            d.unlink()
            self.assertEqual(bound(d, r, out)["status"],
                             "BLOCKED_NO_VERIFIED_INVESTIGATION")
            d.write_text("{broken JSON")
            self.assertEqual(bound(d, r, out)["status"],
                             "BLOCKED_NO_VERIFIED_INVESTIGATION")
            d.write_bytes(b"X" * 8193)
            self.assertEqual(bound(d, r, out)["status"],
                             "BLOCKED_NO_VERIFIED_INVESTIGATION")
            d.write_text("null")
            self.assertEqual(bound(d, r, out)["status"],
                             "BLOCKED_NO_VERIFIED_INVESTIGATION")
            self.assertIsNone(json.loads(out.read_text())["published_state_sha"])

    @unittest.skipUnless(os.name == "posix", "POSIX symlink and inode checks")
    def test_symlink_and_multilink_core_manifest_never_authenticated(self):
        with tempfile.TemporaryDirectory() as folder:
            d, r, out = files(folder)
            backing = Path(folder) / "original"
            backing.write_bytes(d.read_bytes())
            d.unlink()
            d.symlink_to(backing)
            self.assertEqual(bound(d, r, out)["status"],
                             "BLOCKED_NO_VERIFIED_INVESTIGATION")
            d.unlink()
            os.link(backing, d)
            self.assertEqual(bound(d, r, out)["status"],
                             "BLOCKED_NO_VERIFIED_INVESTIGATION")

    def test_partial_original_evidence_is_still_partial_even_if_core_bound(self):
        with tempfile.TemporaryDirectory() as folder:
            data = observation(
                status="BOUNDED_READ_ONLY_REVALIDATION_COMPLETE_WITH_DEFERRED",
                eligible_count=2, deferred_count=1,
            )
            d, r, out = files(folder, receipt=data)
            summary = bound(d, r, out)
            self.assertEqual(summary["status"], "PARTIAL_READ_ONLY")
            self.assertIs(summary["original_delivery_verified"], True)
            self.assertFalse(summary["root_cause_verified"])
            self.assertFalse(summary["execution_authority"])

    def test_untrusted_or_missing_private_receipt_is_blocked_not_attested_green(self):
        with tempfile.TemporaryDirectory() as folder:
            d, r, out = files(folder)
            r.unlink()
            result = bound(d, r, out)
            self.assertEqual(result["status"], "BLOCKED_NO_VERIFIED_INVESTIGATION")
            self.assertIs(result["original_delivery_verified"], False)
            r.write_text("not JSON")
            result = bound(d, r, out)
            self.assertEqual(result["status"], "BLOCKED_NO_VERIFIED_INVESTIGATION")
            self.assertIs(result["original_delivery_verified"], False)

    def test_partial_missing_argument_never_downgrades_to_unbound_green(self):
        with tempfile.TemporaryDirectory() as folder:
            d, r, out = files(folder)
            for kwargs in (
                {"original_delivery": d},
                {"original_run_id": RUN},
                {"original_run_id": RUN, "original_run_attempt": "1"},
                {"original_delivery": d, "original_run_attempt": "1",
                 "published_state_sha": STATE},
            ):
                with self.subTest(kwargs=kwargs):
                    result = finalize(r, out, SOURCE, *SUCCESS, **kwargs)
                    self.assertEqual(result["status"],
                                     "BLOCKED_NO_VERIFIED_INVESTIGATION")
                    self.assertIs(result["original_delivery_verified"], False)

    def test_original_stages_cannot_be_made_green_by_valid_manifest(self):
        for index in range(4):
            stages = ["success"] * 4
            stages[index] = "failure"
            with self.subTest(stage=index), tempfile.TemporaryDirectory() as folder:
                d, r, out = files(folder)
                result = bound(d, r, out, stages=stages)
                self.assertNotEqual(result["status"], "OBSERVED_READ_ONLY")
                self.assertFalse(result["production_accepted"])
                self.assertFalse(result["root_cause_verified"])

    def test_published_core_run_rebound_cli_is_sanitized(self):
        with tempfile.TemporaryDirectory() as folder:
            d, r, out = files(folder)
            arguments = [
                "finalize", "--receipt", str(r), "--output", str(out),
                "--source-sha", SOURCE,
                "--downloaded", "success", "--proven", "success",
                "--state", "success", "--investigated", "success",
                "--original-delivery", str(d),
                "--original-run-id", RUN,
                "--original-run-attempt", "1",
                "--published-state-sha", STATE,
            ]
            with redirect_stdout(io.StringIO()):
                exit_code = main(arguments)
            self.assertEqual(exit_code, 0)
            result = json.loads(out.read_text())
            self.assertEqual(result["original_core_run_id"], RUN)
            self.assertEqual(result["original_core_run_attempt"], "1")
            self.assertEqual(result["published_state_sha"], STATE)
            self.assertIs(result["original_delivery_verified"], True)
            with redirect_stdout(io.StringIO()):
                exit_code = main(arguments[:-1] + [PARENT])
            self.assertEqual(exit_code, 0)
            result = json.loads(out.read_text())
            self.assertEqual(result["status"], "BLOCKED_NO_VERIFIED_INVESTIGATION")

    def test_legacy_no_provenance_has_explicitly_unverified_binding(self):
        with tempfile.TemporaryDirectory() as folder:
            d, r, out = files(folder)
            result = finalize(r, out, SOURCE, *SUCCESS)
            self.assertEqual(result["status"], "OBSERVED_READ_ONLY")
            self.assertIs(result["original_delivery_verified"], False)
            self.assertIsNone(result["original_core_run_id"])
            self.assertIsNone(result["published_state_sha"])


class SidecarWorkflowProtectionTests(unittest.TestCase):
    def test_original_core_bytes_and_original_cron_unmodified(self):
        workflow = (Path(__file__).resolve().parents[1]
                    / ".github/workflows/brain-cycle.yml").read_text()
        original = workflow.split("  readonly_investigation:\n", 1)[0].rstrip("\n") + "\n"
        self.assertEqual(hashlib.sha256(original.encode()).hexdigest(),
                         "32b92383ccbaeb9b1b2e14ac1ad78418ffd72775724e5784c67dc1ad001df2d4")
        self.assertIn('cron: "7,27,47 * * * *"', original)
        self.assertIn("group: brain-v2-state", original)
        child = workflow.split("  readonly_investigation:\n", 1)[1]
        self.assertIn("contents: read", child)
        self.assertIn("actions: read", child)
        self.assertIn("continue-on-error: true", child)
        self.assertNotIn("contents: write", child)
        self.assertNotIn("actions: write", child)
        self.assertIn("--original-delivery /tmp/brain-v7-original/delivery.json", child)
        self.assertIn('--original-run-id "$GITHUB_RUN_ID"', child)
        self.assertIn('--original-run-attempt "$GITHUB_RUN_ATTEMPT"', child)
        self.assertIn('--published-state-sha "$PINNED_PUBLISHED_STATE_SHA"', child)
        self.assertIn("steps.source.outputs.state_sha", child)
        self.assertIn("python -m brain.sidecar prepare", child)
        self.assertIn("python -m brain.sidecar finalize", child)
        self.assertNotIn("path: /tmp/brain-v7/investigation", child)
