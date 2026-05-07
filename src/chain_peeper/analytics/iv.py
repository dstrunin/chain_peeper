"""IV-related analytics over a snapshot DataFrame.

All functions take a DataFrame with the option_snapshots schema and return
small summary frames suitable for direct rendering in Streamlit/Plotly.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def atm_iv_by_expiry(df: pd.DataFrame) -> pd.DataFrame:
    """For each expiry, IV at the strike closest to spot (avg of call+put IV).

    Returns columns: [expiry, dte, strike_atm, iv_atm, n_strikes].
    """
    if df.empty:
        return pd.DataFrame(columns=["expiry", "dte", "strike_atm", "iv_atm", "n_strikes"])

    spot = df["underlying_px"].dropna().iloc[0]
    rows = []
    for (expiry, dte), grp in df.groupby(["expiry", "dte"], sort=True):
        # Pick strike closest to spot
        nearest_k = grp.iloc[(grp["strike"] - spot).abs().argsort()[:1]]["strike"].iloc[0]
        atm = grp[grp["strike"] == nearest_k]
        iv_atm = atm["iv"].dropna().mean()
        rows.append(
            {
                "expiry": expiry,
                "dte": dte,
                "strike_atm": nearest_k,
                "iv_atm": iv_atm,
                "n_strikes": grp["strike"].nunique(),
            }
        )
    return pd.DataFrame(rows).sort_values("dte").reset_index(drop=True)


def iv_30d(df: pd.DataFrame) -> float | None:
    """Linearly interpolate ATM IV at 30 days. Returns None if not bracketing 30."""
    term = atm_iv_by_expiry(df).dropna(subset=["iv_atm"])
    if term.empty:
        return None
    if (term["dte"] <= 30).any() and (term["dte"] >= 30).any():
        return float(np.interp(30, term["dte"], term["iv_atm"]))
    # Otherwise: closest expiry's ATM IV
    return float(term.iloc[(term["dte"] - 30).abs().argsort()[:1]]["iv_atm"].iloc[0])


def iv_smile(df: pd.DataFrame, expiry) -> pd.DataFrame:
    """Strike vs IV for one expiry, calls and puts. Columns: strike, right, iv, delta."""
    sub = df[df["expiry"] == expiry][["strike", "right", "iv", "delta"]].dropna(subset=["iv"])
    return sub.sort_values(["right", "strike"]).reset_index(drop=True)


def deep_otm_iv(df: pd.DataFrame, deltas: tuple[float, ...] = (0.25, 0.10, 0.05)) -> pd.DataFrame:
    """Per expiry, IV at the strike closest to each target |delta|, calls and puts.

    Columns: [expiry, dte, right, target_delta, strike, iv, delta_actual].
    """
    rows = []
    for (expiry, dte, right), grp in df.dropna(subset=["delta", "iv"]).groupby(
        ["expiry", "dte", "right"], sort=True
    ):
        if grp.empty:
            continue
        for d in deltas:
            target = d if right == "C" else -d
            idx = (grp["delta"] - target).abs().idxmin()
            r = grp.loc[idx]
            rows.append(
                {
                    "expiry": expiry,
                    "dte": dte,
                    "right": right,
                    "target_delta": target,
                    "strike": float(r["strike"]),
                    "iv": float(r["iv"]),
                    "delta_actual": float(r["delta"]),
                }
            )
    return pd.DataFrame(rows)
