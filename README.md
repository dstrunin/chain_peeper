# Chain Peeper

Personal options-chain analytics on top of Interactive Brokers. Pulls daily
EOD snapshots of every ticker on your watchlist into DuckDB, then renders a
Streamlit dashboard for ATM / IV30 / term structure, OI and volume
clustering, IV smile, deep-OTM IV, and watchlist-wide CSP / CC annualized
yield rankings.

> **Status:** early personal project. Phases 0–2 (data pipeline + today
> dashboard) work end-to-end. Phases 3 (historical evolution), 4 (tick capture
> for "biggest trades today"), and 5+ are on the roadmap, not built yet.

> **Disclaimer:** This is a research / analytics tool. It does not place
> orders (the IBKR connection is opened `readonly=True`). Nothing here is
> investment advice. Quotes can be wrong, IV calculations can be wrong, the
> code can be wrong. Use at your own risk.

## What you need

- An **Interactive Brokers** account with an **options market-data
  subscription** (US Securities Snapshot, OPRA Top of Book, etc.). Without
  one, the script will run but most fields will come back empty.
- **TWS or IB Gateway** installed locally with the API enabled
  (Configure → API → Settings → "Enable ActiveX and Socket Clients").
- **Python 3.12+** and **`uv`** (https://github.com/astral-sh/uv).

The IBKR connection is read-only — Chain Peeper cannot place trades.

## Setup

```sh
git clone https://github.com/dstrunin/chain_peeper.git
cd chain_peeper
cp .env.example .env       # edit if your TWS port or clientId differs
uv sync                    # installs deps from pyproject + lockfile
```

`.env` knobs:

| var | default | meaning |
|--|--|--|
| `IBKR_HOST` | `127.0.0.1` | where TWS / Gateway listens |
| `IBKR_PORT` | `7497` | `7497`=TWS paper, `7496`=TWS live, `4002`=Gateway paper, `4001`=Gateway live |
| `IBKR_CLIENT_ID` | `42` | any 1–32 not already in use by another API client |
| `CHAIN_PEEPER_DB` | `data/chain_peeper.duckdb` | DuckDB file path |
| `IBKR_MKTDATA_TIMEOUT` | `8` | per-batch wait budget in seconds |

## Usage

```sh
# Phase 0 — confirm we can talk to IBKR
uv run scripts/ping_ibkr.py SPY AAPL

# Phase 1 — pull and store today's chain for the whole watchlist
uv run scripts/snapshot_daily.py
# or a subset:
uv run scripts/snapshot_daily.py SPY QQQ

# Phase 2 — open the dashboard
uv run streamlit run src/chain_peeper/dashboard/app.py
```

## Watchlist

Edit `config/watchlist.yaml`. `defaults` apply to every ticker; `overrides`
per symbol can narrow or widen the expiry / strike window for the names you
care about most.

```yaml
defaults:
  expiry_window_days: 120
  strike_pct_window: 0.25
  primary_exchange: SMART

tickers: [SPY, QQQ, AAPL, MSFT, NVDA, AMZN, GOOGL, META, TSLA]

overrides:
  SPY:
    expiry_window_days: 180
    strike_pct_window: 0.10
```

Aim for 10–50 tickers. Beyond that, daily snapshot time gets uncomfortable.

## How it works

```
config/watchlist.yaml ──► scripts/snapshot_daily.py ──► DuckDB
                                  │
                                  └─ src/chain_peeper/ibkr/chain_fetcher.py
                                       (FROZEN market-data mode, batched
                                        qualify + reqMktData, OI + Greeks)
                                                            │
src/chain_peeper/dashboard/app.py ◄──── analytics/{iv,clusters,yields}.py
```

- **Storage**: DuckDB single file, idempotent upsert keyed on
  `(snapshot_date, symbol, expiry, strike, right)`. Re-running on the same
  day overwrites — never duplicates.
- **Data mode**: `reqMarketDataType(2)` (FROZEN). During market hours this
  is equivalent to LIVE; after close it serves the last cached LIVE values
  so EOD snapshots have real bid/ask/IV instead of `-1` sentinels.
- **Privacy**: connection is read-only and `ib_async.wrapper` noisy logs
  (positions, executions, commission reports) are filtered out so your
  account state never lands in `snapshot.log`.

## Known limitations

- **No historical chain backfill.** IBKR doesn't bulk-deliver historical
  options chains. The week / month / year evolution views (Phase 3) will
  populate as daily snapshots accrue. If you want a real one-year view on
  day one, swap the data tier for Polygon Options Starter (~$29/mo).
- **Daily snapshot is slow.** ~10–15 minutes per liquid ticker. Designed
  for a 16:15 ET cron job, not interactive use. Optimizations
  (`snapshot=True` mode, conId cache) are on the roadmap.
- **OI on very illiquid contracts can be missing** even in FROZEN mode if
  IBKR doesn't have a cached OI tick. Most chains come back >85% populated.
- **`reqSecDefOptParams` returns the union of strikes across all expiries**,
  so far-OTM strikes that exist on long-dated expiries get attempted on
  short-dated ones and fail to qualify. We filter those out silently. Costs
  some time per batch but doesn't affect data quality.

## Schedule daily snapshots (macOS launchd)

A templated plist is provided in
`scripts/com.local.chain-peeper.snapshot.plist.example`. Copy it, fill in
`{{REPO_ROOT}}` and `{{UV_PATH}}`, drop the result in
`~/Library/LaunchAgents/`, and `launchctl load` it. Full instructions are at
the top of the example file.

The job fires Mon–Fri at **13:15 PT (16:15 ET)** — 15 minutes after US
equity close. TWS / IB Gateway must be running at that time. Enable
"Auto Restart" in TWS settings to keep it logged in across days.

## Roadmap

- [x] Phase 0 — IBKR sanity check
- [x] Phase 1 — watchlist + chain fetch + DuckDB persist + daily snapshot
- [x] Phase 2 — Streamlit dashboard: ATM / IV30, term structure, OI / volume
      heatmaps, IV smile, deep-OTM IV, CSP / CC yield rankings
- [ ] Phase 3 — historical evolution: IV-rank, OI evolution, week / month /
      year views
- [ ] Phase 4 — tick-by-tick capture: top 10 trades today by notional
- [ ] Phase 5 — alerts (IV spike, unusual volume)
- [ ] Phase 6 — multi-ticker compare, PDF export

## Contributing

PRs welcome but this is a personal project, so expect opinionated review and
slow turnaround. The analytics functions in `src/chain_peeper/analytics/`
are pure DataFrame in / DataFrame out — easy targets if you want to add a
new view without touching IBKR plumbing.

## License

[MIT](LICENSE).

## Acknowledgements

Built on
[`ib_async`](https://github.com/ib-api-reloaded/ib_async),
[`duckdb`](https://duckdb.org/),
[`streamlit`](https://streamlit.io/), and
[`plotly`](https://plotly.com/python/).
