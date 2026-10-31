"""Local-only, non-executing portfolio analysis for one private individual.

No market-data calls, broker operations, credential reads, prices, or personal
inputs are stored in this public repository. Every result is derived solely from
the operator's explicitly imported snapshot; no forecast or trading advice.
"""
from __future__ import annotations

import argparse
from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
from pathlib import Path
import re
import statistics

SYMBOL = re.compile(r"[A-Z][A-Z0-9.^-]{0,15}\Z")
ALLOWED_KINDS = {"USER_SUPPLIED", "SIMULATED", "ESTIMATED"}
MAX_POSITIONS = 100
MAX_WATCHLIST = 100
MAX_BARS = 2500


class PersonalDataError(ValueError):
    """Invalid or insufficient input. No original sensitive payload in errors."""


def require(condition, reason):
    if not condition:
        raise PersonalDataError(reason)


def money(value, label, *, zero=True):
    require(type(value) in (int, float, str), label + "_INVALID")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise PersonalDataError(label + "_INVALID") from None
    require(result.is_finite() and (result >= 0 if zero else result > 0),
            label + "_OUT_OF_RANGE")
    require(result <= Decimal("100000000000"), label + "_OUT_OF_RANGE")
    return result


def day(value):
    require(type(value) is str, "DATE_INVALID")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise PersonalDataError("DATE_INVALID") from None


def ticker(value):
    require(type(value) is str and SYMBOL.fullmatch(value) is not None,
            "SYMBOL_INVALID")
    return value


def rounded(value, places=2):
    return str(Decimal(value).quantize(Decimal("1").scaleb(-places)))


def _series(raw, as_of):
    require(type(raw) is list and len(raw) <= MAX_BARS, "HISTORY_SIZE_INVALID")
    rows = []
    prev = None
    for row in raw:
        require(type(row) is dict and set(row) == {"date", "close"}, "BAR_SCHEMA_INVALID")
        d = day(row["date"])
        require(d <= as_of and (prev is None or d > prev), "BAR_DATE_ORDER_INVALID")
        p = money(row["close"], "CLOSE", zero=False)
        rows.append((d, p))
        prev = d
    return rows


def load_snapshot(obj):
    """Strict schema validation prevents silent provenance or price fabrication."""
    require(type(obj) is dict and set(obj) == {
        "currency", "as_of", "data_kind", "cash_usd", "positions",
        "quotes", "history", "watchlist"
    }, "SNAPSHOT_SCHEMA_INVALID")
    require(obj["currency"] == "USD", "USD_ONLY")
    as_of = day(obj["as_of"])
    require(type(obj["data_kind"]) is str and obj["data_kind"] in ALLOWED_KINDS,
            "DATA_KIND_INVALID")
    cash = money(obj["cash_usd"], "CASH")
    positions = obj["positions"]
    require(type(positions) is list and len(positions) <= MAX_POSITIONS,
            "POSITIONS_INVALID")
    names = set()
    normalized = []
    for p in positions:
        require(type(p) is dict and set(p) == {
            "symbol", "shares", "total_cost_usd", "sector"
        }, "POSITION_SCHEMA_INVALID")
        sym = ticker(p["symbol"])
        require(sym not in names, "DUPLICATE_POSITION")
        names.add(sym)
        shares = money(p["shares"], "SHARES", zero=False)
        cost = None if p["total_cost_usd"] is None else money(
            p["total_cost_usd"], "COST"
        )
        require(type(p["sector"]) is str and 0 < len(p["sector"]) <= 60,
                "SECTOR_INVALID")
        normalized.append({"symbol": sym, "shares": shares,
                           "total_cost_usd": cost, "sector": p["sector"]})
    require(bool(normalized) or cash > 0, "EMPTY_PORTFOLIO")

    quotes = obj["quotes"]
    require(type(quotes) is dict and set(quotes) == names, "QUOTE_COVERAGE_INVALID")
    normalized_quotes = {}
    for sym, q in quotes.items():
        require(type(q) is dict and set(q) == {
            "price", "observed_on", "source"
        }, "QUOTE_SCHEMA_INVALID")
        observed = day(q["observed_on"])
        require(observed <= as_of, "QUOTE_IN_FUTURE")
        require(type(q["source"]) is str and 0 < len(q["source"]) <= 150,
                "QUOTE_SOURCE_MISSING")
        normalized_quotes[sym] = {
            "price": money(q["price"], "QUOTE", zero=False),
            "observed_on": observed, "source": q["source"]
        }
    history = obj["history"]
    require(type(history) is dict and len(history) <= MAX_POSITIONS + MAX_WATCHLIST,
            "HISTORY_INVALID")
    normalized_history = {}
    for sym, bars in history.items():
        ticker(sym)
        normalized_history[sym] = _series(bars, as_of)
    # A history row is NEVER implied from a quote or another ticker.
    watch = obj["watchlist"]
    require(type(watch) is list and len(watch) <= MAX_WATCHLIST, "WATCHLIST_INVALID")
    watch_names = set()
    normalized_watch = []
    for item in watch:
        require(type(item) is dict and set(item) == {"symbol", "note"},
                "WATCHLIST_SCHEMA_INVALID")
        sym = ticker(item["symbol"])
        require(sym not in watch_names, "DUPLICATE_WATCHLIST")
        watch_names.add(sym)
        require(type(item["note"]) is str and len(item["note"]) <= 180,
                "WATCHLIST_NOTE_INVALID")
        normalized_watch.append({"symbol": sym, "note": item["note"]})
    return {"as_of": as_of, "data_kind": obj["data_kind"],
            "cash": cash, "positions": normalized,
            "quotes": normalized_quotes, "history": normalized_history,
            "watchlist": normalized_watch}


