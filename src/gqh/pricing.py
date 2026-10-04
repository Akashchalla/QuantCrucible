"""Module C — price of risk vs quantity of risk (HYPOTHESIS_C.md).

Decomposes lagged VIX² into realised variance (quantity of risk the liquidity
provider must hold) and the variance risk premium (price paid for holding it),
and asks which one the reversal premium loads on. Adds the VIX term structure
as an independent stress proxy. The books are exactly those of Modules A and B;
only the state variable that switches them on changes.

Units: VIX is annualised vol in %, so VIX² and RV are annualised variance in %²
(VIX 20 -> 400). RV_{t-1} = 252 × mean of (100·r_mkt)² over the window ending t-1.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from . import config, gapfade, signals
from .backtest import run as run_a
from .data import PROCESSED, lag_asof
from .metrics import TD, by_year, nw_regression, perf_table, sharpe, sharpe_difference_test
from .plots import C_CONST, C_GROSS, C_OOS, C_TIMED, _save
from .study import cost_for

RV_WINDOWS = (21, 63)
RULES = ("vrp_median", "vrp_pos", "backwardation")
BOOKS = ("big_rev", "st_rev", "gapfade")
TS_START = pd.Timestamp("2008-01-01")   # VIX3M begins 2007-12-04; a month of history first
N_VARIANTS = len(RV_WINDOWS) * len(RULES) * len(BOOKS)
BOOK_LABEL = {"big_rev": "big-cap reversal leg", "st_rev": "ST_Rev factor", "gapfade": "gap fade (quintile)"}
RULE_LABEL = {"constant": "constant / always-on", "vix_rule": "VIX rule (A: regime, B: VIX≥20)",
              "vrp_median": "VRP > trailing median", "vrp_pos": "VRP > 0", "backwardation": "VIX > VIX3M"}


# ---------------------------------------------------------------------------
# state variables (all dated so that the value on row t is known before t)
# ---------------------------------------------------------------------------
def load_vix3m() -> pd.Series:
    p = PROCESSED / "vix3m_daily.csv"
    if not p.exists():
        raise FileNotFoundError("run `python data/download.py` first")
    return pd.read_csv(p, index_col="date", parse_dates=True)["vix3m"]


def state_variables(panel_a: pd.DataFrame) -> pd.DataFrame:
    """Columns: vix2_lag, rv21_lag, vrp21_lag, vrp21_median, rv63_lag, vrp63_lag, vrp63_median,
    vix3m_lag, ts_ratio_lag. Built on Module A's (French) calendar."""
    out = pd.DataFrame(index=panel_a.index)
    out["vix2_lag"] = panel_a["vix_lag"] ** 2
    sq = (100.0 * panel_a["mkt_rf"]) ** 2
    for w in RV_WINDOWS:
        rv = (TD * sq.rolling(w).mean()).shift(1)            # window ends at t-1
        out[f"rv{w}_lag"] = rv
        out[f"vrp{w}_lag"] = out["vix2_lag"] - rv
        out[f"vrp{w}_median"] = out[f"vrp{w}_lag"].rolling(config.REGIME_WINDOW, min_periods=config.REGIME_WINDOW // 2).median()
    out["vix3m_lag"] = lag_asof(load_vix3m(), panel_a.index, "vix3m")
    out["ts_ratio_lag"] = panel_a["vix_lag"] / out["vix3m_lag"]
    return out


def attach_states(panel: pd.DataFrame, states: pd.DataFrame) -> pd.DataFrame:
    """Join states onto any daily panel. Dates missing from the state calendar take the
    last earlier state (still strictly lagged)."""
    return panel.join(states.reindex(panel.index, method="ffill"))


def participation(panel: pd.DataFrame, rule: str, window: int = 21) -> pd.Series:
    """0/1 series; days where the state is undefined are OFF (reported via share_days_on)."""
    if rule == "constant":
        return pd.Series(1.0, index=panel.index)
    if rule == "vrp_median":
        on = panel[f"vrp{window}_lag"] > panel[f"vrp{window}_median"]
    elif rule == "vrp_pos":
        on = panel[f"vrp{window}_lag"] > 0
    elif rule == "backwardation":
        on = panel["ts_ratio_lag"] > 1.0
    else:
        raise ValueError(rule)
    return on.fillna(False).astype(float)


# ---------------------------------------------------------------------------
# backtests on the existing books
# ---------------------------------------------------------------------------
def backtest(book: str, panel: pd.DataFrame, w: pd.Series) -> pd.DataFrame:
    if book == "gapfade":
        return gapfade.run(panel, "quintile", w)
    return run_a(panel, book, w, cost_for(book))


def perf(book: str, bt: pd.DataFrame) -> dict:
    p = gapfade.perf(bt) if book == "gapfade" else perf_table(bt)
    on = bt["w"] > 0
    p["share_days_on"] = float(on.mean())
    p["mean_net_bps"] = float(bt["net"].mean() * 1e4)
    p["t_mean_net_nw"] = nw_regression(bt["net"] * 1e4, pd.DataFrame(index=bt.index))["t_const"]
    return p


def vix_rule_weights(book: str, panel: pd.DataFrame) -> pd.Series:
    """The Module A / B VIX-level rule each book was pre-registered with."""
    if book == "gapfade":
        return gapfade.participation(panel, gapfade.VIX_THRESHOLD)
    return signals.regime(panel)


# ---------------------------------------------------------------------------
# hypothesis tests
# ---------------------------------------------------------------------------
def c1_decomposition(panel: pd.DataFrame, ret_col: str, window: int = 21) -> dict:
    """r_t (bps) on VRP_{t-1} and RV_{t-1}, both in units of 100 %² (VIX 20 = 4 units)."""
    X = pd.DataFrame({"vrp": panel[f"vrp{window}_lag"] / 100.0, "rv": panel[f"rv{window}_lag"] / 100.0})
    r = nw_regression(panel[ret_col] * 1e4, X)
    single = nw_regression(panel[ret_col] * 1e4, pd.DataFrame({"vix2": panel["vix2_lag"] / 100.0}))
    return {"n": r["n"], "r2": r["r2"],
            "b_vrp_bps_per_100var": r["coef_vrp"], "t_vrp_nw": r["t_vrp"],
            "b_rv_bps_per_100var": r["coef_rv"], "t_rv_nw": r["t_rv"],
            "b_vix2_alone": single["coef_vix2"], "t_vix2_alone": single["t_vix2"]}


def c2_double_sort(panel: pd.DataFrame, ret_col: str, window: int = 21) -> dict:
    """RV terciles, then VRP terciles within each. Sharpe and mean per cell."""
    df = panel[[ret_col, f"rv{window}_lag", f"vrp{window}_lag"]].dropna().copy()
    df["rv_t"] = pd.qcut(df[f"rv{window}_lag"], 3, labels=[1, 2, 3])
    df["vrp_t"] = df.groupby("rv_t", observed=True)[f"vrp{window}_lag"].transform(lambda s: pd.qcut(s, 3, labels=[1, 2, 3]))
    g = df.groupby(["rv_t", "vrp_t"], observed=True)[ret_col]
    sr = (g.mean() / g.std(ddof=1) * np.sqrt(TD)).unstack("vrp_t")
    mean_bps = (g.mean() * 1e4).unstack("vrp_t")
    vol = (g.std(ddof=1) * np.sqrt(TD)).unstack("vrp_t")
    n = g.count().unstack("vrp_t")
    # reverse sort: VRP terciles first, RV within
    df["vrp_t2"] = pd.qcut(df[f"vrp{window}_lag"], 3, labels=[1, 2, 3])
    df["rv_t2"] = df.groupby("vrp_t2", observed=True)[f"rv{window}_lag"].transform(lambda s: pd.qcut(s, 3, labels=[1, 2, 3]))
    g2 = df.groupby(["vrp_t2", "rv_t2"], observed=True)[ret_col]
    sr_rev = (g2.mean() / g2.std(ddof=1) * np.sqrt(TD)).unstack("rv_t2")
    return {
        "sharpe_by_rv_then_vrp": sr.round(3).to_dict(orient="index"),
        "mean_bps_by_rv_then_vrp": mean_bps.round(2).to_dict(orient="index"),
        "ann_vol_by_rv_then_vrp": vol.round(3).to_dict(orient="index"),
        "n_by_rv_then_vrp": n.to_dict(orient="index"),
        "rv_terciles_where_high_vrp_beats_low": int((sr[3] > sr[1]).sum()),
        "sharpe_by_vrp_then_rv": sr_rev.round(3).to_dict(orient="index"),
        "vrp_terciles_where_high_rv_beats_low": int((sr_rev[3] > sr_rev[1]).sum()),
        "_sr": sr, "_sr_rev": sr_rev,
    }


def rule_comparison(book: str, panel: pd.DataFrame, window: int = 21) -> tuple[dict, dict]:
    """C3/C4: every rule on the same book, same days, net of the book's costs."""
    bts = {"constant": backtest(book, panel, participation(panel, "constant")),
           "vix_rule": backtest(book, panel, vix_rule_weights(book, panel))}
    for rule in RULES:
        p = panel if rule != "backwardation" else panel.loc[TS_START:]
        if len(p) == 0:
            continue
        bts[rule] = backtest(book, p, participation(p, rule, window))
    res = {k: perf(book, v) for k, v in bts.items()}
    for rule in RULES:
        if rule not in bts:
            continue
        idx = bts[rule].index
        res[f"{rule}_vs_constant"] = sharpe_difference_test(bts[rule]["net"], bts["constant"]["net"].loc[idx])
        res[f"{rule}_vs_vix_rule"] = sharpe_difference_test(bts[rule]["net"], bts["vix_rule"]["net"].loc[idx])
        if rule == "backwardation":  # C4 compares against constant over the SAME 2008+ days
            res["constant_2008_on"] = perf(book, bts["constant"].loc[idx])
            res["vix_rule_2008_on"] = perf(book, bts["vix_rule"].loc[idx])
    res["by_year"] = {k: {int(y): float(v) for y, v in by_year(bts[k]["net"]).items()} for k in ("constant", "vix_rule", "vrp_median")}
    return res, bts


def variant_grid(panels: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for book, panel in panels.items():
        for window in RV_WINDOWS:
            for rule in RULES:
                p = panel if rule != "backwardation" else panel.loc[TS_START:]
                bt = backtest(book, p, participation(p, rule, window))
                pf = perf(book, bt)
                const = perf(book, backtest(book, p, participation(p, "constant")))
                rows.append({"book": book, "rv_window": window, "rule": rule, "sharpe_net": pf["sharpe_net"],
                             "sharpe_net_constant_same_days": const["sharpe_net"], "ann_return_net": pf["ann_return_net"],
                             "share_days_on": pf["share_days_on"], "n_days": pf["n_days"]})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# figures
# ---------------------------------------------------------------------------
def fig_double_sort(sr_big: pd.DataFrame, sr_strev: pd.DataFrame, path: Path):
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 2.0))
    for ax, sr, title in ((axes[0], sr_big, "big-cap reversal leg"), (axes[1], sr_strev, "ST_Rev factor")):
        im = ax.imshow(sr.values, cmap="RdYlGn", vmin=-1.5, vmax=1.5, aspect="auto", origin="lower")
        for i in range(3):
            for j in range(3):
                ax.text(j, i, f"{sr.values[i, j]:.2f}", ha="center", va="center", fontsize=8)
        ax.set_xticks(range(3), ["low", "mid", "high"]); ax.set_xlabel("VRP tercile (price of risk), within RV tercile")
        ax.set_yticks(range(3), ["low", "mid", "high"]); ax.set_ylabel("realised-variance tercile")
        ax.set_title(f"Ann. Sharpe, {title}", loc="left", fontsize=9); ax.grid(False)
    _save(fig, path)


