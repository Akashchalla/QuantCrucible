"""Performance statistics and the econometric tests of the hypothesis."""
from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats

from . import config

TD = config.TRADING_DAYS


# ---------------------------------------------------------------------------
# performance
# ---------------------------------------------------------------------------
def sharpe(x: pd.Series) -> float:
    s = x.std(ddof=1)
    return float(np.sqrt(TD) * x.mean() / s) if s > 0 else float("nan")


def max_drawdown(net: pd.Series) -> float:
    eq = (1 + net).cumprod()
    return float((eq / eq.cummax() - 1).min())


def perf_table(bt: pd.DataFrame) -> dict:
    net, gross = bt["net"], bt["gross"]
    monthly = (1 + net).resample("ME").prod() - 1
    years = len(net) / TD
    return {
        "ann_return_net": float(net.mean() * TD),
        "ann_return_gross": float(gross.mean() * TD),
        "ann_cost_drag": float(bt["cost"].mean() * TD),
        "ann_vol": float(net.std(ddof=1) * np.sqrt(TD)),
        "sharpe_net": sharpe(net),
        "sharpe_gross": sharpe(gross),
        "max_drawdown": max_drawdown(net),
        "worst_month": float(monthly.min()),
        "best_month": float(monthly.max()),
        "skew": float(stats.skew(net.dropna())),
        "kurtosis_excess": float(stats.kurtosis(net.dropna())),
        "hit_rate": float((net > 0).mean()),
        "turnover_per_year": float(bt["traded"].sum() / years),  # $ traded one-way per $ of capital
        "mean_exposure": float(bt["w"].mean()),
        "n_days": int(len(net)),
        "years": float(years),
        "start": str(net.index[0].date()),
        "end": str(net.index[-1].date()),
    }


def by_year(net: pd.Series) -> pd.Series:
    return (1 + net).groupby(net.index.year).prod() - 1


def rolling_sharpe(net: pd.Series, window: int = 3 * TD) -> pd.Series:
    return np.sqrt(TD) * net.rolling(window).mean() / net.rolling(window).std(ddof=1)


# ---------------------------------------------------------------------------
# hypothesis tests
# ---------------------------------------------------------------------------
def nw_regression(y: pd.Series, X: pd.DataFrame, lags: int = 10) -> dict:
    """OLS with Newey-West (HAC) standard errors."""
    df = pd.concat([y.rename("y"), X], axis=1).dropna()
    model = sm.OLS(df["y"], sm.add_constant(df.drop(columns="y"))).fit(cov_type="HAC", cov_kwds={"maxlags": lags})
    out = {"n": int(model.nobs), "r2": float(model.rsquared)}
    for k in model.params.index:
        out[f"coef_{k}"] = float(model.params[k])
        out[f"t_{k}"] = float(model.tvalues[k])
        out[f"p_{k}"] = float(model.pvalues[k])
    return out


def predictive_regression(panel: pd.DataFrame, universe: str) -> dict:
    """Prediction 1: r_t = a + b * VIX_{t-1}. Reported in bps per VIX point."""
    y = panel[universe] * 1e4  # bps
    X = panel[["vix_lag"]]
    res = nw_regression(y, X)
    return {
        "universe": universe,
        "n": res["n"],
        "alpha_bps": res["coef_const"],
        "slope_bps_per_vix_pt": res["coef_vix_lag"],
        "t_slope_nw": res["t_vix_lag"],
        "p_slope": res["p_vix_lag"],
        "r2": res["r2"],
    }


def vix_quintile_edges(panel: pd.DataFrame) -> np.ndarray:
    return np.quantile(panel["vix_lag"], [0, 0.2, 0.4, 0.6, 0.8, 1.0])


