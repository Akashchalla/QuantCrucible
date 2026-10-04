"""Capacity: how much capital the big-cap reversal book can run before costs
eat the premium. A rough square-root-impact model with every assumption explicit.

    python -m gqh.capacity        (from src/, after run_all.py)

Per-dollar one-way cost at capital K (at VIX = 20):
    participation p(K) = (daily $ traded per name) / ADV
                       = (2 * TAU * K / N_NAMES) / ADV_PER_NAME
    cost_bps(K)        = HALF_SPREAD_BPS + IMPACT_COEF * SIGMA_NAME_DAILY * sqrt(p(K)) * 1e4
This cost replaces c_base in the backtest's cost model (which still scales it
with VIX_{t-1}/20), and the in-sample net Sharpe of the constant-exposure
big-cap book is recomputed at each K.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from . import config, signals
from .backtest import CostModel, run
from .data import build_panel, split
from .metrics import perf_table

# ---- assumptions (large-cap US equities, value-weighted book) --------------
N_NAMES = 500                 # names held across both sides (~30% tails of ~850 above-NYSE-median stocks)
ADV_PER_NAME = 200e6          # value-weighted average daily $ volume per name
SIGMA_NAME_DAILY = 0.02       # single-name daily vol at VIX 20
HALF_SPREAD_BPS = 1.5         # large-cap half-spread + fees, taker
IMPACT_COEF = 1.0             # square-root law coefficient (Almgren et al. 2005 range 0.5-1.5)
CAPITALS = np.array([1e6, 1e7, 2.5e7, 5e7, 1e8, 2.5e8, 5e8, 1e9, 2.5e9, 5e9])


def participation(capital: float) -> float:
    return (2 * config.TAU * capital / N_NAMES) / ADV_PER_NAME


def cost_bps(capital: float) -> float:
    return HALF_SPREAD_BPS + IMPACT_COEF * SIGMA_NAME_DAILY * np.sqrt(participation(capital)) * 1e4


def capacity_table(panel_is: pd.DataFrame, universe: str = "big_rev") -> pd.DataFrame:
    w = signals.constant(panel_is)
    rows = []
    for k in CAPITALS:
        c = cost_bps(k)
        p = perf_table(run(panel_is, universe, w, CostModel(c, config.TAU, True)))
        rows.append({"capital_usd": k, "participation_pct_adv": 100 * participation(k), "cost_bps_one_way": c,
                     "ann_cost_drag": p["ann_cost_drag"], "sharpe_net_in_sample": p["sharpe_net"]})
    return pd.DataFrame(rows)


def solve_capital_for_cost(target_bps: float) -> float:
    """Invert cost_bps(K) = target."""
    imp = max(target_bps - HALF_SPREAD_BPS, 0) / (IMPACT_COEF * SIGMA_NAME_DAILY * 1e4)
    return imp**2 * ADV_PER_NAME * N_NAMES / (2 * config.TAU)


if __name__ == "__main__":
    panel_is, _ = split(build_panel())
    tbl = capacity_table(panel_is)
    out = Path(__file__).resolve().parents[2] / "results" / "tables" / "capacity_big_rev.csv"
    tbl.to_csv(out, index=False, float_format="%.4f")
    sr0 = perf_table(run(panel_is, "big_rev", signals.constant(panel_is), CostModel(HALF_SPREAD_BPS, config.TAU, True)))["sharpe_net"]
    print(tbl.to_string(index=False, formatters={"capital_usd": "${:,.0f}".format}))
    print(f"\nSpread-only net Sharpe (market-taker floor): {sr0:.2f}")
    # break-even c_base for the constant big-cap book is in results/in_sample.json; recompute here for the headline
    from .backtest import breakeven_cost_bps
    be = breakeven_cost_bps(panel_is, "big_rev", signals.constant(panel_is), CostModel(5.0, config.TAU, True))
    print(f"Break-even one-way cost: {be:.1f} bps  ->  capital at which the edge is gone: ${solve_capital_for_cost(be)/1e6:,.0f}M")
    sys.exit(0)