def _metrics(series):
    if len(series) < 2:
        return {"bars": len(series), "price_return_pct": None,
                "drawdown_pct": None, "volatility_per_observation_pct": None,
                "historical_var_95_pct": None}
    vals = [float(v) for _, v in series]
    returns = [b / a - 1 for a, b in zip(vals, vals[1:])]
    peak = vals[0]
    drawdown = 0.0
    for v in vals:
        peak = max(peak, v)
        drawdown = min(drawdown, (v / peak) - 1)
    # Historical VaR is a percentile of supplied observations, NOT a model
    # of the next day or proof these bars have identical exchange-day spacing.
    losses = sorted(-r for r in returns)
    var = (losses[max(0, math.ceil(0.95 * len(losses)) - 1)]
           if len(returns) >= 20 else None)
    return {
        "bars": len(series),
        "price_return_pct": round((vals[-1] / vals[0] - 1) * 100, 3),
        "drawdown_pct": round(drawdown * 100, 3),
        "volatility_per_observation_pct": round(statistics.stdev(returns) * 100, 3)
        if len(returns) >= 2 else None,
        "historical_var_95_pct": round(max(0.0, var) * 100, 3)
        if var is not None else None,
    }


def _fixed_holdings_history(positions, cash, history):
    if not positions or any(p["symbol"] not in history for p in positions):
        return []
    by_symbol = {p["symbol"]: dict(history[p["symbol"]]) for p in positions}
    dates = set.intersection(*(set(bars) for bars in by_symbol.values()))
    return [
        (d, cash + sum(p["shares"] * by_symbol[p["symbol"]][d] for p in positions))
        for d in sorted(dates)
    ]


def backtest_sma(bars, *, short=5, long=20, cost_bps=5):
    """Offline price-only SMA demonstration with PREVIOUS-BAR signals.

    Uses no future price in decisions, no dividends/borrowing/shorting, no
    fill assumptions beyond close and modeled fees. Not a strategy promise.
    """
    require(type(short) is int and type(long) is int and 1 <= short < long <= 250,
            "BACKTEST_WINDOW_INVALID")
    require(type(cost_bps) is int and 0 <= cost_bps <= 500,
            "BACKTEST_COST_INVALID")
    require(type(bars) is list and len(bars) >= long + 2, "BACKTEST_HISTORY_SHORT")
    closes = [float(p) for _, p in bars]
    require(all(math.isfinite(p) and p > 0 for p in closes), "BACKTEST_PRICE_INVALID")
    capital = 10000.0
    shares = 0.0
    fees = 0.0
    trades = 0
    curve = []
    for i in range(long, len(closes)):
        prev = closes[i - long:i]  # excludes bar i; no current-bar signal leakage
        signal = statistics.fmean(prev[-short:]) > statistics.fmean(prev)
        price = closes[i]
        if signal and not shares:
            shares = capital / (price * (1 + cost_bps / 10000))
            fees += shares * price * cost_bps / 10000
            capital = 0.0
            trades += 1
        elif not signal and shares:
            gross = shares * price
            fee = gross * cost_bps / 10000
            fees += fee
            capital = gross - fee
            shares = 0.0
            trades += 1
        curve.append((bars[i][0], capital + shares * price))
    return {
        "status": "SIMULATED_PRICE_ONLY",
        "bars": len(curve),
        "start_value_usd": "10000.00",
        "final_value_usd": rounded(curve[-1][1]),
        "buy_and_hold_same_period_usd": rounded(10000 * closes[-1] / closes[long]),
        "trades": trades,
        "modeled_fees_usd": rounded(fees),
        "signal_uses_previous_bars": True,
        "no_orders_or_broker_calls": True,
    }


