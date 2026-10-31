# Private Brain: Personal Investing Companion (v0.1 review candidate)

**Purpose:** personal-use investment research, a local dashboard, offline paper scenarios and risk checks. **NOT** a commercial product, live brokerage terminal, order platform, recommendation system, or a deployed application.

## Start in 30 seconds

1. Download `personal_investing/dashboard.html` and **open the file on your own computer**. It is a self-contained responsive page with no remote scripts, API calls, cookies or browser storage.
2. Click **Synthetic demo**. This is made-up sample data with fake quotes and historical paths.
3. To use your own data, copy `personal_investing/examples/snapshot.synthetic.json` into a directory **outside this public repository**, edit it with your own holdings/quotes, then choose **Import private JSON** in the browser. The file is read only into this tab's memory. Close the tab or click **Clear memory** when finished. Never paste a broker token in the JSON.
4. Python 3.12 offline numerical verification, from repository root:

   ```sh
   python -m personal_investing.engine --input personal_investing/examples/snapshot.synthetic.json
   ```

   Output defaults to `private_runtime/personal/investing-report.json`, now explicitly excluded by `.gitignore`. **Do not commit or upload real data, generated reports, screenshots, or user-specific account details.**

## Import a spreadsheet export without entering JSON

If you have your own **local CSV exports**, keep the actual files under the ignored `private_runtime/personal/` directory. The importer accepts three small, transparent CSV contracts:

`holdings.csv` columns: `symbol,shares,total_cost_usd,sector,price,observed_on,source`. Prices and sectors are **user-supplied marks**, not authenticated quotes. Leave `total_cost_usd` blank if unavailable.

`history.csv` columns: `symbol,date,close`. Dates are ISO `YYYY-MM-DD`; duplicates, future bars and invalid prices fail closed.

Optional `watchlist.csv` columns: `symbol,note`. These are research notes only.

```sh
python -m personal_investing.import_csv \
  --holdings private_runtime/personal/holdings.csv \
  --history private_runtime/personal/history.csv \
  --watchlist private_runtime/personal/watchlist.csv \
  --cash 2500 --as-of 2026-10-31
```

It validates all inputs **before** creating an owner-local `private_runtime/personal/portfolio.json`. Output is atomic, local, restricted to `private_runtime/personal/` and has user-only permissions on POSIX. Import that JSON into the dashboard. The converter never connects to Tradier, never fetches quotes, never uploads your data, and never adds secret fields.

## Dashboard features

- Long-only holdings, cash, net asset value, relative position weights, single-name and sector concentration, cash-preserving 20% equity shock.
- Strict provenance label and quote-age warning, explicit missing-history status and aligned, fixed-current-share historical scenario curve. **Not** account performance.
- 21-observation imported-history watchlist movement, with no prediction or buy/sell directive. Notes remain in memory.
- Paper buy/sell preview that **never places an order or mutates a portfolio** and blocks oversells, overspend, nonfinite inputs and invalid tickers.
- Historical 5/20 moving-average **demonstration**, using only previous bars to form the signal, with modeled fees and a price-only same-period buy-and-hold comparator. No dividends, slippage, margin, fills, options or forecast.
- Works offline on mobile and desktop. The HTML file intentionally has `connect-src 'none'`.

## Strict snapshot schema

Exactly these top-level keys:

```json
{
  "currency": "USD",
  "as_of": "2026-10-31",
  "data_kind": "USER_SUPPLIED",
  "cash_usd": "2500",
  "positions": [
    {"symbol": "SPY", "shares": "2", "total_cost_usd": "900", "sector": "ETF"}
  ],
  "quotes": {
    "SPY": {"price": "490", "observed_on": "2026-10-30", "source": "my exported quote"}
  },
  "history": {
    "SPY": [{"date": "2026-10-01", "close": "475"}]
  },
  "watchlist": [{"symbol": "SPY", "note": "For research only"}]
}
```

`USER_SUPPLIED` identifies your input, **not independently verified live market data**. Use `SIMULATED` only for made-up values and `ESTIMATED` for estimates. Use only dated, strictly ascending closes. Missing history stays missing: neither CLI nor dashboard fills gaps, manufactures prices or fabricates account returns. For historical experiments you need at least 22 closes, and the annualized performance of a real portfolio is intentionally not claimed.

## Tradier: no extra credential exposure

The separate `P00NSMASHER/trading-platform` repository already operates a **read-only Tradier research workflow**, configured through its GitHub Actions secret, and intentionally forbids brokerage/account trading endpoints. Its October 30, 2026 scheduled workflow completed successfully. That establishes workflow success, not verified personal-account sync, execution quality or any proven trading edge. We do **not** copy its token, market feed, private quotes or user account details into this public repository or browser HTML.

This local companion uses **manual imports only**. A trustworthy account-sync feature would require a separate owner-authorized, private, read-only connector with authenticated consent, redaction, rate limits and safe storage. Neither the current release nor its test suite claims to have connected to or imported a private Tradier account. Live order endpoints are absent.

## Deterministic audit

```sh
python -m unittest -q tests.test_personal_investing_companion
python -m unittest discover -s tests -p 'test_personal_investing_companion.py' -v
```

The tests include **100 separately named portfolio scenarios** (1–5 positions × 5 cash amounts × four synthetic price paths) and adversarial tests for stale/future/duplicate/malformed data, missing coverage, price provenance, paper cash conservation and no external execution. Foundation CI independently runs the existing repository regression suite.

**Deployment state:** This optional companion is a review-only PR until protected GitHub checks authentically pass. The permanent predecessor-acceptance gate may block all new PR merges while the user explicitly holds 12-hour observation. Do not weaken it, fabricate acceptance, or start observation to release this feature.

**Important separation:** Portfolio Brain's existing runtime is a project/research management system, not a brokerage. This standalone offline companion does not alter its scheduler, state branch, repair system, protected verifier, or trading authority.
