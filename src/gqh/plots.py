"""Figures for the note. Matplotlib only, saved as PNG."""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from . import config  # noqa: E402
from .backtest import equity  # noqa: E402
from .metrics import rolling_sharpe  # noqa: E402

plt.rcParams.update({
    "figure.dpi": 150, "savefig.dpi": 150, "font.size": 9, "axes.grid": True,
    "grid.alpha": 0.3, "axes.spines.top": False, "axes.spines.right": False,
})
C_TIMED, C_CONST, C_GROSS, C_OOS = "#1b7f5a", "#4a5a7a", "#9aa5b8", "#c8862a"


def _save(fig, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def equity_curves(bt_timed: pd.DataFrame, bt_const: pd.DataFrame, title: str, path: Path,
                  oos_timed: pd.DataFrame | None = None, oos_const: pd.DataFrame | None = None):
    fig, ax = plt.subplots(figsize=(7.2, 2.6))
    ax.plot(equity(bt_const["net"]), color=C_CONST, lw=1.1, label="constant exposure, net")
    ax.plot(equity(bt_timed["gross"]), color=C_GROSS, lw=0.9, ls="--", label="VIX-timed, gross")
    ax.plot(equity(bt_timed["net"]), color=C_TIMED, lw=1.4, label="VIX-timed, net")
    if oos_timed is not None:
        e0 = equity(bt_timed["net"]).iloc[-1]
        e1 = equity(bt_const["net"]).iloc[-1]
        ax.plot(equity(oos_timed["net"], e0), color=C_TIMED, lw=1.4)
        ax.plot(equity(oos_const["net"], e1), color=C_CONST, lw=1.1)
        ax.axvspan(config.OOS_START, oos_timed.index[-1], color=C_OOS, alpha=0.12)
        ax.annotate("out-of-sample", xy=(config.OOS_START, 0.04), xycoords=("data", "axes fraction"),
                    color=C_OOS, fontsize=8, ha="right", va="bottom", xytext=(-3, 0), textcoords="offset points")
    else:
        ax.axvline(config.IS_END, color=C_OOS, lw=1, ls=":")
        ax.text(config.IS_END, 1.0, " OOS locked", color=C_OOS, fontsize=8, rotation=90, va="bottom")
    ax.set_yscale("log")
    ax.set_ylabel("growth of $1 (log)")
    ax.set_title(title, loc="left", fontsize=10)
    ax.legend(loc="upper left", frameon=False, fontsize=8)
    _save(fig, path)


def quintile_bars(tbl_all: pd.DataFrame, tbl_big: pd.DataFrame, path: Path):
    fig, ax = plt.subplots(figsize=(7.2, 2.1))
    x = np.arange(len(tbl_all))
    w = 0.38
    ax.bar(x - w / 2, tbl_all["mean_bps"], w, yerr=1.96 * tbl_all["se_bps"], color=C_CONST, capsize=3, label="ST_Rev factor (all-cap)")
    ax.bar(x + w / 2, tbl_big["mean_bps"], w, yerr=1.96 * tbl_big["se_bps"], color=C_TIMED, capsize=3, label="big-cap reversal leg")
    labels = [f"Q{i}\n{lo:.0f}–{hi:.0f}" for i, lo, hi in zip(tbl_all.index, tbl_all["vix_lo"], tbl_all["vix_hi"])]
    ax.set_xticks(x, labels)
    ax.set_xlabel("lagged VIX quintile (VIX range)")
    ax.set_ylabel("mean next-day return, bps")
    ax.axhline(0, color="k", lw=0.8)
    ax.set_title("Reversal premium by yesterday's VIX (in-sample, 95% CI)", loc="left", fontsize=10)
    ax.legend(frameon=False, fontsize=8)
    _save(fig, path)


def yearly_bars(by_year_timed: pd.Series, by_year_const: pd.Series, title: str, path: Path):
    fig, ax = plt.subplots(figsize=(7.2, 2.6))
    x = np.arange(len(by_year_timed))
    w = 0.4
    ax.bar(x - w / 2, by_year_const.values * 100, w, color=C_CONST, label="constant")
    ax.bar(x + w / 2, by_year_timed.values * 100, w, color=C_TIMED, label="VIX-timed")
    ax.set_xticks(x, [str(y)[2:] for y in by_year_timed.index], fontsize=7)
    ax.axhline(0, color="k", lw=0.8)
    ax.set_ylabel("net return, %")
    ax.set_title(title, loc="left", fontsize=10)
    ax.legend(frameon=False, fontsize=8, ncol=2)
    _save(fig, path)


def sensitivity_heatmap(grid: pd.DataFrame, universe: str, path: Path, value: str = "sharpe_net"):
    sub = grid[(grid["universe"] == universe) & (grid["rule"] == "linear")]
    piv = sub.pivot(index="cap", columns="norm", values=value)
    fig, ax = plt.subplots(figsize=(3.6, 2.5))
    im = ax.imshow(piv.values, cmap="Greens", aspect="auto")
    for i in range(piv.shape[0]):
        for j in range(piv.shape[1]):
            ax.text(j, i, f"{piv.values[i, j]:.2f}", ha="center", va="center", fontsize=9,
                    color="white" if piv.values[i, j] > piv.values.mean() else "black")
    ax.set_xticks(range(piv.shape[1]), [f"{c:.0f}" for c in piv.columns])
    ax.set_yticks(range(piv.shape[0]), [f"{c:.0f}×" for c in piv.index])
    ax.set_xlabel("VIX normaliser")
    ax.set_ylabel("leverage cap")
    ax.grid(False)
    ax.set_title(f"net Sharpe, {universe}", loc="left", fontsize=10)
    fig.colorbar(im, ax=ax, fraction=0.046)
    _save(fig, path)


def cost_curve(curve: pd.DataFrame, path: Path):
    fig, ax = plt.subplots(figsize=(3.6, 2.5))
    for col, c, lab in [("timed", C_TIMED, "VIX-timed (headline)"), ("constant", C_CONST, "constant"),
                        ("mean_variance", "#7a3fb0", "mean-variance (post-hoc)")]:
        if col in curve:
            ax.plot(curve["c_base_bps"], curve[col], color=c, lw=1.4, label=lab)
    ax.axhline(0, color="k", lw=0.8)
    ax.axvline(config.C_BASE_BPS["big_rev"], color=C_OOS, ls=":", lw=1, label="assumed cost")
    ax.set_xlabel("one-way cost at VIX 20, bps")
    ax.set_ylabel("net Sharpe")
    ax.set_title("Big-cap leg: Sharpe vs cost", loc="left", fontsize=10)
    ax.legend(frameon=False, fontsize=8)
    _save(fig, path)


def rolling_sharpe_plot(bt_timed: pd.DataFrame, bt_const: pd.DataFrame, path: Path):
    fig, ax = plt.subplots(figsize=(7.2, 2.5))
    ax.plot(rolling_sharpe(bt_const["net"]), color=C_CONST, lw=1.1, label="constant")
    ax.plot(rolling_sharpe(bt_timed["net"]), color=C_TIMED, lw=1.4, label="VIX-timed")
    ax.axhline(0, color="k", lw=0.8)
    ax.set_ylabel("rolling 3y Sharpe (net)")
    ax.set_title("Does the edge decay? Rolling 3-year net Sharpe, big-cap leg", loc="left", fontsize=10)
    ax.legend(frameon=False, fontsize=8)
    _save(fig, path)


def post_hoc_curves(bts: dict, title: str, path: Path, log: bool = True):
    fig, ax = plt.subplots(figsize=(7.2, 2.5))
    style = {"constant": (C_CONST, 1.0, "constant exposure"),
             "vol_target": (C_GROSS, 1.0, "vol-targeted (no VIX info)"),
             "mean_variance": (C_TIMED, 1.5, "mean-variance: E[r|VIX]/Var, walk-forward")}
    for k, bt in bts.items():
        c, lw, lab = style[k]
        ax.plot(equity(bt["net"]), color=c, lw=lw, label=lab)
    if log:
        ax.set_yscale("log")
    ax.set_ylabel("growth of $1" + (" (log)" if log else ""))
    ax.set_title(title, loc="left", fontsize=10)
    ax.legend(loc="upper left", frameon=False, fontsize=8)
    _save(fig, path)


def exposure_and_vix(bt_timed: pd.DataFrame, panel: pd.DataFrame, path: Path):
    fig, ax = plt.subplots(figsize=(7.2, 2.3))
    ax.plot(bt_timed["w"], color=C_TIMED, lw=0.8)
    ax.set_ylabel("exposure w_t")
    ax.set_title("Position size = min(VIX_{t-1}/20, 3)", loc="left", fontsize=10)
    _save(fig, path)
