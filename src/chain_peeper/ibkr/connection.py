"""IBKR connection helper.

A thin sync wrapper around ib_async's IB() that:
- reads host/port/clientId from chain_peeper.config
- connects with a clear error message if TWS/Gateway isn't running
- supports `with connect_ibkr() as ib:` usage
"""

from __future__ import annotations

import contextlib
from typing import Iterator

from ib_async import IB

from chain_peeper.config import ibkr_config


@contextlib.contextmanager
def connect_ibkr(client_id_override: int | None = None) -> Iterator[IB]:
    cfg = ibkr_config()
    cid = client_id_override if client_id_override is not None else cfg.client_id
    ib = IB()
    try:
        ib.connect(cfg.host, cfg.port, clientId=cid, readonly=False, timeout=10)
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
