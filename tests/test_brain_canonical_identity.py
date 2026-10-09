"""Identity-binding tests for immutable evidence and exact repository commits.

Fixtures never access real GitHub, brokerage accounts, production state, or
external services. The integrity rule is checked both before admission
and against a deliberately hash-consistent legacy-shaped SQLite ledger.
"""
import json
import tempfile
import unittest
from pathlib import Path

from brain.adapters import event
from brain.core import BrainError, Store, canonical, digest, validate_event
from brain.experiments import invoice_dedup_experiment
from brain.intelligence import validate_payload

SOURCE = "a" * 40
OTHER_SOURCE = "b" * 40
REPO_REVISION = "c" * 40
REPO = "ExampleOrg/verified-project"
NOW = "2026-10-09T16:00:00Z"
CANDIDATE_PATH = "src/invoice_match.py"


def repository_payload():
    return {
        "repository": REPO,
        "head_sha": REPO_REVISION,
        "default_branch": "main",
        "checks": [],
        "open_issues": 2,
        "source_ref": f"https://github.com/{REPO}/commit/{REPO_REVISION}",
    }


def candidate_payload():
    return {
        "repository": REPO,
        "head_sha": REPO_REVISION,
        "path": CANDIDATE_PATH,
        "blob_sha": "d" * 40,
        "code_sha256": "e" * 64,
        "bytes": 200,
        "test_paths": ["tests/test_invoice_match.py"],
        "license": "MIT",
        "source_ref": (
            f"https://github.com/{REPO}/blob/"
            f"{REPO_REVISION}/{CANDIDATE_PATH}"
        ),
        "target": "freight-recovery",
        "query": "freight invoice match",
        "matched_terms": ["invoice", "match"],
    }


def valid_repo(*, source_sha=SOURCE):
    return event("repository", REPO, repository_payload(),
                 source_sha, now=NOW)


def valid_candidate(*, source_sha=SOURCE):
    payload = candidate_payload()
    return event("candidate", f'{REPO}:{CANDIDATE_PATH}',
                 payload, source_sha, now=NOW)


def valid_experiment(*, source_sha=SOURCE):
    payload = invoice_dedup_experiment(20)
    return event("experiment", payload["experiment"], payload,
                 source_sha, now=NOW, data_kind="SIMULATED")


class CanonicalEvidenceIdentityTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.file = Path(directory.name) / "state.sqlite"
        self.store = Store(self.file, visibility="PUBLIC")
        self.addCleanup(self.store.close)

    def test_normal_repository_candidate_and_experiment_replay(self):
        items = [valid_repo(), valid_candidate(), valid_experiment()]
        self.store.submit(items, now=NOW)
        self.assertEqual(self.store.drain(), 3)
        report = self.store.report(SOURCE, now=NOW)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["pending_events"], 0)
        self.assertEqual(report["state_sequence"], 3)
        self.assertEqual(report["repositories"][0]["key"], REPO)
        self.assertEqual(
            report["repositories"][0]["source_ref"],
            repository_payload()["source_ref"],
        )
        self.assertEqual(report["reuse_candidates"][0]["key"],
                         f"{REPO}:{CANDIDATE_PATH}")
        self.assertEqual(report["learning"]["experiments"],
                         [items[-1]["payload"]])
        self.assertEqual(self.store.read_report(SOURCE, now=NOW), report)

    def test_repository_key_cannot_claim_another_repository(self):
        wrong = event("repository", "OtherOrg/another-project",
                      repository_payload(), SOURCE, now=NOW)
        with self.assertRaisesRegex(BrainError, "EVIDENCE_KEY_MISMATCH"):
            self.store.submit([wrong], now=NOW)
        self.assertEqual(self.store.pending(), 0)
        self.assertEqual(
            self.store.db.execute("SELECT count(*) FROM events").fetchone()[0],
            0,
        )

    def test_candidate_key_cannot_claim_another_implementation_path(self):
        wrong = event("candidate", f"{REPO}:src/another_module.py",
                      candidate_payload(), SOURCE, now=NOW)
        with self.assertRaisesRegex(BrainError, "EVIDENCE_KEY_MISMATCH"):
            validate_event(wrong, NOW)
        self.assertEqual(wrong["payload"]["source_ref"],
                         candidate_payload()["source_ref"])

    def test_candidate_key_cannot_claim_another_repository(self):
        wrong = event("candidate",
                      f"OtherOrg/another-project:{CANDIDATE_PATH}",
                      candidate_payload(), SOURCE, now=NOW)
        with self.assertRaisesRegex(BrainError, "EVIDENCE_KEY_MISMATCH"):
            self.store.submit([wrong], now=NOW)
        self.assertEqual(self.store.pending(), 0)

    def test_simulated_experiment_key_must_match_reviewed_payload(self):
        original = valid_experiment()
        wrong = event("experiment", "unrelated-experiment",
                      original["payload"], SOURCE, now=NOW,
                      data_kind="SIMULATED")
        with self.assertRaisesRegex(BrainError, "EVIDENCE_KEY_MISMATCH"):
            validate_event(wrong, NOW)
        validate_event(original, NOW)

    def test_repository_source_ref_must_name_exact_recorded_commit(self):
        payload = repository_payload()
        payload["source_ref"] = f"https://github.com/{REPO}/commit/{OTHER_SOURCE}"
        with self.assertRaisesRegex(BrainError, "SOURCE_REF_MISMATCH"):
            validate_payload("repository", payload, NOW)
        with self.assertRaisesRegex(BrainError, "SOURCE_REF_MISMATCH"):
            self.store.submit([event("repository", REPO, payload,
                                     SOURCE, now=NOW)], now=NOW)

    def test_repository_source_ref_cannot_use_other_repo_page(self):
        payload = repository_payload()
        payload["source_ref"] = f"https://github.com/{REPO}/pull/42"
        with self.assertRaisesRegex(BrainError, "SOURCE_REF_MISMATCH"):
            validate_payload("repository", payload, NOW)

    def test_batch_rejection_retains_no_earlier_valid_event(self):
        good = valid_repo()
        wrong = event("candidate", f"{REPO}:src/other.py",
                      candidate_payload(), SOURCE, now=NOW)
        with self.assertRaisesRegex(BrainError, "EVIDENCE_KEY_MISMATCH"):
            self.store.submit([good, wrong], now=NOW)
        self.assertEqual(self.store.pending(), 0)
        self.assertEqual(
            self.store.db.execute("SELECT count(*) FROM events").fetchone()[0],
            0,
        )

    def test_hash_consistent_invalid_historical_identity_blocks_replay(self):
        """A syntactically valid event hash + ledger chain is not authority."""
        wrong = event("repository", "OtherOrg/spoof",
                      repository_payload(), SOURCE, now=NOW)
        body = canonical(wrong)
        event_hash = digest(wrong)
        previous = "0" * 64
        with self.store.transaction():
            seq = self.store.db.execute(
                "INSERT INTO events(id,body,hash,status,received_at) "
                "VALUES(?,?,?,'APPLIED',?)",
                (wrong["id"], body, event_hash, NOW),
            ).lastrowid
            chain = digest({
                "seq": seq, "event_hash": event_hash, "previous": previous,
            })
            self.store.db.execute(
                "INSERT INTO ledger(seq,prev_hash,chain_hash) VALUES(?,?,?)",
                (seq, previous, chain),
            )
        self.assertEqual(self.store.pending(), 0)
        with self.assertRaisesRegex(BrainError, "EVIDENCE_KEY_MISMATCH"):
            self.store.report(SOURCE, now=NOW)
        self.assertEqual(
            self.store.db.execute(
                "SELECT body FROM events WHERE seq=1"
            ).fetchone()[0], body,
        )

    def test_hash_consistent_wrong_source_ref_blocks_replay(self):
        payload = repository_payload()
        payload["source_ref"] = f"https://github.com/{REPO}/commit/{OTHER_SOURCE}"
        wrong = event("repository", REPO, payload, SOURCE, now=NOW)
        body = canonical(wrong)
        event_hash = digest(wrong)
        with self.store.transaction():
            seq = self.store.db.execute(
                "INSERT INTO events(id,body,hash,status,received_at) "
                "VALUES(?,?,?,'APPLIED',?)",
                (wrong["id"], body, event_hash, NOW),
            ).lastrowid
            self.store.db.execute(
                "INSERT INTO ledger(seq,prev_hash,chain_hash) VALUES(?,?,?)",
                (seq, "0" * 64,
                 digest({"seq": seq, "event_hash": event_hash,
                         "previous": "0" * 64})),
            )
        with self.assertRaisesRegex(BrainError, "SOURCE_REF_MISMATCH"):
            self.store.report(SOURCE, now=NOW)
        self.assertEqual(self.store.pending(), 0)

    def test_identical_fact_from_second_code_revision_is_still_allowed(self):
        first = valid_repo(source_sha=SOURCE)
        second = valid_repo(source_sha=OTHER_SOURCE)
        self.assertNotEqual(first["id"], second["id"])
        self.store.submit([first, second], now=NOW)
        self.store.drain()
        report = self.store.report(SOURCE, now=NOW)
        self.assertEqual(report["state_sequence"], 2)
        self.assertEqual(len(report["repositories"]), 1)
        self.assertEqual(self.store.read_report(SOURCE, now=NOW), report)

    def test_feedback_key_retains_operator_defined_identity(self):
        feedback = {
            "candidate_key": f"{REPO}:{CANDIDATE_PATH}",
            "outcome": "NOT_USEFUL",
            "evidence_ref": "operator-attested private review",
            "basis": "OPERATOR_REPORTED",
            "engineering_seconds_saved": None,
        }
        item = event("feedback", "review-2026-10-09",
                     feedback, SOURCE, now=NOW)
        validate_event(item, NOW)

    def test_holdings_key_retains_operator_defined_identity(self):
        holdings = {
            "currency": "USD",
            "cash": "25",
            "positions": [{
                "symbol": "ABC", "quantity": "1", "cost_basis": None,
                "sector": "Other",
            }],
            "quotes": {
                "ABC": {
                    "price": "12",
                    "observed_at": NOW,
                    "source_ref": "operator-supplied hypothetical",
                    "data_kind": "SIMULATED",
                }
            },
            "authorization": "SIMULATED",
            "historical_prices": [],
        }
        item = event("holdings", "my-test-portfolio",
                     holdings, SOURCE, now=NOW, data_kind="SIMULATED")
        validate_event(item, NOW)


if __name__ == "__main__":
    unittest.main()
