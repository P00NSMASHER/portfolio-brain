"""Canonical content-derived event identities across admission and replay.

A matching event hash/chain is not a substitute for the producer's unique
ID-content binding. All state, evidence and event fixtures are disposable.
"""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from brain.adapters import event
from brain.core import BrainError, Store, canonical, digest, validate_event

SOURCE = "a" * 40
OTHER_SOURCE = "b" * 40
NOW = "2026-10-09T18:00:00Z"
LATER = "2026-10-09T18:05:00Z"
REPO = "ExampleOrg/verified-project"


def observation(*, source=SOURCE, when=NOW, issues=2):
    payload = {
        "repository": REPO,
        "head_sha": OTHER_SOURCE,
        "default_branch": "main",
        "checks": [],
        "open_issues": issues,
        "source_ref": f"https://github.com/{REPO}/commit/{OTHER_SOURCE}",
    }
    return event("repository", REPO, payload, source, now=when)


def expected_id(item):
    return item["kind"] + ":" + digest({**item, "id": ""})


class EventIdIntegrityTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "state.sqlite"
        self.store = Store(self.path, visibility="PUBLIC")
        self.addCleanup(self.store.close)

    def test_existing_factory_identity_is_unchanged(self):
        item = observation()
        self.assertEqual(item["id"], expected_id(item))
        self.assertEqual(len(item["id"].split(":", 1)[1]), 64)
        validate_event(item, LATER)

    def test_arbitrary_well_formed_id_is_rejected(self):
        item = observation()
        item["id"] = "repository:operator-claimed-valid"
        with self.assertRaisesRegex(BrainError, "EVENT_ID_CONTENT_MISMATCH"):
            validate_event(item, LATER)

    def test_wrong_kind_prefix_with_correct_digest_rejected(self):
        item = observation()
        item["id"] = "candidate:" + item["id"].split(":", 1)[1]
        with self.assertRaisesRegex(BrainError, "EVENT_ID_CONTENT_MISMATCH"):
            validate_event(item, LATER)

    def test_wrong_hex_digest_with_correct_kind_rejected(self):
        item = observation()
        item["id"] = "repository:" + "f" * 64
        self.assertNotEqual(item["id"], expected_id(item))
        with self.assertRaisesRegex(BrainError, "EVENT_ID_CONTENT_MISMATCH"):
            validate_event(item, LATER)

    def test_changed_source_revision_cannot_reuse_other_event_id(self):
        original = observation()
        revised = copy.deepcopy(original)
        revised["source_sha"] = OTHER_SOURCE
        with self.assertRaisesRegex(BrainError, "EVENT_ID_CONTENT_MISMATCH"):
            validate_event(revised, LATER)
        corrected = observation(source=OTHER_SOURCE)
        self.assertNotEqual(corrected["id"], original["id"])
        validate_event(corrected, LATER)

    def test_changed_timestamp_cannot_reuse_stale_id(self):
        original = observation()
        changed = copy.deepcopy(original)
        changed["observed_at"] = NOW[:-1] + ".000000Z"
        with self.assertRaisesRegex(BrainError, "EVENT_ID_CONTENT_MISMATCH"):
            validate_event(changed, LATER)
        correct = observation(when=changed["observed_at"])
        self.assertNotEqual(correct["id"], original["id"])
        validate_event(correct, LATER)

    def test_changed_payload_cannot_reuse_id_or_write_partial_batch(self):
        original = observation()
        altered = copy.deepcopy(original)
        altered["payload"]["open_issues"] = 999
        with self.assertRaisesRegex(BrainError, "EVENT_ID_CONTENT_MISMATCH"):
            self.store.submit(
                [observation(when=LATER), altered], now=LATER,
            )
        self.assertEqual(self.store.pending(), 0)
        self.assertEqual(
            self.store.db.execute("SELECT count(*) FROM events").fetchone()[0],
            0,
        )

    def test_second_invented_id_for_identical_fact_cannot_inflate_ledger(self):
        original = observation()
        alternate = copy.deepcopy(original)
        alternate["id"] = "repository:" + "c" * 64
        self.store.submit([original], now=LATER)
        self.store.drain()
        with self.assertRaisesRegex(BrainError, "EVENT_ID_CONTENT_MISMATCH"):
            self.store.submit([alternate], now=LATER)
        result = self.store.report(SOURCE, now=LATER)
        self.assertEqual(result["state_sequence"], 1)
        self.assertEqual(result["learning"]["events"], 1)

    def test_hash_consistent_historical_alias_fails_closed(self):
        forged = observation()
        forged["id"] = "repository:alternate-alias"
        forged_hash = digest(forged)
        previous = "0" * 64
        with self.store.transaction():
            cursor = self.store.db.execute(
                "INSERT INTO events(id,body,hash,status,received_at) "
                "VALUES(?,?,?,'APPLIED',?)",
                (forged["id"], canonical(forged), forged_hash, LATER),
            )
            seq = cursor.lastrowid
            chain = digest({
                "seq": seq, "event_hash": forged_hash, "previous": previous,
            })
            self.store.db.execute(
                "INSERT INTO ledger(seq,prev_hash,chain_hash) VALUES(?,?,?)",
                (seq, previous, chain),
            )
        self.assertEqual(self.store.pending(), 0)
        with self.assertRaisesRegex(BrainError, "EVENT_ID_CONTENT_MISMATCH"):
            self.store.report(SOURCE, now=LATER)
        self.assertEqual(
            self.store.db.execute("SELECT hash FROM events").fetchone()[0],
            forged_hash,
        )

    def test_forged_durable_pending_record_blocks_drain_atomically(self):
        fake = observation()
        fake["id"] = "repository:" + "c" * 64
        with self.store.transaction():
            self.store.db.execute(
                "INSERT INTO events(id,body,hash,status,received_at) "
                "VALUES(?,?,?,'PENDING',?)",
                (fake["id"], canonical(fake), digest(fake), LATER),
            )
        self.assertEqual(self.store.pending(), 1)
        with self.assertRaisesRegex(BrainError, "EVENT_ID_CONTENT_MISMATCH"):
            self.store.drain()
        self.assertEqual(self.store.pending(), 1)
        self.assertEqual(
            self.store.db.execute("SELECT count(*) FROM ledger").fetchone()[0],
            0,
        )

    def test_valid_repeated_revisions_preserve_two_historical_records(self):
        first = observation(source=SOURCE)
        repeat = observation(source=OTHER_SOURCE)
        self.assertNotEqual(first["id"], repeat["id"])
        self.store.submit([first, repeat], now=LATER)
        self.assertEqual(self.store.drain(), 2)
        result = self.store.report(SOURCE, now=LATER)
        self.assertEqual(result["state_sequence"], 2)
        self.assertEqual(result["learning"]["events"], 2)
        self.assertEqual(len(result["repositories"]), 1)
        self.assertEqual(self.store.read_report(SOURCE, now=LATER), result)

    def test_equivalent_utc_precision_keeps_legitimate_semantic_replay(self):
        first = observation()
        second = observation(source=OTHER_SOURCE,
                             when=NOW[:-1] + ".000000Z")
        self.store.submit([first, second], now=LATER)
        self.store.drain()
        result = self.store.report(SOURCE, now=LATER)
        self.assertEqual(result["repository_changes"], [])
        self.assertEqual(result["state_sequence"], 2)

    def test_restart_and_replay_keep_valid_ids_and_report_hash(self):
        item = observation()
        self.store.submit([item], now=LATER)
        self.store.drain()
        report = self.store.report(SOURCE, now=LATER)
        original = self.store.db.execute(
            "SELECT body,hash FROM events WHERE id=?", (item["id"],)
        ).fetchone()
        self.store.close()
        reopened = Store(self.path, visibility="PUBLIC")
        try:
            self.assertEqual(reopened.read_report(SOURCE, now=LATER), report)
            row = reopened.db.execute(
                "SELECT body,hash FROM events WHERE id=?", (item["id"],)
            ).fetchone()
            self.assertEqual(row["body"], original["body"])
            self.assertEqual(row["hash"], original["hash"])
        finally:
            reopened.close()

    def test_simulated_experiment_must_have_content_bound_id(self):
        from brain.experiments import invoice_dedup_experiment
        payload = invoice_dedup_experiment(20)
        legitimate = event("experiment", payload["experiment"], payload,
                           SOURCE, now=NOW, data_kind="SIMULATED")
        validate_event(legitimate, LATER)
        forged = copy.deepcopy(legitimate)
        forged["id"] = "experiment:manually-labelled"
        with self.assertRaisesRegex(BrainError, "EVENT_ID_CONTENT_MISMATCH"):
            validate_event(forged, LATER)

    def test_feedback_identity_is_bound_without_changing_operator_key(self):
        payload = {
            "candidate_key": f"{REPO}:src/invoice_match.py",
            "outcome": "NOT_USEFUL",
            "evidence_ref": "reviewer attested",
            "basis": "OPERATOR_REPORTED",
            "engineering_seconds_saved": None,
        }
        accepted = event("feedback", "reviewer-note-1", payload,
                         SOURCE, now=NOW)
        validate_event(accepted, LATER)
        forged = copy.deepcopy(accepted)
        forged["id"] = "feedback:synthetic-id"
        with self.assertRaisesRegex(BrainError, "EVENT_ID_CONTENT_MISMATCH"):
            validate_event(forged, LATER)


if __name__ == "__main__":
    unittest.main()