def analyze(snapshot):
    s = load_snapshot(snapshot)
    positions, cash, quotes = s["positions"], s["cash"], s["quotes"]
    line_items = []
    sector_values = {}
    marks = {}
    cost_complete = all(p["total_cost_usd"] is not None for p in positions)
    for p in positions:
        q = quotes[p["symbol"]]
        value = p["shares"] * q["price"]
        marks[p["symbol"]] = value
        sector_values[p["sector"]] = sector_values.get(p["sector"], Decimal(0)) + value
        age = (s["as_of"] - q["observed_on"]).days
        line_items.append({
            "symbol": p["symbol"], "sector": p["sector"], "shares": str(p["shares"]),
            "price_usd": str(q["price"]), "value_usd": rounded(value),
            "cost_usd": None if p["total_cost_usd"] is None else rounded(p["total_cost_usd"]),
            "quote_age_calendar_days": age, "source": q["source"],
        })
    nav = cash + sum(marks.values(), Decimal(0))
    require(nav > 0, "NAV_ZERO")
    for row in line_items:
        value = Decimal(row["value_usd"])
        row["weight_pct"] = round(float(value / nav * 100), 3)
    history = _fixed_holdings_history(positions, cash, s["history"])
    metrics = _metrics(history)
    alerts = []
    if any(row["weight_pct"] > 35 for row in line_items):
        alerts.append("HIGH_SINGLE_POSITION_CONCENTRATION")
    if any(float(v / nav * 100) > 50 for v in sector_values.values()):
        alerts.append("HIGH_SECTOR_CONCENTRATION")
    if any(row["quote_age_calendar_days"] > 7 for row in line_items):
        alerts.append("STALE_OPERATOR_SUPPLIED_QUOTE")
    if metrics["bars"] < 20:
        alerts.append("INSUFFICIENT_ALIGNED_HISTORICAL_BARS")
    hhi = float(sum((v / nav) ** 2 for v in marks.values()) + (cash / nav) ** 2)
    watchlist = []
    for w in s["watchlist"]:
        bars = s["history"].get(w["symbol"], [])
        m = _metrics(bars)
        # Momentum is descriptive, not a BUY/SELL direction or prediction.
        watchlist.append({
            **w, "historical_bars": len(bars),
            "trailing_price_return_pct": m["price_return_pct"]
            if len(bars) >= 21 else None,
            "evidence": "IMPORTED_HISTORY_ONLY" if len(bars) >= 21 else "INSUFFICIENT_HISTORY",
        })
    return {
        "status": "OFFLINE_READ_ONLY", "as_of": str(s["as_of"]),
        "data_kind": s["data_kind"], "quote_sources_independently_verified": False,
        "currency": "USD", "nav_usd": rounded(nav), "cash_usd": rounded(cash),
        "positions": line_items, "watchlist": watchlist,
        "sector_weight_pct": {k: round(float(v / nav * 100), 3)
                              for k, v in sorted(sector_values.items())},
        "concentration_hhi": round(hhi, 5),
        "unrealized_gain_usd": rounded(sum(marks.values()) -
            sum((p["total_cost_usd"] for p in positions), Decimal(0)))
            if cost_complete else None,
        "fixed_holdings_history": [
            {"date": str(d), "nav_usd": rounded(v)} for d, v in history
        ],
        "history_metrics": metrics, "alerts": alerts,
        "stress_equities_down_20_usd": rounded(cash + sum(marks.values()) * Decimal("0.8")),
        "execution_authority": False, "paper_only": True,
        "limitations": [
            "Historical fixed-current-shares scenario, not account performance.",
            "Prices are user-supplied and have not been independently verified.",
            "Risk measures describe supplied samples, not future losses or profit.",
            "No brokerage connection or order placement in this module.",
        ]
    }


def paper_preview(snapshot, symbol, delta_shares, *, proposed_price):
    """Hypothetical long-only trade impact; does not place any order."""
    s = load_snapshot(snapshot)
    sym = ticker(symbol)
    require(type(delta_shares) in (int, float, str), "DELTA_INVALID")
    try:
        signed = Decimal(str(delta_shares))
    except (InvalidOperation, ValueError):
        raise PersonalDataError("DELTA_INVALID") from None
    require(signed.is_finite() and signed != 0, "DELTA_INVALID")
    shares = money(str(abs(signed)), "DELTA", zero=False)
    direction = "SELL" if signed < 0 else "BUY"
    px = money(proposed_price, "PAPER_PRICE", zero=False)
    existing = next((p["shares"] for p in s["positions"] if p["symbol"] == sym), Decimal(0))
    if direction == "SELL":
        require(shares <= existing, "PAPER_CANNOT_SELL_UNHELD")
        cash_after = s["cash"] + shares * px
    else:
        require(shares * px <= s["cash"], "PAPER_INSUFFICIENT_CASH")
        cash_after = s["cash"] - shares * px
    return {"status": "PAPER_ONLY", "symbol": sym, "direction": direction,
            "shares": str(shares), "hypothetical_price_usd": str(px),
            "cash_after_usd": rounded(cash_after),
            "shares_after": str(existing + (shares if direction == "BUY" else -shares)),
            "submitted_to_broker": False}


def cli():
    parser = argparse.ArgumentParser(description="Private, local-only investing analysis")
    parser.add_argument("--input", required=True,
                        help="Private JSON snapshot. Never commit this file.")
    parser.add_argument("--output", default="private_runtime/personal/investing-report.json")
    args = parser.parse_args()
    obj = json.loads(Path(args.input).read_text(encoding="utf-8"))
    report = analyze(obj)
    dest = Path(args.output)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("OFFLINE_REPORT_CREATED: " + str(dest))


if __name__ == "__main__":
    cli()
