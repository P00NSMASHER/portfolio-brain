"""V5 holdings provenance prevents estimated/simulated market truth laundering.

Tests use operator-supplied synthetic fixtures only; no brokerage, prices
retrieval, external writes or trading authority.
"""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from brain.adapters import event
from brain.core import BrainError, Store, canonical, digest, validate_event
from brain.intelligence import holdings_evidence, holdings_projection

SOURCE = "a" * 40
NOW = "2026-10-09T13:00:00Z"
HISTORY = "2026-10-08T13:00:00Z"


def fixture(*, quotes=None, historical=None):
    quotes = quotes or {"A": "ACTUAL", "B": "ACTUAL"}
    historical = historical if historical is not None else ["ACTUAL", "ACTUAL"]
    rows = []
    for i, kind in enumerate(historical):
        rows.append({
            "observed_at": f"2026-10-0{7 + i}T13:00:00Z",
            "prices": {"A": str(50 + i), "B": str(100 + i)},
            "source_ref": f"operator-provided historical series {i}",
            "data_kind": kind,
        })
    return {
        "currency": "USD",
        "cash": "100",
        "positions": [
            {"symbol": "A", "quantity": "2", "cost_basis": "50", "sector": "Tech"},
            {"symbol": "B", "quantity": "1", "cost_basis": None, "sector": "Other"},
        ],
        "quotes": {
            symbol: {
                "price": "100" if symbol == "A" else "200",
                "observed_at": NOW,
                "source_ref": f"explicit operator supplied mark for {symbol}",
                "data_kind": kind,
            }
            for symbol, kind in quotes.items()
        },
        "authorization": "USER_AUTHORIZED",
        "historical_prices": rows,
    }


def observation(payload, kind="ACTUAL", *, now=NOW):
    return event("holdings", "example/portfolio", payload, SOURCE,
                 now=now, data_kind=kind)


