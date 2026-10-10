"""Independent adversarial checks for the replacement's substantive guarantees."""
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from brain.adapters import GitHub, event
from brain.core import BrainError, Store, canonical, digest
from brain.experiments import invoice_dedup_experiment
from brain.intelligence import build_report

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

    def test_same_time_simulated_to_actual_relabel_rejected_atomically(self):
        actual = observation()
        simulated = event(
            "repository", actual["key"], actual["payload"], SHA,
            now=NOW, data_kind="SIMULATED",
        )
        self.assertNotEqual(actual["id"], simulated["id"])
        with self.assertRaisesRegex(BrainError, "AMBIGUOUS_OBSERVATION"):
            self.store.submit([simulated, actual], now=LATER)
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM events").fetchone()[0], 0)

        self.ingest(simulated)
        with self.assertRaisesRegex(BrainError, "AMBIGUOUS_OBSERVATION"):
            self.store.submit([actual], now=LATER)
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM events").fetchone()[0], 1)
        report = self.store.report(SHA, now=LATER)
        self.assertEqual(report["repositories"][0]["data_kind"], "SIMULATED")

    def test_same_time_private_to_public_relabel_rejected(self):
        path = Path(self.directory.name) / "private-authority.sqlite"
        private_store = Store(path, visibility="PRIVATE")
        self.addCleanup(private_store.close)
        public = observation()
        private = observation(private=True)
        self.assertEqual(public["payload"], private["payload"])
        with self.assertRaisesRegex(BrainError, "AMBIGUOUS_OBSERVATION"):
            private_store.submit([private, public], now=LATER)
        self.assertEqual(
            private_store.db.execute("SELECT count(*) FROM events").fetchone()[0], 0,
        )

    def test_exact_fact_with_different_producer_source_sha_is_valid_replay(self):
        first = observation()
        second = event(
            "repository", first["key"], first["payload"], "b" * 40,
            now=NOW, data_kind=first["data_kind"],
        )
        self.assertNotEqual(first["id"], second["id"])
        self.ingest(first, second)
        report = self.store.report(SHA, now=LATER)
        self.assertEqual(report["state_sequence"], 2)
        self.assertEqual(len(report["repositories"]), 1)
        self.assertEqual(self.store.read_report(SHA, now=LATER), report)

    def test_same_utc_instant_with_different_text_precision_cannot_relabel(self):
        first = observation()
        alias = event(
            "repository", first["key"], first["payload"], SHA,
            now=NOW[:-1] + ".000000Z", data_kind="SIMULATED",
        )
        self.assertNotEqual(first["observed_at"], alias["observed_at"])
        with self.assertRaisesRegex(BrainError, "AMBIGUOUS_OBSERVATION"):
            self.store.submit([first, alias], now=LATER)
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM events").fetchone()[0], 0)
        self.ingest(first)
        with self.assertRaisesRegex(BrainError, "AMBIGUOUS_OBSERVATION"):
            self.store.submit([alias], now=LATER)
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM events").fetchone()[0], 1)

    def test_identical_utc_instant_alias_keeps_legal_replay_without_false_change(self):
        first = observation()
        alias = event(
            "repository", first["key"], first["payload"], "b" * 40,
            now=NOW[:-1] + ".000000Z", data_kind="ACTUAL",
        )
        self.ingest(first, alias)
        report = self.store.report(SHA, now=LATER)
        self.assertEqual(report["state_sequence"], 2)
        self.assertEqual(len(report["repositories"]), 1)
        self.assertEqual(report["repository_changes"], [])
        self.assertEqual(self.store.read_report(SHA, now=LATER), report)

    def test_historical_same_time_label_conflict_not_hidden_by_newer_fact(self):
        old_actual = observation(issues=1)
        old_simulated = event(
            "repository", old_actual["key"], old_actual["payload"], SHA,
            now=NOW[:-1] + ".000000Z", data_kind="SIMULATED",
        )
        newer = observation(issues=2, observed_at=LATER)
        with self.assertRaisesRegex(BrainError, "AMBIGUOUS_OBSERVATION"):
            build_report(
                [old_actual, newer, old_simulated],
                now=LATER, max_age=172800,
            )

    def test_legacy_valid_hash_chain_cannot_launder_conflicting_labels(self):
        """Regression for historical accepted events with internally valid hashes."""
        first = observation()
        second = event(
            "repository", first["key"], first["payload"], SHA,
            now=NOW[:-1] + ".000000Z", data_kind="SIMULATED",
        )
        previous = "0" * 64
        with self.store.transaction():
            for item in (first, second):
                body, event_hash = canonical(item), digest(item)
                row = self.store.db.execute(
                    "INSERT INTO events(id,body,hash,status,received_at) "
                    "VALUES(?,?,?,'APPLIED',?)",
                    (item["id"], body, event_hash, LATER),
                )
                seq = row.lastrowid
                current = digest({
                    "seq": seq, "event_hash": event_hash,
                    "previous": previous,
                })
                self.store.db.execute(
                    "INSERT INTO ledger(seq,prev_hash,chain_hash) VALUES(?,?,?)",
                    (seq, previous, current),
                )
                previous = current
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM ledger").fetchone()[0], 2)
        with self.assertRaisesRegex(BrainError, "AMBIGUOUS_OBSERVATION"):
            self.store.report(SHA, now=LATER)
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM events").fetchone()[0], 2)

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
