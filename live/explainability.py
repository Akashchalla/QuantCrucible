"""Evidence-first explainability features for Quant Crucible.

These helpers never place orders or alter committed research. They reconstruct only what
is present in the stored live ledger or committed research artefacts and explicitly mark
counterfactual/scenario results as hypothetical.
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .black_box import inspect_live_session, inspect_research_day
from .crucible import HypothesisSpec, _series, load_panel, run_red_team
from .settings import SETTINGS
from .store import Store

ROOT = SETTINGS.root


def _date_from_question(question: str, fallback: str | date | None = None) -> pd.Timestamp | None:
    q = question or ""
    m = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", q)
    raw = m.group(1) if m else fallback
    if not raw:
        return None
    try:
        return pd.Timestamp(raw).normalize()
    except Exception:
        return None


def _nearest_research_day(day: pd.Timestamp | None) -> pd.Timestamp:
    panel = load_panel()
    if day is None:
        # Default to the most recent committed research day, not "today".
        return pd.Timestamp(panel.index[-1])
    if day in panel.index:
        return day
    prior = panel.index[panel.index <= day]
    if len(prior):
        return pd.Timestamp(prior[-1])
    return pd.Timestamp(panel.index[0])


def explain_day(store: Store, question: str, symbol: str, selected_date: str | date | None = None) -> dict[str, Any]:
    """Explain a selected live/research day without inventing unavailable detail."""
    requested = _date_from_question(question, selected_date)
    # Prefer a live paper ledger when it exists for the requested date.
    if requested is not None:
        d = requested.date()
        try:
            gate = store.gate(d)
            pnl = store.df("SELECT * FROM live_pnl WHERE session_date=%s", (d,))
            steps = store.step_log(d)
            fills = store.fills(d)
            signals = store.signals(d)
            if gate or len(pnl) or len(steps) or len(fills) or len(signals):
                report = inspect_live_session(store, d)
                selected = None
                if isinstance(signals, pd.DataFrame) and len(signals):
                    if symbol in signals.index:
                        selected = signals.loc[symbol].to_dict()
                attr = report.get("fill_attribution")
                biggest = None
                if isinstance(attr, pd.DataFrame) and len(attr):
                    biggest = attr.iloc[0].to_dict()
                answer = [f"Recorded paper-session review for {d}."]
                if gate:
                    answer.append(f"The VIX gate was {'ON' if bool(gate.get('gate_on')) else 'OFF'} because {gate.get('reason') or 'of the recorded gate rule' }.")
                if selected:
                    side = int(selected.get("side") or 0)
                    answer.append(
                        f"{symbol} was {'selected long' if side > 0 else 'selected short' if side < 0 else 'not assigned a position'} "
                        f"with relative gap {float(selected.get('relgap') or 0)*1e4:+.1f} bps and percentile rank {float(selected.get('pct_rank') or 0):.1%}."
                    )
                elif "select" in question.lower() or "company" in question.lower():
                    answer.append(f"I do not have a recorded {symbol} signal for this session, so I cannot claim why that company was selected.")
                if biggest:
                    answer.append(f"The lowest recorded fill-attribution row is {biggest.get('symbol')} at {float(biggest.get('net_pnl') or 0):+.0f} dollars, but cash-flow attribution is not a mark-to-market position P&L unless the ledger contains both sides.")
                return {
                    "kind": "live",
                    "date": str(d),
                    "gate": gate or {},
                    "pnl": report.get("pnl") or {},
                    "timeline": report.get("timeline"),
                    "fill_attribution": attr,
                    "selected_signal": selected or {},
                    "answer": " ".join(answer),
                    "limitations": ["Only recorded steps, fills, risk events and snapshots are shown; missing events are not reconstructed."],
                }
        except Exception:
            pass

    day = _nearest_research_day(requested)
    rep = inspect_research_day(day)
    gate_on = float(rep["vix"]) >= HypothesisSpec().threshold
    answer = (
        f"Research-day review for {rep['date']}. Lagged VIX was {rep['vix']:.2f}, so the pre-registered VIX≥20 participation rule was "
        f"{'ON' if gate_on else 'OFF'}. Gross spread outcome was {rep['gross_bps']:+.1f} bps, modeled costs were {rep['cost_bps']:.1f} bps, "
        f"and net was {rep['net_bps']:+.1f} bps."
    )
    limitations = [rep["note"]]
    if "select" in question.lower() or "company" in question.lower():
        answer += " This committed daily panel stores aggregate quintile legs, not the stock-level pre-open selection ledger, so it cannot prove why a specific company was selected on that historical research day."
        limitations.append("Company-level selection evidence is unavailable in the committed aggregate daily panel.")
    return {**rep, "kind": "research", "answer": answer, "limitations": limitations}


def profit_bridge(store: Store, question: str = "") -> dict[str, Any]:
    """Explain gross -> costs -> net and label hypothetical changes separately."""
    panel = load_panel()
    spec = HypothesisSpec()
    base = _series(panel, spec)
    double = _series(panel, spec, cost_mult=2.0)
    traded = base[base["w"] > 0]
    traded_double = double[double["w"] > 0]
    gross_bps = float(traded["gross"].sum() * 1e4)
    cost_bps = float(traded["cost"].sum() * 1e4)
    net_bps = float(traded["net"].sum() * 1e4)
    double_net_bps = float(traded_double["net"].sum() * 1e4)
    mean_gross = float(traded["gross"].mean() * 1e4) if len(traded) else np.nan
    mean_cost = float(traded["cost"].mean() * 1e4) if len(traded) else np.nan
    mean_net = float(traded["net"].mean() * 1e4) if len(traded) else np.nan
    bridge = pd.DataFrame([
        {"component": "Gross research P&L", "bps": gross_bps, "status": "actual committed backtest"},
        {"component": "Modeled trading costs", "bps": -cost_bps, "status": "actual committed cost model"},
        {"component": "Net research P&L", "bps": net_bps, "status": "actual committed backtest"},
        {"component": "Net if costs doubled", "bps": double_net_bps, "status": "HYPOTHETICAL scenario"},
    ])

    live = store.pnl_history(500)
    paper = {}
    if isinstance(live, pd.DataFrame) and len(live):
        paper = {
            "sessions": int(len(live)),
            "gross_pnl": float(pd.to_numeric(live.get("gross_pnl"), errors="coerce").fillna(0).sum()) if "gross_pnl" in live else 0.0,
            "cost": float(pd.to_numeric(live.get("cost"), errors="coerce").fillna(0).sum()) if "cost" in live else 0.0,
            "net_pnl": float(pd.to_numeric(live.get("net_pnl"), errors="coerce").fillna(0).sum()) if "net_pnl" in live else 0.0,
            "shortfall_bps_mean": float(pd.to_numeric(live.get("shortfall_bps"), errors="coerce").dropna().mean()) if "shortfall_bps" in live and pd.to_numeric(live.get("shortfall_bps"), errors="coerce").notna().any() else None,
        }
    answer = (
        f"Across committed gate-on research days, gross cumulative return contribution is {gross_bps:+.1f} bps. "
        f"The modeled cost schedule removes {cost_bps:.1f} bps, leaving {net_bps:+.1f} bps net. "
        f"On an average traded day that is {mean_gross:+.1f} gross, {mean_cost:.1f} cost, and {mean_net:+.1f} net bps. "
        f"If costs were doubled—a hypothetical, not an observed result—the same historical signal path would finish at {double_net_bps:+.1f} cumulative bps."
    )
    if paper:
        answer += f" The paper ledger currently has {paper['sessions']} recorded sessions with ${paper['net_pnl']:+,.0f} net P&L. Backtest and paper results can differ because the backtest uses modeled official-open/close execution while paper trading records actual order/fill timing, spread and shortfall when available."
    else:
        answer += " There is no populated paper P&L ledger in this store, so I cannot quantify a backtest-versus-paper gap yet."
    return {
        "bridge": bridge,
        "gross_bps": gross_bps,
        "cost_bps": cost_bps,
        "net_bps": net_bps,
        "double_cost_net_bps": double_net_bps,
        "cost_drag_fraction_of_gross": float(cost_bps / gross_bps) if gross_bps else None,
        "paper": paper,
        "answer": answer,
        "limitations": ["Doubled-cost output is counterfactual and is explicitly separate from committed actual results."],
    }


def replay_day(store: Store, question: str, symbol: str, selected_date: str | date | None = None) -> dict[str, Any]:
    requested = _date_from_question(question, selected_date)
    day = _nearest_research_day(requested)
    rep = inspect_research_day(day)
    q = question.lower()
    if any(k in q for k in ["close", "closing", "end of day", "results"]):
        stage = "close"
    elif any(k in q for k in ["decision", "opening", "open", "pause"]):
        stage = "decision"
    else:
        stage = "preopen"
    stages = [
        {"stage": "PRE-OPEN", "available": True, "detail": f"Lagged VIX {rep['vix']:.2f}; participation threshold is fixed at 20. No same-day close outcome is revealed."},
        {"stage": "OPEN / DECISION", "available": stage in {"decision", "close"}, "detail": "The daily research panel contains official opening gaps and aggregate quintiles. It does not preserve historical indicative-auction snapshots, so a truly tradable pre-open stock ranking cannot be reconstructed."},
        {"stage": "CLOSE / RESULTS", "available": stage == "close", "detail": f"Gross {rep['gross_bps']:+.1f} bps; modeled costs {rep['cost_bps']:.1f} bps; net {rep['net_bps']:+.1f} bps."},
    ]
    visible = [x for x in stages if x["available"]]
    if stage == "preopen":
        answer = f"Replay paused before the market open on {rep['date']}. The information I can reveal is lagged VIX {rep['vix']:.2f} and the fixed VIX≥20 gate rule. I will not reveal the same-day opening gaps or closing outcome yet."
    elif stage == "decision":
        answer = f"Replay is at the opening decision on {rep['date']}. I can show the official-open aggregate research state, but the committed daily dataset does not contain the historical indicative auction feed needed to prove what stock-level information was available seconds before 9:30. Closing P&L remains hidden."
    else:
        answer = f"Replay moved to closing results for {rep['date']}: gross {rep['gross_bps']:+.1f} bps, modeled costs {rep['cost_bps']:.1f} bps, net {rep['net_bps']:+.1f} bps."
    return {
        "date": rep["date"], "stage": stage, "stages": pd.DataFrame(stages), "visible_stages": visible,
        "answer": answer, "attribution": rep["attribution"] if stage == "close" else pd.DataFrame(),
        "limitations": ["Replay enforces information timing from the stored daily evidence; missing intraday/auction history is identified rather than invented."],
    }


def _load_json(name: str) -> dict[str, Any]:
    try:
        return json.loads((ROOT / "results" / name).read_text())
    except Exception:
        return {}


def research_trial(question: str) -> dict[str, Any]:
    """Put committed research claims on trial, always leading with strongest limitations."""
    q = question.lower()
    red = run_red_team()
    gap_oos = _load_json("gapfade_out_of_sample.json")
    opt_oos = _load_json("eightk_out_of_sample.json")
    claims = [
        {
            "claim": "Headline VIX-gated gap-fade strategy is robust",
            "verdict": red["verdict"],
            "evidence": f"Crucible robustness {red['score']}/100; held-out mean {red['oos_metrics'].get('mean_bps', float('nan')):+.2f} bps/day.",
            "strongest_limitation": "Daily bars cannot measure pre-open indicative-to-official-open slippage; the current S&P 500 universe omits removed constituents.",
            "source": "HYPOTHESIS_B.md / gapfade_out_of_sample.json",
        },
        {
            "claim": "Out-of-sample window was untouched",
            "verdict": "PROTOCOL EVIDENCE, NOT CRYPTOGRAPHIC PROOF",
            "evidence": "The hypothesis pre-specifies 2024-09-01→2026-08-31 and a separate one-time --oos evaluation; the committed OOS result labels the period evaluated once.",
            "strongest_limitation": "Repository chronology and separate commands support the protocol, but they cannot mathematically prove a human never viewed the data elsewhere.",
            "source": "HYPOTHESIS_B.md / gapfade_out_of_sample.json",
        },
        {
            "claim": "8-K repurchase option experiment is trustworthy",
            "verdict": "FRAGILE / SMALL OOS SAMPLE",
            "evidence": f"OOS has {opt_oos.get('n_filings',0)} filings, but only {(opt_oos.get('horizons_event_minus_control_bps') or {}).get('21',{}).get('n',0)} paired observations at 21 sessions; the reported 95% interval is very wide.",
            "strongest_limitation": "Sparse option-bar coverage and tiny paired OOS sample make the 21-session estimate highly uncertain even if its point estimate is positive.",
            "source": "HYPOTHESIS_8K.md / eightk_out_of_sample.json",
        },
        {
            "claim": "Current-constituent universe is free of survivorship bias",
            "verdict": "FALSE",
            "evidence": "HYPOTHESIS_B explicitly states removed S&P 500 constituents are not in the committed snapshot.",
            "strongest_limitation": "Survivorship bias can distort stock-level cross-sectional results; B4 is a diagnostic, not a full repair.",
            "source": "HYPOTHESIS_B.md",
        },
    ]
    df = pd.DataFrame(claims)
    if "delist" in q or "surviv" in q or "removed" in q:
        focus = claims[3]
    elif "untouched" in q or "final test" in q or "out of sample" in q or "oos" in q:
        focus = claims[1]
    elif "option" in q or "8-k" in q or "repurchase" in q:
        focus = claims[2]
    else:
        focus = claims[0]
    answer = f"Research-trial verdict: {focus['verdict']}. {focus['evidence']} Strongest limitation: {focus['strongest_limitation']}"
    return {
        "answer": answer,
        "focus": focus,
        "claims": df,
        "red_team": red,
        "gap_oos": gap_oos,
        "options_oos": opt_oos,
        "documents": ["HYPOTHESIS.md", "HYPOTHESIS_B.md", "HYPOTHESIS_C.md", "HYPOTHESIS_8K.md", "results/gapfade_out_of_sample.json", "results/eightk_out_of_sample.json"],
    }
