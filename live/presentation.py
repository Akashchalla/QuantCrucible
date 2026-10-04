"""Convert internal Quant Crucible results into a small JSON view model.

The Streamlit app can render DataFrames directly. The full-duplex browser voice client cannot,
so this module produces a provider-neutral UI contract: metrics, charts, tables and sources.
It intentionally contains no model logic and no order/execution mutation path.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

import numpy as np
import pandas as pd


def _scalar(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, (date, datetime, pd.Timestamp)):
        return v.isoformat()
    if isinstance(v, (np.bool_, bool)):
        return bool(v)
    if isinstance(v, (np.integer, int)):
        return int(v)
    if isinstance(v, (np.floating, float)):
        x = float(v)
        return x if np.isfinite(x) else None
    if hasattr(v, "item"):
        try:
            return _scalar(v.item())
        except Exception:
            pass
    return str(v)


def _records(df: pd.DataFrame | None, limit: int = 300) -> list[dict[str, Any]]:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return []
    x = df.head(limit).copy()
    if not isinstance(x.index, pd.RangeIndex):
        idx_name = x.index.name or "date"
        if idx_name in x.columns:
            idx_name = "index"
        x = x.reset_index(names=idx_name)
    rows: list[dict[str, Any]] = []
    for r in x.to_dict(orient="records"):
        rows.append({str(k): _scalar(v) for k, v in r.items()})
    return rows


def _series_chart(df: pd.DataFrame | None, title: str, *, kind: str = "line", limit: int = 320) -> dict[str, Any] | None:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return None
    x = df.tail(limit).copy()
    idx_name = x.index.name or "date"
    if idx_name in x.columns:
        idx_name = "index"
    x = x.reset_index(names=idx_name)
    numeric = [c for c in x.columns if c != idx_name and pd.api.types.is_numeric_dtype(x[c])]
    if not numeric:
        return None
    return {
        "type": kind,
        "title": title,
        "xKey": idx_name,
        "series": [{"key": c, "label": str(c)} for c in numeric[:8]],
        "data": [{str(k): _scalar(v) for k, v in r.items()} for r in x.to_dict(orient="records")],
    }


def _xy_bar(df: pd.DataFrame | None, x: str, y: str, title: str, limit: int = 60) -> dict[str, Any] | None:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty or x not in df or y not in df:
        return None
    data = []
    for _, r in df[[x, y]].head(limit).iterrows():
        data.append({"x": _scalar(r[x]), "value": _scalar(r[y])})
    return {"type": "bar", "title": title, "xKey": "x", "series": [{"key": "value", "label": y}], "data": data}


def _metric(label: str, value: Any, fmt: str = "raw") -> dict[str, Any]:
    return {"label": label, "value": _scalar(value), "format": fmt}


def turn_to_view_model(turn: dict[str, Any]) -> dict[str, Any]:
    """Return a fully JSON-serializable frontend payload for text or voice clients."""
    route = str(turn.get("route") or "analysis")
    payload = turn.get("payload") or {}
    vm: dict[str, Any] = {
        "route": route,
        "symbol": str(turn.get("symbol") or payload.get("symbol") or ""),
        "question": str(turn.get("question") or ""),
        "answer": str(turn.get("answer") or ""),
        "speech": str(turn.get("speech") or turn.get("answer") or ""),
        "sources": [
            {"title": str(s.get("title") or s.get("url") or "Source"), "url": str(s.get("url") or "")}
            for s in (turn.get("sources") or []) if isinstance(s, dict)
        ],
        "metrics": [],
        "charts": [],
        "tables": [],
        "actions": [],
        "toolTrace": list(turn.get("tool_trace") or []),
    }

    if route == "company_research":
        s = payload.get("snapshot") or {}
        if not s.get("market_data_error"):
            vm["metrics"] = [
                _metric("Price", s.get("price"), "price"),
                _metric("1D move", s.get("return_1d"), "percent"),
                _metric("20D move", s.get("return_20d"), "percent"),
                _metric("20D realized vol", s.get("realized_vol_20d"), "percent"),
                _metric("Move vs 60D", s.get("move_sigma_60d"), "sigma"),
            ]
        h = payload.get("market_history")
        if isinstance(h, pd.DataFrame) and "close" in h:
            c = _series_chart(h[["close"]].rename(columns={"close": vm["symbol"] or "price"}), f"{vm['symbol']} · recent price")
            if c: vm["charts"].append(c)

    elif route == "vision":
        snap = payload.get("snapshot") or {}
        if not snap.get("market_data_error"):
            vm["metrics"] = [
                _metric("Price", snap.get("price"), "price"),
                _metric("1D move", snap.get("return_1d"), "percent"),
                _metric("20D move", snap.get("return_20d"), "percent"),
                _metric("20D realized vol", snap.get("realized_vol_20d"), "percent"),
                _metric("Move vs 60D", snap.get("move_sigma_60d"), "sigma"),
            ]
        rows = []
        for kind, key in [("Observed", "observed_visual_features"), ("Caution", "cautions"), ("Next action", "suggested_next_actions")]:
            for item in payload.get(key) or []:
                rows.append({"type": kind, "detail": str(item)})
        if rows:
            vm["tables"].append({"title": "Market Vision evidence", "rows": rows})

    elif route == "market_snapshot":
        vm["metrics"] = [
            _metric("Price", payload.get("price"), "price"),
            _metric("1D move", payload.get("return_1d"), "percent"),
            _metric("5D move", payload.get("return_5d"), "percent"),
            _metric("20D move", payload.get("return_20d"), "percent"),
            _metric("20D realized vol", payload.get("realized_vol_20d"), "percent"),
            _metric("Move vs 60D", payload.get("move_sigma_60d"), "sigma"),
        ]
        h = payload.get("history")
        if isinstance(h, pd.DataFrame) and "close" in h:
            c = _series_chart(h[["close"]].rename(columns={"close": vm["symbol"] or "price"}), f"{vm['symbol']} · adjusted close")
            if c: vm["charts"].append(c)
            ret = h["close"].pct_change().dropna().tail(252)
            if len(ret):
                counts, edges = np.histogram(ret.to_numpy(float), bins=28)
                hist = pd.DataFrame({"bucket": [float((edges[i]+edges[i+1])/2) for i in range(len(counts))], "count": counts})
                c = _xy_bar(hist, "bucket", "count", "Daily-return distribution · trailing sample")
                if c: vm["charts"].append(c)

    elif route == "compare":
        comp = payload.get("comparison")
        c = _series_chart(comp, "Normalized performance · start = 100")
        if c: vm["charts"].append(c)
        r = payload.get("returns")
        if isinstance(r, pd.Series):
            rd = r.rename("return").reset_index().rename(columns={r.index.name or "index": "symbol"})
            c = _xy_bar(rd, "symbol", "return", "Window return")
            if c: vm["charts"].append(c)

    elif route == "analogs":
        a = payload.get("analogs")
        if isinstance(a, pd.DataFrame):
            c = _xy_bar(a.assign(date=a["date"].astype(str)), "date", "similarity", "Closest historical states")
            if c: vm["charts"].append(c)
            c = _xy_bar(a.assign(date=a["date"].astype(str)), "date", "fwd_20d", "20-session outcomes after analogues")
            if c: vm["charts"].append(c)
            vm["tables"].append({"title": "Historical analogue ledger", "rows": _records(a, 20)})

    elif route == "crucible":
        b, o = payload.get("base_metrics", {}), payload.get("oos_metrics", {})
        vm["metrics"] = [
            _metric("Verdict", payload.get("verdict"), "text"),
            _metric("Robustness", payload.get("score"), "score100"),
            _metric("Headline Sharpe", b.get("sharpe"), "number"),
            _metric("Held-out mean", o.get("mean_bps"), "bps"),
        ]
        for df, x, y, title in [
            (payload.get("thresholds"), "threshold", "sharpe", "Threshold neighborhood · Sharpe"),
            (payload.get("costs"), "cost_mult", "mean_bps", "Execution-cost attack · mean bps/day"),
            (payload.get("outliers"), "removed_best_days", "mean_bps", "Outlier dependence · remove strongest days"),
        ]:
            c = _xy_bar(df, x, y, title)
            if c: vm["charts"].append(c)
        c = _series_chart(payload.get("equity"), "Red-team equity paths")
        if c: vm["charts"].append(c)
        checks = pd.DataFrame([{"attack": str(k).replace("_", " "), "pass": bool(v)} for k, v in (payload.get("checks") or {}).items()])
        vm["tables"].append({"title": "Attack ledger", "rows": _records(checks, 50)})

    elif route == "multiverse":
        b, s = payload.get("base_metrics", {}), payload.get("stress_metrics", {})
        vm["metrics"] = [
            _metric("Base Sharpe", b.get("sharpe"), "number"),
            _metric("Stress Sharpe", s.get("sharpe"), "number"),
            _metric("Stress max DD", s.get("max_drawdown"), "percent"),
            _metric("P(loss) · horizon", (payload.get("stress_sim") or {}).get("p_loss"), "percent"),
            _metric("Break-even costs", payload.get("break_even_cost_mult"), "multiple"),
        ]
        c = _series_chart(payload.get("historical_equity"), "Base vs stressed history")
        if c: vm["charts"].append(c)
        bands = (payload.get("stress_sim") or {}).get("bands")
        if isinstance(bands, pd.DataFrame):
            keep = [x for x in ["p05", "median", "p95"] if x in bands]
            c = _series_chart(bands[keep], "Monte Carlo stress envelope", kind="area")
            if c: vm["charts"].append(c)
        surface = payload.get("surface")
        if isinstance(surface, pd.DataFrame):
            vm["tables"].append({"title": "Alpha-retention × cost sensitivity", "rows": _records(surface, 20)})

    elif route == "black_box":
        vm["metrics"] = [
            _metric("Gross", payload.get("gross_bps"), "bps"),
            _metric("Costs", payload.get("cost_bps"), "bps"),
            _metric("Net", payload.get("net_bps"), "bps"),
            _metric("VIX", payload.get("vix"), "number"),
        ]
        c = _xy_bar(payload.get("attribution"), "component", "bps", f"Loss attribution · {payload.get('date','session')}")
        if c: vm["charts"].append(c)
        trail = pd.DataFrame(payload.get("evidence_trail") or [])
        if len(trail): vm["tables"].append({"title": "Evidence trail", "rows": _records(trail, 30)})

    elif route == "ghost":
        vm["metrics"] = [
            _metric("Gate net value", payload.get("gate_net_value"), "dollar"),
            _metric("Losses avoided", payload.get("avoided_losses"), "dollar"),
            _metric("Gains missed", payload.get("missed_gains"), "dollar"),
        ]
        c = _series_chart(payload.get("equity_dollars"), "Actual portfolio vs ghost universes")
        if c: vm["charts"].append(c)
        c = _xy_bar(payload.get("ledger"), "effect", "value_usd", "Economic value / opportunity cost")
        if c: vm["charts"].append(c)
        if isinstance(payload.get("summary"), pd.DataFrame):
            vm["tables"].append({"title": "Ghost universe scorecard", "rows": _records(payload["summary"], 20)})

    elif route == "explain_day":
        if payload.get("kind") == "live":
            p = payload.get("pnl") or {}
            vm["metrics"] = [
                _metric("Session", payload.get("date"), "text"),
                _metric("Gross P&L", p.get("gross_pnl"), "dollar"),
                _metric("Costs", p.get("cost"), "dollar"),
                _metric("Net P&L", p.get("net_pnl"), "dollar"),
            ]
            c = _xy_bar(payload.get("fill_attribution"), "symbol", "net_pnl", "Recorded fill attribution")
            if c: vm["charts"].append(c)
            if isinstance(payload.get("timeline"), pd.DataFrame):
                vm["tables"].append({"title": "Recorded session timeline", "rows": _records(payload["timeline"], 60)})
            if payload.get("selected_signal"):
                vm["tables"].append({"title": "Selected company evidence", "rows": [{"field": k, "value": _scalar(v)} for k, v in payload["selected_signal"].items()]})
        else:
            vm["metrics"] = [
                _metric("Session", payload.get("date"), "text"),
                _metric("Lagged VIX", payload.get("vix"), "number"),
                _metric("Gross", payload.get("gross_bps"), "bps"),
                _metric("Costs", payload.get("cost_bps"), "bps"),
                _metric("Net", payload.get("net_bps"), "bps"),
            ]
            c = _xy_bar(payload.get("attribution"), "component", "bps", "Research-day attribution")
            if c: vm["charts"].append(c)
            trail = pd.DataFrame(payload.get("evidence_trail") or [])
            if len(trail): vm["tables"].append({"title": "Evidence available for this day", "rows": _records(trail, 30)})
        lim = payload.get("limitations") or []
        if lim: vm["tables"].append({"title": "Known evidence limits", "rows": [{"limitation": str(x)} for x in lim]})

    elif route == "profit_bridge":
        vm["metrics"] = [
            _metric("Gross cumulative", payload.get("gross_bps"), "bps"),
            _metric("Cost drag", payload.get("cost_bps"), "bps"),
            _metric("Net cumulative", payload.get("net_bps"), "bps"),
            _metric("Net · 2× costs", payload.get("double_cost_net_bps"), "bps"),
            _metric("Cost / gross", payload.get("cost_drag_fraction_of_gross"), "percent"),
        ]
        c = _xy_bar(payload.get("bridge"), "component", "bps", "Where did the profit go?")
        if c: vm["charts"].append(c)
        if payload.get("paper"):
            vm["tables"].append({"title": "Recorded paper-trading ledger", "rows": [{"field": k, "value": _scalar(v)} for k, v in payload["paper"].items()]})
        vm["tables"].append({"title": "Actual vs hypothetical", "rows": _records(payload.get("bridge"), 10)})

    elif route == "replay":
        vm["metrics"] = [
            _metric("Replay day", payload.get("date"), "text"),
            _metric("Current stage", str(payload.get("stage") or "").upper(), "text"),
        ]
        if isinstance(payload.get("stages"), pd.DataFrame):
            vm["tables"].append({"title": "Point-in-time replay · unavailable evidence stays hidden", "rows": _records(payload["stages"], 10)})
        c = _xy_bar(payload.get("attribution"), "component", "bps", "Closing attribution · revealed only at close")
        if c: vm["charts"].append(c)
        vm["actions"] = [
            {"label": "Start before market open", "prompt": "Start before the market opens for this replay day."},
            {"label": "Pause at the decision", "prompt": "Pause and explain the opening decision. Show only information available then."},
            {"label": "Move to closing results", "prompt": "Move to the closing results for this replay day."},
        ]

    elif route == "research_trial":
        red = payload.get("red_team") or {}
        vm["metrics"] = [
            _metric("Crucible verdict", red.get("verdict"), "text"),
            _metric("Robustness", red.get("score"), "score100"),
            _metric("Held-out mean", (red.get("oos_metrics") or {}).get("mean_bps"), "bps"),
        ]
        if isinstance(payload.get("claims"), pd.DataFrame):
            vm["tables"].append({"title": "Research claims on trial", "rows": _records(payload["claims"], 20)})
        vm["actions"] = [
            {"label": "Challenge headline claim", "prompt": "Challenge this claim: did our original headline hypothesis really succeed? Show the strongest limitation."},
            {"label": "Challenge survivorship", "prompt": "Could missing delisted or removed stocks affect the result? Challenge the survivorship claim."},
            {"label": "Challenge OOS integrity", "prompt": "Was the final test period genuinely untouched? Show evidence and what cannot be proven."},
            {"label": "Challenge options experiment", "prompt": "Why should I trust the options experiment? Show the strongest limitation and failed/fragile evidence."},
        ]

    elif route == "scope_refusal":
        vm["metrics"] = [_metric("Scope", "Quant / market research only", "text")]

    elif route == "project_state":
        if isinstance(payload, dict):
            contract = payload.get("strategy_contract") or {}
            gate = payload.get("today") or {}
            vm["metrics"] = [
                _metric("VIX threshold", contract.get("vix_threshold"), "raw"),
                _metric("Lagged VIX", gate.get("vix"), "raw"),
                _metric("Gate", "ON" if gate.get("on") else ("OFF" if gate else "—"), "raw"),
                _metric("Per-side notional", contract.get("notional_per_side_usd"), "dollar"),
                _metric("Kill switch", "ON" if payload.get("kill_switch") else "OFF", "raw"),
            ]
            for title, key in [
                ("Recent live paper P&L", "recent_pnl"),
                ("Risk events", "risk_events"),
                ("Current targets", "targets"),
                ("Orders", "orders"),
            ]:
                rows = payload.get(key) or []
                if isinstance(rows, list) and rows:
                    vm["tables"].append({"title": title, "rows": rows[:20]})
            vm["tables"].append({
                "title": "Live strategy contract",
                "rows": [{"field": k, "value": _scalar(v)} for k, v in contract.items()],
            })

    # Remove empty cards so the browser has a simple contract.
    vm["charts"] = [c for c in vm["charts"] if c]
    vm["tables"] = [t for t in vm["tables"] if t.get("rows")]
    return vm
