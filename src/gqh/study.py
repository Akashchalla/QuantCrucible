"""The study itself: every number in the note is produced here.

Two layers, kept separate on purpose:

  PRE-REGISTERED  — the headline rule, its constant-exposure benchmark, the
                    two hypothesis tests and the 36-variant sensitivity grid.
                    Fixed in HYPOTHESIS.md before any backtest was run.
  POST-HOC        — designed after the in-sample result was seen: the
                    mean-variance-consistent sizing of the same hypothesis and
                    its vol-targeted benchmark. Flagged as such everywhere and
                    counted as extra trials.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from . import config, plots, signals
from .backtest import CostModel, breakeven_cost_bps, run
from .metrics import (by_year, deflated_sharpe, factor_alpha, perf_table, predictive_regression,
                      sharpe_difference_test, vix_quintile_edges, vix_quintile_table)

UNIVERSE_LABEL = {"st_rev": "ST_Rev factor (all-cap)", "big_rev": "big-cap reversal leg", "small_rev": "small-cap leg"}
UNIVERSES = ("st_rev", "big_rev")
SUBPERIODS = {"1990-2003 (pre-decimalisation / pre-HFT)": ("1990-01-01", "2003-12-31"),
              "2004-2024 (electronic market making)": ("2004-01-01", "2024-08-31")}
N_POST_HOC_TRIALS = 2   # mean-variance rule and its vol-target benchmark


def cost_for(universe: str, multiplier: float = 1.0, scale: bool | None = None) -> CostModel:
    return CostModel(config.C_BASE_BPS[universe], config.TAU,
                     config.COST_SCALES_WITH_VIX if scale is None else scale, multiplier)


def _json(obj):
    if isinstance(obj, dict):
        return {str(k): _json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json(v) for v in obj]
    if isinstance(obj, (np.floating, float)):
        return None if np.isnan(obj) else float(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, pd.Timestamp):
        return str(obj.date())
    return obj


# ---------------------------------------------------------------------------
# weights (always computed on the full causal history, then sliced)
# ---------------------------------------------------------------------------
def all_weights(panel_full: pd.DataFrame) -> dict:
    """Every rule's weight series on the full panel passed in. All causal."""
    w = {"headline": signals.linear(panel_full, config.VIX_NORM, config.LEVERAGE_CAP),
         "constant": signals.constant(panel_full)}
    for u in UNIVERSES:
        w[f"vol_target_{u}"] = signals.vol_target(panel_full, u)
        mv, scale = signals.mean_variance(panel_full, u)
        w[f"mean_variance_{u}"] = mv
        w[f"mean_variance_scale_{u}"] = scale
    return w


def _slice(s: pd.Series, start, end) -> pd.Series:
    return s.loc[start:end]


