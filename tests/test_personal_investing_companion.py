"""One hundred independent synthetic personal-investing scenarios, plus hostile cases.

No token, broker, market network, private portfolio or actual return is used.
"""
from datetime import date, timedelta
from decimal import Decimal
import copy
import json
import unittest

from personal_investing.engine import (
    PersonalDataError, analyze, backtest_sma, load_snapshot, paper_preview
)

SYMS = ["AAPL", "MSFT", "NVDA", "SPY", "QQQ"]
SECTORS = ["Technology", "Technology", "Technology", "ETF", "ETF"]
AS_OF = "2026-10-31"


def fixture(count=2, cash=1000, pattern=0):
    holdings = []
    quotes = {}
    history = {}
    for i in range(count):
        sym = SYMS[i]
        px = Decimal(90 + i * 13)
        holdings.append({
            "symbol": sym, "shares": str(i + 1),
            "total_cost_usd": str((i + 1) * (px - 10)),
            "sector": SECTORS[i]
        })
        quotes[sym] = {"price": str(px), "observed_on": AS_OF, "source": "synthetic"}
        rows = []
        for d in range(45):
            if pattern == 0:
                close = px
            elif pattern == 1:
                close = px + Decimal(d) / 3
            elif pattern == 2:
                close = px - Decimal(d) / 3
            else:
                close = px + Decimal(4 if d % 2 == 0 else -4)
            rows.append({
                "date": str(date(2026, 9, 1) + timedelta(days=d)),
                "close": str(close)
            })
        history[sym] = rows
    history["IWM"] = [
        {"date": str(date(2026, 9, 1) + timedelta(days=d)),
         "close": str(200 + (d if pattern != 2 else -d / 4))}
        for d in range(45)
    ]
    return {
        "currency": "USD", "as_of": AS_OF, "data_kind": "SIMULATED",
        "cash_usd": str(cash), "positions": holdings,
        "quotes": quotes, "history": history,
        "watchlist": [{"symbol": "IWM", "note": "Synthetic-only research candidate"}]
    }