def vix_quintile_table(panel: pd.DataFrame, universe: str, edges: np.ndarray | None = None) -> pd.DataFrame:
    """Prediction 2: mean next-day reversal return by lagged-VIX quintile.

    Descriptive: quintile edges use the whole in-sample distribution unless
    `edges` is given (used to compare sub-periods on the same VIX bins).
    """
    if edges is None:
        q = pd.qcut(panel["vix_lag"], 5, labels=[1, 2, 3, 4, 5])
    else:
        e = edges.copy(); e[0], e[-1] = -np.inf, np.inf
        q = pd.cut(panel["vix_lag"], e, labels=[1, 2, 3, 4, 5])
    g = (panel[universe] * 1e4).groupby(q, observed=True)
    tbl = pd.DataFrame({
        "vix_lo": panel["vix_lag"].groupby(q, observed=True).min(),
        "vix_hi": panel["vix_lag"].groupby(q, observed=True).max(),
        "mean_bps": g.mean(),
        "se_bps": g.std(ddof=1) / np.sqrt(g.count()),
        "ann_vol": g.std(ddof=1) * np.sqrt(TD) / 1e4,
        "ann_sharpe": g.mean() / g.std(ddof=1) * np.sqrt(TD),
        "p05_bps": g.quantile(0.05),
        "worst_day_bps": g.min(),
        "n_days": g.count(),
    })
    tbl.index.name = "vix_quintile"
    return tbl


def factor_alpha(net: pd.Series, panel: pd.DataFrame, factors=("mkt_rf", "smb", "hml", "rmw", "cma", "mom")) -> dict:
    """Prediction 4: alpha of the strategy on FF5 + Momentum, HAC t-stats."""
    res = nw_regression(net * 1e4, panel.loc[net.index, list(factors)] * 1e4)  # same units -> unitless betas
    out = {
        "alpha_bps_per_day": res["coef_const"],
        "alpha_ann": res["coef_const"] * TD / 1e4,
        "t_alpha_nw": res["t_const"],
        "r2": res["r2"],
        "n": res["n"],
    }
    for f in factors:
        out[f"beta_{f}"] = res[f"coef_{f}"]
        out[f"t_{f}"] = res[f"t_{f}"]
    return out


def sharpe_difference_test(a: pd.Series, b: pd.Series, lags: int = 10) -> dict:
    """Is strategy a's Sharpe higher than b's? Regress a on b (HAC): a positive,
    significant intercept means a adds return not explained by b (Jobson-Korkie
    flavoured, but via the spanning regression which is robust to the two
    strategies being highly correlated)."""
    res = nw_regression(a * 1e4, b.rename("b").to_frame() * 1e4, lags=lags)
    return {"alpha_bps_per_day": res["coef_const"], "t_alpha_nw": res["t_const"], "beta_on_benchmark": res["coef_b"]}


# ---------------------------------------------------------------------------
# multiple-testing adjustment (Bailey & Lopez de Prado, 2014)
# ---------------------------------------------------------------------------
def expected_max_sharpe(n_trials: int, sharpe_var: float) -> float:
    """E[max of N iid Sharpe draws] with variance `sharpe_var` across trials."""
    if n_trials <= 1:
        return 0.0
    g = 0.5772156649
    z1 = stats.norm.ppf(1 - 1 / n_trials)
    z2 = stats.norm.ppf(1 - 1 / (n_trials * np.e))
    return float(np.sqrt(sharpe_var) * ((1 - g) * z1 + g * z2))


def probabilistic_sharpe(sr_hat_ann: float, sr0_ann: float, n: int, skew: float, kurt_excess: float) -> float:
    """PSR: probability the true (annualised) Sharpe exceeds sr0, given skew/kurtosis."""
    sr = sr_hat_ann / np.sqrt(TD)   # daily
    sr0 = sr0_ann / np.sqrt(TD)
    denom = np.sqrt((1 - skew * sr + (kurt_excess + 3 - 1) / 4 * sr**2) / (n - 1))
    return float(stats.norm.cdf((sr - sr0) / denom))


def deflated_sharpe(sr_hat_ann: float, n_trials: int, trial_sharpes_ann: list[float], n: int, skew: float, kurt_excess: float) -> dict:
    var_daily = float(np.var(np.array(trial_sharpes_ann) / np.sqrt(TD), ddof=1)) if len(trial_sharpes_ann) > 1 else 0.0
    sr0_daily = expected_max_sharpe(n_trials, var_daily)
    sr0_ann = sr0_daily * np.sqrt(TD)
    return {
        "n_trials": n_trials,
        "expected_max_sharpe_from_luck_ann": sr0_ann,
        "deflated_sharpe_prob": probabilistic_sharpe(sr_hat_ann, sr0_ann, n, skew, kurt_excess),
    }