# ---------------------------------------------------------------------------
# one evaluation period
# ---------------------------------------------------------------------------
def evaluate(panel_full: pd.DataFrame, start, end, label: str, is_edges: np.ndarray | None = None) -> dict:
    """Everything for one period. `panel_full` must end at or after `end` and
    contain all history before `start` (the walk-forward rule needs it).
    `is_edges`: in-sample VIX quintile edges, so an out-of-sample period can be
    binned on the SAME VIX levels as the in-sample table."""
    W = all_weights(panel_full)
    panel = panel_full.loc[start:end]
    out = {"label": label, "start": str(panel.index[0].date()), "end": str(panel.index[-1].date()), "n_days": len(panel)}
    w_timed, w_const = _slice(W["headline"], start, end), _slice(W["constant"], start, end)
    out["exposure"] = signals.exposure_summary(w_timed)

    out["prediction_1_regression"] = {u: predictive_regression(panel, u) for u in UNIVERSES}
    out["prediction_2_quintiles"] = {u: vix_quintile_table(panel, u).reset_index().to_dict(orient="records") for u in UNIVERSES}
    if is_edges is not None:
        out["prediction_2_quintiles_in_sample_edges"] = {
            u: vix_quintile_table(panel, u, is_edges).reset_index().to_dict(orient="records") for u in UNIVERSES}
        out["in_sample_edges"] = [float(e) for e in is_edges]

    out["strategies"], out["backtests"], out["post_hoc"] = {}, {}, {}
    for u in UNIVERSES:
        cost = cost_for(u)
        bt_t, bt_c = run(panel, u, w_timed, cost), run(panel, u, w_const, cost)
        out["backtests"][u] = {"timed": bt_t, "constant": bt_c}
        out["strategies"][u] = {
            "timed": perf_table(bt_t),
            "constant": perf_table(bt_c),
            "timed_flat_costs": perf_table(run(panel, u, w_timed, cost_for(u, scale=False))),
            "timed_costs_x2": perf_table(run(panel, u, w_timed, cost_for(u, 2.0))),
            "constant_costs_x2": perf_table(run(panel, u, w_const, cost_for(u, 2.0))),
            "timed_vs_constant": sharpe_difference_test(bt_t["net"], bt_c["net"]),
            "factor_alpha_timed": factor_alpha(bt_t["net"], panel),
            "factor_alpha_constant": factor_alpha(bt_c["net"], panel),
            "breakeven_c_base_bps_timed": breakeven_cost_bps(panel, u, w_timed, cost),
            "breakeven_c_base_bps_constant": breakeven_cost_bps(panel, u, w_const, cost),
            "by_year_timed": by_year(bt_t["net"]).round(4).to_dict(),
            "by_year_constant": by_year(bt_c["net"]).round(4).to_dict(),
        }

        # ---- post-hoc: risk-aware sizing, all three on the same days --------
        w_mv = _slice(W[f"mean_variance_{u}"], start, end)
        valid = w_mv.notna()
        if valid.sum() < 2 * config.TRADING_DAYS and label == "in-sample":
            continue
        p_sub = panel.loc[valid]
        trio = {"constant": w_const.loc[valid], "vol_target": _slice(W[f"vol_target_{u}"], start, end).loc[valid],
                "mean_variance": w_mv.loc[valid]}
        bts = {k: run(p_sub, u, w, cost) for k, w in trio.items()}
        out["backtests"][u].update({f"ph_{k}": v for k, v in bts.items()})
        ph = {k: perf_table(v) for k, v in bts.items()}
        ph["start"], ph["end"] = str(p_sub.index[0].date()), str(p_sub.index[-1].date())
        ph["mean_variance_vs_vol_target"] = sharpe_difference_test(bts["mean_variance"]["net"], bts["vol_target"]["net"])
        ph["mean_variance_vs_constant"] = sharpe_difference_test(bts["mean_variance"]["net"], bts["constant"]["net"])
        ph["factor_alpha_mean_variance"] = factor_alpha(bts["mean_variance"]["net"], p_sub)
        ph["breakeven_c_base_bps_mean_variance"] = breakeven_cost_bps(p_sub, u, trio["mean_variance"], cost)
        ph["mean_variance_exposure"] = signals.exposure_summary(trio["mean_variance"])
        ph["mean_variance_scale"] = W[f"mean_variance_scale_{u}"]
        ph["by_year_mean_variance"] = by_year(bts["mean_variance"]["net"]).round(4).to_dict()
        ph["by_year_vol_target"] = by_year(bts["vol_target"]["net"]).round(4).to_dict()
        out["post_hoc"][u] = ph
    return out


def sensitivity_grid(panel: pd.DataFrame) -> pd.DataFrame:
    """The 36 pre-registered variants, all reported."""
    rows = []
    for universe in config.GRID_UNIVERSES:
        cost = cost_for(universe)
        for rule in config.GRID_RULES:
            for norm in config.GRID_NORMS:
                for cap in config.GRID_CAPS:
                    w = signals.regime(panel, cap=1.0) if rule == "regime" else signals.linear(panel, norm, cap)
                    p = perf_table(run(panel, universe, w, cost))
                    rows.append({"universe": universe, "rule": rule, "norm": norm, "cap": cap,
                                 "sharpe_net": p["sharpe_net"], "sharpe_gross": p["sharpe_gross"],
                                 "ann_return_net": p["ann_return_net"], "max_drawdown": p["max_drawdown"],
                                 "mean_exposure": p["mean_exposure"]})
    return pd.DataFrame(rows)


