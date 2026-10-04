"""Simulated broker: MOO/MOC orders fill at the official auction prints, market orders at the
last trade, and every fill is charged the pre-registered toll c_base x VIX_{t-1}/20 bps per
dollar traded. State lives entirely in the store, so a restart loses nothing.
"""
from __future__ import annotations

from datetime import date

import pandas as pd

from ..settings import SETTINGS, Settings
from ..store import Store, new_id, utcnow
from .base import Broker, Order


class PaperBroker(Broker):
    name = "paper"

    def __init__(self, store: Store, settings: Settings = SETTINGS):
        self.store, self.s = store, settings

    # ----------------------------------------------------------------- orders
    def submit(self, orders: list[Order]) -> list[Order]:
        for o in orders:
            o.status, o.broker_order_id = "accepted", "paper-" + o.order_id
        self.store.save_orders([o.row(self.name) for o in orders])
        return orders

    def cancel_open(self, session: date) -> int:
        od = self.store.orders(session)
        open_ = od[od["status"] == "accepted"] if len(od) else od
        if len(open_):
            self.store.save_orders([{**r, "status": "cancelled"} for r in open_.to_dict("records")])
        return int(len(open_))

    # ------------------------------------------------------------------ fills
    def cost_bps(self, vix_lag: float | None) -> float:
        return self.s.c_base_bps * (max(vix_lag or 20.0, 1.0) / 20.0)

    def fill_auction(self, session: date, order_type: str, prices: pd.Series, vix_lag: float | None,
                     venue: str) -> pd.DataFrame:
        """Fill every accepted order of `order_type` at `prices` (official auction print)."""
        od = self.store.orders(session, order_type)
        od = od[od["status"] == "accepted"] if len(od) else od
        bps = self.cost_bps(vix_lag)
        fills, updated, ts = [], [], utcnow()
        for r in od.to_dict("records"):
            px = prices.get(r["symbol"])
            if px is None or pd.isna(px) or px <= 0:
                updated.append({**r, "status": "rejected", "note": "no auction print"})
                continue
            notional = r["qty"] * float(px)
            fills.append({"fill_id": new_id(), "order_id": r["order_id"], "ts": ts, "session_date": session,
                          "symbol": r["symbol"], "side": r["side"], "qty": int(r["qty"]), "price": float(px),
                          "cost": notional * bps / 1e4, "venue": venue})
            updated.append({**r, "status": "filled"})
        self.store.save_fills(fills)
        self.store.save_orders(updated)
        return pd.DataFrame(fills)

    def fill_market(self, session: date, orders: list[Order], last: pd.Series, vix_lag: float | None) -> pd.DataFrame:
        """Immediate fill at the last trade (used by the loss-limit flatten)."""
        self.submit(orders)
        return self.fill_auction(session, orders[0].order_type if orders else "MKT", last, vix_lag, "paper-market")

    def fills(self, session: date) -> pd.DataFrame:
        return self.store.fills(session)

    # --------------------------------------------------------------- positions
    def positions(self, session: date | None = None) -> pd.DataFrame:
        q = "SELECT symbol, side, qty, price FROM live_fills"
        f = self.store.df(q + (" WHERE session_date=%s" if session else ""), (session,) if session else ())
        if f.empty:
            return pd.DataFrame(columns=["qty", "avg_price"])
        f["signed"] = f["qty"].where(f["side"] == "buy", -f["qty"])
        g = f.groupby("symbol")
        qty = g["signed"].sum()
        buys = f[f["side"] == "buy"].groupby("symbol").apply(lambda x: (x["qty"] * x["price"]).sum() / x["qty"].sum(), include_groups=False)
        sells = f[f["side"] == "sell"].groupby("symbol").apply(lambda x: (x["qty"] * x["price"]).sum() / x["qty"].sum(), include_groups=False)
        avg = buys.where(qty > 0, sells).reindex(qty.index)
        out = pd.DataFrame({"qty": qty.astype(int), "avg_price": avg})
        return out[out["qty"] != 0]
