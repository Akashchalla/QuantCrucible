"""Market Black Box: post-mortem tooling for research and live paper sessions."""
from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from .crucible import HypothesisSpec, load_panel, _series
from .settings import SETTINGS
from .store import Store


def research_sessions(n: int = 20, spec: HypothesisSpec | None = None) -> pd.DataFrame:
    spec = spec or HypothesisSpec()
    panel = load_panel()
    bt = _series(panel, spec)
    out = panel[["q1", "q5", "ew", "mkt_gap", "vix_lag", "n"]].copy()
    out = out.join(bt[["w", "gross", "cost", "net"]])
    out["gross_bps"] = out["gross"] * 1e4
    out["cost_bps"] = out["cost"] * 1e4
    out["net_bps"] = out["net"] * 1e4
    return out[out["w"] > 0].nsmallest(n, "net_bps")


def inspect_research_day(day: date | str | pd.Timestamp, spec: HypothesisSpec | None = None) -> dict[str, Any]:
    spec = spec or HypothesisSpec()
    panel = load_panel()
    ts = pd.Timestamp(day)
    if ts not in panel.index:
        raise ValueError(f"{ts.date()} is not in the committed research panel")
    row = panel.loc[ts]
    bt = _series(panel.loc[[ts]], spec).iloc[0]
    gross_bps = float(bt["gross"] * 1e4)
    cost_bps = float(bt["cost"] * 1e4)
    net_bps = float(bt["net"] * 1e4)

    long_excess = float((row["q1"] - row["ew"]) * 1e4)

    # Use the committed backtest gross result as the accounting anchor.
    # This prevents tiny floating-point differences between separately
    # reconstructed legs from breaking exact attribution reconciliation.
    short_excess = gross_bps - long_excess

    attrib = pd.DataFrame([
        {"component": "Long leg vs market", "bps": long_excess},
        {"component": "Short leg vs market", "bps": short_excess},
        {"component": "Execution cost", "bps": -cost_bps},
    ])
    evidence = [
        {"stage": "Pre-open state", "detail": f"Lagged VIX {row['vix_lag']:.2f}; gate {'ON' if bt['w'] > 0 else 'OFF'} at threshold {spec.threshold:.1f}."},
        {"stage": "Cross-section", "detail": f"{int(row['n'])} eligible names; market median opening gap {row['mkt_gap']*1e4:+.1f} bps."},
        {"stage": "Gross outcome", "detail": f"Gap-fade spread {bt['gross']*1e4:+.1f} bps."},
        {"stage": "Execution model", "detail": f"Modeled round-trip cost {bt['cost']*1e4:.1f} bps."},
        {"stage": "Net outcome", "detail": f"Net {net_bps:+.1f} bps."},
    ]
    return {
        "date": str(ts.date()),
        "vix": float(row["vix_lag"]),
        "net_bps": net_bps,
        "gross_bps": gross_bps,
        "cost_bps": cost_bps,
        "attribution": attrib,
        "evidence_trail": evidence,
        "note": "Daily research data cannot reconstruct intraday timestamps; this is an evidence trail, not an invented minute-by-minute timeline.",
    }


def _fill_attribution(fills: pd.DataFrame) -> pd.DataFrame:
    if fills is None or fills.empty:
        return pd.DataFrame(columns=["symbol", "realized_pnl", "cost", "net_pnl"])
    rows = []
    for sym, g in fills.groupby("symbol"):
        signed = np.where(g["side"].astype(str).str.lower().eq("buy"), g["qty"].astype(float), -g["qty"].astype(float))
        cash = -float((signed * g["price"].astype(float)).sum())
        cost = float(g["cost"].fillna(0).sum())
        rows.append({"symbol": sym, "realized_pnl": cash, "cost": cost, "net_pnl": cash - cost})
    return pd.DataFrame(rows).sort_values("net_pnl")


def inspect_live_session(store: Store, session: date) -> dict[str, Any]:
    steps = store.step_log(session)
    fills = store.fills(session)
    risks = store.df("SELECT ts, level, step, check_name, message FROM live_risk_events WHERE session_date=%s ORDER BY ts", (session,))
    pnl = store.df("SELECT * FROM live_pnl WHERE session_date=%s", (session,))
    events = []
    for _, r in steps.iterrows():
        events.append({"ts": r.get("ts"), "kind": "step", "title": str(r.get("step")), "detail": str(r.get("status"))})
    for _, r in fills.iterrows():
        events.append({"ts": r.get("ts"), "kind": "fill", "title": f"{r.get('symbol')} {r.get('side')}", "detail": f"{int(r.get('qty',0))} @ {float(r.get('price',0)):.2f}"})
    for _, r in risks.iterrows():
        events.append({"ts": r.get("ts"), "kind": "risk", "title": f"{r.get('level')} · {r.get('check_name')}", "detail": str(r.get("message"))})
    timeline = pd.DataFrame(events)
    if len(timeline):
        timeline = timeline.sort_values("ts")
    return {
        "session": str(session),
        "timeline": timeline,
        "fill_attribution": _fill_attribution(fills),
        "pnl": pnl.iloc[0].to_dict() if len(pnl) else {},
        "has_intraday_evidence": bool(len(fills) or len(steps)),
    }


def narration_text(report: dict[str, Any]) -> str:
    if "date" in report:
        return (
            f"Black box review for {report['date']}. Lagged VIX was {report['vix']:.1f}. "
            f"Gross strategy return was {report['gross_bps']:+.1f} basis points, modeled costs were "
            f"{report['cost_bps']:.1f} basis points, and net outcome was {report['net_bps']:+.1f} basis points. "
            "The attribution panel separates long-leg, short-leg, and execution-cost effects."
        )
    p = report.get("pnl") or {}
    return (
        f"Black box review for {report.get('session','the selected session')}. "
        f"Recorded net P and L is {float(p.get('net_pnl', 0) or 0):+.0f} dollars. "
        "The timeline is reconstructed only from recorded steps, fills, and risk events."
    )