class AdversarialPersonalInvesting(unittest.TestCase):
    def test_missing_quote_fails_closed(self):
        p = fixture()
        del p["quotes"]["MSFT"]
        with self.assertRaisesRegex(PersonalDataError, "QUOTE_COVERAGE_INVALID"):
            analyze(p)

    def test_nonfinite_data_and_boolean_rejected(self):
        for bad in ("NaN", "Infinity", "-Infinity", -5, True, None, 1e101):
            p = fixture()
            p["cash_usd"] = bad
            with self.subTest(bad=str(bad)), self.assertRaises(PersonalDataError):
                analyze(p)

    def test_duplicate_position_and_watchlist_rejected(self):
        p = fixture()
        p["positions"].append(copy.deepcopy(p["positions"][0]))
        with self.assertRaisesRegex(PersonalDataError, "DUPLICATE_POSITION"):
            analyze(p)
        p = fixture()
        p["watchlist"].append(copy.deepcopy(p["watchlist"][0]))
        with self.assertRaisesRegex(PersonalDataError, "DUPLICATE_WATCHLIST"):
            analyze(p)

    def test_quote_future_and_old_quote_declared_stale(self):
        p = fixture()
        p["quotes"]["AAPL"]["observed_on"] = "2026-11-01"
        with self.assertRaisesRegex(PersonalDataError, "QUOTE_IN_FUTURE"):
            analyze(p)
        p = fixture()
        p["quotes"]["AAPL"]["observed_on"] = "2026-10-20"
        result = analyze(p)
        self.assertIn("STALE_OPERATOR_SUPPLIED_QUOTE", result["alerts"])
        self.assertEqual(result["positions"][0]["quote_age_calendar_days"], 11)

    def test_history_unsorted_duplicate_future_and_zero_price_denied(self):
        for bad in ("2026-09-01", "2026-11-02"):
            p = fixture()
            p["history"]["AAPL"][4]["date"] = bad
            with self.subTest(bad=bad), self.assertRaisesRegex(
                PersonalDataError, "BAR_DATE_ORDER_INVALID"
            ):
                analyze(p)
        p = fixture()
        p["history"]["AAPL"][4]["close"] = "0"
        with self.assertRaisesRegex(PersonalDataError, "CLOSE_OUT_OF_RANGE"):
            analyze(p)

    def test_align_only_identical_observation_dates_never_fill(self):
        p = fixture()
        p["history"]["MSFT"].pop()
        a = analyze(p)
        self.assertEqual(a["history_metrics"]["bars"], 44)
        self.assertEqual(len(a["fixed_holdings_history"]), 44)

    def test_historical_price_is_not_realized_portfolio_return(self):
        p = fixture()
        a = analyze(p)
        self.assertIn("Historical fixed-current-shares scenario", a["limitations"][0])
        self.assertFalse(a["quote_sources_independently_verified"])
        self.assertFalse(a["execution_authority"])
        self.assertTrue(a["paper_only"])

    def test_cost_gap_never_claims_unrealized_pnl(self):
        p = fixture()
        p["positions"][0]["total_cost_usd"] = None
        self.assertIsNone(analyze(p)["unrealized_gain_usd"])

    def test_cash_only_snapshot(self):
        p = fixture(count=1)
        p["positions"] = []
        p["quotes"] = {}
        self.assertEqual(analyze(p)["nav_usd"], "1000.00")

    def test_cash_zero_no_holdings_fails(self):
        p = fixture(count=1, cash=0)
        p["positions"] = []
        p["quotes"] = {}
        with self.assertRaisesRegex(PersonalDataError, "EMPTY_PORTFOLIO"):
            analyze(p)

    def test_paper_buy_sell_are_nonexecuting_and_cash_conserving(self):
        p = fixture(count=1, cash=1000)
        buy = paper_preview(p, "AAPL", "2", proposed_price="100")
        sell = paper_preview(p, "AAPL", "-1", proposed_price="100")
        self.assertEqual(buy["cash_after_usd"], "800.00")
        self.assertEqual(sell["cash_after_usd"], "1100.00")
        self.assertFalse(buy["submitted_to_broker"])
        self.assertFalse(sell["submitted_to_broker"])

    def test_paper_oversell_and_overspend_denied(self):
        p = fixture(count=1)
        with self.assertRaisesRegex(PersonalDataError, "PAPER_CANNOT_SELL_UNHELD"):
            paper_preview(p, "AAPL", "-2", proposed_price="100")
        with self.assertRaisesRegex(PersonalDataError, "PAPER_INSUFFICIENT_CASH"):
            paper_preview(p, "AAPL", "200", proposed_price="100")

    def test_backtest_previous_bar_and_fees(self):
        rows = load_snapshot(fixture(count=1, pattern=1))["history"]["AAPL"]
        gross = backtest_sma(rows, short=3, long=12, cost_bps=0)
        fee = backtest_sma(rows, short=3, long=12, cost_bps=20)
        self.assertTrue(gross["signal_uses_previous_bars"])
        self.assertFalse(gross["no_orders_or_broker_calls"] is False)
        self.assertLessEqual(float(fee["final_value_usd"]), float(gross["final_value_usd"]))
        self.assertTrue(fee["trades"] >= 1)

    def test_unsupported_backtest_and_cost_rejected(self):
        bars = load_snapshot(fixture(count=1))["history"]["AAPL"]
        for kwargs in ({"short": 20, "long": 20}, {"short": 5, "long": 251},
                       {"cost_bps": -1}, {"cost_bps": 501}):
            with self.subTest(kwargs=kwargs), self.assertRaises(PersonalDataError):
                backtest_sma(bars, **kwargs)
        with self.assertRaisesRegex(PersonalDataError, "BACKTEST_HISTORY_SHORT"):
            backtest_sma(bars[:10])

    def test_history_not_available_cannot_be_presented_as_observed(self):
        p = fixture()
        p["history"] = {}
        result = analyze(p)
        self.assertIsNone(result["history_metrics"]["price_return_pct"])
        self.assertIn("INSUFFICIENT_ALIGNED_HISTORICAL_BARS", result["alerts"])

    def test_invalid_data_kind_unknown_fields_and_symbol_fail_closed(self):
        p = fixture()
        p["data_kind"] = "LIVE_VERIFIED"
        with self.assertRaisesRegex(PersonalDataError, "DATA_KIND_INVALID"):
            analyze(p)
        p = fixture()
        p["token"] = "secrets-should-never-be-supported"
        with self.assertRaisesRegex(PersonalDataError, "SNAPSHOT_SCHEMA_INVALID"):
            analyze(p)
        p = fixture()
        p["positions"][0]["symbol"] = "../foo"
        with self.assertRaisesRegex(PersonalDataError, "SYMBOL_INVALID"):
            analyze(p)

    def test_watchlist_is_evidence_labelled_not_trade_directive(self):
        p = fixture()
        out = analyze(p)
        self.assertEqual(out["watchlist"][0]["evidence"], "IMPORTED_HISTORY_ONLY")
        self.assertNotIn("recommendation", out["watchlist"][0])
        self.assertNotIn("target_price", out["watchlist"][0])
        self.assertNotIn("order", out)

    def test_no_secret_or_orders_or_network_in_public_analytics_module(self):
        from pathlib import Path
        source = Path("personal_investing/engine.py").read_text()
        for disallowed in ("api.tradier.com", "urllib.request.urlopen", "requests.post",
                           "submit_order(", "send_order("):
            self.assertNotIn(disallowed, source)

    def test_private_runtime_ignored_from_public_git(self):
        from pathlib import Path
        content = Path(".gitignore").read_text()
        self.assertIn("private_runtime/", content)

    def test_serializable_snapshot_avoids_credential_output(self):
        p = fixture()
        out = analyze(p)
        encoded = json.dumps(out)
        self.assertIn("OFFLINE_READ_ONLY", encoded)
        self.assertNotIn("API_TOKEN", encoded)


