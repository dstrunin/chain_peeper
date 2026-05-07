"""Load and validate config/watchlist.yaml."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from chain_peeper.config import paths


@dataclass(frozen=True)
class TickerSpec:
    symbol: str
    expiry_window_days: int
    strike_pct_window: float
    primary_exchange: str


def load_watchlist(path: Path | None = None) -> list[TickerSpec]:
    p = path or paths().watchlist_path
    if not p.exists():
        raise FileNotFoundError(f"Watchlist not found at {p}. Copy config/watchlist.yaml.")
    raw = yaml.safe_load(p.read_text())

    defaults = raw.get("defaults", {}) or {}
    overrides = raw.get("overrides", {}) or {}
    tickers = raw.get("tickers") or []
    if not tickers:
        raise ValueError(f"Watchlist {p} has no tickers.")

    out: list[TickerSpec] = []
    for sym in tickers:
        sym = sym.upper().strip()
        merged = {**defaults, **(overrides.get(sym, {}) or {})}
        out.append(
            TickerSpec(
                symbol=sym,
                expiry_window_days=int(merged.get("expiry_window_days", 120)),
                strike_pct_window=float(merged.get("strike_pct_window", 0.25)),
                primary_exchange=str(merged.get("primary_exchange", "SMART")),
            )
        )
    return out
