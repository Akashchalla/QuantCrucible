"""Lagged VIX for the participation gate.

The rule uses VIX_{t-1} (yesterday's close), so a real-time index feed is not required —
only yesterday's official close, available before the open from several sources. Chain:
Massive indices (if entitled) -> Yahoo (^VIX, ^VIX3M) -> FRED cache from the research
pipeline. Each source reports the date it refers to so staleness can be checked.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from ..settings import SETTINGS


@dataclass
class VixState:
    as_of: date          # the close this value refers to (should be the previous session)
    vix: float
    vix3m: float | None
    source: str

    @property
    def term_ratio(self) -> float | None:
        return self.vix / self.vix3m if self.vix3m else None


def _from_massive() -> VixState:
    from .massive import MassiveFeed
    d, v = MassiveFeed().vix_prev_close()
    return VixState(d, v, None, "massive")


def _from_yahoo(before: date) -> VixState:
    import yfinance as yf
    start = pd.Timestamp(before) - pd.Timedelta(days=14)
    px = yf.download("^VIX ^VIX3M", start=start.strftime("%Y-%m-%d"), progress=False, auto_adjust=False)["Close"]
    px = px[px.index.date < before].dropna(subset=["^VIX"])
    if px.empty:
        raise RuntimeError("yahoo returned no VIX rows")
    last = px.iloc[-1]
    v3 = last.get("^VIX3M")
    return VixState(px.index[-1].date(), float(last["^VIX"]), None if pd.isna(v3) else float(v3), "yahoo")


def _from_fred_cache(before: date) -> VixState:
    vix = pd.read_csv(SETTINGS.cache_dir.parent / "processed" / "vix_daily.csv", index_col=0, parse_dates=True).iloc[:, 0]
    vix = vix[vix.index.date < before].dropna()
    v3 = None
    p3 = SETTINGS.cache_dir.parent / "processed" / "vix3m_daily.csv"
    if p3.exists():
        s3 = pd.read_csv(p3, index_col=0, parse_dates=True).iloc[:, 0].dropna()
        s3 = s3[s3.index <= vix.index[-1]]
        v3 = float(s3.iloc[-1]) if len(s3) else None
    return VixState(vix.index[-1].date(), float(vix.iloc[-1]), v3, "fred-cache")


def lagged_vix(session: date) -> VixState:
    """VIX close strictly before `session`, from the first source that answers."""
    errors = []
    for fn in (_from_massive, lambda: _from_yahoo(session), lambda: _from_fred_cache(session)):
        try:
            st = fn()
            if st.as_of < session:
                return st
            errors.append(f"{st.source}: as_of {st.as_of} not before {session}")
        except Exception as e:  # noqa: BLE001 — try the next source
            errors.append(f"{fn.__name__}: {type(e).__name__}: {str(e)[:120]}")
    raise RuntimeError("no VIX source available: " + " | ".join(errors))
