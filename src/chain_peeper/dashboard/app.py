"""Chain Peeper — today-snapshot dashboard.

Run with:
    uv run streamlit run src/chain_peeper/dashboard/app.py
"""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from chain_peeper.analytics.clusters import oi_heatmap, top_strikes_by, volume_heatmap
from chain_peeper.analytics.iv import (
    atm_iv_by_expiry,
    deep_otm_iv,
    iv_30d,
    iv_smile,
)
from chain_peeper.analytics.yields import top_yields
from chain_peeper.config import paths
from chain_peeper.storage.duckdb_store import open_db

st.set_page_config(page_title="Chain Peeper", layout="wide")


def _db_exists() -> bool:
    return paths().db_path.exists()


@st.cache_data(ttl=60)
def _load_symbols() -> list[str]:
    if not _db_exists():
        return []
    with open_db(read_only=True) as con:
        return [
            r[0]
            for r in con.execute(
                "SELECT DISTINCT symbol FROM option_snapshots ORDER BY symbol"
            ).fetchall()
        ]


@st.cache_data(ttl=60)
def _load_dates(symbol: str) -> list:
    if not _db_exists():
        return []
    with open_db(read_only=True) as con:
        return [
            r[0]
            for r in con.execute(
                "SELECT DISTINCT snapshot_date FROM option_snapshots "
                "WHERE symbol = ? ORDER BY snapshot_date DESC",
                [symbol],
            ).fetchall()
        ]


@st.cache_data(ttl=60)
def _load_snapshot(symbol: str, snap_date) -> pd.DataFrame:
    if not _db_exists():
        return pd.DataFrame()
    with open_db(read_only=True) as con:
        return con.execute(
            "SELECT * FROM option_snapshots WHERE symbol = ? AND snapshot_date = ? "
            'ORDER BY expiry, strike, "right"',
            [symbol, snap_date],
        ).df()


@st.cache_data(ttl=60)
def _load_all_snapshot(snap_date) -> pd.DataFrame:
    if not _db_exists():
        return pd.DataFrame()
    with open_db(read_only=True) as con:
        return con.execute(
            "SELECT * FROM option_snapshots WHERE snapshot_date = ?", [snap_date]
        ).df()


# ───────────────────────── Sidebar ─────────────────────────
st.sidebar.title("Chain Peeper")
symbols = _load_symbols()
if not symbols:
    st.warning(
        "No data yet. Run `uv run scripts/snapshot_daily.py` while TWS / IB Gateway is open."
    )
    st.stop()

sym = st.sidebar.selectbox("Symbol", symbols, index=0)
dates = _load_dates(sym)
snap_date = st.sidebar.selectbox("Snapshot date", dates, index=0, format_func=str)

df = _load_snapshot(sym, snap_date)
if df.empty:
    st.warning(f"No data for {sym} on {snap_date}.")
    st.stop()

spot = float(df["underlying_px"].dropna().iloc[0])
n_contracts = len(df)

# ───────────────────────── Header ─────────────────────────
st.title(f"{sym} — {snap_date}")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Spot", f"${spot:,.2f}")
term = atm_iv_by_expiry(df)
nearest_atm = term.iloc[0] if not term.empty else None
c2.metric(
    "ATM IV (front)",
    f"{nearest_atm['iv_atm'] * 100:,.1f}%" if nearest_atm is not None and pd.notna(nearest_atm["iv_atm"]) else "n/a",
    help=f"Front-month expiry strike {nearest_atm['strike_atm']:.0f}" if nearest_atm is not None else "",
)
iv30 = iv_30d(df)
c3.metric("IV30", f"{iv30 * 100:,.1f}%" if iv30 is not None else "n/a")
c4.metric("Contracts", f"{n_contracts:,}")

# ───────────────────────── Term structure ─────────────────────────
st.subheader("IV term structure")
if not term.empty and term["iv_atm"].notna().any():
    fig = px.line(
        term.dropna(subset=["iv_atm"]),
        x="dte",
        y="iv_atm",
        markers=True,
        labels={"dte": "Days to expiry", "iv_atm": "ATM IV"},
    )
    fig.update_yaxes(tickformat=".1%")
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("No IV data in this snapshot.")

