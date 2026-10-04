"""From prices to target positions, exactly as HYPOTHESIS_B.md defines the book.

    gap    = est_open / prev_close - 1
    relgap = gap - cross-sectional median gap
    long the bottom quintile of relgap (gapped down), short the top quintile, equal weight,
    $notional_per_side on each side, no overnight position.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .settings import SETTINGS


def build_signals(prev_close: pd.Series, est_open: pd.Series, *, n_buckets: int | None = None,
                  gap_filter: float | None = None, min_price: float | None = None,
                  notional_per_side: float | None = None, max_name_pct: float | None = None) -> pd.DataFrame:
    n_buckets = n_buckets or SETTINGS.n_buckets
    gap_filter = SETTINGS.gap_filter if gap_filter is None else gap_filter
    min_price = SETTINGS.min_price if min_price is None else min_price
    notional_per_side = notional_per_side or SETTINGS.notional_per_side
    max_name_pct = SETTINGS.max_name_pct_of_side if max_name_pct is None else max_name_pct

    df = pd.DataFrame({"prev_close": prev_close.astype(float), "est_open": est_open.reindex(prev_close.index).astype(float)})
    df["gap"] = df["est_open"] / df["prev_close"] - 1
    df["excluded"] = None
    df.loc[df["prev_close"].isna() | df["est_open"].isna(), "excluded"] = "no_price"
    df.loc[df["excluded"].isna() & (df["gap"].abs() > gap_filter), "excluded"] = "gap_filter"
    df.loc[df["excluded"].isna() & (df["est_open"] < min_price), "excluded"] = "min_price"

    ok = df["excluded"].isna()
    df["relgap"] = np.nan
    df.loc[ok, "relgap"] = df.loc[ok, "gap"] - df.loc[ok, "gap"].median()
    df["pct_rank"] = df.loc[ok, "relgap"].rank(pct=True)
    df["bucket"] = np.nan
    df.loc[ok, "bucket"] = np.minimum(np.ceil(df.loc[ok, "pct_rank"] * n_buckets), n_buckets)
    df["side"] = 0
    df.loc[df["pct_rank"] <= 1.0 / n_buckets, "side"] = 1
    df.loc[df["pct_rank"] > 1.0 - 1.0 / n_buckets, "side"] = -1

    df["target_notional"] = 0.0
    for side in (1, -1):
        names = df.index[df["side"] == side]
        if len(names):
            per = min(notional_per_side / len(names), max_name_pct * notional_per_side)
            df.loc[names, "target_notional"] = side * per
    df["target_qty"] = 0
    live = df["side"] != 0
    df.loc[live, "target_qty"] = (df.loc[live, "target_notional"] / df.loc[live, "est_open"]).apply(
        lambda x: int(math.copysign(math.floor(abs(x)), x)))
    zero = live & (df["target_qty"] == 0)
    df.loc[zero, ["side", "target_notional"]] = [0, 0.0]
    df.loc[zero, "excluded"] = "qty0"
    return df


def ideal_book(prev_close: pd.Series, official_open: pd.Series, n_buckets: int | None = None) -> pd.DataFrame:
    """The backtest's equal-weight book on official opens: no share rounding, no price floor."""
    return build_signals(prev_close, official_open, n_buckets=n_buckets, min_price=0.0,
                         notional_per_side=1e12, max_name_pct=1.0)


def spread_bps(ret_oc: pd.Series, side: pd.Series) -> tuple[float, float, float]:
    """(long mean, short mean, long-short) open-to-close return in bps for the selected names."""
    lo = ret_oc[side == 1].mean()
    hi = ret_oc[side == -1].mean()
    return 1e4 * lo, 1e4 * hi, 1e4 * (lo - hi)


def implementation_shortfall(sig: pd.DataFrame, official_open: pd.Series, official_close: pd.Series,
                             n_buckets: int | None = None) -> dict:
    """How different were the baskets chosen on indicative prices from the ones the backtest
    would have chosen on official opens, and what did that cost in spread?"""
    n_buckets = n_buckets or SETTINGS.n_buckets
    real = ideal_book(sig["prev_close"], official_open.reindex(sig.index), n_buckets=n_buckets)
    ret_oc = official_close.reindex(sig.index) / official_open.reindex(sig.index) - 1
    chosen = sig.index[sig["side"] != 0]
    same = (sig.loc[chosen, "side"] == real.loc[chosen, "side"]).mean() if len(chosen) else np.nan
    _, _, traded = spread_bps(ret_oc, sig["side"])
    _, _, ideal = spread_bps(ret_oc, real["side"])
    est_gap_err = (sig["gap"] - real["gap"]).abs()
    return {
        "basket_overlap": float(same) if same == same else None,
        "traded_spread_bps": float(traded) if traded == traded else None,
        "ideal_spread_bps": float(ideal) if ideal == ideal else None,
        "shortfall_bps": float(ideal - traded) if (ideal == ideal and traded == traded) else None,
        "median_abs_gap_error_bps": float(1e4 * est_gap_err.median()) if est_gap_err.notna().any() else None,
        "n_chosen": int(len(chosen)),
    }
