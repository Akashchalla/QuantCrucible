"""Load processed data and align the conditioning variable WITHOUT lookahead."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from . import config

ROOT = Path(__file__).resolve().parents[2]
PROCESSED = ROOT / "data" / "processed"


def load_returns() -> pd.DataFrame:
    p = PROCESSED / "returns_daily.csv"
    if not p.exists():
        raise FileNotFoundError("run `python data/download.py` first")
    return pd.read_csv(p, index_col="date", parse_dates=True)


def load_vix() -> pd.Series:
    p = PROCESSED / "vix_daily.csv"
    if not p.exists():
        raise FileNotFoundError("run `python data/download.py` first")
    return pd.read_csv(p, index_col="date", parse_dates=True)["vix"]


def lag_asof(signal: pd.Series, target_index: pd.DatetimeIndex, name: str) -> pd.Series:
    """For each target date t, return the last signal value dated STRICTLY before t.

    This is the only place the conditioning variable touches the return
    calendar. `allow_exact_matches=False` guarantees that a VIX close on day t
    can never influence the position held on day t.
    """
    left = pd.DataFrame({"date": target_index})
    right = signal.rename(name).reset_index().rename(columns={signal.index.name or "index": "date"})
    right = right.sort_values("date")
    merged = pd.merge_asof(left, right, on="date", direction="backward", allow_exact_matches=False)
    return merged.set_index("date")[name]


def build_panel(start: pd.Timestamp = config.SAMPLE_START,
                end: pd.Timestamp = config.OOS_END) -> pd.DataFrame:
    """Daily panel: reversal returns, factor returns, and lagged VIX.

    Columns
    -------
    st_rev, big_rev, small_rev : reversal portfolio returns on day t (decimal)
    mkt_rf, smb, hml, rmw, cma, mom, rf : Fama-French factors on day t
    vix_lag  : VIX close of the last trading day strictly before t
    vix_lag_median : trailing median of vix_lag over REGIME_WINDOW days (ends at t-1)
    """
    rets = load_returns()
    vix = load_vix()
    rets = rets.loc[(rets.index >= start) & (rets.index <= end)].dropna(subset=["st_rev", "big_rev"])
    panel = rets.copy()
    panel["vix_lag"] = lag_asof(vix, panel.index, "vix")
    # the median only uses values already in vix_lag, so it ends at t-1 as well
    panel["vix_lag_median"] = panel["vix_lag"].rolling(config.REGIME_WINDOW, min_periods=config.REGIME_WINDOW // 2).median()
    panel = panel.dropna(subset=["vix_lag"])
    panel.index.name = "date"
    return panel


def split(panel: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """In-sample / out-of-sample split by the pre-registered dates."""
    is_ = panel.loc[: config.IS_END]
    oos = panel.loc[config.OOS_START: config.OOS_END]
    return is_, oos