def cost_sensitivity_curve(panel: pd.DataFrame, universe: str, weights: dict) -> pd.DataFrame:
    rows = []
    for c in np.arange(0, 30.5, 1.0):
        cm = CostModel(c, config.TAU, config.COST_SCALES_WITH_VIX)
        row = {"c_base_bps": c}
        for k, w in weights.items():
            p = panel.loc[w.dropna().index]
            row[k] = perf_table(run(p, universe, w.dropna(), cm))["sharpe_net"]
        rows.append(row)
    return pd.DataFrame(rows)


def subperiod_analysis(panel_is: pd.DataFrame) -> dict:
    edges = vix_quintile_edges(panel_is)
    out = {}
    for name, (a, b) in SUBPERIODS.items():
        p = panel_is.loc[a:b]
        out[name] = {"start": str(p.index[0].date()), "end": str(p.index[-1].date()), "n_days": len(p),
                     "regression": {u: predictive_regression(p, u) for u in UNIVERSES},
                     "quintiles": {u: vix_quintile_table(p, u, edges).reset_index().to_dict(orient="records") for u in UNIVERSES},
                     "constant_sharpe_net": {u: perf_table(run(p, u, signals.constant(p), cost_for(u)))["sharpe_net"] for u in UNIVERSES}}
    return out


