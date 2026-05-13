"""IBKR connection helper.

A thin sync wrapper around ib_async's IB() that:
- reads host/port/clientId from chain_peeper.config
- connects with a clear error message if TWS/Gateway isn't running
- supports `with connect_ibkr() as ib:` usage
- silences ib_async's INFO-level logging that dumps account state and
  Error 200 spam when strike menus are sparse
"""

from __future__ import annotations

import contextlib
import logging
from typing import Iterator

from ib_async import IB

from chain_peeper.config import ibkr_config


def _quiet_ib_async_logging() -> None:
    """Suppress noisy logs we don't need.

    ib_async.wrapper logs every position, portfolio update, execDetails, and
    commissionReport at INFO — that's PII (account #, P&L, fills) flooding our
    snapshot.log. It also logs Error 200 ('no security definition') at ERROR,
    which we expect to see for sparse strike menus on near-dated expiries.

    We only want our app's logs plus genuine connection issues from ib_async.
    """
    logging.getLogger("ib_async.wrapper").setLevel(logging.WARNING)
    # Filter out the specific 'Unknown contract' WARNINGs and Error 200s that
    # spam when strikes don't exist for an expiry.
    class _DropNoise(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            msg = record.getMessage()
            if "Unknown contract" in msg:
                return False
            if "Error 200" in msg and "No security definition" in msg:
                return False
            return True
    for name in ("ib_async.wrapper", "ib_async.ib", "ib_async.client"):
        logging.getLogger(name).addFilter(_DropNoise())


_quiet_ib_async_logging()


@contextlib.contextmanager
def connect_ibkr(client_id_override: int | None = None) -> Iterator[IB]:
    """Read-only IBKR connection.

    `readonly=True` does two things we want:
      1) makes it impossible for this process to place an order, and
      2) suppresses TWS's auto-stream of account state (positions, executions,
         commission reports) — so logs don't capture sensitive PII.
    """
    cfg = ibkr_config()
    cid = client_id_override if client_id_override is not None else cfg.client_id
    ib = IB()
    try:
        ib.connect(cfg.host, cfg.port, clientId=cid, readonly=True, timeout=10)
    except (ConnectionRefusedError, TimeoutError) as e:
        raise SystemExit(
            f"Could not reach IBKR at {cfg.host}:{cfg.port} (clientId={cid}). "
            f"Is TWS or IB Gateway running with API access enabled?\n  {e}"
        ) from e
    try:
        yield ib
    finally:
        if ib.isConnected():
            ib.disconnect()
