"""Rules for the repurchase-8-K put study. No network, no 2026 market data."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from gqh.eightk_logic import (  # noqa: E402
    HEADLINE, HORIZONS, N_VARIANTS, control_ok, entry_session, kill_checks,
    mean_ci, monthly_expiry, occ_raw_symbol, pnl_bps, put_symbol,
    strike_from_prior, third_friday, ticker_from_display, tickers_from_display,
    trade_horizons,
)
from run_eightk import _reprice, window_problem  # noqa: E402


def _sessions():
    return pd.bdate_range("2024-06-03", periods=40)


def test_variant_count_is_the_pre_registered_54():
    assert N_VARIANTS == 54
    assert HEADLINE == {"delay": "clock", "haircut": 0.05, "otm": 0.05, "expiry_k": 1}
    assert HORIZONS == (1, 2, 3, 5, 10, 21, 42, 63)


def test_third_friday_and_monthly_expiry():
    assert third_friday(2024, 6) == pd.Timestamp("2024-06-21")
    assert third_friday(2024, 7) == pd.Timestamp("2024-07-19")
    entry = pd.Timestamp("2024-06-03")
    assert monthly_expiry(entry, 1) == pd.Timestamp("2024-07-19")
    assert monthly_expiry(entry, 2) == pd.Timestamp("2024-08-16")


def test_symbols():
    osi = put_symbol("AAPL", pd.Timestamp("2024-07-19"), 190)
    assert osi == "O:AAPL240719P00190000"
    assert occ_raw_symbol(osi) == "AAPL  240719P00190000"
    assert strike_from_prior(200, 0.05) == 190
    assert ticker_from_display("Asana, Inc.  (ASAN)  (CIK 0001477720)") == "ASAN"
    assert tickers_from_display("Foo (DE) (AAPL) (CIK 0000320193)") == ["DE", "AAPL"]


def test_entry_clock_does_not_trade_a_late_or_dateless_filing_at_the_same_close():
    sessions = _sessions()
    same_day = "2024-06-03T18:00:00Z"   # 14:00 America/New_York
    late = "2024-06-03T20:00:00Z"       # 16:00 America/New_York
    assert entry_session("2024-06-03", same_day, sessions, "clock") == pd.Timestamp("2024-06-03")
    assert entry_session("2024-06-03", late, sessions, "clock") == pd.Timestamp("2024-06-04")
    assert entry_session("2024-06-03", None, sessions, "clock") == pd.Timestamp("2024-06-04")
    assert entry_session("2024-06-03", same_day, sessions, "next") == pd.Timestamp("2024-06-04")
    assert entry_session("2024-06-03", same_day, sessions, "skip2") == pd.Timestamp("2024-06-05")
    friday_late = "2024-06-07T20:00:00Z"
    assert entry_session("2024-06-07", friday_late, sessions, "clock") == pd.Timestamp("2024-06-10")


def test_haircut_is_charged_on_both_sides_against_collateral():
    # Sell 2.00, buy back 1.00, 5% haircut, strike 100.
    # Credit 1.90, debit 1.05, 0.85 / 100 = 85 bps.
    assert pnl_bps(2.0, 1.0, 0.05, 100) == pytest.approx(85)
    # Unchanged mark: the round trip is a pure toll, twice as wide at 10%.
    assert pnl_bps(2.0, 2.0, 0.05, 100) == pytest.approx(-20)
    assert pnl_bps(2.0, 2.0, 0.10, 100) == pytest.approx(-40)
    assert np.isnan(pnl_bps(np.nan, 1.0, 0.05, 100))


def test_control_rejects_a_nearby_repurchase_entry():
    sessions = _sessions()
    control = sessions[15]
    assert control_ok(control, [sessions[0]], sessions, window=10)
    assert not control_ok(control, [sessions[15]], sessions, window=10)
    assert not control_ok(control, [sessions[20]], sessions, window=10)
    assert not control_ok(pd.NaT, [sessions[0]], sessions, window=10)


def test_horizon_past_the_window_is_missing():
    sessions = _sessions()
    entry = sessions[30]
    opt = pd.Series(2.0, index=sessions)
    spot = pd.Series(100.0, index=sessions)
    expiry = pd.Timestamp("2024-08-16")
    out = trade_horizons(opt, spot, entry, expiry, strike=95, haircut=0.05, sessions=sessions)
    assert np.isfinite(out["1"])
    assert np.isnan(out["21"])  # 30+21 is past the 40-session index
    assert np.isnan(out["expiry"])  # August expiry is not in this short spot index


def test_mean_ci_and_kill_flags():
    stats = mean_ci([10, 12, 8, 11])
    assert stats["n"] == 4
    assert stats["lo"] < stats["mean"] < stats["hi"]
    diffs = {str(h): {"mean": 5.0, "lo": 1.0, "hi": 9.0} for h in HORIZONS}
    diffs["21"] = {"mean": 5.0, "lo": 1.0, "hi": 9.0}
    grid = [
        {"delay": "clock", "haircut": 0.10, "otm": 0.05, "expiry_k": 1, "diff_21": -3.0},
        {"delay": "clock", "haircut": 0.05, "otm": 0.10, "expiry_k": 1, "diff_21": 4.0},
        {"delay": "skip2", "haircut": 0.05, "otm": 0.05, "expiry_k": 1, "diff_21": 2.0},
    ]
    flags = kill_checks(diffs, grid)
    assert flags["neighbour_sign_flip"]["haircut_10"] is True
    assert flags["neighbour_sign_flip"]["otm_10"] is False
    assert flags["diff_21_not_positive"] is False
    empty = kill_checks({}, [])
    assert empty["diff_21_not_positive"] is True


def test_window_cannot_cross_the_seal_or_rerun_oos(tmp_path):
    assert window_problem("2025-06-01", "2026-03-01") == "crosses"
    assert window_problem("2023-01-01", "2025-12-31") is None
    seal = tmp_path / "eightk_out_of_sample.json"
    assert window_problem("2026-01-01", "2026-08-31", seal) is None
    seal.write_text("{}")
    assert window_problem("2026-01-01", "2026-08-31", seal) == "oos_exists"


def test_double_haircut_is_a_paired_difference_on_marks_already_in_memory():
    sessions = _sessions()
    entry = sessions[5]
    control_entry = sessions[0]
    expiry = sessions[30]
    event_opt = pd.Series(2.0, index=sessions)
    control_opt = pd.Series(2.0, index=sessions)
    control_opt.loc[sessions[21]] = 3.0
    spot = {"AAA": pd.Series(100.0, index=sessions)}
    opts = {"O:EVENT": event_opt, "O:CTRL": control_opt}
    events = pd.DataFrame([{
        "accession": "A", "ticker": "AAA", "entry": entry, "strike": 95, "expiry": expiry,
        "osi": "O:EVENT", "delay": "clock", "haircut": 0.05, "otm": 0.05, "expiry_k": 1,
    }])
    controls = pd.DataFrame([{
        "pair_accession": "A", "delay": "clock", "haircut": 0.05, "otm": 0.05, "expiry_k": 1,
        "osi": "O:CTRL", "entry": control_entry, "expiry": expiry, "strike": 95, "ticker": "AAA",
    }])
    out = _reprice(events, controls, opts, spot, sessions, haircut=0.10)
    paired = out["paired_mean_bps_21"]
    assert paired["n"] == 1
    assert paired["mean"] > 0
