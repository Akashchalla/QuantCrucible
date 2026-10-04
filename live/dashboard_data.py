"""Everything the dashboard shows, as plain dicts and DataFrames. No Streamlit import,
so the page and the tests share one data layer and a failing query surfaces here first.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from . import clock
from .feeds.massive import FeedError, MassiveFeed
from .settings import SETTINGS
from .store import Store

ROOT = SETTINGS.root
RESULTS = ROOT / "results"


def _date(x) -> date | None:
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return None
    return pd.Timestamp(x).date()


def live_view(store: Store, session: date | None = None, n_days: int = 60) -> dict:
    session = session or clock.session_date()
    g = store.gate(session)
    gate = None
    if g:
        gate = {"on": bool(g["gate_on"]), "reason": g["reason"], "vix": g["vix_lag"], "vix3m": g["vix3m_lag"],
                "vix_as_of": _date(g["vix_as_of"]), "source": g["vix_source"], "n_universe": int(g["n_universe"] or 0)}
    steps = store.step_log(session)
    pos = store.positions(session)
    if len(pos):
        pos = pos.copy()
        pos["notional"] = pos["qty"] * pos["avg_price"]
    hist = store.pnl_history(n_days)
    if len(hist):
        hist = hist.copy()
        hist["session_date"] = pd.to_datetime(hist["session_date"]).dt.date
        hist["cost_bps"] = 1e4 * hist["cost"].fillna(0) / SETTINGS.notional_per_side
        hist["cum_net"] = hist["net_pnl"].fillna(0).cumsum()
    sig = store.signals(session)
    if len(sig):
        sig = sig[sig["side"] != 0].copy()
        sig["est_gap_bps"] = 1e4 * sig["gap"]
    return {
        "session": session, "store_kind": store.kind, "broker": "paper" if SETTINGS.paper else "alpaca",
        "notional_per_side": SETTINGS.notional_per_side, "vix_threshold": SETTINGS.vix_threshold,
        "kill_switch": SETTINGS.kill_switch.exists(), "gate": gate,
        "steps": steps, "positions": pos, "history": hist, "targets": sig,
        "orders": store.orders(session), "risk_events": store.recent_risk_events(40),
    }


def marks(feed: MassiveFeed, positions: pd.DataFrame) -> tuple[pd.DataFrame, str | None]:
    """Attach last trade and mark-to-market to open positions. Returns (frame, error)."""
    if positions is None or not len(positions):
        return positions, None
    try:
        snap = feed.snapshots(positions.index.tolist())
    except FeedError as e:
        return positions, str(e)[:160]
    out = positions.copy()
    out["last"] = snap["last"].astype(float).reindex(out.index)
    out["mark_pnl"] = (out["last"] - out["avg_price"]) * out["qty"]
    return out, None


def research_view(results: Path = RESULTS) -> dict:
    """Committed research artefacts the note is built from. All optional: a missing file is skipped."""
    def csv(name):
        p = results / "tables" / name
        return pd.read_csv(p) if p.exists() else None

    def js(name):
        p = results / name
        return json.loads(p.read_text()) if p.exists() else None

    panel = csv("gapfade_panel_daily.csv")
    if panel is not None:
        panel["date"] = pd.to_datetime(panel["date"])
    return {
        "vix_quintiles": csv("gapfade_vix_quintiles_is.csv"),
        "grid": csv("gapfade_sensitivity_grid.csv"),
        "grid_oos": csv("gapfade_sensitivity_grid_oos.csv"),
        "panel": panel,
        "figures": sorted((results / "figures").glob("*.png")) if (results / "figures").exists() else [],
        "in_sample": js("gapfade_in_sample.json"),
        "out_of_sample": js("gapfade_out_of_sample.json"),
    }


def replay_session(store: Store, session: date) -> dict:
    """Run the full historical cycle for one session. Raises if it is not a trading day."""
    from .pipeline import Pipeline
    res = Pipeline(store=store, replay=True).run_session(session)
    if res.get("status") == "not_a_session":
        raise ValueError(f"{session} is not a trading session")
    return res


def kill(engage: bool) -> None:
    if engage:
        SETTINGS.kill_switch.write_text(f"engaged {datetime.now(clock.ET).isoformat()}\n")
    else:
        SETTINGS.kill_switch.unlink(missing_ok=True)
