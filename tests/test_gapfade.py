"""Module B sanity tests: point-in-time universe, signal timing, bucket maths, costs.

    python -m pytest -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gqh import gapfade  # noqa: E402


def _fake_panel(n: int = 300, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2018-01-01", periods=n)
    p = pd.DataFrame({"spread_q": rng.normal(0.001, 0.008, n), "spread_d": rng.normal(0.002, 0.011, n)}, index=idx)
    p["vix_lag"] = 10 + 20 * rng.random(n)
    return p


def test_membership_mask_is_point_in_time(tmp_path, monkeypatch):
    cons = pd.DataFrame({"yahoo_symbol": ["AAA", "BBB"], "date_added": ["2010-01-01", "2020-06-15"]})
    f = tmp_path / "c.csv"; cons.to_csv(f, index=False)
    monkeypatch.setattr(gapfade, "CONSTITUENTS", f)
    idx = pd.DatetimeIndex(["2020-06-12", "2020-06-15", "2020-06-16"])
    m = gapfade.membership_mask(idx, pd.Index(["AAA", "BBB"]))
    assert m["AAA"].all()
    assert list(m["BBB"]) == [False, True, True]


def test_bucket_means_pick_extremes():
    relgap = pd.DataFrame([[-3, -2, -1, 0, 1, 2, 3, 4, 5, 6]], index=[pd.Timestamp("2020-01-02")], dtype=float)
    vals = pd.DataFrame([list(range(10))], index=relgap.index, dtype=float)
    lo, hi = gapfade._bucket_means(vals, relgap, 5)
    assert lo.iloc[0] == 0.5     # two smallest relgaps -> values 0,1
    assert hi.iloc[0] == 8.5     # two largest -> values 8,9


def test_bucket_means_ignore_ineligible_names():
    relgap = pd.DataFrame([[-3, np.nan, -1, 0, 1, 2, 3, 4, 5, 6]], index=[pd.Timestamp("2020-01-02")], dtype=float)
    vals = pd.DataFrame([[100] + list(range(1, 10))], index=relgap.index, dtype=float)
    lo, _ = gapfade._bucket_means(vals, relgap, 5)
    # 9 eligible names, bottom quintile = rank pct <= 0.2 -> only the single most negative name
    assert lo.iloc[0] == 100


def test_participation_uses_only_lagged_vix():
    p = _fake_panel()
    part = gapfade.participation(p, 20.0)
    assert set(part.unique()) <= {0.0, 1.0}
    assert ((p["vix_lag"] >= 20) == (part == 1)).all()


def test_no_overnight_position_and_cost_accounting():
    p = _fake_panel()
    bt = gapfade.run(p, "quintile", gapfade.participation(p, None), c_base_bps=5.0)
    # every day is opened and closed: 4 dollars traded per day, always
    assert (bt["traded"] == 4.0).all()
    expected_cost = 4.0 * 5e-4 * p["vix_lag"] / 20.0
    assert np.allclose(bt["cost"], expected_cost)
    assert np.allclose(bt["net"], bt["gross"] - bt["cost"])
    off = gapfade.run(p, "quintile", gapfade.participation(p, 1000.0))
    assert (off["net"] == 0).all() and (off["traded"] == 0).all()


def test_breakeven_cost_zeroes_the_mean():
    p = _fake_panel()
    part = gapfade.participation(p, None)
    be = gapfade.breakeven_cost_bps(p, "quintile", part)
    assert abs(gapfade.run(p, "quintile", part, be)["net"].mean()) < 1e-12


def test_gap_filter_uses_open_information_only():
    """The cleaning rule must depend on the gap (known at the open), never on the intraday return."""
    import inspect
    src = inspect.getsource(gapfade.build_gap_panel)
    assert "gap.abs() <= gap_filter" in src
    assert "r_oc.abs()" not in src
