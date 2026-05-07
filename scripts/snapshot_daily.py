"""Phase 1: pull every watchlist ticker's option chain and persist to DuckDB.

Designed to run from launchd / cron once per day (e.g. 16:15 ET).

Usage:
    uv run scripts/snapshot_daily.py                  # whole watchlist
    uv run scripts/snapshot_daily.py SPY AAPL         # subset by CLI args
"""

from __future__ import annotations

import logging
import sys
import time

from chain_peeper.ibkr.chain_fetcher import fetch_chain
from chain_peeper.ibkr.connection import connect_ibkr
from chain_peeper.storage.duckdb_store import open_db, write_snapshot
from chain_peeper.watchlist import load_watchlist

log = logging.getLogger("snapshot_daily")


def main(argv: list[str]) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    requested = {a.upper() for a in argv[1:]} if len(argv) > 1 else None
    specs = [s for s in load_watchlist() if (requested is None or s.symbol in requested)]
    if not specs:
        log.error("No matching tickers in watchlist for %s", requested)
        return 2

    log.info("Snapshotting %d ticker(s): %s", len(specs), ", ".join(s.symbol for s in specs))
    started = time.time()
    successes = 0
    failures: list[tuple[str, str]] = []

    with connect_ibkr() as ib, open_db() as con:
        for spec in specs:
            t0 = time.time()
            try:
                snap = fetch_chain(ib, spec)
                n = write_snapshot(
                    con,
                    underlying={
                        "snapshot_date": snap.snapshot_ts.date(),
                        "snapshot_ts": snap.snapshot_ts,
                        "symbol": snap.symbol,
                        "underlying_px": snap.underlying_px,
                    },
                    options=snap.contracts,
                )
                dt = time.time() - t0
                log.info(
                    "%s: spot=%.2f  contracts=%d  written=%d  (%.1fs)",
                    spec.symbol, snap.underlying_px, len(snap.contracts), n, dt,
                )
                successes += 1
            except Exception as e:
                log.exception("%s: FAILED — %s", spec.symbol, e)
                failures.append((spec.symbol, str(e)))

    log.info(
        "Done: %d ok, %d failed in %.1fs",
        successes, len(failures), time.time() - started,
    )
    if failures:
        for sym, msg in failures:
            log.warning("  %s: %s", sym, msg)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
