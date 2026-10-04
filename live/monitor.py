"""Operator view: gate, positions, today's steps, recent P&L and risk events, as text."""
from __future__ import annotations

from datetime import date

import pandas as pd

from . import clock
from .settings import SETTINGS
from .store import Store


def _fmt_money(x) -> str:
    return "n/a" if x is None or pd.isna(x) else f"${x:,.0f}"


def render(store: Store, session: date | None = None, n_days: int = 15) -> str:
    session = session or clock.session_date()
    lines = [f"== gap-fade paper book | {session} | store={store.kind} | {'PAPER' if SETTINGS.paper else 'ALPACA'} =="]
    g = store.gate(session)
    if g:
        lines.append(f"gate: {'ON ' if g['gate_on'] else 'OFF'}  {g['reason']}  universe={g['n_universe']}")
    else:
        lines.append("gate: (pre_open has not run for this session)")
    steps = store.step_log(session)
    if len(steps):
        lines.append("steps: " + "  ".join(f"{r.step}={r.status}" for r in steps.itertuples()))
    pos = store.positions(session)
    if len(pos):
        gross = (pos["qty"].abs() * pos["avg_price"]).sum()
        lines.append(f"positions: {len(pos)} names, long {(pos['qty'] > 0).sum()} / short {(pos['qty'] < 0).sum()}, gross {_fmt_money(gross)}")
    else:
        lines.append("positions: flat")
    hist = store.pnl_history(n_days)
    if len(hist):
        lines.append(f"\nlast {len(hist)} sessions (bps per $1 per side; 'rule book' = spread the backtest's book earned whether or not we traded):")
        lines.append(f"{'date':<12}{'gate':<6}{'VIX-1':>7}{'gross':>8}{'cost':>7}{'net':>8}{'rule book':>11}{'overlap':>9}{'shortfall':>10}")
        for r in hist.itertuples():
            cost_bps = 1e4 * (r.cost or 0) / SETTINGS.notional_per_side
            ov = "" if r.basket_overlap is None or pd.isna(r.basket_overlap) else f"{r.basket_overlap:.0%}"
            sf = "" if r.shortfall_bps is None or pd.isna(r.shortfall_bps) else f"{r.shortfall_bps:+.1f}"
            rb = "" if r.realised_spread_bps is None or pd.isna(r.realised_spread_bps) else f"{r.realised_spread_bps:+.1f}"
            lines.append(f"{str(r.session_date)[:10]:<12}{'ON' if r.gate_on else 'off':<6}{(r.vix_lag or 0):>7.2f}"
                         f"{(r.gross_bps or 0):>8.1f}{cost_bps:>7.1f}{(r.net_bps or 0):>8.1f}{rb:>11}{ov:>9}{sf:>10}")
        traded = hist[hist["gate_on"].astype(bool)]
        if len(traded):
            lines.append(f"traded {len(traded)} sessions: net {traded['net_pnl'].sum():+,.0f} USD, mean net {traded['net_bps'].mean():+.1f} bps/day")
    ev = store.recent_risk_events(8)
    if len(ev):
        lines.append("\nrecent risk events:")
        for r in ev.itertuples():
            lines.append(f"  {str(r.ts)[:19]} [{r.level}] {r.step}/{r.check_name}: {r.message[:110]}")
    if SETTINGS.kill_switch.exists():
        lines.append(f"\n!! KILL SWITCH ENGAGED ({SETTINGS.kill_switch}) — no orders will be sent")
    return "\n".join(lines)
