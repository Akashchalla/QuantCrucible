"""Module B — opening-auction gap fade in large caps (HYPOTHESIS_B.md).

Everything here was specified in HYPOTHESIS_B.md before any single-stock price
was downloaded. The only data-cleaning rule not in that file is the |gap| > 20%
exclusion (corporate-action artefacts such as spin-offs in adjusted prices),
which uses information known at the open only, and whose effect is reported.

Per stock i, day t (all adjusted prices):
    gap     = Open_t / Close_{t-1} - 1
    relgap  = gap - cross-sectional median gap
    r_oc    = Close_t / Open_t - 1
Portfolio: equal-weighted quintiles (or deciles) on relgap; spread = Q1 - Q5.
Book: $1 per side, entered at the open, exited at the close, so 4 dollars are
traded per day per $1-per-side and there is never an overnight position.
Rule: participate on day t iff VIX_{t-1} >= threshold (headline 20).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from . import config
from .data import PROCESSED, lag_asof, load_vix
from .metrics import (TD, by_year, max_drawdown, nw_regression, sharpe, sharpe_difference_test,
                      vix_quintile_edges, vix_quintile_table)
from .plots import C_CONST, C_GROSS, C_OOS, C_TIMED, _save

ROOT = Path(__file__).resolve().parents[2]
CONSTITUENTS = ROOT / "data" / "sp500_constituents.csv"

# ---- pre-registered constants (HYPOTHESIS_B.md) ---------------------------
B_SAMPLE_START = pd.Timestamp("2005-01-03")
MIN_NAMES = 100
VIX_THRESHOLD = 20.0
C_BASE_BPS = 5.0
DOLLARS_TRADED_PER_DAY = 4.0          # buy+sell each of two $1 legs
GAP_FILTER = 0.20                      # data cleaning, known at the open
GRID_THRESHOLDS = (15.0, 20.0, 25.0)
GRID_SORTS = ("quintile", "decile")
GRID_COSTS = (2.5, 5.0, 10.0)
N_VARIANTS = len(GRID_THRESHOLDS) * len(GRID_SORTS) * len(GRID_COSTS) + len(GRID_SORTS) * len(GRID_COSTS)


# ---------------------------------------------------------------------------
# data
# ---------------------------------------------------------------------------
def load_prices() -> tuple[pd.DataFrame, pd.DataFrame]:
    o, c = PROCESSED / "stocks_open.csv.gz", PROCESSED / "stocks_close.csv.gz"
    if not (o.exists() and c.exists()):
        raise FileNotFoundError("run `python data/download_stocks.py` first")
    opn = pd.read_csv(o, index_col="date", parse_dates=True)
    cls = pd.read_csv(c, index_col="date", parse_dates=True)
    return opn, cls


def membership_mask(index: pd.DatetimeIndex, columns: pd.Index) -> pd.DataFrame:
    """True where the stock was already an index member on that date (point-in-time inclusion)."""
    cons = pd.read_csv(CONSTITUENTS, parse_dates=["date_added"]).set_index("yahoo_symbol")["date_added"]
    added = cons.reindex(columns)
    dates = np.asarray(index.values)[:, None]
    return pd.DataFrame(dates >= added.values[None, :], index=index, columns=columns)


def _bucket_means(values: pd.DataFrame, relgap: pd.DataFrame, n_buckets: int) -> tuple[pd.Series, pd.Series]:
    """Equal-weighted mean of `values` in the bottom and top relgap bucket, per day."""
    pct = relgap.rank(axis=1, pct=True)                       # NaNs stay NaN
    lo = values.where(pct <= 1.0 / n_buckets).mean(axis=1)
    hi = values.where(pct > 1.0 - 1.0 / n_buckets).mean(axis=1)
    return lo, hi


def build_gap_panel(start: pd.Timestamp = B_SAMPLE_START, end: pd.Timestamp = config.OOS_END,
                    gap_filter: float | None = GAP_FILTER) -> pd.DataFrame:
    """Daily series of the gap-fade portfolios plus lagged VIX.

    Columns: q1, q5, d1, d10 (open-to-close returns of the extreme buckets),
    ew (equal-weighted universe open-to-close), spread_q = q1 - q5,
    spread_d = d1 - d10, mkt_gap (median gap), n (eligible names), vix_lag.
    """
    opn, cls = load_prices()
    gap = opn / cls.shift(1) - 1.0
    r_oc = cls / opn - 1.0
    eligible = membership_mask(opn.index, opn.columns) & gap.notna() & r_oc.notna()
    if gap_filter is not None:
        eligible &= gap.abs() <= gap_filter
    gap = gap.where(eligible)
    r_oc = r_oc.where(eligible)
    relgap = gap.sub(gap.median(axis=1), axis=0)

    q1, q5 = _bucket_means(r_oc, relgap, 5)
    d1, d10 = _bucket_means(r_oc, relgap, 10)
    panel = pd.DataFrame({
        "q1": q1, "q5": q5, "d1": d1, "d10": d10,
        "ew": r_oc.mean(axis=1),
        "mkt_gap": gap.median(axis=1),
        "n": eligible.sum(axis=1),
    })
    panel["spread_q"] = panel["q1"] - panel["q5"]
    panel["spread_d"] = panel["d1"] - panel["d10"]
    panel = panel.loc[(panel.index >= start) & (panel.index <= end)]
    panel = panel[panel["n"] >= MIN_NAMES]
    panel["vix_lag"] = lag_asof(load_vix(), panel.index, "vix")
    panel = panel.dropna(subset=["vix_lag", "spread_q"])
    panel.index.name = "date"
    return panel


def split(panel: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    return panel.loc[: config.IS_END], panel.loc[config.OOS_START: config.OOS_END]


# ---------------------------------------------------------------------------
# backtest
# ---------------------------------------------------------------------------
def participation(panel: pd.DataFrame, threshold: float | None) -> pd.Series:
    """1 on days with VIX_{t-1} >= threshold; always 1 if threshold is None."""
    if threshold is None:
        return pd.Series(1.0, index=panel.index)
    return (panel["vix_lag"] >= threshold).astype(float)


def run(panel: pd.DataFrame, sort: str, part: pd.Series, c_base_bps: float = C_BASE_BPS) -> pd.DataFrame:
    spread = panel["spread_q" if sort == "quintile" else "spread_d"]
    part = part.reindex(panel.index).astype(float)
    c = c_base_bps * 1e-4 * panel["vix_lag"] / config.VIX_NORM
    traded = DOLLARS_TRADED_PER_DAY * part
    gross = part * spread
    cost = traded * c
    out = pd.DataFrame({"w": part, "gross": gross, "cost": cost, "net": gross - cost,
                        "traded": traded, "underlying": spread})
    out.index.name = "date"
    return out


def perf(bt: pd.DataFrame) -> dict:
    net = bt["net"]
    on = bt["w"] > 0
    monthly = (1 + net).resample("ME").prod() - 1
    years = len(net) / TD
    mean_test = nw_regression(net * 1e4, pd.DataFrame(index=net.index))
    return {
        "ann_return_net": float(net.mean() * TD),
        "ann_return_gross": float(bt["gross"].mean() * TD),
        "ann_cost_drag": float(bt["cost"].mean() * TD),
        "ann_vol": float(net.std(ddof=1) * np.sqrt(TD)),
        "sharpe_net": sharpe(net),
        "sharpe_gross": sharpe(bt["gross"]),
        "mean_net_bps": float(net.mean() * 1e4),
        "t_mean_net_nw": mean_test["t_const"],
        "mean_net_bps_on_days": float(net[on].mean() * 1e4) if on.any() else float("nan"),
        "max_drawdown": max_drawdown(net),
        "worst_month": float(monthly.min()),
        "worst_day": float(net.min()),
        "hit_rate_on_days": float((net[on] > 0).mean()) if on.any() else float("nan"),
        "share_days_on": float(on.mean()),
        "n_days_on": int(on.sum()),
        "n_days": int(len(net)),
        "start": str(net.index[0].date()),
        "end": str(net.index[-1].date()),
    }


def breakeven_cost_bps(panel: pd.DataFrame, sort: str, part: pd.Series) -> float:
    """c_base at which the net mean is zero (net mean is linear in c_base)."""
    g = run(panel, sort, part, 0.0)
    cost_per_bp = (run(panel, sort, part, 1.0)["cost"]).mean()
    return float(g["gross"].mean() / cost_per_bp) if cost_per_bp > 0 else float("inf")


# ---------------------------------------------------------------------------
# study
# ---------------------------------------------------------------------------
def _json(obj):
    if isinstance(obj, dict):
        return {str(k): _json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json(v) for v in obj]
    if isinstance(obj, (np.floating, float)):
        return None if np.isnan(obj) else float(obj)
    if isinstance(obj, (np.integer, np.bool_)):
        return obj.item()
    if isinstance(obj, pd.Timestamp):
        return str(obj.date())
    return obj


def hypothesis_tests(panel: pd.DataFrame, is_edges: np.ndarray | None = None) -> dict:
    y = panel["spread_q"] * 1e4
    b1 = nw_regression(y, pd.DataFrame(index=y.index))
    b2 = nw_regression(y, panel[["vix_lag"]])
    qt = vix_quintile_table(panel, "spread_q", is_edges)
    legs = {
        "long_leg_excess_bps": nw_regression((panel["q1"] - panel["ew"]) * 1e4, pd.DataFrame(index=y.index)),
        "short_leg_excess_bps": nw_regression((panel["q5"] - panel["ew"]) * 1e4, pd.DataFrame(index=y.index)),
    }
    legs_by_vix = pd.DataFrame({
        "long_leg_excess_bps": ((panel["q1"] - panel["ew"]) * 1e4).groupby(pd.qcut(panel["vix_lag"], 5, labels=[1, 2, 3, 4, 5]) if is_edges is None else _cut(panel["vix_lag"], is_edges), observed=True).mean(),
        "short_leg_excess_bps": ((panel["q5"] - panel["ew"]) * 1e4).groupby(pd.qcut(panel["vix_lag"], 5, labels=[1, 2, 3, 4, 5]) if is_edges is None else _cut(panel["vix_lag"], is_edges), observed=True).mean(),
    })
    return {
        "B1_gross_spread": {"mean_bps": b1["coef_const"], "t_nw": b1["t_const"], "n": b1["n"],
                            "ann_sharpe_gross": sharpe(panel["spread_q"])},
        "B2_slope_on_vix": {"alpha_bps": b2["coef_const"], "slope_bps_per_vix_pt": b2["coef_vix_lag"],
                            "t_slope_nw": b2["t_vix_lag"], "p_slope": b2["p_vix_lag"], "r2": b2["r2"]},
        "B2_vix_quintiles": qt.reset_index().to_dict(orient="records"),
        "B4_legs": {k: {"mean_bps": v["coef_const"], "t_nw": v["t_const"]} for k, v in legs.items()},
        "B4_legs_by_vix_quintile": legs_by_vix.reset_index().to_dict(orient="records"),
        "market_gap_abs_mean_bps": float(panel["mkt_gap"].abs().mean() * 1e4),
        "mean_names_per_day": float(panel["n"].mean()),
    }


def _cut(x: pd.Series, edges: np.ndarray) -> pd.Series:
    e = edges.copy(); e[0], e[-1] = -np.inf, np.inf
    return pd.cut(x, e, labels=[1, 2, 3, 4, 5])


def strategies(panel: pd.DataFrame) -> tuple[dict, dict]:
    bts = {
        "always_on": run(panel, "quintile", participation(panel, None)),
        "participation": run(panel, "quintile", participation(panel, VIX_THRESHOLD)),
    }
    res = {k: perf(v) for k, v in bts.items()}
    res["B3_participation_vs_always_on"] = sharpe_difference_test(bts["participation"]["net"], bts["always_on"]["net"])
    res["breakeven_c_base_bps_always_on"] = breakeven_cost_bps(panel, "quintile", participation(panel, None))
    res["breakeven_c_base_bps_participation"] = breakeven_cost_bps(panel, "quintile", participation(panel, VIX_THRESHOLD))
    res["by_year_participation_net"] = {int(k): float(v) for k, v in by_year(bts["participation"]["net"]).items()}
    res["by_year_always_on_net"] = {int(k): float(v) for k, v in by_year(bts["always_on"]["net"]).items()}
    return res, bts


def sensitivity_grid(panel: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for sort in GRID_SORTS:
        for c in GRID_COSTS:
            for thr in (None, *GRID_THRESHOLDS):
                p = perf(run(panel, sort, participation(panel, thr), c))
                rows.append({"sort": sort, "c_base_bps": c, "threshold": "always on" if thr is None else thr,
                             "sharpe_net": p["sharpe_net"], "ann_return_net": p["ann_return_net"],
                             "mean_net_bps": p["mean_net_bps"], "t_mean_net_nw": p["t_mean_net_nw"],
                             "share_days_on": p["share_days_on"]})
    return pd.DataFrame(rows)


SUBPERIODS = {"2005-2012": ("2005-01-01", "2012-12-31"), "2013-2024": ("2013-01-01", "2024-08-31")}


def subperiod_analysis(panel_is: pd.DataFrame) -> dict:
    """Descriptive, decided after seeing the by-year table: has the premium decayed?"""
    out = {}
    for label, (a, b) in SUBPERIODS.items():
        sub = panel_is.loc[a:b]
        y = sub["spread_q"] * 1e4
        b1 = nw_regression(y, pd.DataFrame(index=y.index))
        b2 = nw_regression(y, sub[["vix_lag"]])
        strat, _ = strategies(sub)
        q = vix_quintile_table(sub, "spread_q")
        out[label] = {"n_days": int(len(sub)), "gross_mean_bps": b1["coef_const"], "t_nw": b1["t_const"],
                      "slope_bps_per_vix_pt": b2["coef_vix_lag"], "t_slope_nw": b2["t_vix_lag"],
                      "vix_q1_mean_bps": float(q["mean_bps"].iloc[0]), "vix_q5_mean_bps": float(q["mean_bps"].iloc[-1]),
                      "sharpe_net_always_on": strat["always_on"]["sharpe_net"],
                      "sharpe_net_participation": strat["participation"]["sharpe_net"],
                      "breakeven_c_base_bps_always_on": strat["breakeven_c_base_bps_always_on"],
                      "breakeven_c_base_bps_participation": strat["breakeven_c_base_bps_participation"]}
    return out


def unfiltered_robustness(start, end) -> dict:
    """Headline numbers without the |gap| > 20% cleaning rule."""
    p = build_gap_panel(start, end, gap_filter=None)
    res, _ = strategies(p)
    b1 = nw_regression(p["spread_q"] * 1e4, pd.DataFrame(index=p.index))
    return {"gross_spread_mean_bps": b1["coef_const"], "t_nw": b1["t_const"],
            "sharpe_net_always_on": res["always_on"]["sharpe_net"],
            "sharpe_net_participation": res["participation"]["sharpe_net"]}


# ---------------------------------------------------------------------------
# figures
# ---------------------------------------------------------------------------
def fig_equity(bts: dict, path: Path, oos_bts: dict | None = None):
    fig, ax = plt.subplots(figsize=(7.2, 2.2))
    def eq(s, start=1.0): return start * (1 + s).cumprod()
    ax.plot(eq(bts["always_on"]["gross"]), color=C_GROSS, lw=0.9, ls="--", label="always on, gross")
    ax.plot(eq(bts["always_on"]["net"]), color=C_CONST, lw=1.1, label="always on, net")
    ax.plot(eq(bts["participation"]["net"]), color=C_TIMED, lw=1.4, label="VIX≥20 participation, net")
    if oos_bts is not None:
        for k, col, lw in (("always_on", C_CONST, 1.1), ("participation", C_TIMED, 1.4)):
            ax.plot(eq(oos_bts[k]["net"], eq(bts[k]["net"]).iloc[-1]), color=col, lw=lw)
        ax.plot(eq(oos_bts["always_on"]["gross"], eq(bts["always_on"]["gross"]).iloc[-1]), color=C_GROSS, lw=0.9, ls="--")
        ax.axvspan(config.OOS_START, oos_bts["participation"].index[-1], color=C_OOS, alpha=0.12)
        ax.annotate("out-of-sample", xy=(config.OOS_START, 0.04), xycoords=("data", "axes fraction"), color=C_OOS,
                    fontsize=8, ha="right", va="bottom", xytext=(-3, 0), textcoords="offset points")
    else:
        ax.axvline(config.IS_END, color=C_OOS, lw=1, ls=":")
    ax.set_yscale("log"); ax.set_ylabel("growth of $1 (log)")
    ax.set_title("Gap fade, S&P 500 names, open→close, $1 per side", loc="left", fontsize=10)
    ax.legend(loc="upper left", frameon=False, fontsize=8)
    _save(fig, path)


def fig_vix_quintiles(tbl: pd.DataFrame, legs: pd.DataFrame, path: Path):
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 2.2))
    x = np.arange(len(tbl))
    axes[0].bar(x, tbl["mean_bps"], 0.6, yerr=1.96 * tbl["se_bps"], color=C_TIMED, capsize=3)
    axes[0].axhline(DOLLARS_TRADED_PER_DAY * C_BASE_BPS, color=C_OOS, lw=1, ls="--")
    axes[0].text(x[0] - 0.4, DOLLARS_TRADED_PER_DAY * C_BASE_BPS, " cost at VIX 20", color=C_OOS, fontsize=7, va="bottom")
    axes[0].set_xticks(x, [f"Q{i}\n{lo:.0f}–{hi:.0f}" for i, lo, hi in zip(tbl.index, tbl["vix_lo"], tbl["vix_hi"])], fontsize=7)
    axes[0].set_ylabel("gross spread, bps/day"); axes[0].set_title("Q1−Q5 spread by lagged-VIX quintile", loc="left", fontsize=9)
    w = 0.38
    axes[1].bar(x - w / 2, legs["long_leg_excess_bps"], w, color=C_TIMED, label="long gap-down leg")
    axes[1].bar(x + w / 2, legs["short_leg_excess_bps"], w, color=C_CONST, label="short gap-up leg")
    axes[1].set_xticks(x, [f"Q{i}" for i in legs.index], fontsize=7)
    axes[1].set_ylabel("excess over universe, bps/day"); axes[1].set_title("Which leg earns it", loc="left", fontsize=9)
    axes[1].legend(frameon=False, fontsize=7)
    _save(fig, path)


def fig_grid(grid: pd.DataFrame, path: Path):
    fig, ax = plt.subplots(figsize=(3.6, 2.5))
    sub = grid[grid["sort"] == "quintile"].pivot(index="threshold", columns="c_base_bps", values="sharpe_net")
    sub = sub.reindex(["always on", *GRID_THRESHOLDS])
    im = ax.imshow(sub.values, cmap="RdYlGn", vmin=-1, vmax=1, aspect="auto")
    for i in range(sub.shape[0]):
        for j in range(sub.shape[1]):
            ax.text(j, i, f"{sub.values[i, j]:.2f}", ha="center", va="center", fontsize=8)
    ax.set_xticks(range(sub.shape[1]), [f"{c:g}" for c in sub.columns]); ax.set_xlabel("c_base, bps per $ traded")
    ax.set_yticks(range(sub.shape[0]), [str(t) for t in sub.index]); ax.set_ylabel("VIX threshold")
    ax.set_title("Net Sharpe, quintile sort", loc="left", fontsize=9); ax.grid(False)
    _save(fig, path)


# ---------------------------------------------------------------------------
# entry points
# ---------------------------------------------------------------------------
def run_in_sample(panel_is: pd.DataFrame, out_dir: Path) -> dict:
    tables, figures = out_dir / "tables", out_dir / "figures"
    tables.mkdir(parents=True, exist_ok=True)
    tests = hypothesis_tests(panel_is)
    strat, bts = strategies(panel_is)
    grid = sensitivity_grid(panel_is)
    grid.to_csv(tables / "gapfade_sensitivity_grid.csv", index=False)
    pd.DataFrame(tests["B2_vix_quintiles"]).to_csv(tables / "gapfade_vix_quintiles_is.csv", index=False)
    pd.DataFrame(bts["participation"]).to_csv(tables / "gapfade_daily_participation_is.csv")
    fig_equity(bts, figures / "gapfade_equity_is.png")
    fig_vix_quintiles(pd.DataFrame(tests["B2_vix_quintiles"]).set_index("vix_quintile"),
                      pd.DataFrame(tests["B4_legs_by_vix_quintile"]).set_index("vix_lag"), figures / "gapfade_vix_quintiles.png")
    fig_grid(grid, figures / "gapfade_grid.png")
    res = {
        "module": "B: opening-auction gap fade",
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "period": "in-sample", "start": str(panel_is.index[0].date()), "end": str(panel_is.index[-1].date()),
        "n_days": int(len(panel_is)),
        "hypothesis_tests": tests, "strategies": strat,
        "sensitivity_grid": grid.to_dict(orient="records"), "n_variants": N_VARIANTS,
        "subperiods_post_hoc_descriptive": subperiod_analysis(panel_is),
        "unfiltered_gap_robustness": unfiltered_robustness(panel_is.index[0], panel_is.index[-1]),
        "vix_quintile_edges_is": vix_quintile_edges(panel_is).tolist(),
    }
    (out_dir / "gapfade_in_sample.json").write_text(json.dumps(_json(res), indent=2))
    return res


def run_out_of_sample(panel_full: pd.DataFrame, out_dir: Path, is_res: dict) -> dict:
    panel_is, panel_oos = split(panel_full)
    tables, figures = out_dir / "tables", out_dir / "figures"
    edges = np.array(is_res["vix_quintile_edges_is"])
    tests = hypothesis_tests(panel_oos, edges)
    strat, bts = strategies(panel_oos)
    _, bts_is = strategies(panel_is)
    grid = sensitivity_grid(panel_oos)
    grid.to_csv(tables / "gapfade_sensitivity_grid_oos.csv", index=False)
    pd.DataFrame(bts["participation"]).to_csv(tables / "gapfade_daily_participation_oos.csv")
    fig_equity(bts_is, figures / "gapfade_equity_full.png", oos_bts=bts)
    res = {
        "module": "B: opening-auction gap fade",
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "period": "out-of-sample (evaluated once)", "start": str(panel_oos.index[0].date()),
        "end": str(panel_oos.index[-1].date()), "n_days": int(len(panel_oos)),
        "hypothesis_tests": tests, "strategies": strat,
        "sensitivity_grid": grid.to_dict(orient="records"),
    }
    (out_dir / "gapfade_out_of_sample.json").write_text(json.dumps(_json(res), indent=2))
    return res
