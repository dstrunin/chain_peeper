"""Open-interest and volume clustering on a snapshot."""

from __future__ import annotations

import pandas as pd


def oi_heatmap(df: pd.DataFrame) -> pd.DataFrame:
    """Pivot OI -> rows=strike, cols=expiry, vals=total OI (calls+puts)."""
    return _pivot(df, "oi")


def volume_heatmap(df: pd.DataFrame) -> pd.DataFrame:
    return _pivot(df, "volume")


def _pivot(df: pd.DataFrame, col: str) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    sub = df[["strike", "expiry", col]].dropna(subset=[col])
    if sub.empty:
        return pd.DataFrame()
    pivot = sub.pivot_table(
        index="strike", columns="expiry", values=col, aggfunc="sum", fill_value=0
    )
    return pivot.sort_index()


def top_strikes_by(df: pd.DataFrame, col: str, n: int = 10) -> pd.DataFrame:
    """Top strikes by total `col` (oi or volume), summed across all expiries.

    Returns columns: [strike, total, calls, puts].
    """
    if df.empty:
        return pd.DataFrame(columns=["strike", "total", "calls", "puts"])
    grp = (
        df.groupby(["strike", "right"])[col].sum(min_count=1).unstack(fill_value=0)
    )
    grp.columns = [str(c) for c in grp.columns]
    grp["calls"] = grp.get("C", 0)
    grp["puts"] = grp.get("P", 0)
    grp["total"] = grp["calls"] + grp["puts"]
    out = grp.reset_index()[["strike", "total", "calls", "puts"]]
    return out.sort_values("total", ascending=False).head(n).reset_index(drop=True)