def fig_equity(bts_is: dict, book: str, path: Path, bts_oos: dict | None = None):
    fig, ax = plt.subplots(figsize=(7.2, 2.2))
    def eq(s, start=1.0): return start * (1 + s).cumprod()
    series = (("constant", C_CONST, 1.0, "constant / always-on, net"), ("vix_rule", C_GROSS, 1.0, "VIX-level rule, net"),
              ("vrp_median", C_TIMED, 1.4, "VRP > trailing median, net"))
    for k, col, lw, lab in series:
        ax.plot(eq(bts_is[k]["net"]), color=col, lw=lw, label=lab, ls="--" if k == "vix_rule" else "-")
        if bts_oos is not None:
            ax.plot(eq(bts_oos[k]["net"], eq(bts_is[k]["net"]).iloc[-1]), color=col, lw=lw, ls="--" if k == "vix_rule" else "-")
    if bts_oos is not None:
        ax.axvspan(config.OOS_START, bts_oos["constant"].index[-1], color=C_OOS, alpha=0.12)
        ax.annotate("out-of-sample", xy=(config.OOS_START, 0.04), xycoords=("data", "axes fraction"), color=C_OOS,
                    fontsize=8, ha="right", va="bottom", xytext=(-3, 0), textcoords="offset points")
    ax.set_yscale("log"); ax.set_ylabel("growth of $1 (log)")
    ax.set_title(f"{BOOK_LABEL[book]}: which state variable to switch on", loc="left", fontsize=10)
    ax.legend(loc="upper left", frameon=False, fontsize=8)
    _save(fig, path)