class HoldingsEvidenceIntegration(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.db_path = Path(temp.name) / "state.sqlite"
        self.store = Store(self.db_path, visibility="PRIVATE")
        self.addCleanup(self.store.close)

    def record(self, payload, kind):
        item = observation(payload, kind)
        self.store.submit([item], now=NOW)
        self.store.drain()
        self.store.report(SOURCE, now=NOW)
        return self.store.read_report(SOURCE, now=NOW)["holdings"][0]

    def test_actually_declared_only_for_all_actual_quotes_and_history(self):
        payload = fixture()
        validate_event(observation(payload), NOW)
        actual = self.record(payload, "ACTUAL")
        self.assertEqual(actual["data_kind"], "ACTUAL")
        self.assertEqual(actual["valuation_data_kind"], "ACTUAL")
        self.assertEqual(actual["historical_data_kind"], "ACTUAL")
        self.assertFalse(actual["legacy_provenance_understated"])
        self.assertFalse(actual["sources_independently_verified"])
        self.assertEqual(actual["evidence_basis"], "SOURCE_ATTESTED_NOT_INDEPENDENTLY_VERIFIED")
        self.assertFalse(actual["execution_authority"])
        self.assertEqual(actual["net_asset_value_usd"], "500")

    def test_estimated_quote_cannot_be_relabelled_actual(self):
        payload = fixture(quotes={"A": "ESTIMATED", "B": "ACTUAL"})
        with self.assertRaisesRegex(BrainError, "HOLDINGS_EVIDENCE_KIND_UNDERSTATED"):
            self.store.submit([observation(payload, "ACTUAL")], now=NOW)
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM events").fetchone()[0], 0)
        result = self.record(payload, "ESTIMATED")
        self.assertEqual(result["data_kind"], "ESTIMATED")
        self.assertEqual(result["valuation_data_kind"], "ESTIMATED")
        self.assertEqual(result["historical_data_kind"], "ACTUAL")
        self.assertEqual(result["quote_data_kinds"], ["ACTUAL", "ESTIMATED"])

    def test_simulated_historical_prices_reject_actual_and_estimated_claims(self):
        payload = fixture(historical=["ACTUAL", "SIMULATED"])
        for kind in ("ACTUAL", "ESTIMATED"):
            with self.subTest(kind=kind):
                with self.assertRaisesRegex(BrainError, "HOLDINGS_EVIDENCE_KIND_UNDERSTATED"):
                    validate_event(observation(payload, kind), NOW)
        result = self.record(payload, "SIMULATED")
        self.assertEqual(result["data_kind"], "SIMULATED")
        self.assertEqual(result["valuation_data_kind"], "ACTUAL")
        self.assertEqual(result["historical_data_kind"], "SIMULATED")
        self.assertEqual(result["history"]["data_kind"], "SIMULATED")
        self.assertEqual(result["history"]["data_kinds"], ["ACTUAL", "SIMULATED"])
        self.assertEqual(len(result["history"]["sources"]), 2)

    def test_estimated_historical_prices_require_estimated_or_more_conservative(self):
        payload = fixture(historical=["ESTIMATED"])
        with self.assertRaisesRegex(BrainError, "HOLDINGS_EVIDENCE_KIND_UNDERSTATED"):
            validate_event(observation(payload, "ACTUAL"), NOW)
        result = self.record(payload, "ESTIMATED")
        self.assertEqual(result["valuation_data_kind"], "ACTUAL")
        self.assertEqual(result["historical_data_kind"], "ESTIMATED")
        self.assertEqual(result["data_kind"], "ESTIMATED")

    def test_simulated_current_quotes_dominate_estimated_history(self):
        payload = fixture(quotes={"A": "SIMULATED", "B": "ESTIMATED"},
                          historical=["ESTIMATED"])
        self.assertEqual(holdings_evidence(payload)["required_data_kind"], "SIMULATED")
        with self.assertRaisesRegex(BrainError, "HOLDINGS_EVIDENCE_KIND_UNDERSTATED"):
            validate_event(observation(payload, "ESTIMATED"), NOW)
        result = self.record(payload, "SIMULATED")
        self.assertEqual(result["valuation_data_kind"], "SIMULATED")
        self.assertEqual(result["historical_data_kind"], "ESTIMATED")

    def test_conservative_outer_label_is_accepted_without_inventing_actuality(self):
        payload = fixture()
        result = self.record(payload, "SIMULATED")
        self.assertEqual(result["data_kind"], "SIMULATED")
        self.assertEqual(result["declared_data_kind"], "SIMULATED")
        self.assertEqual(result["valuation_data_kind"], "ACTUAL")
        self.assertFalse(result["sources_independently_verified"])

    def test_history_absent_is_unavailable_not_actual_or_simulated(self):
        result = self.record(fixture(historical=[]), "ACTUAL")
        self.assertEqual(result["historical_data_kind"], "UNAVAILABLE")
        self.assertEqual(result["history"]["data_kind"], "UNAVAILABLE")
        self.assertEqual(result["historical_data_kinds"], [])
        self.assertEqual(result["history"]["sources"], [])

    def test_mixed_input_batch_rejected_atomically(self):
        valid = observation(fixture(), "ACTUAL")
        invalid = observation(
            fixture(quotes={"A": "ESTIMATED", "B": "ACTUAL"}),
            "ACTUAL", now="2026-10-09T12:59:00Z",
        )
        with self.assertRaisesRegex(BrainError, "HOLDINGS_EVIDENCE_KIND_UNDERSTATED"):
            self.store.submit([valid, invalid], now=NOW)
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM events").fetchone()[0], 0)
        self.assertEqual(self.store.pending(), 0)

    def test_hash_consistent_legacy_mislabel_replays_with_downgrade_no_rewrite(self):
        payload = fixture(historical=["ACTUAL", "SIMULATED"])
        legacy = observation(payload, "ACTUAL")
        # Pre-V5 versions permitted this data classification. Reconstruct an
        # already-persisted, valid one-event transaction WITHOUT using new
        # strict ingestion, demonstrating historic data compatibility.
        prior = "0" * 64
        body = canonical(legacy)
        hashed = digest(legacy)
        with self.store.transaction():
            seq = self.store.db.execute(
                "INSERT INTO events(id,body,hash,status,received_at) "
                "VALUES(?,?,?,'APPLIED',?)",
                (legacy["id"], body, hashed, NOW),
            ).lastrowid
            chain = digest({"seq": seq, "event_hash": hashed, "previous": prior})
            self.store.db.execute(
                "INSERT INTO ledger(seq,prev_hash,chain_hash) VALUES(?,?,?)",
                (seq, prior, chain),
            )
        self.assertEqual(self.store.pending(), 0)
        with self.assertRaisesRegex(BrainError, "HOLDINGS_EVIDENCE_KIND_UNDERSTATED"):
            validate_event(legacy, NOW)
        pre_report_event = self.store.db.execute(
            "SELECT body,hash FROM events WHERE id=?", (legacy["id"],)
        ).fetchone()
        self.assertEqual(pre_report_event["body"], body)
        self.assertEqual(pre_report_event["hash"], hashed)
        view = self.store.report(SOURCE, now=NOW)
        self.assertEqual(view["holdings"][0]["declared_data_kind"], "ACTUAL")
        self.assertEqual(view["holdings"][0]["data_kind"], "SIMULATED")
        self.assertTrue(view["holdings"][0]["legacy_provenance_understated"])
        self.assertEqual(self.store.read_report(SOURCE, now=NOW), view)
        after = self.store.db.execute(
            "SELECT body,hash FROM events WHERE id=?", (legacy["id"],)
        ).fetchone()
        self.assertEqual(tuple(after), (body, hashed))
        self.store.close()
        reopened = Store(self.db_path, visibility="PRIVATE")
        try:
            self.assertEqual(reopened.read_report(SOURCE, now=NOW), view)
        finally:
            reopened.close()

    def test_historical_facts_not_mutated_by_report_projection(self):
        row = observation(fixture(), "ACTUAL")
        before = copy.deepcopy(row)
        result = holdings_projection(row)
        self.assertEqual(row, before)
        self.assertFalse(result["sources_independently_verified"])
        self.assertEqual(result["history"]["basis"],
                         "FIXED_CURRENT_HOLDINGS_SCENARIO_NOT_REALIZED_PERFORMANCE")
        self.assertIsNone(result["history"]["annualized_volatility"])


if __name__ == "__main__":
    unittest.main()
