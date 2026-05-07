# Chain Peeper

Personal options-chain analytics on top of IBKR. Pulls daily snapshots of every
ticker on your watchlist into DuckDB and renders a Streamlit dashboard.

Phases shipped (per `~/.claude/plans/i-want-to-be-distributed-pie.md`):

- **Phase 0** — uv project, IBKR connection sanity check (`scripts/ping_ibkr.py`)
- **Phase 1** — watchlist config, `fetch_chain` via `ib_async`, idempotent DuckDB upsert,
  daily snapshot script (`scripts/snapshot_daily.py`)
- **Phase 2** — Streamlit "today" dashboard with ATM IV, IV30, term structure,
  OI/volume heatmaps, IV smile, deep-OTM IV, and watchlist-wide top CSP/CC yields

Pending: Phase 3 (historical evolution), Phase 4 (tick capture / biggest trades),
Phase 5 deeper polish, Phase 6.

## Setup

```sh
cp .env.example .env       # edit if your TWS port differs
uv sync                    # installs deps from pyproject + lockfile
```

Make sure TWS or IB Gateway is running with API access enabled (Configure → API → Settings → Enable ActiveX and Socket Clients) and the right port matches `IBKR_PORT` in `.env`.

## Usage

```sh
# Phase 0 — confirm we can talk to IBKR
uv run scripts/ping_ibkr.py SPY AAPL

# Phase 1 — pull and store today's chain for the whole watchlist
uv run scripts/snapshot_daily.py
# Or a subset:
uv run scripts/snapshot_daily.py SPY QQQ

# Phase 2 — open the dashboard
uv run streamlit run src/chain_peeper/dashboard/app.py
```

## Watchlist

Edit `config/watchlist.yaml`. `defaults` apply to every ticker; `overrides` per
symbol can widen expiry / strike windows for the names you care about most.

## Storage

DuckDB file at `data/chain_peeper.duckdb`. Snapshots are idempotent — rerunning
the same day overwrites that day's rows. Two tables: `option_snapshots` (one
row per contract per day) and `underlying_snapshots`.

## Schedule daily snapshots (macOS launchd)

Create `~/Library/LaunchAgents/com.local.chain-peeper.snapshot.plist` pointing
to `uv run scripts/snapshot_daily.py` with a `StartCalendarInterval` at 16:15 ET.
This is on the to-do list — not auto-installed.