# ---------------------------------------------------------------------------
# entry points
# ---------------------------------------------------------------------------
def _json(obj):
    if isinstance(obj, dict):
        return {str(k): _json(v) for k, v in obj.items() if not str(k).startswith("_")}
    if isinstance(obj, (list, tuple)):
        return [_json(v) for v in obj]
    if isinstance(obj, (np.floating, float)):
        return None if np.isnan(obj) else float(obj)
    if isinstance(obj, (np.integer, np.bool_)):
        return obj.item()
    if isinstance(obj, pd.Timestamp):
        return str(obj.date())
    return obj


def build_panels(panel_a_full: pd.DataFrame, panel_b_full: pd.DataFrame | None) -> dict[str, pd.DataFrame]:
    states = state_variables(panel_a_full)
    pa = attach_states(panel_a_full, states)
    panels = {"big_rev": pa, "st_rev": pa}
    if panel_b_full is not None:
        panels["gapfade"] = attach_states(panel_b_full, states)
    return panels


def _slice(panels: dict, start, end) -> dict:
    return {k: v.loc[start:end] for k, v in panels.items()}


def evaluate(panels: dict, label: str) -> tuple[dict, dict]:
    out = {"label": label, "c1": {}, "c2": {}, "rules": {}}
    bts_all = {}
    for book, panel in panels.items():
        ret_col = "spread_q" if book == "gapfade" else book
        out["c1"][book] = {str(w): c1_decomposition(panel, ret_col, w) for w in RV_WINDOWS}
        out["c2"][book] = c2_double_sort(panel, ret_col)
        out["rules"][book], bts_all[book] = rule_comparison(book, panel)
    out["grid"] = variant_grid(panels).to_dict(orient="records")
    return out, bts_all


