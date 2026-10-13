"""Fail-closed private-to-public historical CI observation evidence."""
import copy
import unittest

from brain.sidecar import summarize
from test_brain_temporal import follow_up, sample, T0, T1, SOURCE
from test_brain_sidecar import observation as legacy_receipt


def classified(*observations):
    receipt, _ = follow_up(*observations)
    return receipt


def result(receipt):
    return summarize(receipt, SOURCE, *["success"] * 4)


class TemporalSidecarTests(unittest.TestCase):
    def test_two_original_adverse_samples_publish_names_free_bucket(self):
        receipt = classified(sample(T0), sample(T1))
        public = result(receipt)
        self.assertEqual(public["status"], "OBSERVED_READ_ONLY")
        self.assertEqual(public["historical_adverse_streak_bands"], {"TWO": 1})
        self.assertEqual(public["historical_repeated_terminal_movements"], 0)
        self.assertEqual(public["historical_sample_caps"], 0)
        self.assertNotIn("validate", str(public))
        self.assertNotIn("P00NSMASHER", str(public))
        self.assertFalse(public["root_cause_verified"])
        self.assertFalse(public["execution_authority"])

    def test_repeated_adverse_success_movements_are_sample_counts_only(self):
        receipt = classified(
            sample("2026-10-12T12:00:00Z", conclusion="failure"),
            sample("2026-10-12T13:00:00Z", conclusion="success"),
            sample(T0, conclusion="failure"), sample(T1, conclusion="failure"))
        public = result(receipt)
        self.assertEqual(public["status"], "OBSERVED_READ_ONLY")
        self.assertEqual(public["historical_adverse_streak_bands"], {"TWO": 1})
        self.assertEqual(public["historical_repeated_terminal_movements"], 1)
        self.assertFalse(public["production_accepted"])

    def test_observed_recovery_has_no_current_adverse_streak(self):
        receipt = classified(sample(T0, conclusion="failure"),
                             sample(T1, conclusion="success"))
        public = result(receipt)
        self.assertEqual(public["historical_adverse_streak_bands"], {"NONE": 1})
        self.assertFalse(public["root_cause_verified"])

    def test_original_gap_breaks_streak_even_when_provider_rechecks_successfully(self):
        receipt = classified(sample(T0), sample(T1, included=False))
        public = result(receipt)
        self.assertEqual(public["status"], "OBSERVED_READ_ONLY")
        self.assertEqual(public["historical_adverse_streak_bands"], {"NONE": 1})

    def test_unresolved_provider_gap_remains_partial(self):
        from brain.adapters import GitHub
        from brain.investigate import investigate
        from test_brain_temporal import NOW
        from test_brain_investigate import Transport
        from test_brain_evidence_gaps import verified

        report, history = verified(sample(T0), sample(T1, included=False))
        transport = Transport()
        transport.check_mutation = lambda item: item.update(name="unrelated")
        receipt = investigate(report, history=history, now=NOW,
                              api=GitHub(transport=transport))
        public = result(receipt)
        self.assertEqual(public["status"], "PARTIAL_READ_ONLY")
        self.assertEqual(public["historical_adverse_streak_bands"], {"NONE": 1})
        self.assertEqual(public["observed_outcomes"],
                         {"UNVERIFIED_MISSING_OR_AMBIGUOUS_CHECK": 1})
        self.assertEqual(len(transport.calls), 4)
        self.assertFalse(public["root_cause_verified"])

    def test_stale_or_forged_history_metrics_never_become_public(self):
        original = classified(sample(T0), sample(T1))
        record = original["investigations"][0]
        valid = record["historical_check_patterns"]["validate"]
        attacks = [
            ("scope", "SCHEDULE_REAL_CUSTOMER_REPAIR"),
            ("terminal_samples", True),
            ("terminal_samples", 13),
            ("terminal_samples", -1),
            ("adverse_streak_samples", True),
            ("adverse_streak_samples", 3),
            ("adverse_success_flips_observed", 2),
            ("adverse_success_flips_observed", -1),
            ("capped_at_12_samples", "yes"),
            ("capped_at_12_samples", True),
            ("adverse_streak_first_observed_at", "2099-01-01T00:00:00Z"),
            ("latest_terminal_observed_at", "2099-01-01T00:00:00Z"),
        ]
        for field, value in attacks:
            with self.subTest(field=field, value=value):
                tampered = copy.deepcopy(original)
                changed = tampered["investigations"][0]["historical_check_patterns"]["validate"]
                changed[field] = value
                tampered["investigations"][0]["checks"][0]["historical_observations"] = changed
                public = result(tampered)
                self.assertEqual(public["status"], "BLOCKED_NO_VERIFIED_INVESTIGATION")
                self.assertEqual(public["historical_adverse_streak_bands"], {})
                self.assertFalse(public["execution_authority"])
                self.assertEqual(public["events_written"], 0)
        self.assertEqual(record["historical_check_patterns"]["validate"], valid)

    def test_plan_and_observed_check_temporal_histories_must_match(self):
        original = classified(sample(T0), sample(T1))
        plan = original["investigations"][0]["historical_check_patterns"]["validate"]
        checked = original["investigations"][0]["checks"][0]["historical_observations"]
        self.assertIsNot(plan, checked)
        self.assertEqual(plan, checked)
        for attack in ("omit_check", "omit_plan", "change_check", "rename_plan"):
            tampered = copy.deepcopy(original)
            row = tampered["investigations"][0]
            check_row = row["checks"][0]
            if attack == "omit_check":
                del check_row["historical_observations"]
            elif attack == "omit_plan":
                del row["historical_check_patterns"]
            elif attack == "change_check":
                check_row["historical_observations"]["adverse_streak_samples"] = 1
            else:
                row["historical_check_patterns"]["forged"] = (
                    row["historical_check_patterns"].pop("validate")
                )
            with self.subTest(attack=attack):
                self.assertEqual(result(tampered)["status"],
                                 "BLOCKED_NO_VERIFIED_INVESTIGATION")

    def test_incoherent_zero_sample_timestamp_never_promoted(self):
        original = classified(sample(T0), sample(T1, included=False))
        row = original["investigations"][0]
        mutated = copy.deepcopy(original)
        for value in (False, True):
            altered = copy.deepcopy(mutated)
            data = altered["investigations"][0]["historical_check_patterns"]["validate"]
            data["capped_at_12_samples"] = value
            data["latest_terminal_observed_at"] = T1
            altered["investigations"][0]["checks"][0]["historical_observations"] = data
            with self.subTest(cap=value):
                self.assertEqual(result(altered)["status"],
                                 "BLOCKED_NO_VERIFIED_INVESTIGATION")
        self.assertEqual(row["historical_check_patterns"]["validate"]["terminal_samples"], 0)

    def test_cap_is_explicitly_counted_not_inferred_as_full_history(self):
        records = [sample(f"2026-10-12T12:{m:02d}:00Z") for m in range(13)]
        original = classified(*records)
        public = result(original)
        self.assertEqual(public["historical_adverse_streak_bands"],
                         {"THREE_OR_MORE": 1})
        self.assertEqual(public["historical_sample_caps"], 1)
        self.assertNotIn("2026-10", str(public))

    def test_legacy_receipt_remains_backward_readable_without_fabricated_history(self):
        public = result(legacy_receipt())
        self.assertEqual(public["status"], "OBSERVED_READ_ONLY")
        self.assertEqual(public["historical_adverse_streak_bands"], {})
        self.assertEqual(public["historical_repeated_terminal_movements"], 0)
        self.assertEqual(public["historical_sample_caps"], 0)

    def test_missing_report_time_blocks_temporal_metrics(self):
        original = classified(sample(T0), sample(T1))
        deleted = copy.deepcopy(original)
        del deleted["checked_at"]
        self.assertEqual(result(deleted)["status"],
                         "BLOCKED_NO_VERIFIED_INVESTIGATION")


if __name__ == "__main__":
    unittest.main()
