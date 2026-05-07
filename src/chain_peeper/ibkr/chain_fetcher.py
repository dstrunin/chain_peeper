"""Fetch a stock's full options chain from IBKR and return it as a DataFrame.

Two-step process:
  1. reqSecDefOptParams -> universe of (expiry, strike) pairs for the underlying
  2. Build, qualify, and reqMktData on filtered Option contracts; gather IV +
     Greeks (modelGreeks), bid/ask/last, OI, volume.

The chain for a liquid US name can be 5,000+ contracts. We trim before fetching:
  - expiry_window_days  — keep expiries within N days from today
  - strike_pct_window   — keep strikes within +/- pct of underlying spot

Pacing: IBKR allows ~50 messages/sec, but practical limit is ~100 simultaneous
market-data lines unless you have the top-tier subscription. We chunk requests
in batches of MKTDATA_BATCH and small sleeps between batches to stay safe.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone

import pandas as pd
from ib_async import IB, Index, Option, Stock, Ticker

from chain_peeper.config import ibkr_config
from chain_peeper.watchlist import TickerSpec

# Max number of option contracts subscribed at once. Tune down if you hit
# "max number of tickers reached" errors.
MKTDATA_BATCH = 80
# Per-contract poll budget for snapshot to settle (seconds).
PER_BATCH_TIMEOUT = 8.0


@dataclass
class ChainSnapshot:
    """Canonical shape returned by fetch_chain — wraps the per-contract DataFrame
    plus underlying spot info captured in the same pass."""

    symbol: str
    snapshot_ts: datetime
    underlying_px: float
    contracts: pd.DataFrame  # see COLUMNS below


COLUMNS = [
    "snapshot_ts",
    "symbol",
    "expiry",       # date
    "dte",          # int days to expiry from snapshot date
    "strike",       # float
    "right",        # "C" or "P"
    "exchange",
    "multiplier",
    "bid",
    "ask",
    "last",
    "iv",           # implied vol from modelGreeks
    "delta",
    "gamma",
    "theta",
    "vega",
    "und_price",    # underlying spot used by IBKR for greeks
    "oi",           # open interest
    "volume",       # day's volume
    "underlying_px", "snapshot_date",
]


def _to_date(yyyymmdd: str) -> date:
    return datetime.strptime(yyyymmdd, "%Y%m%d").date()


def _spot_price(t: Ticker) -> float | None:
    """Best estimate of underlying spot from a Ticker."""
    for v in (t.last, t.marketPrice(), t.close):
        if v is not None and not (isinstance(v, float) and math.isnan(v)):
            return float(v)
    return None


def _greek_attr(t: Ticker, attr: str) -> float | None:
    g = t.modelGreeks
    if g is None:
        return None
    val = getattr(g, attr, None)
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return None
    return float(val)


def _safe_float(x) -> float | None:
    if x is None:
        return None
    if isinstance(x, float) and math.isnan(x):
        return None
    return float(x)


def _safe_int(x) -> int | None:
    f = _safe_float(x)
    return int(f) if f is not None else None


def _build_underlying(spec: TickerSpec):
    """Return an unqualified IBKR contract for the underlying.

    Index symbols (SPX, VIX, etc.) need Index() instead of Stock() — handled by
    a small known-set check; everything else is treated as a stock.
    """
    if spec.symbol in {"SPX", "SPXW", "VIX", "RUT", "NDX", "XSP"}:
        return Index(spec.symbol, "CBOE", "USD")
    return Stock(spec.symbol, "SMART", "USD", primaryExchange=spec.primary_exchange or "")


def fetch_chain(ib: IB, spec: TickerSpec) -> ChainSnapshot:
    """Pull and assemble one ticker's options chain. Caller owns the IB connection."""
    snapshot_ts = datetime.now(timezone.utc)
    today = snapshot_ts.date()

    # 1. Underlying — qualify and grab spot
    und = _build_underlying(spec)
    ib.qualifyContracts(und)
    und_ticker = ib.reqMktData(und, "", snapshot=False, regulatorySnapshot=False)
    deadline = time.time() + 4
    while time.time() < deadline and _spot_price(und_ticker) is None:
        ib.sleep(0.1)
    spot = _spot_price(und_ticker)
    if spot is None:
        ib.cancelMktData(und)
        raise RuntimeError(f"Could not get spot price for {spec.symbol}")

    # 2. Options universe via reqSecDefOptParams
    chains = ib.reqSecDefOptParams(
        underlyingSymbol=und.symbol,
        futFopExchange="",
        underlyingSecType=und.secType,
        underlyingConId=und.conId,
    )
    if not chains:
        ib.cancelMktData(und)
        raise RuntimeError(f"No option chains returned for {spec.symbol}")

    # Prefer SMART with the largest strike set
    chain = max(
        (c for c in chains if c.exchange == "SMART") or chains,
        key=lambda c: len(c.strikes),
    )

    # 3. Filter expiries + strikes
    max_exp = today.toordinal() + spec.expiry_window_days
    expiries = sorted(
        e for e in chain.expirations
        if today.toordinal() <= _to_date(e).toordinal() <= max_exp
    )
    lo = spot * (1 - spec.strike_pct_window)
    hi = spot * (1 + spec.strike_pct_window)
    strikes = sorted(s for s in chain.strikes if lo <= s <= hi)

    if not expiries or not strikes:
        ib.cancelMktData(und)
        raise RuntimeError(
            f"No contracts match window for {spec.symbol}: "
            f"{len(expiries)} expiries, {len(strikes)} strikes"
        )

    # 4. Build, qualify, and request market data in batches
    contracts: list[Option] = []
    for exp in expiries:
        for k in strikes:
            for right in ("C", "P"):
                contracts.append(
                    Option(
                        symbol=spec.symbol,
                        lastTradeDateOrContractMonth=exp,
                        strike=k,
                        right=right,
                        exchange="SMART",
                        currency="USD",
                        tradingClass=chain.tradingClass,
                        multiplier=str(chain.multiplier),
                    )
                )

    rows: list[dict] = []
    cfg = ibkr_config()
    timeout = max(cfg.mktdata_timeout, PER_BATCH_TIMEOUT)

    for i in range(0, len(contracts), MKTDATA_BATCH):
        batch = contracts[i : i + MKTDATA_BATCH]
        try:
            qualified = ib.qualifyContracts(*batch)
        except Exception:
            qualified = []
        qualified = [c for c in qualified if c.conId]
        if not qualified:
            continue

        tickers = [
            ib.reqMktData(c, "100,101,106", snapshot=False, regulatorySnapshot=False)
            for c in qualified
        ]
        # Wait until each ticker has at least one of bid/ask/last/iv populated,
        # or we run out of budget.
        deadline = time.time() + timeout
        while time.time() < deadline:
            ib.sleep(0.25)
            if all(
                (t.bid is not None and not (isinstance(t.bid, float) and math.isnan(t.bid)))
                or (t.ask is not None and not (isinstance(t.ask, float) and math.isnan(t.ask)))
                or (t.last is not None and not (isinstance(t.last, float) and math.isnan(t.last)))
                or t.modelGreeks is not None
                for t in tickers
            ):
                break

        for c, t in zip(qualified, tickers):
            exp_d = _to_date(c.lastTradeDateOrContractMonth)
            rows.append(
                {
                    "snapshot_ts": snapshot_ts,
                    "snapshot_date": today,
                    "symbol": spec.symbol,
                    "expiry": exp_d,
                    "dte": (exp_d - today).days,
                    "strike": float(c.strike),
                    "right": c.right,
                    "exchange": c.exchange,
                    "multiplier": int(c.multiplier) if c.multiplier else 100,
                    "bid": _safe_float(t.bid),
                    "ask": _safe_float(t.ask),
                    "last": _safe_float(t.last),
                    "iv": _greek_attr(t, "impliedVol"),
                    "delta": _greek_attr(t, "delta"),
                    "gamma": _greek_attr(t, "gamma"),
                    "theta": _greek_attr(t, "theta"),
                    "vega": _greek_attr(t, "vega"),
                    "und_price": _greek_attr(t, "undPrice"),
                    "oi": _safe_int(
                        t.callOpenInterest if c.right == "C" else t.putOpenInterest
                    ),
                    "volume": _safe_int(t.volume),
                    "underlying_px": spot,
                }
            )
            ib.cancelMktData(c)

    ib.cancelMktData(und)
    df = pd.DataFrame(rows, columns=COLUMNS)
    return ChainSnapshot(
        symbol=spec.symbol,
        snapshot_ts=snapshot_ts,
        underlying_px=spot,
        contracts=df,
    )