def run_in_sample(panels_full: dict, out_dir: Path) -> dict:
    tables, figures = out_dir / "tables", out_dir / "figures"
    tables.mkdir(parents=True, exist_ok=True)
    panels_is = _slice(panels_full, None, config.IS_END)
    res, bts = evaluate(panels_is, "in-sample")
    res.update({"module": "C: price of risk vs quantity of risk", "n_variants": N_VARIANTS,
                "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "start": {k: str(v.index[0].date()) for k, v in panels_is.items()},
                "end": {k: str(v.index[-1].date()) for k, v in panels_is.items()}})
    pd.DataFrame(res["grid"]).to_csv(tables / "pricing_variant_grid.csv", index=False)
    fig_double_sort(res["c2"]["big_rev"]["_sr"], res["c2"]["st_rev"]["_sr"], figures / "pricing_double_sort.png")
    fig_equity(bts["big_rev"], "big_rev", figures / "pricing_equity_big_rev_is.png")
    (out_dir / "pricing_in_sample.json").write_text(json.dumps(_json(res), indent=2))
    return res


def run_out_of_sample(panels_full: dict, out_dir: Path) -> dict:
    tables, figures = out_dir / "tables", out_dir / "figures"
    panels_oos = _slice(panels_full, config.OOS_START, config.OOS_END)
    panels_is = _slice(panels_full, None, config.IS_END)
    res, bts = evaluate(panels_oos, "out-of-sample (evaluated once)")
    _, bts_is = evaluate(panels_is, "in-sample")
    res.update({"module": "C: price of risk vs quantity of risk",
                "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "start": {k: str(v.index[0].date()) for k, v in panels_oos.items()},
                "end": {k: str(v.index[-1].date()) for k, v in panels_oos.items()}})
    pd.DataFrame(res["grid"]).to_csv(tables / "pricing_variant_grid_oos.csv", index=False)
    for book in ("big_rev", "gapfade"):
        if book in bts:
            fig_equity(bts_is[book], book, figures / f"pricing_equity_{book}_full.png", bts_oos=bts[book])
    (out_dir / "pricing_out_of_sample.json").write_text(json.dumps(_json(res), indent=2))
    return res
