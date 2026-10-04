"""Ghost Desk: counterfactual portfolios that quantify what risk controls saved or cost."""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .crucible import HypothesisSpec, load_panel, _metrics, _series
from .settings import SETTINGS


def _always_on(panel: pd.DataFrame, spec: HypothesisSpec) -> pd.DataFrame:
    spread_col = "spread_q" if spec.sort == "quintile" else "spread_d"
    w = pd.Series(1.0, index=panel.index)
    gross = panel[spread_col] * spec.alpha_retention
    cost = 4.0 * spec.cost_bps * 1e-4 * (panel["vix_lag"] / 20.0)
    return pd.DataFrame({"w": w, "gross": gross, "cost": cost, "net": gross - cost}, index=panel.index)


def run_ghost_desk(spec: HypothesisSpec | None = None, notional_per_side: float | None = None) -> dict[str, Any]:
    spec = spec or HypothesisSpec()
    notional = float(notional_per_side or SETTINGS.notional_per_side)
    panel = load_panel()
    real = _series(panel, spec)
    always = _always_on(panel, spec)
    low_gate = _series(panel, spec, threshold=15.0)
    high_gate = _series(panel, spec, threshold=25.0)
    no_cost = _series(panel, HypothesisSpec(**{**spec.__dict__, "cost_bps": 0.0}))

    gate_off = real["w"] == 0
    ghost_off_returns = always.loc[gate_off, "net"]
    avoided_losses = float((-ghost_off_returns[ghost_off_returns < 0]).sum() * notional)
    missed_gains = float(ghost_off_returns[ghost_off_returns > 0].sum() * notional)
    actual_dollars = float(real["net"].sum() * notional)
    always_dollars = float(always["net"].sum() * notional)
    gate_net_value = actual_dollars - always_dollars
    cost_paid = float(real["cost"].sum() * notional)

    summary = pd.DataFrame([
        {"universe": "Actual · VIX≥20", "pnl_usd": actual_dollars, **_metrics(real)},
        {"universe": "Ghost · always on", "pnl_usd": always_dollars, **_metrics(always)},
        {"universe": "Ghost · VIX≥15", "pnl_usd": float(low_gate["net"].sum()*notional), **_metrics(low_gate)},
        {"universe": "Ghost · VIX≥25", "pnl_usd": float(high_gate["net"].sum()*notional), **_metrics(high_gate)},
        {"universe": "Ghost · no modeled costs", "pnl_usd": float(no_cost["net"].sum()*notional), **_metrics(no_cost)},
    ])

    ledger = pd.DataFrame([
        {"effect": "Avoided losses on gate-off days", "value_usd": avoided_losses},
        {"effect": "Missed gains on gate-off days", "value_usd": -missed_gains},
        {"effect": "Net value of VIX gate vs always-on", "value_usd": gate_net_value},
        {"effect": "Modeled costs paid by actual rule", "value_usd": -cost_paid},
    ])

    eq = pd.DataFrame({
        "Actual · VIX≥20": real["net"].cumsum() * notional,
        "Ghost · always on": always["net"].cumsum() * notional,
        "Ghost · VIX≥15": low_gate["net"].cumsum() * notional,
        "Ghost · VIX≥25": high_gate["net"].cumsum() * notional,
    })

    return {
        "summary": summary,
        "ledger": ledger,
        "equity_dollars": eq,
        "avoided_losses": avoided_losses,
        "missed_gains": missed_gains,
        "gate_net_value": gate_net_value,
        "actual_dollars": actual_dollars,
        "always_dollars": always_dollars,
        "notional_per_side": notional,
    }
