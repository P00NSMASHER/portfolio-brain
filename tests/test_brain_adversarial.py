"""Independent adversarial checks for the replacement's substantive guarantees."""
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from brain.adapters import GitHub, event
from brain.core import BrainError, Store, canonical, digest
from brain.experiments import invoice_dedup_experiment

SHA = "a" * 40
NOW = "2026-10-07T21:00:00Z"
LATER = "2026-10-07T21:01:00Z"


def observation(*, key="fixture/project", issues=1, observed_at=NOW, private=False):
    return event("repository", key, {
        "repository": key, "head_sha": SHA, "default_branch": "main", "checks": [],
        "open_issues": issues, "source_ref": f"https://github.com/{key}/commit/{SHA}",
    }, SHA, now=observed_at, private=private)


class BrainIndependentAdversarialTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "authority.sqlite"
        self.store = Store(self.path, visibility="PUBLIC")
        self.addCleanup(lambda: self.store.close() if self.store is not None else None)

    def ingest(self, *events):
        self.store.submit(list(events), now=LATER)
        self.store.drain()

    def test_rehashed_report_cannot_invent_analysis_absent_from_ledger(self):
        self.ingest(observation())
        report = self.store.report(SHA, now=LATER)
        report["repositories"][0]["open_issues"] = 999999
        self.store.db.execute("UPDATE reports SET body=?,hash=? WHERE id=1", (canonical(report), digest(report)))
        with self.assertRaises(BrainError):
            self.store.read_report(SHA, now=LATER)

    def test_sql_identity_column_must_match_immutable_event_identity(self):
        self.ingest(observation())
        self.store.db.execute("UPDATE events SET id='renamed-event-id'")
        with self.assertRaises(BrainError):
            self.store.report(SHA, now=LATER)

    def test_simultaneous_conflicting_observations_fail_closed(self):
        try:
            self.ingest(observation(issues=1), observation(issues=2))
            result = self.store.report(SHA, now=LATER)
        except BrainError:
            return
        self.assertEqual(result["status"], "BLOCKED", "Competing equal-time evidence cannot acquire authority by lexical event ID")

    def test_as_of_before_observation_never_passes(self):
        self.ingest(observation())
        try:
            result = self.store.report(SHA, now="2026-10-07T20:59:00Z")
        except BrainError:
            return
        self.assertEqual(result["status"], "BLOCKED")

    def test_delayed_delivery_does_not_override_newer_source_observation(self):
        self.ingest(observation(issues=8, observed_at=LATER))
        self.ingest(observation(issues=3, observed_at=NOW))
        result = self.store.report(SHA, now=LATER)
        self.assertEqual(result["repositories"][0]["open_issues"], 8)
        self.assertEqual(result["state_sequence"], 2)
        self.assertEqual(result["pending_events"], 0)

    def test_pending_durable_input_blocks_dependent_reads(self):
        self.ingest(observation())
        self.store.report(SHA, now=LATER)
        self.store.submit([observation(key="fixture/second")], now=LATER)
        with self.assertRaises(BrainError):
            self.store.read_report(SHA, now=LATER)
        self.assertEqual(self.store.pending(), 1)

    def test_interrupted_drain_recovers_entire_acknowledged_batch(self):
        self.store.submit([observation(), observation(key="fixture/second")], now=LATER)
        def interrupt(_sequence):
            raise RuntimeError("simulated abrupt job interruption")
        with self.assertRaisesRegex(RuntimeError, "interruption"):
            self.store.drain(fault=interrupt)
        self.assertEqual(self.store.pending(), 2)
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM ledger").fetchone()[0], 0)
        self.store.close()
        self.store = Store(self.path, visibility="PUBLIC")
        self.assertEqual(self.store.drain(), 2)
        result = self.store.report(SHA, now=LATER)
        self.assertEqual(result["state_sequence"], 2)
        self.assertEqual(result["pending_events"], 0)

    def test_two_real_concurrent_writers_preserve_both_events(self):
        def worker(key):
            connection = Store(self.path, visibility="PUBLIC")
            try:
                connection.submit([observation(key=key)], now=LATER)
                connection.drain()
            finally:
                connection.close()
        with ThreadPoolExecutor(max_workers=2) as executor:
            list(executor.map(worker, ["fixture/first", "fixture/second"]))
        result = self.store.report(SHA, now=LATER)
        self.assertEqual(result["state_sequence"], 2)
        self.assertEqual({row["key"] for row in result["repositories"]}, {"fixture/first", "fixture/second"})

    def test_public_batch_rejects_private_record_atomically(self):
        with self.assertRaises(BrainError):
            self.store.submit([observation(), observation(key="fixture/private", private=True)], now=LATER)
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM events").fetchone()[0], 0)

    def test_reopening_private_authority_as_public_is_rejected(self):
        private_path = Path(self.directory.name) / "private.sqlite"
        private = Store(private_path, visibility="PRIVATE")
        private.close()
        with self.assertRaises(BrainError):
            Store(private_path, visibility="PUBLIC")

    def test_incomplete_check_delivery_is_rejected(self):
        responses = {
            "/repos/fixture/project": {"full_name": "fixture/project", "private": False, "default_branch": "main", "open_issues_count": 0},
            "/repos/fixture/project/branches/main": {"commit": {"sha": SHA}},
            f"/repos/fixture/project/commits/{SHA}/check-runs?per_page=100": {"total_count": 1, "check_runs": []},
        }
        with self.assertRaises(BrainError):
            GitHub(transport=lambda path: responses[path]).observe("fixture/project")

    def test_dedup_experiment_exercises_positive_and_negative_cases(self):
        result = invoice_dedup_experiment(500)
        self.assertEqual(result["dataset_kind"], "SIMULATED")
        self.assertTrue(result["equal_outputs"])
        self.assertGreater(result.get("duplicate_cases", 0), 0, "A deduplication experiment must contain actual duplicate fixture rows")
        self.assertLess(result["duplicate_cases"], result["cases"], "It must retain distinct rows as negative controls")


if __name__ == "__main__":
    unittest.main()