# ---------------------------------------------------------------------------
# drivers
# ---------------------------------------------------------------------------
def run_in_sample(panel_is: pd.DataFrame, out_dir: Path) -> dict:
    fig_dir, tab_dir = out_dir / "figures", out_dir / "tables"
    fig_dir.mkdir(parents=True, exist_ok=True)
    tab_dir.mkdir(parents=True, exist_ok=True)

    res = evaluate(panel_is, panel_is.index[0], config.IS_END, "in-sample")
    grid = sensitivity_grid(panel_is)
    grid.to_csv(tab_dir / "sensitivity_grid.csv", index=False)
    res["sensitivity_grid"] = grid.to_dict(orient="records")
    res["subperiods"] = subperiod_analysis(panel_is)

    n_trials = len(grid) + N_POST_HOC_TRIALS
    trial_sharpes = grid["sharpe_net"].tolist() + [res["post_hoc"][u][k]["sharpe_net"] for u in UNIVERSES for k in ("vol_target", "mean_variance")]
    res["n_trials_total"] = n_trials
    for u in UNIVERSES:
        s = res["strategies"][u]["timed"]
        res[f"deflated_sharpe_headline_{u}"] = deflated_sharpe(s["sharpe_net"], n_trials, trial_sharpes, s["n_days"], s["skew"], s["kurtosis_excess"])
        m = res["post_hoc"][u]["mean_variance"]
        res[f"deflated_sharpe_mean_variance_{u}"] = deflated_sharpe(m["sharpe_net"], n_trials, trial_sharpes, m["n_days"], m["skew"], m["kurtosis_excess"])

    W = all_weights(panel_is)
    curve = cost_sensitivity_curve(panel_is, "big_rev", {"timed": W["headline"], "constant": W["constant"],
                                                          "mean_variance": W["mean_variance_big_rev"]})
    curve.to_csv(tab_dir / "cost_curve_big_rev.csv", index=False)
    for u in UNIVERSES:
        vix_quintile_table(panel_is, u).to_csv(tab_dir / f"quintiles_{u}.csv", float_format="%.4f")
    pd.DataFrame({(u, k): v for u, s in res["strategies"].items() for k, v in s.items() if isinstance(v, dict) and "sharpe_net" in v}
                 ).to_csv(tab_dir / "performance_in_sample.csv", float_format="%.4f")
    pd.DataFrame({(u, k): v for u, s in res["post_hoc"].items() for k, v in s.items() if isinstance(v, dict) and "sharpe_net" in v}
                 ).to_csv(tab_dir / "post_hoc_in_sample.csv", float_format="%.4f")

    B = res["backtests"]
    plots.equity_curves(B["big_rev"]["timed"], B["big_rev"]["constant"], "Big-cap reversal leg, net of costs (in-sample)", fig_dir / "equity_big_rev.png")
    plots.equity_curves(B["st_rev"]["timed"], B["st_rev"]["constant"], "ST_Rev factor, net of costs (in-sample)", fig_dir / "equity_st_rev.png")
    plots.quintile_bars(vix_quintile_table(panel_is, "st_rev"), vix_quintile_table(panel_is, "big_rev"), fig_dir / "quintiles.png")
    plots.yearly_bars(by_year(B["big_rev"]["timed"]["net"]), by_year(B["big_rev"]["constant"]["net"]), "Big-cap leg: net return by year (in-sample)", fig_dir / "by_year_big_rev.png")
    plots.sensitivity_heatmap(grid, "big_rev", fig_dir / "sensitivity_big_rev.png")
    plots.sensitivity_heatmap(grid, "st_rev", fig_dir / "sensitivity_st_rev.png")
    plots.cost_curve(curve, fig_dir / "cost_curve_big_rev.png")
    plots.rolling_sharpe_plot(B["big_rev"]["timed"], B["big_rev"]["constant"], fig_dir / "rolling_sharpe_big_rev.png")
    plots.exposure_and_vix(B["big_rev"]["timed"], panel_is, fig_dir / "exposure.png")
    for u in UNIVERSES:
        plots.post_hoc_curves({k: B[u][f"ph_{k}"] for k in ("constant", "vol_target", "mean_variance")},
                              f"Post-hoc risk-aware sizing, {UNIVERSE_LABEL[u]}, net (in-sample)", fig_dir / f"post_hoc_{u}.png")

    res.pop("backtests")
    res["generated_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    (out_dir / "in_sample.json").write_text(json.dumps(_json(res), indent=1))
    return res


def run_out_of_sample(panel_full: pd.DataFrame, out_dir: Path) -> dict:
    """Evaluated ONCE. Weights use only history before each day; the
    mean-variance scale constant is the in-sample one."""
    fig_dir = out_dir / "figures"
    panel_is = panel_full.loc[: config.IS_END]
    res = evaluate(panel_full, config.OOS_START, config.OOS_END, "out-of-sample", is_edges=vix_quintile_edges(panel_is))
    is_res = evaluate(panel_is, panel_full.index[0], config.IS_END, "in-sample")
    for u in UNIVERSES:
        plots.equity_curves(is_res["backtests"][u]["timed"], is_res["backtests"][u]["constant"],
                            f"{UNIVERSE_LABEL[u]}, net of costs: in-sample and out-of-sample", fig_dir / f"equity_{u}_with_oos.png",
                            oos_timed=res["backtests"][u]["timed"], oos_const=res["backtests"][u]["constant"])
        plots.post_hoc_curves({k: res["backtests"][u][f"ph_{k}"] for k in ("constant", "vol_target", "mean_variance")},
                              f"Out-of-sample, {UNIVERSE_LABEL[u]}: constant vs vol-target vs mean-variance (net)", fig_dir / f"oos_post_hoc_{u}.png", log=False)
    full_res = evaluate(panel_full, panel_full.index[0], config.OOS_END, "full-sample")
    plots.yearly_bars(by_year(full_res["backtests"]["big_rev"]["timed"]["net"]), by_year(full_res["backtests"]["big_rev"]["constant"]["net"]),
                      "Big-cap leg: net return by year (full sample; last two years are out-of-sample)", fig_dir / "by_year_big_rev_full.png")
    res.pop("backtests")
    res["evaluated_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    res["note"] = "Single evaluation of the pre-registered rule (and the disclosed post-hoc rules) on the held-out period. Nothing was changed after this run."
    (out_dir / "out_of_sample.json").write_text(json.dumps(_json(res), indent=1))
    return res
