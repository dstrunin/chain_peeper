"""Phase 0 sanity check: connect to TWS, request a quote, print it.

Diagnoses common pitfalls:
- prints any IBKR errors as they arrive (error code 10168 = no market data sub,
  10089 = need delayed data, 200 = no security definition, etc.)
- waits up to 12s for live data
- if live returns nothing, retries automatically with delayed-frozen data

Usage:
    uv run scripts/ping_ibkr.py            # default symbol SPY
    uv run scripts/ping_ibkr.py AAPL TSLA  # any number of symbols
"""

from __future__ import annotations

import math
import sys
import time

from ib_async import Stock, Ticker

from chain_peeper.ibkr.connection import connect_ibkr

# 1=live, 2=frozen, 3=delayed, 4=delayed-frozen
DATA_TYPE_NAMES = {1: "LIVE", 2: "FROZEN", 3: "DELAYED", 4: "DELAYED_FROZEN"}


def _fmt(x: float | None) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "    n/a"
    return f"{x:8.2f}"


def _has_quote(t: Ticker) -> bool:
    """True if the ticker has any usable price field."""
    for v in (t.bid, t.ask, t.last, t.close, t.marketPrice()):
        if v is not None and not (isinstance(v, float) and math.isnan(v)):
            return True
    return False


def _wait_for_quotes(ib, tickers: list[Ticker], timeout: float) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline and not all(_has_quote(t) for t in tickers):
        ib.sleep(0.2)


def _print_table(symbols: list[str], tickers: list[Ticker]) -> None:
    print(f"{'SYMBOL':<8}{'BID':>10}{'ASK':>10}{'LAST':>10}{'CLOSE':>10}{'TYPE':>14}")
    print("-" * 62)
    for sym, t in zip(symbols, tickers):
        dt = DATA_TYPE_NAMES.get(getattr(t, "marketDataType", 0), "?")
        print(
            f"{sym:<8}{_fmt(t.bid):>10}{_fmt(t.ask):>10}"
            f"{_fmt(t.last):>10}{_fmt(t.close):>10}{dt:>14}"
        )
    print()


def main(argv: list[str]) -> int:
    symbols = argv[1:] or ["SPY"]
    with connect_ibkr() as ib:
        print(f"Connected. Server version {ib.client.serverVersion()}.\n")

        # Surface any IBKR errors live so permission issues are obvious
        def _on_err(reqId, errorCode, errorString, contract):
            # 2104/2106/2158 are "OK, market data farm connected" status messages
            if errorCode in (2104, 2106, 2158, 2107, 2119):
                return
            sym = contract.symbol if contract is not None else "-"
            print(f"  [IBKR err {errorCode} on {sym}] {errorString}")

        ib.errorEvent += _on_err

        contracts = [Stock(s, "SMART", "USD") for s in symbols]
        try:
            ib.qualifyContracts(*contracts)
        except Exception as e:
            print(f"  qualifyContracts failed: {e}")

        # 1) Try LIVE
        tickers = [
            ib.reqMktData(c, "", snapshot=False, regulatorySnapshot=False)
            for c in contracts
        ]
        _wait_for_quotes(ib, tickers, timeout=12)

        live_ok = all(_has_quote(t) for t in tickers)
        if live_ok:
            print("Live data:")
            _print_table(symbols, tickers)
        else:
            print("No live quotes after 12s — falling back to DELAYED_FROZEN.\n")
            for c in contracts:
                ib.cancelMktData(c)
            # 4 = DELAYED_FROZEN: returns last known delayed quote even after hours
            ib.reqMarketDataType(4)
            tickers = [
                ib.reqMktData(c, "", snapshot=False, regulatorySnapshot=False)
                for c in contracts
            ]
            _wait_for_quotes(ib, tickers, timeout=12)
            print("Delayed/frozen data:")
            _print_table(symbols, tickers)

            if not all(_has_quote(t) for t in tickers):
                print(
                    "Still no quotes. Likely causes:\n"
                    "  - IBKR live account has no US options/equity market-data subscription.\n"
                    "    Check: Account → Settings → Market Data Subscriptions.\n"
                    "  - The errors printed above (if any) usually identify the exact reason.\n"
                )
                return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
