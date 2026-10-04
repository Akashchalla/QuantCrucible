"""Massive (formerly Polygon.io) REST feed: official daily opens/closes, real-time snapshots,
market status. Daily `o` is the consolidated official opening print — it matches the Nasdaq
auction reference price to the cent (checked against Databento NOII), so it is what the
backtest's "fill at the open" maps to in production.
"""
from __future__ import annotations

import time
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import requests

from ..settings import SETTINGS

BASE = "https://api.massive.com"


class FeedError(RuntimeError):
    pass


class NotEntitled(FeedError):
    pass


class MassiveFeed:
    def __init__(self, api_key: str | None = None, session: requests.Session | None = None):
        self.key = api_key or SETTINGS.massive_api_key
        if not self.key:
            raise FeedError("MASSIVE_API_KEY missing from .env")
        self.s = session or requests.Session()

    # ----------------------------------------------------------------- http
    def _get(self, path: str, retries: int = 4, **params) -> dict:
        params["apiKey"] = self.key
        for attempt in range(retries):
            r = self.s.get(BASE + path, params=params, timeout=30)
            if r.status_code == 429 and attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            if r.status_code == 403:
                raise NotEntitled(r.json().get("message", r.text))
            if r.status_code >= 400:
                raise FeedError(f"{r.status_code} {path}: {r.text[:200]}")
            js = r.json()
            if isinstance(js, dict) and js.get("status") == "NOT_AUTHORIZED":
                raise NotEntitled(js.get("message", ""))
            return js
        raise FeedError(f"rate limited: {path}")

    # --------------------------------------------------------------- daily
    def grouped_daily(self, d: date, adjusted: bool = True) -> pd.DataFrame:
        """Official OHLCV for every US stock on session `d`, indexed by ticker.
        Empty frame on a non-session day."""
        js = self._get(f"/v2/aggs/grouped/locale/us/market/stocks/{d:%Y-%m-%d}", adjusted=str(adjusted).lower())
        rows = js.get("results") or []
        if not rows:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume", "vwap", "n"])
        df = pd.DataFrame(rows).rename(columns={"T": "symbol", "o": "open", "h": "high", "l": "low",
                                                "c": "close", "v": "volume", "vw": "vwap"})
        df = df.drop_duplicates("symbol").set_index("symbol")
        return df[["open", "high", "low", "close", "volume", "vwap", "n"]].astype(float)

    def official_prices(self, d: date, symbols: list[str]) -> pd.DataFrame:
        """open/close for `symbols` on `d` (NaN if missing)."""
        g = self.grouped_daily(d)
        return g.reindex(symbols)[["open", "close", "volume"]]

    # ------------------------------------------------------------ real time
    def snapshots(self, symbols: list[str], batch: int = 250) -> pd.DataFrame:
        """Latest consolidated state per ticker: last trade, today's open (if printed),
        previous close, fair market value, update time. Pre-market last trades are included
        when the plan carries them, which is what makes this usable as a gap estimate."""
        out = []
        for i in range(0, len(symbols), batch):
            chunk = symbols[i:i + batch]
            js = self._get("/v2/snapshot/locale/us/markets/stocks/tickers", tickers=",".join(chunk))
            for t in js.get("tickers", []):
                day, prev, lt = t.get("day") or {}, t.get("prevDay") or {}, t.get("lastTrade") or {}
                out.append({
                    "symbol": t["ticker"],
                    "last": lt.get("p"),
                    "last_ts": pd.Timestamp(lt["t"], unit="ns", tz="UTC") if lt.get("t") else pd.NaT,
                    "today_open": day.get("o") or None,
                    "prev_close": prev.get("c"),
                    "fmv": t.get("fmv"),
                    "updated": pd.Timestamp(t["updated"], unit="ns", tz="UTC") if t.get("updated") else pd.NaT,
                })
        df = pd.DataFrame(out).set_index("symbol") if out else pd.DataFrame()
        return df.reindex(symbols) if len(df) else df

    def market_status(self) -> dict:
        return self._get("/v1/marketstatus/now")

    def upcoming_holidays(self) -> pd.DataFrame:
        js = self._get("/v1/marketstatus/upcoming")
        return pd.DataFrame(js if isinstance(js, list) else js.get("results", []))

    def is_session(self, d: date) -> bool:
        """True if `d` is a trading day: weekday and not a full-closure holiday."""
        if d.weekday() >= 5:
            return False
        try:
            hol = self.upcoming_holidays()
            if len(hol):
                closed = hol[(hol["status"] == "closed") & (hol["exchange"].isin(["NYSE", "NASDAQ"]))]
                if (pd.to_datetime(closed["date"]).dt.date == d).any():
                    return False
        except FeedError:
            pass
        return True

    def previous_session(self, d: date, max_back: int = 6) -> date:
        """Most recent session before `d` that has official prices."""
        cur = d
        for _ in range(max_back):
            cur = cur - timedelta(days=1)
            if cur.weekday() >= 5:
                continue
            if len(self.grouped_daily(cur)):
                return cur
        raise FeedError(f"no session found before {d}")

    def vix_prev_close(self) -> tuple[date, float]:
        """Requires an indices entitlement; raises NotEntitled otherwise."""
        js = self._get("/v2/aggs/ticker/I:VIX/prev")
        r = js["results"][0]
        return datetime.fromtimestamp(r["t"] / 1000, tz=timezone.utc).date(), float(r["c"])
