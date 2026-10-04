"""Market Multiverse: deterministic strategy stress scenarios and Monte-Carlo projections."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

import numpy as np
import pandas as pd

from .crucible import HypothesisSpec, load_panel, _metrics, _series


@dataclass(frozen=True)
class Scenario:
    name: str = "Custom stress"
    vix_multiplier: float = 1.5
    cost_multiplier: float = 2.0
    alpha_retention: float = 0.7
    extra_slippage_bps: float = 5.0
    volatility_multiplier: float = 1.25
    horizon_sessions: int = 60
    n_paths: int = 1200


def _scenario_series(panel: pd.DataFrame, spec: HypothesisSpec, sc: Scenario) -> pd.DataFrame:
    # Preserve the pre-registered participation rule, but stress the execution environment.
    # Higher VIX raises the cost schedule and volatility_multiplier widens residual outcomes.
    stressed = panel.copy()
    stressed["vix_lag"] = stressed["vix_lag"] * sc.vix_multiplier
    bt = _series(stressed, spec, cost_mult=sc.cost_multiplier,
                 alpha_retention=sc.alpha_retention, extra_slippage_bps=sc.extra_slippage_bps)
    # Volatility shock: widen deviations around the strategy's conditional mean without changing mean.
    x = bt["net"]
    mu = x.mean()
    bt["net"] = mu + (x - mu) * sc.volatility_multiplier
    bt["gross"] = bt["net"] + bt["cost"]
    return bt


def _simulate(x: pd.Series, horizon: int, n_paths: int, seed: int = 314159) -> dict[str, Any]:
    vals = x.dropna().to_numpy(float)
    if len(vals) < 20:
        raise ValueError("not enough observations for scenario simulation")
    rng = np.random.default_rng(seed)
    samples = rng.choice(vals, size=(n_paths, horizon), replace=True)
    eq = np.cumprod(1.0 + samples, axis=1)
    terminal = eq[:, -1] - 1.0
    running_max = np.maximum.accumulate(eq, axis=1)
    dd = eq / running_max - 1.0
    maxdd = dd.min(axis=1)
    bands = pd.DataFrame({
        "session": np.arange(1, horizon + 1),
        "p05": np.quantile(eq, 0.05, axis=0) - 1.0,
        "p25": np.quantile(eq, 0.25, axis=0) - 1.0,
        "median": np.quantile(eq, 0.50, axis=0) - 1.0,
        "p75": np.quantile(eq, 0.75, axis=0) - 1.0,
        "p95": np.quantile(eq, 0.95, axis=0) - 1.0,
    }).set_index("session")
    return {
        "terminal": terminal,
        "max_drawdown": maxdd,
        "bands": bands,
        "p_loss": float((terminal < 0).mean()),
        "p_drawdown_10": float((maxdd <= -0.10).mean()),
        "median_terminal": float(np.median(terminal)),
        "p05_terminal": float(np.quantile(terminal, 0.05)),
        "p95_terminal": float(np.quantile(terminal, 0.95)),
    }


def run_scenario(sc: Scenario | None = None, spec: HypothesisSpec | None = None) -> dict[str, Any]:
    sc, spec = sc or Scenario(), spec or HypothesisSpec()
    panel = load_panel()
    base = _series(panel, spec)
    stress = _scenario_series(panel, spec, sc)
    sim_base = _simulate(base.loc[base["w"] > 0, "net"], sc.horizon_sessions, sc.n_paths, seed=7)
    sim_stress = _simulate(stress.loc[stress["w"] > 0, "net"], sc.horizon_sessions, sc.n_paths, seed=11)

    # Sensitivity surface: cost x alpha retention -> mean net bps/day.
    cost_grid = [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0]
    alpha_grid = [1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4]
    surface = []
    for a in alpha_grid:
        row = {"alpha_retention": a}
        for c in cost_grid:
            tmp = _series(panel.assign(vix_lag=panel["vix_lag"] * sc.vix_multiplier), spec,
                          cost_mult=c, alpha_retention=a, extra_slippage_bps=sc.extra_slippage_bps)
            row[f"cost_{c:g}x"] = float(tmp["net"].mean() * 1e4)
        surface.append(row)
    surface_df = pd.DataFrame(surface)

    # Solve breakpoints under current VIX + extra-slippage assumptions.
    costs = np.linspace(0.0, 8.0, 161)
    means = []
    stressed_panel = panel.assign(vix_lag=panel["vix_lag"] * sc.vix_multiplier)
    for c in costs:
        means.append(_series(stressed_panel, spec, cost_mult=float(c), alpha_retention=sc.alpha_retention,
                             extra_slippage_bps=sc.extra_slippage_bps)["net"].mean())
    idx = np.where(np.array(means) <= 0)[0]
    cost_break = float(costs[idx[0]]) if len(idx) else float("inf")

    return {
        "scenario": asdict(sc),
        "base_metrics": _metrics(base),
        "stress_metrics": _metrics(stress),
        "base_sim": sim_base,
        "stress_sim": sim_stress,
        "surface": surface_df,
        "break_even_cost_mult": cost_break,
        "historical_equity": pd.DataFrame({
            "base": (1 + base["net"]).cumprod() - 1,
            "stressed": (1 + stress["net"]).cumprod() - 1,
        }),
    }
