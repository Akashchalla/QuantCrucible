"""Position-sizing rules. Every input is already lagged (see data.lag_asof)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config


def constant(panel: pd.DataFrame) -> pd.Series:
    """Benchmark: hold one unit of the reversal portfolio every day."""
    return pd.Series(1.0, index=panel.index, name="w")


def linear(panel: pd.DataFrame, norm: float = config.VIX_NORM, cap: float = config.LEVERAGE_CAP) -> pd.Series:
    """Headline rule: w_t = min(VIX_{t-1} / norm, cap)."""
    w = (panel["vix_lag"] / norm).clip(lower=0.0, upper=cap)
    return w.rename("w")


def regime(panel: pd.DataFrame, cap: float = 1.0, **_: float) -> pd.Series:
    """Variant: on only when lagged VIX is above its trailing-1y median.

    `cap` is the size when on (1 by default so the average exposure is ~0.5).
    Days before the median is available are held at the constant benchmark.
    """
    med = panel["vix_lag_median"]
    on = (panel["vix_lag"] > med).astype(float) * cap
    on = on.where(med.notna(), 1.0)
    return on.rename("w")


RULES = {"constant": constant, "linear": linear, "regime": regime}


# ---------------------------------------------------------------------------
# POST-HOC rules — designed AFTER the in-sample result of the pre-registered
# rule was seen (see HYPOTHESIS.md "variant budget" and the note). They are
# the mean-variance-consistent implementation of the same hypothesis: size by
# expected return per unit of variance rather than by VIX level. Everything
# they use is known at t-1. They count as extra trials in the deflated Sharpe.
# ---------------------------------------------------------------------------
VT_TARGET = 0.10      # annualised volatility target for the risk-scaled rules
VT_WINDOW = 63        # trailing window (days) for realised vol of the reversal book
MV_BURN_IN_DAYS = 5 * config.TRADING_DAYS   # the walk-forward regression needs history first


def trailing_vol(panel: pd.DataFrame, universe: str, window: int = VT_WINDOW) -> pd.Series:
    """Annualised realised vol of the reversal book over the `window` days ENDING at t-1."""
    return panel[universe].shift(1).rolling(window).std(ddof=1) * np.sqrt(config.TRADING_DAYS)


def vol_target(panel: pd.DataFrame, universe: str, target: float = VT_TARGET,
               cap: float = config.LEVERAGE_CAP) -> pd.Series:
    """Benchmark for the risk-scaled rule: constant risk, no VIX information
    (Moreira & Muir 2017 applied to the reversal book)."""
    s = (target / trailing_vol(panel, universe)).clip(upper=cap)
    return s.fillna(1.0).rename("w")


def expanding_forecast(panel: pd.DataFrame, universe: str) -> pd.Series:
    """Walk-forward expected return: r_t ~ a + b * VIX_{t-1}, estimated on
    all days strictly before t (expanding window, updated daily)."""
    y = panel[universe].shift(1)          # realised return of day t-1 ...
    x = panel["vix_lag"].shift(1)         # ... paired with the VIX that preceded it
    n = y.expanding().count()
    sx, sy = x.expanding().sum(), y.expanding().sum()
    sxx, sxy = (x * x).expanding().sum(), (x * y).expanding().sum()
    b = (sxy - sx * sy / n) / (sxx - sx * sx / n)
    a = (sy - b * sx) / n
    mu = a + b * panel["vix_lag"]          # forecast for day t uses VIX_{t-1}
    mu[n < MV_BURN_IN_DAYS] = np.nan
    return mu.rename("mu_hat")


def mean_variance(panel: pd.DataFrame, universe: str, scale: float | None = None,
                  cap: float = config.LEVERAGE_CAP) -> tuple[pd.Series, float]:
    """w_t = scale * max(mu_hat_t, 0) / sigma_hat_t^2, capped.

    mu_hat is the walk-forward forecast, sigma_hat the trailing realised vol.
    Negative forecasts mean 'stand aside' — we never short liquidity provision.
    `scale` is a constant: it does not affect the Sharpe ratio (returns and
    costs are both linear in w) and is fixed so the in-sample mean exposure is
    1, then reused unchanged out-of-sample. Returns (weights, scale).
    """
    mu = expanding_forecast(panel, universe).clip(lower=0.0)
    var = (trailing_vol(panel, universe) / np.sqrt(config.TRADING_DAYS)) ** 2
    raw = (mu / var).replace([np.inf, -np.inf], np.nan)
    if scale is None:
        scale = 1.0 / raw.loc[: config.IS_END].mean()
    w = (raw * scale).clip(upper=cap)
    return w.rename("w"), float(scale)


def exposure_summary(w: pd.Series) -> dict:
    return {
        "mean_exposure": float(w.mean()),
        "median_exposure": float(w.median()),
        "max_exposure": float(w.max()),
        "share_days_above_1": float((w > 1).mean()),
        "share_days_at_cap": float(np.isclose(w, w.max()).mean()) if w.max() > 1 else 0.0,
    }
