"""Alpaca adapter (paper or live endpoint). Activated automatically when ALPACA_API_KEY and
ALPACA_API_SECRET are present in .env. Uses Alpaca's native auction order types:
time_in_force 'opg' = market-on-open, 'cls' = market-on-close.

This adapter has not been exercised against a funded account in this repository; it is the
thin, obvious mapping of the Broker interface onto Alpaca's REST v2.
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import requests

from ..settings import SETTINGS, Settings
from ..store import Store, new_id
from .base import Broker, Order

TIF = {"MOO": "opg", "MOC": "cls", "MKT": "day"}


class AlpacaBroker(Broker):
    name = "alpaca"

    def __init__(self, store: Store, settings: Settings = SETTINGS):
        self.store, self.s = store, settings
        self.h = {"APCA-API-KEY-ID": settings.alpaca_api_key, "APCA-API-SECRET-KEY": settings.alpaca_api_secret}
        self.base = settings.alpaca_base_url.rstrip("/")

    def _req(self, method: str, path: str, **kw):
        r = requests.request(method, self.base + path, headers=self.h, timeout=30, **kw)
        if r.status_code >= 400:
            raise RuntimeError(f"alpaca {method} {path}: {r.status_code} {r.text[:200]}")
        return r.json() if r.text else None

    def submit(self, orders: list[Order]) -> list[Order]:
        for o in orders:
            try:
                js = self._req("POST", "/v2/orders", json={
                    "symbol": o.symbol, "qty": str(o.qty), "side": o.side, "type": "market",
                    "time_in_force": TIF[o.order_type], "client_order_id": o.order_id})
                o.status, o.broker_order_id = js.get("status", "accepted"), js.get("id")
            except RuntimeError as e:
                o.status, o.note = "rejected", str(e)[:200]
        self.store.save_orders([o.row(self.name) for o in orders])
        return orders

    def cancel_open(self, session: date) -> int:
        js = self._req("DELETE", "/v2/orders") or []
        return len(js)

    def positions(self, session: date | None = None) -> pd.DataFrame:
        js = self._req("GET", "/v2/positions") or []
        if not js:
            return pd.DataFrame(columns=["qty", "avg_price"])
        df = pd.DataFrame([{"symbol": p["symbol"], "qty": int(float(p["qty"])), "avg_price": float(p["avg_entry_price"])} for p in js])
        return df.set_index("symbol")

    def fills(self, session: date) -> pd.DataFrame:
        """Pull filled orders for the session from Alpaca and mirror them into the store."""
        js = self._req("GET", "/v2/orders", params={"status": "closed", "after": f"{session}T00:00:00Z", "limit": 500}) or []
        rows = []
        for o in js:
            if o.get("filled_qty") and float(o["filled_qty"]) > 0:
                qty, px = int(float(o["filled_qty"])), float(o["filled_avg_price"])
                rows.append({"fill_id": "alp-" + o["id"][:12], "order_id": o.get("client_order_id") or new_id(),
                             "ts": pd.Timestamp(o["filled_at"]), "session_date": session, "symbol": o["symbol"],
                             "side": o["side"], "qty": qty, "price": px, "cost": 0.0, "venue": "alpaca"})
        self.store.save_fills(rows)
        return self.store.fills(session)
