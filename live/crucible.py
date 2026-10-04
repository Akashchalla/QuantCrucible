"""Quant Crucible: deterministic strategy red-team and hypothesis stress lab.

All metrics are computed from committed research artefacts. Gemini may explain the
results, but the PASS/REVIEW/REJECT verdict is produced here from deterministic tests.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .settings import SETTINGS

ROOT = SETTINGS.root
PANEL_PATH = ROOT / "results" / "tables" / "gapfade_panel_daily.csv"
TD = 252
IS_END = pd.Timestamp("2024-08-31")
OOS_START = pd.Timestamp("2024-09-01")


@dataclass(frozen=True)
class HypothesisSpec:
    name: str = "VIX-gated opening-auction gap fade"
    threshold: float = 20.0
    cost_bps: float = 5.0
    sort: str = "quintile"
    alpha_retention: float = 1.0
    min_sharpe: float = 0.35
    require_positive_oos: bool = True


def load_panel() -> pd.DataFrame:
    df = pd.read_csv(PANEL_PATH, parse_dates=["date"]).set_index("date").sort_index()
    need = {"spread_q", "spread_d", "vix_lag", "q1", "q5", "ew"}
    missing = need - set(df.columns)
    if missing:
        raise RuntimeError(f"committed gap-fade panel missing {sorted(missing)}")
    return df


def _series(panel: pd.DataFrame, spec: HypothesisSpec, *, cost_mult: float = 1.0,
            threshold: float | None = None, alpha_retention: float | None = None,
            extra_slippage_bps: float = 0.0) -> pd.DataFrame:
    threshold = spec.threshold if threshold is None else threshold
    alpha_retention = spec.alpha_retention if alpha_retention is None else alpha_retention
    spread_col = "spread_q" if spec.sort == "quintile" else "spread_d"
    w = (panel["vix_lag"] >= threshold).astype(float)
    gross = panel[spread_col].astype(float) * w * alpha_retention
    # $1 long + $1 short is bought/sold intraday => 4 dollars one-way-equivalent turnover.
    one_way = spec.cost_bps * cost_mult * 1e-4 * (panel["vix_lag"] / 20.0)
    cost = w * (4.0 * one_way + extra_slippage_bps * 1e-4)
    out = pd.DataFrame({"w": w, "gross": gross, "cost": cost, "net": gross - cost}, index=panel.index)
    return out


def _max_dd(x: pd.Series) -> float:
    eq = (1.0 + x.fillna(0)).cumprod()
    return float((eq / eq.cummax() - 1.0).min())


def _metrics(bt: pd.DataFrame) -> dict[str, float | int]:
    x = bt["net"].dropna()
    on = bt.loc[x.index, "w"] > 0
    std = x.std(ddof=1)
    sharpe = float(np.sqrt(TD) * x.mean() / std) if std > 0 else float("nan")
    tail = x.quantile(0.05)
    cvar = x[x <= tail].mean() if len(x) else np.nan
    return {
        "sharpe": sharpe,
        "ann_return": float(x.mean() * TD),
        "ann_vol": float(std * np.sqrt(TD)) if np.isfinite(std) else np.nan,
        "mean_bps": float(x.mean() * 1e4),
        "mean_bps_on": float(x[on].mean() * 1e4) if on.any() else np.nan,
        "max_drawdown": _max_dd(x),
        "hit_rate_on": float((x[on] > 0).mean()) if on.any() else np.nan,
        "n_days_on": int(on.sum()),
        "n_days": int(len(x)),
        "var_95": float(tail),
        "cvar_95": float(cvar) if pd.notna(cvar) else np.nan,
    }


def _bootstrap_mean_bps(x: pd.Series, n: int = 1500, seed: int = 73) -> dict[str, Any]:
    vals = x.dropna().to_numpy(float)
    if not len(vals):
        return {"mean": np.nan, "lo": np.nan, "hi": np.nan, "samples": []}
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(vals), size=(n, len(vals)))
    means = vals[idx].mean(axis=1) * 1e4
    return {
        "mean": float(vals.mean() * 1e4),
        "lo": float(np.quantile(means, 0.025)),
        "hi": float(np.quantile(means, 0.975)),
        "samples": means.tolist(),
    }


def run_red_team(spec: HypothesisSpec | None = None) -> dict[str, Any]:
    spec = spec or HypothesisSpec()
    panel = load_panel()
    base = _series(panel, spec)
    is_bt, oos_bt = base.loc[:IS_END], base.loc[OOS_START:]
    base_m, is_m, oos_m = _metrics(base), _metrics(is_bt), _metrics(oos_bt)

    thresholds = [15.0, 17.5, 20.0, 22.5, 25.0, 30.0]
    threshold_rows = []
    for t in thresholds:
        m = _metrics(_series(panel, spec, threshold=t))
        threshold_rows.append({"threshold": t, **m})
    threshold_df = pd.DataFrame(threshold_rows)

    cost_rows = []
    for mult in [0.5, 1.0, 1.5, 2.0, 3.0, 4.0]:
        m = _metrics(_series(panel, spec, cost_mult=mult))
        cost_rows.append({"cost_mult": mult, "effective_base_bps": spec.cost_bps * mult, **m})
    cost_df = pd.DataFrame(cost_rows)

    alpha_rows = []
    for keep in [1.0, 0.9, 0.75, 0.6, 0.5, 0.4, 0.25]:
        m = _metrics(_series(panel, spec, alpha_retention=keep))
        alpha_rows.append({"alpha_retention": keep, **m})
    alpha_df = pd.DataFrame(alpha_rows)

    # Outlier dependence: remove the strongest strategy days from the full sample.
    outlier_rows = []
    for k in [0, 1, 3, 5, 10, 20]:
        tmp = base.copy()
        if k:
            strongest = tmp["net"].nlargest(k).index
            tmp = tmp.drop(index=strongest)
        outlier_rows.append({"removed_best_days": k, **_metrics(tmp)})
    outlier_df = pd.DataFrame(outlier_rows)

    # Calendar stability.
    yearly = []
    for year, g in base.groupby(base.index.year):
        if len(g) >= 100:
            yearly.append({"year": int(year), **_metrics(g)})
    yearly_df = pd.DataFrame(yearly)

    boot = _bootstrap_mean_bps(base.loc[base["w"] > 0, "net"])

    # Break-even cost multiplier via monotone grid interpolation.
    grid = np.linspace(0.0, 8.0, 161)
    means = np.array([_series(panel, spec, cost_mult=float(m))["net"].mean() for m in grid])
    nonpos = np.where(means <= 0)[0]
    cost_break = float(grid[nonpos[0]]) if len(nonpos) else float("inf")

    # Break-even alpha retention.
    agrid = np.linspace(0.0, 1.0, 201)
    amean = np.array([_series(panel, spec, alpha_retention=float(a))["net"].mean() for a in agrid])
    pos = np.where(amean > 0)[0]
    alpha_break = float(agrid[pos[0]]) if len(pos) else float("inf")

    checks = {
        "positive_full_sample": base_m["mean_bps"] > 0,
        "sharpe_floor": base_m["sharpe"] >= spec.min_sharpe,
        "positive_oos": (oos_m["mean_bps"] > 0) if spec.require_positive_oos else True,
        "bootstrap_excludes_zero": boot["lo"] > 0,
        "survives_double_cost": float(cost_df.loc[cost_df["cost_mult"] == 2.0, "mean_bps"].iloc[0]) > 0,
        "survives_remove_5_best": float(outlier_df.loc[outlier_df["removed_best_days"] == 5, "mean_bps"].iloc[0]) > 0,
        "threshold_neighborhood_positive": int((threshold_df.query("threshold >= 17.5 and threshold <= 25")['mean_bps'] > 0).sum()) >= 3,
        "year_stability": float((yearly_df["mean_bps"] > 0).mean()) >= 0.60 if len(yearly_df) else False,
    }
    score = int(round(100 * sum(bool(v) for v in checks.values()) / len(checks)))
    hard_fail = (not checks["positive_full_sample"]) or (spec.require_positive_oos and not checks["positive_oos"])
    verdict = "REJECT" if hard_fail or score < 50 else ("PROVISIONAL PASS" if score < 80 else "ROBUST PASS")

    # Evidence bullets are deterministic and safe for direct display / TTS.
    findings = [
        f"Headline net Sharpe is {base_m['sharpe']:.2f} with mean {base_m['mean_bps']:+.2f} bps/day across the full committed sample.",
        f"Held-out mean is {oos_m['mean_bps']:+.2f} bps/day; held-out Sharpe is {oos_m['sharpe']:.2f}.",
        f"95% bootstrap interval for traded-day mean is {boot['lo']:+.2f} to {boot['hi']:+.2f} bps.",
        f"Break-even cost multiplier is approximately {cost_break:.2f}× headline costs." if np.isfinite(cost_break) else "The tested cost grid never erased the full-sample mean.",
        f"The strategy needs roughly {alpha_break:.0%} of measured gross alpha to retain a positive full-sample mean." if np.isfinite(alpha_break) else "No tested alpha-retention level produced a positive mean.",
    ]

    from .math_verifier import verify_return_metrics
    verification = verify_return_metrics(base["net"], base_m)

    return {
        "spec": asdict(spec),
        "verdict": verdict,
        "score": score,
        "checks": checks,
        "verification": verification,
        "findings": findings,
        "base_metrics": base_m,
        "is_metrics": is_m,
        "oos_metrics": oos_m,
        "thresholds": threshold_df,
        "costs": cost_df,
        "alpha": alpha_df,
        "outliers": outlier_df,
        "yearly": yearly_df,
        "bootstrap": boot,
        "break_even_cost_mult": cost_break,
        "break_even_alpha_retention": alpha_break,
        "equity": pd.DataFrame({
            "headline": (1 + base["net"]).cumprod(),
            "double_cost": (1 + _series(panel, spec, cost_mult=2.0)["net"]).cumprod(),
            "half_alpha": (1 + _series(panel, spec, alpha_retention=0.5)["net"]).cumprod(),
        }),
    }


def compact(result: dict[str, Any]) -> dict[str, Any]:
    """JSON-safe compact result for Gemini explanation."""
    return {
        "spec": result["spec"],
        "verdict": result["verdict"],
        "score": result["score"],
        "checks": result["checks"],
        "verification": result.get("verification"),
        "findings": result["findings"],
        "base_metrics": result["base_metrics"],
        "is_metrics": result["is_metrics"],
        "oos_metrics": result["oos_metrics"],
        "break_even_cost_mult": result["break_even_cost_mult"],
        "break_even_alpha_retention": result["break_even_alpha_retention"],
    }
