"""DuckDB persistence for option chain snapshots.

Two tables:
  - underlying_snapshots(snapshot_date, symbol, ...)
  - option_snapshots(snapshot_date, symbol, expiry, strike, right, ...)

Both are keyed so the daily snapshot job is idempotent — re-running the same day
overwrites that day's rows, never duplicates them.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Iterator

import duckdb
import pandas as pd

from chain_peeper.config import paths

UNDERLYING_DDL = """
CREATE TABLE IF NOT EXISTS underlying_snapshots (
    snapshot_date DATE NOT NULL,
    snapshot_ts   TIMESTAMP NOT NULL,
    symbol        VARCHAR  NOT NULL,
    underlying_px DOUBLE,
    PRIMARY KEY (snapshot_date, symbol)
);
"""

OPTION_DDL = """
CREATE TABLE IF NOT EXISTS option_snapshots (
    snapshot_date  DATE NOT NULL,
    snapshot_ts    TIMESTAMP NOT NULL,
    symbol         VARCHAR NOT NULL,
    expiry         DATE NOT NULL,
    dte            INTEGER,
    strike         DOUBLE NOT NULL,
    "right"        VARCHAR NOT NULL,
    exchange       VARCHAR,
    multiplier     INTEGER,
    bid            DOUBLE,
    ask            DOUBLE,
    last           DOUBLE,
    iv             DOUBLE,
    delta          DOUBLE,
    gamma          DOUBLE,
    theta          DOUBLE,
    vega           DOUBLE,
    und_price      DOUBLE,
    oi             BIGINT,
    volume         BIGINT,
    underlying_px  DOUBLE,
    PRIMARY KEY (snapshot_date, symbol, expiry, strike, "right")
);
"""

# Daily-rollup index for the dashboard's quick reads.
INDEX_DDL = [
    "CREATE INDEX IF NOT EXISTS idx_opt_sym_date ON option_snapshots(symbol, snapshot_date);",
    "CREATE INDEX IF NOT EXISTS idx_opt_sym_exp  ON option_snapshots(symbol, expiry);",
]


@contextlib.contextmanager
def open_db(path: Path | None = None, *, read_only: bool = False) -> Iterator[duckdb.DuckDBPyConnection]:
    db_path = path or paths().db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path), read_only=read_only)
    try:
        if not read_only:
            _ensure_schema(con)
        yield con
    finally:
        con.close()


def _ensure_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(UNDERLYING_DDL)
    con.execute(OPTION_DDL)
    for stmt in INDEX_DDL:
        con.execute(stmt)


def write_snapshot(
    con: duckdb.DuckDBPyConnection,
    *,
    underlying: dict,
    options: pd.DataFrame,
) -> int:
    """Idempotent upsert of one symbol's snapshot for one day.

    underlying: dict with keys snapshot_date, snapshot_ts, symbol, underlying_px
    options:    DataFrame matching the option_snapshots schema
    Returns the number of option rows written.
    """
    if options.empty:
        return 0

    # 1. Upsert underlying row
    con.execute(
        "DELETE FROM underlying_snapshots WHERE snapshot_date = ? AND symbol = ?",
        [underlying["snapshot_date"], underlying["symbol"]],
    )
    con.execute(
        "INSERT INTO underlying_snapshots VALUES (?, ?, ?, ?)",
        [
            underlying["snapshot_date"],
            underlying["snapshot_ts"],
            underlying["symbol"],
            underlying["underlying_px"],
        ],
    )

    # 2. Upsert option rows (delete-then-insert keeps it simple and idempotent)
    snap_date = underlying["snapshot_date"]
    symbol = underlying["symbol"]
    con.execute(
        "DELETE FROM option_snapshots WHERE snapshot_date = ? AND symbol = ?",
        [snap_date, symbol],
    )

    # Reorder to match table column order, drop any extras
    cols = [
        "snapshot_date", "snapshot_ts", "symbol", "expiry", "dte",
        "strike", "right", "exchange", "multiplier",
        "bid", "ask", "last", "iv", "delta", "gamma", "theta", "vega",
        "und_price", "oi", "volume", "underlying_px",
    ]
    df = options.loc[:, [c for c in cols if c in options.columns]].copy()
    # Ensure all expected columns are present
    for c in cols:
        if c not in df.columns:
            df[c] = None
    df = df[cols]

    con.register("opt_df", df)
    con.execute("INSERT INTO option_snapshots SELECT * FROM opt_df")
    con.unregister("opt_df")
    return len(df)


def latest_snapshot_date(con: duckdb.DuckDBPyConnection, symbol: str) -> pd.Timestamp | None:
    row = con.execute(
        "SELECT MAX(snapshot_date) FROM option_snapshots WHERE symbol = ?",
        [symbol],
    ).fetchone()
    return row[0] if row and row[0] else None


def read_snapshot(con: duckdb.DuckDBPyConnection, symbol: str, snapshot_date) -> pd.DataFrame:
    return con.execute(
        "SELECT * FROM option_snapshots WHERE symbol = ? AND snapshot_date = ? "
        'ORDER BY expiry, strike, "right"',
        [symbol, snapshot_date],
    ).df()


def list_symbols(con: duckdb.DuckDBPyConnection) -> list[str]:
    return [r[0] for r in con.execute(
        "SELECT DISTINCT symbol FROM option_snapshots ORDER BY symbol"
    ).fetchall()]
