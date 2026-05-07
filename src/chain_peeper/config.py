"""Runtime configuration: env vars + project paths.

Single source of truth so scripts and the dashboard agree on where things live.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Repo root = parent of src/
REPO_ROOT = Path(__file__).resolve().parents[2]

# Load .env once, on import. Override=False so a real shell env wins.
load_dotenv(REPO_ROOT / ".env", override=False)


@dataclass(frozen=True)
class IBKRConfig:
    host: str
    port: int
    client_id: int
    mktdata_timeout: float


@dataclass(frozen=True)
class Paths:
    repo_root: Path
    data_dir: Path
    db_path: Path
    config_dir: Path
    watchlist_path: Path


def _env_int(key: str, default: int) -> int:
    raw = os.getenv(key)
    return int(raw) if raw is not None and raw != "" else default


def _env_float(key: str, default: float) -> float:
    raw = os.getenv(key)
    return float(raw) if raw is not None and raw != "" else default


def ibkr_config() -> IBKRConfig:
    return IBKRConfig(
        host=os.getenv("IBKR_HOST", "127.0.0.1"),
        port=_env_int("IBKR_PORT", 7497),
        client_id=_env_int("IBKR_CLIENT_ID", 42),
        mktdata_timeout=_env_float("IBKR_MKTDATA_TIMEOUT", 8.0),
    )


def paths() -> Paths:
    db_rel = os.getenv("CHAIN_PEEPER_DB", "data/chain_peeper.duckdb")
    db_path = (REPO_ROOT / db_rel).resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return Paths(
        repo_root=REPO_ROOT,
        data_dir=REPO_ROOT / "data",
        db_path=db_path,
        config_dir=REPO_ROOT / "config",
        watchlist_path=REPO_ROOT / "config" / "watchlist.yaml",
    )
