"""Backtest engine: apply a (lagged) weight series to a reversal portfolio return,
charge costs on every dollar traded, and return a daily P&L frame.

Book convention
---------------
One unit of exposure (w = 1) is $1 long losers / $1 short winners, i.e. gross
notional 2. Capital is one unit, so returns are per unit of exposure capital.

Dollars traded (one-way) on day t
---------------------------------
  reformation : the reversal portfolio is re-formed every day; a fraction TAU
                of the gross book (2 * w_t) is replaced  ->  2 * w_t * TAU
  timing      : moving exposure from w_{t-1} to w_t     ->  2 * |w_t - w_{t-1}|
Cost on day t = (dollars traded) * c_t, where c_t = c_base * (VIX_{t-1} / 20)
when COST_SCALES_WITH_VIX else c_base. All inputs lagged, so the cost for day t
is known when the trade is placed.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import config


@dataclass(frozen=True)
class CostModel:
    c_base_bps: float
    tau: float = config.TAU
    scale_with_vix: bool = config.COST_SCALES_WITH_VIX
    multiplier: float = 1.0  # stress: x2 costs

    def per_dollar(self, vix_lag: pd.Series) -> pd.Series:
        c = pd.Series(self.c_base_bps * 1e-4 * self.multiplier, index=vix_lag.index)
        if self.scale_with_vix:
            c = c * (vix_lag / config.VIX_NORM)
        return c


def run(panel: pd.DataFrame, universe: str, w: pd.Series, cost: CostModel) -> pd.DataFrame:
    """Return a frame with gross, cost, net returns, dollars traded and weights."""
    r = panel[universe]
    w = w.reindex(panel.index).astype(float)
    assert not w.isna().any(), "weights contain NaN"
    w_prev = w.shift(1).fillna(w.iloc[0])  # the first day's book is set up at the start, no extra churn
    traded = 2.0 * (w * cost.tau + (w - w_prev).abs())
    c = cost.per_dollar(panel["vix_lag"])
    gross = w * r
    cost_ret = traded * c
    out = pd.DataFrame({
        "w": w,
        "gross": gross,
        "cost": cost_ret,
        "net": gross - cost_ret,
        "traded": traded,
        "underlying": r,
    })
    out.index.name = "date"
    return out


def equity(net: pd.Series, start_value: float = 1.0) -> pd.Series:
    return start_value * (1.0 + net).cumprod()


def breakeven_cost_bps(panel: pd.DataFrame, universe: str, w: pd.Series, cost: CostModel,
                       lo: float = 0.0, hi: float = 200.0, tol: float = 0.05) -> float:
    """c_base (bps) at which the net Sharpe crosses zero, by bisection.

    Net return is linear in c_base, so the net mean is monotone in it, and the
    bisection is on the sign of the mean (Sharpe has the same sign).
    """
    def mean_net(c_bps: float) -> float:
        cm = CostModel(c_bps, cost.tau, cost.scale_with_vix, cost.multiplier)
        return run(panel, universe, w, cm)["net"].mean()

    if mean_net(lo) <= 0:
        return 0.0
    if mean_net(hi) > 0:
        return float("inf")
    while hi - lo > tol:
        mid = 0.5 * (lo + hi)
        if mean_net(mid) > 0:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)