class HundredScenarios(unittest.TestCase):
    """5 position counts × 5 cash amounts × 4 market paths = 100 cases."""


def make_scenario(n, size, cash, pattern):
    def test(self):
        p = fixture(count=size, cash=cash, pattern=pattern)
        result = analyze(p)
        expected = Decimal(cash) + sum(
            Decimal(row["shares"]) * Decimal(row["price_usd"])
            for row in result["positions"]
        )
        self.assertEqual(Decimal(result["nav_usd"]), expected)
        self.assertEqual(len(result["positions"]), size)
        self.assertEqual(result["history_metrics"]["bars"], 45)
        self.assertTrue(result["fixed_holdings_history"])
        self.assertTrue(0 <= result["concentration_hhi"] <= 1.00001)
        self.assertEqual(result["status"], "OFFLINE_READ_ONLY")
        self.assertEqual(result["data_kind"], "SIMULATED")
        self.assertEqual(len(result["watchlist"]), 1)
        self.assertEqual(result["execution_authority"], False)
        self.assertEqual(result["stress_equities_down_20_usd"],
                         str((Decimal(cash) + (expected - Decimal(cash)) * Decimal("0.8")).quantize(Decimal(".01"))))
    return test


for s in range(1, 6):
    for c in (0, 100, 1000, 10000, 50000):
        for k in range(4):
            name = "test_case_%03d_%d_positions_%d_cash_%d_path" % (
                1 + (s - 1) * 20 + (0, 100, 1000, 10000, 50000).index(c) * 4 + k,
                s, c, k
            )
            setattr(HundredScenarios, name, make_scenario(name, s, c, k))


if __name__ == "__main__":
    unittest.main()