# ───────────────────────── Heatmaps ─────────────────────────
st.subheader("Open interest & volume clustering")
left, right = st.columns(2)
oi = oi_heatmap(df)
vol = volume_heatmap(df)


def _heatmap(pivot: pd.DataFrame, title: str) -> go.Figure:
    fig = go.Figure(
        data=go.Heatmap(
            z=pivot.values,
            x=[str(c) for c in pivot.columns],
            y=pivot.index,
            colorscale="Viridis",
            colorbar=dict(title=title),
        )
    )
    fig.update_layout(
        xaxis_title="Expiry",
        yaxis_title="Strike",
        height=500,
        margin=dict(l=10, r=10, t=30, b=10),
    )
    return fig


with left:
    st.markdown("**Open Interest** (calls + puts, per strike × expiry)")
    if not oi.empty:
        st.plotly_chart(_heatmap(oi, "OI"), use_container_width=True)
    else:
        st.info("No OI data.")

with right:
    st.markdown("**Volume** (today, per strike × expiry)")
    if not vol.empty:
        st.plotly_chart(_heatmap(vol, "Volume"), use_container_width=True)
    else:
        st.info("No volume data.")

# Top strikes tables
ta, tb = st.columns(2)
with ta:
    st.markdown("**Top 10 strikes by OI**")
    st.dataframe(top_strikes_by(df, "oi", n=10), use_container_width=True)
with tb:
    st.markdown("**Top 10 strikes by volume**")
    st.dataframe(top_strikes_by(df, "volume", n=10), use_container_width=True)

# ───────────────────────── IV smile ─────────────────────────
st.subheader("IV smile (single expiry)")
expiries = sorted(df["expiry"].unique())
exp_sel = st.selectbox("Expiry", expiries, index=0, format_func=str)
smile = iv_smile(df, exp_sel)
if not smile.empty:
    fig = px.line(
        smile,
        x="strike",
        y="iv",
        color="right",
        markers=True,
        labels={"strike": "Strike", "iv": "Implied vol", "right": "C/P"},
    )
    fig.add_vline(x=spot, line_dash="dash", annotation_text=f"Spot {spot:.2f}")
    fig.update_yaxes(tickformat=".1%")
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("No IV smile data for this expiry.")

# ───────────────────────── Deep OTM IV ─────────────────────────
st.subheader("Deep OTM IV (25Δ / 10Δ / 5Δ)")
otm = deep_otm_iv(df)
if not otm.empty:
    pivot = otm.pivot_table(
        index=["expiry", "dte"],
        columns=["right", "target_delta"],
        values="iv",
    ).round(4)
    st.dataframe(pivot, use_container_width=True)
else:
    st.info("Need delta + IV data to compute deep-OTM IV.")

# ───────────────────────── Watchlist-wide yield ranking ─────────────────────────
st.subheader("Top CSP / CC annualized yields (watchlist-wide)")
all_df = _load_all_snapshot(snap_date)
yc1, yc2 = st.columns(2)
with st.sidebar.expander("Yield filters"):
    max_d = st.slider("Max |delta|", 0.05, 0.5, 0.30, 0.05)
    min_dte = st.slider("Min DTE", 1, 60, 7, 1)
    min_oi = st.number_input("Min OI", 0, 10000, 100, 50)

with yc1:
    st.markdown("**Top 5 puts (CSP yield)**")
    st.dataframe(
        top_yields(
            all_df, n=5, right="P",
            max_abs_delta=max_d, min_dte=min_dte, min_open_interest=int(min_oi),
        ),
        use_container_width=True,
    )
with yc2:
    st.markdown("**Top 5 calls (CC yield)**")
    st.dataframe(
        top_yields(
            all_df, n=5, right="C",
            max_abs_delta=max_d, min_dte=min_dte, min_open_interest=int(min_oi),
        ),
        use_container_width=True,
    )

st.caption(
    f"Snapshot loaded: {n_contracts:,} contracts for {sym} on {snap_date}. "
    "Historical (week/month/year) views activate after multiple daily snapshots accrue (Phase 3)."
)
