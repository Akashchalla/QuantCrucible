"""Databento: Nasdaq opening-auction imbalance (NOII) as the pre-open indicative price.

Before 09:28 ET the opening price is unknown; the MOO cut-off is 09:28. The Nasdaq Net Order
Imbalance Indicator publishes an indicative/reference auction price every second from 09:25,
which is the best public estimate of where the auction will print. Historical queries are
cost-guarded (metadata.get_cost before every get_range); live subscription is attempted only
if the account is entitled.
"""
from __future__ import annotations

from datetime import date, time, timedelta

import pandas as pd

from .. import clock
from ..settings import SETTINGS

DATASET = "XNAS.ITCH"


class CostCapExceeded(RuntimeError):
    pass


class DatabentoFeed:
    def __init__(self, api_key: str | None = None, cost_cap: float | None = None):
        import databento as db
        self.key = api_key or SETTINGS.databento_api_key
        if not self.key:
            raise RuntimeError("DATABENTO_API_KEY missing from .env")
        self.db = db
        self.hist = db.Historical(self.key)
        self.cost_cap = SETTINGS.databento_cost_cap_usd if cost_cap is None else cost_cap

    def _guarded_range(self, **kw) -> pd.DataFrame:
        cost = self.hist.metadata.get_cost(dataset=DATASET, **kw)
        if cost > self.cost_cap:
            raise CostCapExceeded(f"query would cost ${cost:.4f} > cap ${self.cost_cap:.2f}")
        return self.hist.timeseries.get_range(dataset=DATASET, **kw).to_df()

    def opening_indicative(self, d: date, symbols: list[str], at: time = time(9, 27),
                           window_s: int = 60) -> pd.DataFrame:
        """Last NOII reference price per symbol in the `window_s` seconds ending at `at` ET.

        Returns index=symbol, columns: ref_price, paired_qty, total_imbalance_qty, side, ts.
        Symbols without a Nasdaq opening auction (NYSE-listed) are absent.
        """
        end = clock.et(d, at)
        start = end - timedelta(seconds=window_s)
        df = self._guarded_range(schema="imbalance", symbols=symbols, stype_in="raw_symbol",
                                 start=clock.to_utc_iso(start), end=clock.to_utc_iso(end))
        if df.empty:
            return pd.DataFrame(columns=["ref_price", "paired_qty", "total_imbalance_qty", "side", "ts"])
        df = df[df["auction_type"] == "O"]
        df = df[df["ref_price"] > 0]
        df = df.sort_index()                       # index is ts_recv
        last = df.groupby("symbol").tail(1)
        out = last[["ref_price", "paired_qty", "total_imbalance_qty", "side"]].copy()
        out["ts"] = pd.to_datetime(last.index, utc=True)
        out.index = pd.Index(last["symbol"].astype(str).values, name="symbol")
        return out

    def opening_indicative_live(self, symbols: list[str], seconds: int = 20) -> pd.DataFrame:
        """Subscribe to NOII in real time for `seconds`, then return the latest reference price
        per symbol. Raises if the account is not entitled to live XNAS.ITCH."""
        live = self.db.Live(self.key)
        live.subscribe(dataset=DATASET, schema="imbalance", stype_in="raw_symbol", symbols=symbols)
        rows = []
        import time as _t
        deadline = _t.time() + seconds
        for rec in live:
            if isinstance(rec, self.db.ImbalanceMsg) and rec.auction_type == "O" and rec.ref_price > 0:
                rows.append({"symbol": live.symbology_map.get(rec.instrument_id, rec.instrument_id),
                             "ref_price": rec.ref_price / 1e9, "paired_qty": rec.paired_qty,
                             "total_imbalance_qty": rec.total_imbalance_qty, "side": rec.side,
                             "ts": pd.Timestamp(rec.ts_recv, unit="ns", tz="UTC")})
            if _t.time() > deadline:
                break
        live.stop()
        if not rows:
            return pd.DataFrame(columns=["ref_price", "paired_qty", "total_imbalance_qty", "side", "ts"])
        return pd.DataFrame(rows).groupby("symbol").tail(1).set_index("symbol")
