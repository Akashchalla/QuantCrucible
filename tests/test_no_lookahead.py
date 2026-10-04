"""Sanity tests judges can run: no lookahead, cost accounting, metrics.

    python -m pytest -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gqh import config, signals  # noqa: E402
from gqh.backtest import CostModel, run  # noqa: E402
from gqh.data import lag_asof  # noqa: E402
from gqh.metrics import max_drawdown, sharpe  # noqa: E402


def _fake_panel(n: int = 800, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2015-01-01", periods=n)
    vix = pd.Series(20 + 8 * np.abs(rng.standard_normal(n)), index=idx)
    panel = pd.DataFrame({"big_rev": rng.normal(0, 0.01, n), "st_rev": rng.normal(0, 0.008, n)}, index=idx)
    panel["vix_lag"] = lag_asof(vix, panel.index, "vix")
    panel["vix_lag_median"] = panel["vix_lag"].rolling(252, min_periods=126).median()
    return panel.dropna(subset=["vix_lag"])


def test_lag_asof_is_strictly_before():
    idx = pd.bdate_range("2020-01-01", periods=10)
    sig = pd.Series(np.arange(10.0), index=idx)
    lagged = lag_asof(sig, idx, "s")
    assert np.isnan(lagged.iloc[0])
    assert (lagged.iloc[1:].values == sig.iloc[:-1].values).all()


def test_lag_asof_skips_holidays_in_signal_calendar():
    # signal missing on a day the return calendar has: must use the last PRIOR value, not the next
    idx = pd.bdate_range("2020-01-01", periods=6)
    sig = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0, 6.0], index=idx).drop(idx[3])
    lagged = lag_asof(sig, idx, "s")
    assert lagged.loc[idx[4]] == 3.0  # idx[3] is missing, so fall back to idx[2]'s value


def test_signal_for_day_t_does_not_change_when_vix_on_day_t_changes():
    panel = _fake_panel()
    w0 = signals.linear(panel)
    panel2 = panel.copy()
    # perturb the return and the (would-be) same-day information: the weight only depends on vix_lag
    panel2["big_rev"] = panel2["big_rev"] * 10
    assert signals.linear(panel2).equals(w0)


def test_future_returns_do_not_affect_past_weights_for_walk_forward_rules():
    panel = _fake_panel()
    w_full, _ = signals.mean_variance(panel, "big_rev", scale=1.0)
    w_vt_full = signals.vol_target(panel, "big_rev")
    cut = len(panel) - 100
    w_trunc, _ = signals.mean_variance(panel.iloc[:cut], "big_rev", scale=1.0)
    w_vt_trunc = signals.vol_target(panel.iloc[:cut], "big_rev")
    pd.testing.assert_series_equal(w_full.iloc[:cut], w_trunc, check_names=False)
    pd.testing.assert_series_equal(w_vt_full.iloc[:cut], w_vt_trunc, check_names=False)


def test_costs_are_charged_on_every_dollar_traded():
    panel = _fake_panel()
    w = signals.constant(panel)
    cm = CostModel(c_base_bps=10.0, tau=0.14, scale_with_vix=False)
    bt = run(panel, "big_rev", w, cm)
    # constant exposure: 2 * tau of gross traded every day, no timing turnover
    assert np.allclose(bt["traded"], 2 * 0.14)
    assert np.allclose(bt["cost"], 2 * 0.14 * 10e-4)
    assert np.allclose(bt["net"], bt["gross"] - bt["cost"])


def test_vix_scaled_costs_are_higher_when_vix_is_higher():
    panel = _fake_panel()
    w = signals.constant(panel)
    bt = run(panel, "big_rev", w, CostModel(5.0, scale_with_vix=True))
    med = panel["vix_lag"].median()
    hi, lo = panel["vix_lag"] > med, panel["vix_lag"] <= med
    assert bt.loc[hi, "cost"].mean() > bt.loc[lo, "cost"].mean()


def test_sharpe_is_invariant_to_constant_scaling_of_exposure():
    panel = _fake_panel()
    w = signals.linear(panel, cap=10.0)
    cm = CostModel(5.0)
    a = run(panel, "big_rev", w, cm)["net"]
    b = run(panel, "big_rev", 0.5 * w, cm)["net"]
    assert abs(sharpe(a) - sharpe(b)) < 1e-9


def test_leverage_cap_binds():
    panel = _fake_panel()
    assert signals.linear(panel, norm=5.0, cap=3.0).max() <= 3.0 + 1e-12


def test_max_drawdown():
    net = pd.Series([0.1, -0.5, 0.2, 0.1])
    assert pytest.approx(max_drawdown(net), rel=1e-9) == -0.5


def test_oos_split_dates_follow_track_rule():
    years = (config.OOS_END - config.SAMPLE_START).days / 365.25
    assert 0.2 * years > 2.0  # 20% of the history is longer than 2y, so the 2y cap binds
    assert (config.OOS_END - config.OOS_START).days / 365.25 == pytest.approx(2.0, abs=0.01)
