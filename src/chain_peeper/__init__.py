"""Chain Peeper — options-chain analytics for a personal watchlist."""

__version__ = "0.1.0"


def main() -> None:  # pragma: no cover — placeholder entrypoint
    print(
        "chain-peeper installed. Use one of:\n"
        "  uv run scripts/ping_ibkr.py        # Phase 0 sanity check\n"
        "  uv run scripts/snapshot_daily.py   # Phase 1 daily snapshot\n"
        "  uv run streamlit run src/chain_peeper/dashboard/app.py\n"
    )
