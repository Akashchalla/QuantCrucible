"""Live layer: signal construction, paper fills and cost accounting, risk controls, flatness.
Everything runs on an in-memory SQLite store with synthetic prices — no network."""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from live import risk
from live.broker.base import closing_orders, orders_from_targets
from live.broker.paper import PaperBroker
from live.settings import Settings
from live.signal import build_signals, ideal_book, implementation_shortfall, spread_bps
from live.store import Store

SESSION = date(2026, 7, 30)


@pytest.fixture
def store(tmp_path):
    s = Store(url=None, sqlite_path=tmp_path / "t.sqlite")
    yield s
    s.close()


@pytest.fixture
def settings(tmp_path):
    return Settings(notional_per_side=1_000_000.0, kill_switch=tmp_path / "KILL", database_url=None)


def _prices(n=200, seed=0):
    rng = np.random.default_rng(seed)
    syms = [f"S{i:03d}" for i in range(n)]
    prev = pd.Series(rng.uniform(20, 400, n), index=syms)
    gap = rng.normal(0, 0.01, n)
    opn = prev * (1 + gap)
    cls = opn * (1 + rng.normal(0, 0.01, n) - 0.5 * gap)    # reversal baked in
    return prev, opn, cls


def test_signals_are_dollar_neutral_quintiles():
    prev, opn, _ = _prices()
    sig = build_signals(prev, opn, notional_per_side=1_000_000)
    live = sig[sig["side"] != 0]
    assert (live["side"] == 1).sum() == 40 and (live["side"] == -1).sum() == 40
    # longs are the names that gapped down relative to the median, shorts gapped up
    assert sig.loc[sig["side"] == 1, "relgap"].max() < sig.loc[sig["side"] == -1, "relgap"].min()
    long_n = (live.loc[live["side"] == 1, "target_qty"] * live.loc[live["side"] == 1, "est_open"]).sum()
    short_n = -(live.loc[live["side"] == -1, "target_qty"] * live.loc[live["side"] == -1, "est_open"]).sum()
    assert abs(long_n - 1_000_000) / 1_000_000 < 0.02 and abs(short_n - 1_000_000) / 1_000_000 < 0.02


def test_gap_filter_and_missing_prices_are_excluded_before_ranking():
    prev, opn, _ = _prices()
    opn = opn.copy()
    opn.iloc[0] = prev.iloc[0] * 1.5          # spin-off style artefact
    opn.iloc[1] = np.nan
    sig = build_signals(prev, opn)
    assert sig["excluded"].iloc[0] == "gap_filter" and sig["excluded"].iloc[1] == "no_price"
    assert sig["side"].iloc[0] == 0 and sig["side"].iloc[1] == 0
    assert sig["relgap"].iloc[2:].notna().all()


def test_ideal_book_is_independent_of_notional():
    prev, opn, cls = _prices()
    a = ideal_book(prev, opn)
    b = build_signals(prev, opn, notional_per_side=50_000)   # small book -> rounding drops names
    assert (a["side"] != 0).sum() == 80
    assert (b["side"] != 0).sum() <= 80
    ret = cls / opn - 1
    assert spread_bps(ret, a["side"])[2] > 0                 # reversal baked into synthetic data


def test_paper_broker_round_trip_is_flat_and_charges_the_toll(store, settings):
    prev, opn, cls = _prices()
    sig = build_signals(prev, opn, notional_per_side=settings.notional_per_side)
    br = PaperBroker(store, settings)
    br.submit(orders_from_targets(SESSION, sig, "MOO"))
    fills_o = br.fill_auction(SESSION, "MOO", opn, vix_lag=25.0, venue="open-auction")
    pos = br.positions(SESSION)
    assert len(fills_o) == (sig["side"] != 0).sum() and len(pos) == len(fills_o)
    br.submit(closing_orders(SESSION, pos, "MOC"))
    fills_c = br.fill_auction(SESSION, "MOC", cls, vix_lag=25.0, venue="close-auction")
    assert len(fills_c) == len(fills_o)
    assert br.positions(SESSION).empty                       # flat after the close
    assert risk.flat_check(br.positions(SESSION)) == []
    f = store.fills(SESSION)
    # toll = c_base * VIX/20 bps on every dollar traded, both legs, both auctions
    expected = (f["qty"] * f["price"]).sum() * settings.c_base_bps * (25.0 / 20.0) / 1e4
    assert abs(f["cost"].sum() - expected) < 1e-6
    # P&L from fills equals sum over names of qty * (close - open)
    signed = f["qty"].where(f["side"] == "buy", -f["qty"])
    cash = -(signed * f["price"]).sum()
    live = sig[sig["side"] != 0]
    assert abs(cash - (live["target_qty"] * (cls.reindex(live.index) - opn.reindex(live.index))).sum()) < 1e-6


def test_missing_auction_print_rejects_order_instead_of_inventing_a_fill(store, settings):
    prev, opn, _ = _prices()
    sig = build_signals(prev, opn, notional_per_side=settings.notional_per_side)
    br = PaperBroker(store, settings)
    br.submit(orders_from_targets(SESSION, sig, "MOO"))
    first = sig.index[sig["side"] != 0][0]
    opn2 = opn.copy()
    opn2[first] = np.nan
    fills = br.fill_auction(SESSION, "MOO", opn2, 20.0, "open-auction")
    assert first not in set(fills["symbol"])
    od = store.orders(SESSION)
    assert (od.loc[od["symbol"] == first, "status"] == "rejected").all()


