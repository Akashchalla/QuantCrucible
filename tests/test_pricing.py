"""Module C sanity tests: state variables are strictly lagged, rules are causal.

    python -m pytest -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gqh import pricing  # noqa: E402
from gqh.data import lag_asof  # noqa: E402


def _fake_panel_a(n: int = 700, seed: int = 3) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2016-01-01", periods=n)
    vix = pd.Series(15 + 10 * rng.random(n), index=idx)
    p = pd.DataFrame({"big_rev": rng.normal(0, 0.01, n), "st_rev": rng.normal(0, 0.008, n),
                      "mkt_rf": rng.normal(0, 0.01, n)}, index=idx)
    p["vix_lag"] = lag_asof(vix, p.index, "vix")
    p["vix_lag_median"] = p["vix_lag"].rolling(252, min_periods=126).median()
    return p.dropna(subset=["vix_lag"])


def test_realised_variance_excludes_same_day_return(monkeypatch):
    p = _fake_panel_a()
    monkeypatch.setattr(pricing, "load_vix3m", lambda: pd.Series(20.0, index=p.index))
    s = pricing.state_variables(p)
    # recompute RV on row t from returns strictly before t and compare
    t = p.index[300]
    prior = p["mkt_rf"].loc[:t].iloc[:-1].tail(21)
    expected = 252 * ((100 * prior) ** 2).mean()
    assert np.isclose(s.loc[t, "rv21_lag"], expected)
    # shocking today's return must not move today's state
    p2 = p.copy(); p2.loc[t, "mkt_rf"] = 0.5
    s2 = pricing.state_variables(p2)
    assert np.isclose(s2.loc[t, "rv21_lag"], s.loc[t, "rv21_lag"])
    assert np.isclose(s2.loc[t, "vrp21_lag"], s.loc[t, "vrp21_lag"])


def test_vrp_identity_and_median_is_causal(monkeypatch):
    p = _fake_panel_a()
    monkeypatch.setattr(pricing, "load_vix3m", lambda: pd.Series(20.0, index=p.index))
    s = pricing.state_variables(p)
    ok = s.dropna(subset=["rv21_lag"])
    assert np.allclose(ok["vrp21_lag"], ok["vix2_lag"] - ok["rv21_lag"])
    t = s.index[400]
    hist = s["vrp21_lag"].loc[:t].tail(252)
    assert np.isclose(s.loc[t, "vrp21_median"], hist.median())


def test_term_structure_uses_prior_day_vix3m(monkeypatch):
    p = _fake_panel_a()
    vix3m = pd.Series(np.linspace(10, 30, len(p)), index=p.index)
    monkeypatch.setattr(pricing, "load_vix3m", lambda: vix3m)
    s = pricing.state_variables(p)
    assert np.isnan(s["vix3m_lag"].iloc[0])
    assert np.allclose(s["vix3m_lag"].iloc[1:].values, vix3m.iloc[:-1].values)


def test_participation_is_binary_and_off_when_undefined(monkeypatch):
    p = _fake_panel_a()
    monkeypatch.setattr(pricing, "load_vix3m", lambda: pd.Series(20.0, index=p.index))
    panel = pricing.attach_states(p, pricing.state_variables(p))
    for rule in pricing.RULES:
        w = pricing.participation(panel, rule)
        assert set(w.unique()) <= {0.0, 1.0}
        assert not w.isna().any()
    undefined = panel["vrp21_median"].isna()
    assert (pricing.participation(panel, "vrp_median")[undefined] == 0).all()
