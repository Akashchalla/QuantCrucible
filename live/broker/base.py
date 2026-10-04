from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from ..store import new_id


@dataclass
class Order:
    session_date: date
    symbol: str
    side: str            # 'buy' | 'sell'
    qty: int
    order_type: str      # 'MOO' | 'MOC' | 'MKT'
    order_id: str = field(default_factory=new_id)
    status: str = "new"
    broker_order_id: str | None = None
    note: str | None = None

    def row(self, broker: str) -> dict:
        return {"order_id": self.order_id, "session_date": self.session_date, "symbol": self.symbol, "side": self.side,
                "qty": self.qty, "order_type": self.order_type, "status": self.status, "broker": broker,
                "broker_order_id": self.broker_order_id, "note": self.note}


def orders_from_targets(session: date, sig: pd.DataFrame, order_type: str = "MOO") -> list[Order]:
    out = []
    for sym, r in sig[sig["side"] != 0].iterrows():
        q = int(r["target_qty"])
        out.append(Order(session, sym, "buy" if q > 0 else "sell", abs(q), order_type))
    return out


def closing_orders(session: date, positions: pd.DataFrame, order_type: str = "MOC") -> list[Order]:
    out = []
    for sym, r in positions.iterrows():
        q = int(r["qty"])
        if q:
            out.append(Order(session, sym, "sell" if q > 0 else "buy", abs(q), order_type, note="flatten"))
    return out


class Broker(ABC):
    name: str

    @abstractmethod
    def submit(self, orders: list[Order]) -> list[Order]: ...

    @abstractmethod
    def positions(self) -> pd.DataFrame:
        """index=symbol, columns qty (signed), avg_price."""

    @abstractmethod
    def fills(self, session: date) -> pd.DataFrame: ...

    @abstractmethod
    def cancel_open(self, session: date) -> int: ...
