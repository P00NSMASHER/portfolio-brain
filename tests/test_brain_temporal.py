"""V7 read-only historic check-pattern evidence; all inputs are synthetic."""
import copy
import hashlib
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from brain.adapters import GitHub
from brain.core import BrainError, Store
from brain.investigate import investigate, main
from brain.temporal import _SCOPE
from test_brain_evidence_gaps import check, observe, verified, T0, T1
from test_brain_investigate import Transport, REPO, REV, SOURCE, NOW


def sample(at, *, conclusion="failure", kind="ACTUAL", revision=REV,
           status="completed", included=True):
    rows = [check(REPO, conclusion=conclusion, sha=revision, status=status)] if included else []
    return observe(REPO, at, rows, kind=kind, sha=revision)


def follow_up(*events, provider=None):
    report, history = verified(*events)
    original = copy.deepcopy((report, history))
    provider = provider or Transport()
    receipt = investigate(report, history=history,
                          api=GitHub(transport=provider), now=NOW)
    assert (report, history) == original
    return receipt, provider


def original_observations(receipt):
    return receipt["investigations"][0]["checks"][0]["historical_observations"]


class HistoricalCheckPatternTests(unittest.TestCase):
    def test_four_successive_adverse_samples_are_counted_not_outage_minutes(self):
        result, provider = follow_up(
            sample("2026-10-12T12:00:00Z"),
            sample("2026-10-12T13:00:00Z"),
            sample(T0), sample(T1))
        temporal = original_observations(result)
        self.assertEqual(temporal["scope"], _SCOPE)
        self.assertEqual(temporal["terminal_samples"], 4)
        self.assertEqual(temporal["adverse_streak_samples"], 4)
        self.assertEqual(temporal["adverse_streak_first_observed_at"],
                         "2026-10-12T12:00:00Z")
        self.assertEqual(temporal["latest_terminal_observed_at"], T1)
        self.assertEqual(temporal["adverse_success_flips_observed"], 0)
        self.assertIs(temporal["capped_at_12_samples"], False)
        self.assertEqual(result["requests_used"], 4)
        self.assertEqual(len(provider.calls), 4)
        self.assertFalse(result["root_cause_verified"])
        self.assertEqual(result["events_written"], 0)

    def test_two_opposite_terminal_transitions_do_not_infer_flaky_root_cause(self):
        result, _ = follow_up(
            sample("2026-10-12T12:00:00Z", conclusion="failure"),
            sample("2026-10-12T13:00:00Z", conclusion="success"),
            sample(T0, conclusion="failure"),
            sample(T1, conclusion="failure"))
        temporal = original_observations(result)
        self.assertEqual(temporal["adverse_streak_samples"], 2)
        self.assertEqual(temporal["adverse_streak_first_observed_at"], T0)
        self.assertEqual(temporal["terminal_samples"], 4)
        self.assertEqual(temporal["adverse_success_flips_observed"], 2)
        self.assertNotIn("flaky", json.dumps(result).lower())

    def test_observed_recovery_resets_adverse_streak_without_claiming_a_fix(self):
        receipt, _ = follow_up(sample(T0, conclusion="failure"),
                               sample(T1, conclusion="success"),
                               provider=Transport(conclusion="success"))
        pattern = original_observations(receipt)
        self.assertEqual(pattern["adverse_streak_samples"], 0)
        self.assertIsNone(pattern["adverse_streak_first_observed_at"])
        self.assertEqual(pattern["adverse_success_flips_observed"], 1)
        self.assertEqual(receipt["investigations"][0]["checks"][0]["outcome"],
                         "SUCCESS_OBSERVED_NOT_RESOLUTION")
        self.assertFalse(receipt["root_cause_verified"])

    def test_missing_check_breaks_history_not_false_current_adversity(self):
        receipt, _ = follow_up(sample(T0), sample(T1, included=False))
        pattern = original_observations(receipt)
        self.assertEqual(pattern["terminal_samples"], 0)
        self.assertEqual(pattern["adverse_streak_samples"], 0)
        self.assertEqual(pattern["adverse_success_flips_observed"], 0)
        self.assertIsNone(pattern["latest_terminal_observed_at"])

    def test_pending_check_breaks_history_without_skipping_observation(self):
        receipt, _ = follow_up(sample(T0),
                               sample(T1, conclusion=None, status="in_progress"))
        pattern = original_observations(receipt)
        self.assertEqual(pattern["terminal_samples"], 0)
        self.assertEqual(pattern["adverse_streak_samples"], 0)

    def test_changed_revision_resets_historical_streak(self):
        revised = "c" * 40
        receipt, _ = follow_up(
            sample("2026-10-12T12:00:00Z"),
            sample("2026-10-12T13:00:00Z"),
            sample(T0, revision=revised),
            sample(T1, revision=revised),
            provider=Transport(revision=revised))
        pattern = original_observations(receipt)
        self.assertEqual(pattern["terminal_samples"], 2)
        self.assertEqual(pattern["adverse_streak_samples"], 2)
        self.assertEqual(pattern["adverse_streak_first_observed_at"], T0)

    def test_nonactual_middle_sample_stops_historical_continuity(self):
        receipt, _ = follow_up(
            sample("2026-10-12T12:00:00Z"),
            sample("2026-10-12T13:00:00Z", kind="SIMULATED"),
            sample(T0), sample(T1))
        pattern = original_observations(receipt)
        self.assertEqual(pattern["terminal_samples"], 2)
        self.assertEqual(pattern["adverse_streak_samples"], 2)

    def test_old_sample_outside_existing_freshness_cutoff_is_not_carried(self):
        receipt, _ = follow_up(
            sample("2026-10-09T12:00:00Z"),
            sample(T0), sample(T1))
        pattern = original_observations(receipt)
        self.assertEqual(pattern["terminal_samples"], 2)
        self.assertEqual(pattern["adverse_streak_samples"], 2)

    def test_twelve_sample_cap_cannot_claim_full_historical_coverage(self):
        records = [sample(f"2026-10-12T12:{minute:02d}:00Z")
                   for minute in range(13)]
        receipt, _ = follow_up(*records)
        pattern = original_observations(receipt)
        self.assertEqual(pattern["terminal_samples"], 12)
        self.assertEqual(pattern["adverse_streak_samples"], 12)
        self.assertIs(pattern["capped_at_12_samples"], True)
        self.assertEqual(pattern["latest_terminal_observed_at"],
                         "2026-10-12T12:12:00Z")

    def test_provider_change_does_not_rewrite_original_historical_evidence(self):
        receipt, _ = follow_up(sample(T0), sample(T1),
                               provider=Transport(conclusion="success"))
        pattern = original_observations(receipt)
        self.assertEqual(pattern["adverse_streak_samples"], 2)
        self.assertEqual(receipt["investigations"][0]["checks"][0]["outcome"],
                         "SUCCESS_OBSERVED_NOT_RESOLUTION")

    def test_legacy_one_shot_without_history_has_no_historical_claim(self):
        report, _ = verified(sample(T0, conclusion="success"), sample(T1))
        provider = Transport()
        receipt = investigate(report, api=GitHub(transport=provider), now=NOW)
        self.assertNotIn("historical_check_patterns", receipt["investigations"][0])
        self.assertNotIn("historical_observations",
                         receipt["investigations"][0]["checks"][0])
        self.assertEqual(len(provider.calls), 4)

    def test_corrupted_original_events_are_rejected_before_provider_contact(self):
        report, events = verified(sample(T0), sample(T1))
        tampered = copy.deepcopy(events)
        tampered[0]["payload"]["open_issues"] = 17
        provider = Transport()
        with self.assertRaises(BrainError):
            investigate(report, history=tampered,
                        api=GitHub(transport=provider), now=NOW)
        self.assertEqual(provider.calls, [])

    @unittest.skipUnless(os.name == "posix", "private receipt permission tests require POSIX")
    def test_cli_does_not_mutate_original_sqlite_or_make_extra_gets(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            database = root / "original.sqlite"
            with patch("brain.core.utcnow", return_value=NOW):
                store = Store(database, visibility="PUBLIC")
                try:
                    store.submit([sample(T0), sample(T1)], now=NOW)
                    store.drain()
                    store.report(SOURCE, now=NOW)
                finally:
                    store.close()
            before = (hashlib.sha256(database.read_bytes()).hexdigest(),
                      database.stat().st_mtime_ns, database.stat().st_mode)
            transport = Transport()
            provider = GitHub(transport=transport)
            with patch("brain.__main__.source_sha", return_value=SOURCE), \
                 patch("brain.core.utcnow", return_value=NOW), \
                 patch("brain.investigate.utcnow", return_value=NOW), \
                 patch("brain.investigate.GitHub", return_value=provider), \
                 redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                code = main(["--db", str(database),
                             "--expected-sha", SOURCE,
                             "--output", str(root / "private")])
            self.assertEqual(code, 0)
            after = (hashlib.sha256(database.read_bytes()).hexdigest(),
                     database.stat().st_mtime_ns, database.stat().st_mode)
            self.assertEqual(before, after)
            result = json.loads((root / "private" / "report.json").read_text())
            self.assertEqual(
                result["investigations"][0]["checks"][0]
                ["historical_observations"]["adverse_streak_samples"], 2)
            self.assertEqual(len(transport.calls), 4)
            self.assertEqual((root / "private").stat().st_mode & 0o777, 0o700)


if __name__ == "__main__":
    unittest.main()
