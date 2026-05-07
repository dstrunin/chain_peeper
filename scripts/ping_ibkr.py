"""Phase 0 sanity check: connect to TWS, request a quote, print it.

Usage:
    uv run scripts/ping_ibkr.py            # default symbol SPY
    uv run scripts/ping_ibkr.py AAPL TSLA  # any number of symbols
"""

from __future__ import annotations

import math
import sys
import time

from ib_async import Stock

from chain_peeper.ibkr.connection import connect_ibkr


def _fmt(x: float | None) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "    n/a"
    return f"{x:8.2f}"


def main(argv: list[str]) -> int:
    symbols = argv[1:] or ["SPY"]
    with connect_ibkr() as ib:
        print(f"Connected. Server version {ib.client.serverVersion()}.\n")
        contracts = [Stock(s, "SMART", "USD") for s in symbols]
        ib.qualifyContracts(*contracts)

        # Request snapshot quotes for all symbols in parallel
        tickers = [ib.reqMktData(c, "", snapshot=False, regulatorySnapshot=False) for c in contracts]
        # Give IBKR a moment to fill in bid/ask/last
        deadline = time.time() + 5
        while time.time() < deadline and not all(
            (t.bid and t.ask) or t.last for t in tickers
        ):
            ib.sleep(0.1)

        print(f"{'SYMBOL':<8}{'BID':>10}{'ASK':>10}{'LAST':>10}{'CLOSE':>10}")
        print("-" * 48)
        for sym, t in zip(symbols, tickers):
            print(
                f"{sym:<8}{_fmt(t.bid):>10}{_fmt(t.ask):>10}"
                f"{_fmt(t.last):>10}{_fmt(t.close):>10}"
            )
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
