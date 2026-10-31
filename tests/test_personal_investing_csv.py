"""Hostile offline CSV-to-private-snapshot import tests."""
import csv
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from personal_investing import import_csv as imp
from personal_investing.engine import PersonalDataError, analyze


class LocalCSVImportTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.root = Path(self.dir.name)
        self.hold = self.root / "holdings.csv"
        self.history = self.root / "history.csv"
        self.watch = self.root / "watchlist.csv"
        self.csv(self.hold,
                 ["symbol", "shares", "total_cost_usd", "sector",
                  "price", "observed_on", "source"],
                 [["SPY", "2", "900", "ETF", "500", "2026-10-30", "manual"],
                  ["AAPL", "1", "", "Technology", "190", "2026-10-30", "manual"]])
        self.csv(self.history, ["symbol", "date", "close"],
                 [["SPY", "2026-10-01", "490"],
                  ["AAPL", "2026-10-01", "180"],
                  ["SPY", "2026-10-02", "495"],
                  ["AAPL", "2026-10-02", "185"]])
        self.csv(self.watch, ["symbol", "note"],
                 [["SPY", "Local paper research"]])

    def csv(self, path, headers, rows):
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow(headers)
            writer.writerows(rows)

    def produce(self, **kwargs):
        return imp.make_snapshot(
            self.hold, self.history, self.watch,
            cash_usd="1000", as_of="2026-10-31", **kwargs
        )

    def test_valid_import_aligns_data_and_retains_unverified_provenance(self):
        value = self.produce()
        self.assertEqual(value["data_kind"], "USER_SUPPLIED")
        self.assertEqual([p["symbol"] for p in value["positions"]], ["SPY", "AAPL"])
        self.assertEqual(value["positions"][1]["total_cost_usd"], None)
        out = analyze(value)
        self.assertEqual(out["nav_usd"], "2190.00")
        self.assertEqual(out["history_metrics"]["bars"], 2)
        self.assertFalse(out["quote_sources_independently_verified"])
        self.assertIsNone(out["unrealized_gain_usd"])
        self.assertFalse(out["execution_authority"])

    def test_duplicate_holding_cannot_override_original_quote(self):
        with self.hold.open("a", encoding="utf-8") as f:
            f.write("SPY,5,20,ETF,1,2026-10-30,forged\n")
        with self.assertRaisesRegex(PersonalDataError, "CSV_DUPLICATE_HOLDING"):
            self.produce()

    def test_duplicate_hist_date_fails_before_write(self):
        with self.history.open("a", encoding="utf-8") as f:
            f.write("SPY,2026-10-01,499\n")
        with self.assertRaisesRegex(PersonalDataError, "CSV_DUPLICATE_HISTORY_DATE"):
            self.produce()

    def test_input_columns_unknown_and_malformed_row_fails(self):
        self.csv(self.hold, ["symbol", "shares"], [["SPY", "2"]])
        with self.assertRaisesRegex(PersonalDataError, "CSV_COLUMNS_INVALID"):
            self.produce()
        self.csv(self.hold, [
            "symbol", "shares", "total_cost_usd", "sector",
            "price", "observed_on", "source"
        ], [["SPY", "2"]])
        with self.assertRaisesRegex(PersonalDataError, "CSV_ROW_MALFORMED"):
            self.produce()

    def test_no_network_or_broker_or_token_use(self):
        source = Path("personal_investing/import_csv.py").read_text()
        for token in ("requests.get", "urllib.request", "api.tradier.com",
                      "TRADIER_TOKEN", "orders/place", "submit_order"):
            self.assertNotIn(token, source)

    def test_atomically_written_snapshots_private_and_public_path_denied(self):
        payload = self.produce()
        private = self.root / "private_runtime" / "personal"
        dest = private / "portfolio.json"
        with patch.object(imp, "PRIVATE_DIR", private):
            result = imp.atomic_private_write(payload, dest)
            self.assertEqual(result, dest)
            self.assertEqual(json.loads(dest.read_text()), payload)
            if os.name != "nt":
                self.assertEqual(stat.S_IMODE(dest.stat().st_mode), 0o600)
            self.assertFalse(list(private.glob(".private-*")))
            with self.assertRaisesRegex(
                PersonalDataError, "PRIVATE_OUTPUT_DIRECTORY_REQUIRED"
            ):
                imp.atomic_private_write(payload, self.root / "public_snapshot.json")

    def test_future_and_incorrect_source_price_denied(self):
        self.csv(self.hold, [
            "symbol", "shares", "total_cost_usd", "sector",
            "price", "observed_on", "source"
        ], [["SPY", "2", "900", "ETF", "-500", "2026-11-01", "manual"]])
        with self.assertRaises(PersonalDataError):
            self.produce()

    def test_history_is_deterministically_sorted_only_by_date(self):
        self.csv(self.history, ["symbol", "date", "close"],
                 [["SPY", "2026-10-02", "495"], ["AAPL", "2026-10-02", "185"],
                  ["SPY", "2026-10-01", "490"], ["AAPL", "2026-10-01", "180"]])
        value = self.produce()
        self.assertEqual([r["date"] for r in value["history"]["SPY"]],
                         ["2026-10-01", "2026-10-02"])


if __name__ == "__main__":
    unittest.main()