def test_pre_trade_blocks_on_gate_kill_switch_and_stale_vix(settings):
    prev, opn, _ = _prices()
    sig = build_signals(prev, opn, notional_per_side=settings.notional_per_side)
    ok = risk.pre_trade(SESSION, gate_on=True, vix_as_of=date(2026, 7, 29), n_priced=200, n_universe=200, sig=sig,
                        indicative_age_s=10, already_submitted=False, s=settings)
    assert not risk.blocked(ok)
    off = risk.pre_trade(SESSION, gate_on=False, vix_as_of=date(2026, 7, 29), n_priced=200, n_universe=200, sig=sig,
                         indicative_age_s=10, already_submitted=False, s=settings)
    assert {v.check for v in off if v.level == "block"} == {"vix_gate"}
    stale = risk.pre_trade(SESSION, gate_on=True, vix_as_of=date(2026, 7, 20), n_priced=200, n_universe=200, sig=sig,
                           indicative_age_s=10, already_submitted=True, s=settings)
    assert {"stale_vix", "duplicate_session"} <= {v.check for v in stale}
    settings.kill_switch.write_text("x")
    killed = risk.pre_trade(SESSION, gate_on=True, vix_as_of=date(2026, 7, 29), n_priced=200, n_universe=200, sig=sig,
                            indicative_age_s=10, already_submitted=False, s=settings)
    assert "kill_switch" in {v.check for v in killed}
    thin = risk.pre_trade(SESSION, gate_on=True, vix_as_of=date(2026, 7, 29), n_priced=50, n_universe=200, sig=sig,
                          indicative_age_s=10, already_submitted=False, s=settings)
    assert "universe_coverage" in {v.check for v in thin}


def test_reconcile_flags_book_vs_broker_mismatch():
    book = pd.DataFrame({"qty": [10, -5]}, index=["A", "B"])
    same = pd.DataFrame({"qty": [10, -5]}, index=["A", "B"])
    diff = pd.DataFrame({"qty": [10, -4, 1]}, index=["A", "B", "C"])
    assert risk.reconcile(book, same) == []
    v = risk.reconcile(book, diff)
    assert v and v[0].check == "reconciliation" and "B:-1" in v[0].message and "C:-1" in v[0].message


def test_implementation_shortfall_zero_when_indicative_equals_open():
    prev, opn, cls = _prices()
    sig = build_signals(prev, opn, notional_per_side=1e12, min_price=0.0, max_name_pct=1.0)
    sf = implementation_shortfall(sig, opn, cls)
    assert sf["basket_overlap"] == 1.0 and abs(sf["shortfall_bps"]) < 1e-9
    noisy = opn * (1 + np.random.default_rng(1).normal(0, 0.004, len(opn)))
    sig2 = build_signals(prev, noisy, notional_per_side=1e12, min_price=0.0, max_name_pct=1.0)
    sf2 = implementation_shortfall(sig2, opn, cls)
    assert sf2["basket_overlap"] < 1.0 and sf2["median_abs_gap_error_bps"] > 0


def test_dashboard_view_shapes(store, tmp_path):
    """The dashboard reads only through dashboard_data; pin the contract it relies on."""
    from live import dashboard_data as dd
    from live.feeds.vix import VixState
    assert dd.live_view(store, SESSION)["gate"] is None          # empty store, no crash
    store.save_gate(SESSION, VixState(date(2026, 7, 29), 20.66, 22.1, "test"), True, "VIX>=20", 500)
    store.log_step(SESSION, "open_auction", "submitted", {"n": 1})
    store.save_pnl(SESSION, {"gate_on": True, "vix_lag": 20.66, "gross_pnl": 100.0, "cost": 20.0, "net_pnl": 80.0, "net_bps": 0.8})
    v = dd.live_view(store, SESSION)
    assert v["gate"]["on"] is True and v["gate"]["vix"] == pytest.approx(20.66)
    assert list(v["steps"]["step"]) == ["open_auction"]
    assert v["history"]["cost_bps"].iloc[0] == pytest.approx(1e4 * 20.0 / v["notional_per_side"])
    assert v["history"]["cum_net"].iloc[0] == pytest.approx(80.0)
    rv = dd.research_view(tmp_path)                               # empty dir: every artefact absent
    assert rv["vix_quintiles"] is None and rv["figures"] == []
    rv = dd.research_view()                                       # committed results
    assert rv["vix_quintiles"] is not None and {"mean_bps", "n_days"} <= set(rv["vix_quintiles"].columns)
    ks = tmp_path / "KILL"
    import live.dashboard_data as ddmod
    ddmod.SETTINGS.kill_switch = ks
    dd.kill(True)
    assert ks.exists()
    dd.kill(False)
    assert not ks.exists()


def test_store_round_trip_sqlite(store):
    from live.feeds.vix import VixState
    store.save_gate(SESSION, VixState(date(2026, 7, 29), 20.66, 22.1, "test"), True, "r", 500)
    g = store.gate(SESSION)
    assert bool(g["gate_on"]) is True and abs(g["vix_lag"] - 20.66) < 1e-9
    store.log_step(SESSION, "open_auction", "submitted", {"n": 1})
    store.log_step(SESSION, "open_auction", "blocked", {"n": 2})       # upsert
    assert store.step_status(SESSION, "open_auction") == "blocked"
    store.save_pnl(SESSION, {"gate_on": True, "vix_lag": 20.66, "net_pnl": -5.0, "net_bps": -0.5, "detail": {"a": 1}})
    h = store.pnl_history()
    assert len(h) == 1 and h["net_pnl"].iloc[0] == -5.0
    store.reset_session(SESSION)
    assert store.gate(SESSION) is None and store.pnl_history().empty
