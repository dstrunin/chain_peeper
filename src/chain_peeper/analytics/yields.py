"""CSP / CC annualized yield rankings.

Yield definitions (as agreed in plan):
  - Put yield  (cash-secured): mid_premium / strike       * 365 / dte
  - Call yield (covered):      mid_premium / underlying   * 365 / dte

Filtered to liquid, reasonable-delta contracts so results aren't dominated by
junk wide-spread quotes.
"""

from __future__ import annotations

import pandas as pd


def _mid(df: pd.DataFrame) -> pd.Series:
    bid = df["bid"].fillna(0)
    ask = df["ask"].fillna(0)
    last = df["last"].fillna(0)
    mid = (bid + ask) / 2
    # If bid/ask both missing, fall back to last
    return mid.where(mid > 0, last)


def annualized_yields(
    df: pd.DataFrame,
    *,
    max_abs_delta: float = 0.30,
    min_dte: int = 7,
    min_open_interest: int = 100,
) -> pd.DataFrame:
    """Compute annualized yield per contract and apply liquidity filters.

    Returns columns:
      symbol, expiry, dte, strike, right, mid, delta, oi, volume, yield_annual_pct
    """
    if df.empty:
        return df.assign(mid=[], yield_annual_pct=[])

    work = df.copy()
    work["mid"] = _mid(work)

    work = work[
        (work["dte"] >= min_dte)
        & (work["oi"].fillna(0) >= min_open_interest)
        & (work["mid"] > 0)
        & (work["delta"].abs() <= max_abs_delta)
    ].copy()
    if work.empty:
        return work

    den_put = work["strike"]
    den_call = work["underlying_px"]
    base = (work["mid"] / den_put.where(work["right"] == "P", den_call))
    work["yield_annual_pct"] = (base * 365.0 / work["dte"]) * 100.0

    cols = ["symbol", "expiry", "dte", "strike", "right",
            "mid", "delta", "oi", "volume", "yield_annual_pct"]
    return work[cols].sort_values("yield_annual_pct", ascending=False).reset_index(drop=True)


def top_yields(
    df: pd.DataFrame,
    *,
    n: int = 5,
    right: str | None = None,
    **kwargs,
) -> pd.DataFrame:
    out = annualized_yields(df, **kwargs)
    if right:
        out = out[out["right"] == right]
    return out.head(n).reset_index(drop=True)
