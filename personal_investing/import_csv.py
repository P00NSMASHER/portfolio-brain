"""Import manually exported holdings/prices to a private local JSON snapshot.

No Tradier or other broker/API access; the only operations are local file reads
and an atomic owner-local output. Never run this on a hosted/public runner with
private inputs.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
import tempfile

from personal_investing.engine import PersonalDataError, analyze

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_DIR = ROOT / "private_runtime" / "personal"


def _rows(path, fields, limit):
    path = Path(path)
    if not path.is_file() or path.stat().st_size > 5_000_000:
        raise PersonalDataError("LOCAL_INPUT_UNAVAILABLE_OR_OVERSIZED")
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None or set(reader.fieldnames) != set(fields) \
                or len(reader.fieldnames) != len(fields):
            raise PersonalDataError("CSV_COLUMNS_INVALID")
        rows = []
        for row in reader:
            if len(rows) >= limit:
                raise PersonalDataError("CSV_ROW_LIMIT")
            if None in row or any(value is None for value in row.values()):
                raise PersonalDataError("CSV_ROW_MALFORMED")
            rows.append(row)
        return rows


def make_snapshot(holdings_csv, history_csv, watchlist_csv=None, *,
                  cash_usd="0", as_of="2026-10-31"):
    """Market values are user-marked CSV values, never verified live quotes."""
    pos = []
    quotes = {}
    for row in _rows(holdings_csv, (
        "symbol", "shares", "total_cost_usd", "sector",
        "price", "observed_on", "source",
    ), 100):
        symbol = row["symbol"].strip().upper()
        pos.append({
            "symbol": symbol, "shares": row["shares"].strip(),
            "total_cost_usd": row["total_cost_usd"].strip() or None,
            "sector": row["sector"].strip()
        })
        if symbol in quotes:
            raise PersonalDataError("CSV_DUPLICATE_HOLDING")
        quotes[symbol] = {
            "price": row["price"].strip(),
            "observed_on": row["observed_on"].strip(),
            "source": row["source"].strip()
        }
    history = {}
    seen = set()
    for row in _rows(history_csv, ("symbol", "date", "close"), 250000):
        symbol = row["symbol"].strip().upper()
        date = row["date"].strip()
        if (symbol, date) in seen:
            raise PersonalDataError("CSV_DUPLICATE_HISTORY_DATE")
        seen.add((symbol, date))
        history.setdefault(symbol, []).append({
            "date": date, "close": row["close"].strip()
        })
    for rows in history.values():
        rows.sort(key=lambda r: r["date"])
    watchlist = []
    if watchlist_csv is not None:
        for row in _rows(watchlist_csv, ("symbol", "note"), 100):
            watchlist.append({
                "symbol": row["symbol"].strip().upper(),
                "note": row["note"].strip()
            })
    snapshot = {
        "currency": "USD", "as_of": as_of,
        "data_kind": "USER_SUPPLIED", "cash_usd": str(cash_usd),
        "positions": pos, "quotes": quotes, "history": history,
        "watchlist": watchlist,
    }
    analyze(snapshot)  # validate ALL rows before any private write
    return snapshot


def atomic_private_write(snapshot, path):
    private_root = PRIVATE_DIR.resolve()
    target = Path(path).resolve()
    if not target.is_relative_to(private_root) or target.suffix != ".json":
        raise PersonalDataError("PRIVATE_OUTPUT_DIRECTORY_REQUIRED")
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # The generated snapshot contains user holdings. Never log its contents.
    tmp_name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=target.parent, prefix=".private-",
            suffix=".tmp", delete=False,
        ) as stream:
            tmp_name = stream.name
            os.chmod(tmp_name, 0o600)
            json.dump(snapshot, stream, separators=(",", ":"))
            stream.write("\n")
        os.replace(tmp_name, target)
        os.chmod(target, 0o600)
    finally:
        if tmp_name is not None and Path(tmp_name).exists():
            Path(tmp_name).unlink()
    return target


def cli():
    p = argparse.ArgumentParser(description="Prepare a fully local holdings snapshot")
    p.add_argument("--holdings", required=True)
    p.add_argument("--history", required=True)
    p.add_argument("--watchlist")
    p.add_argument("--as-of", required=True)
    p.add_argument("--cash", default="0")
    p.add_argument("--output",
                   default="private_runtime/personal/portfolio.json")
    args = p.parse_args()
    snapshot = make_snapshot(args.holdings, args.history, args.watchlist,
                             cash_usd=args.cash, as_of=args.as_of)
    target = atomic_private_write(snapshot, args.output)
    print("PRIVATE_SNAPSHOT_CREATED: " + str(target))


if __name__ == "__main__":
    cli()
