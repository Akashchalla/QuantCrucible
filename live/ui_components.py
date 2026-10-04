"""Reusable Streamlit renderers for Quant Crucible's agent-generated workspace."""
from __future__ import annotations

import html
import json
from typing import Any

import numpy as np
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

try:
    import plotly.express as px
    import plotly.graph_objects as go
except Exception:  # optional fallback; requirements-live includes plotly
    px = go = None

from .market_intel import tradingview_symbol, history


def tradingview(symbol: str, height: int = 520) -> None:
    tv = tradingview_symbol(symbol)
    cfg = {
        "allow_symbol_change": True,
        "calendar": False,
        "details": True,
        "hide_side_toolbar": False,
        "hide_top_toolbar": False,
        "hide_legend": False,
        "hide_volume": False,
        "interval": "60",
        "locale": "en",
        "save_image": True,
        "style": "1",
        "symbol": tv,
        "theme": "dark",
        "timezone": "America/New_York",
        "withdateranges": True,
        "support_host": "https://www.tradingview.com",
        "autosize": True,
    }
    body = f"""
    <div class="tradingview-widget-container" style="height:{height}px;width:100%;background:#070b11;border-radius:14px;overflow:hidden">
      <div class="tradingview-widget-container__widget" style="height:calc(100% - 28px);width:100%"></div>
      <div class="tradingview-widget-copyright" style="font-family:system-ui;font-size:11px;padding:5px 10px;color:#7f8a99">
        {html.escape(tv)} chart by TradingView
      </div>
      <script type="text/javascript" src="https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js" async>
      {json.dumps(cfg)}
      </script>
    </div>
    """
    components.html(body, height=height + 8, scrolling=False)


def _plot_line(df: pd.DataFrame, title: str, y_title: str = ""):
    if px is None:
        st.line_chart(df, height=330)
        return
    d = df.reset_index().melt(id_vars=df.index.name or "index", var_name="series", value_name="value")
    x = df.index.name or "index"
    fig = px.line(d, x=x, y="value", color="series", title=title)
    fig.update_layout(height=350, margin=dict(l=15, r=15, t=45, b=15), legend_title_text="", yaxis_title=y_title, xaxis_title="")
    st.plotly_chart(fig, width="stretch")


def _bar(df: pd.DataFrame, x: str, y: str, title: str):
    if px is None:
        st.bar_chart(df.set_index(x)[y])
        return
    fig = px.bar(df, x=x, y=y, title=title)
    fig.update_layout(height=330, margin=dict(l=15, r=15, t=45, b=15), xaxis_title="", yaxis_title="")
    st.plotly_chart(fig, width="stretch")


def render_sources(sources: list[dict[str, str]]) -> None:
    if not sources:
        return
    with st.expander(f"Sources · {len(sources)} grounded links"):
        for i, s in enumerate(sources, 1):
            title = s.get("title") or s.get("url") or f"Source {i}"
            url = s.get("url")
            st.markdown(f"{i}. [{title}]({url})" if url else f"{i}. {title}")


def render_turn(turn: dict[str, Any], compact: bool = False) -> None:
    """Render the visualization requested by an agent turn."""
    route = turn.get("route")
    payload = turn.get("payload") or {}
    if route == "company_research":
        snap = payload.get("snapshot") or {}
        if snap and not snap.get("market_data_error"):
            cols = st.columns(4)
            cols[0].metric("Price", f"{snap.get('price', float('nan')):,.2f}", f"{snap.get('return_1d',0):+.2%} 1D")
            cols[1].metric("20D", f"{snap.get('return_20d',0):+.2%}")
            cols[2].metric("20D realized vol", f"{snap.get('realized_vol_20d',0):.1%}")
            cols[3].metric("Move vs 60D", f"{snap.get('move_sigma_60d',0):+.2f}σ")
        h = payload.get("market_history")
        if isinstance(h, pd.DataFrame) and len(h) and "close" in h:
            _plot_line(h[["close"]].rename(columns={"close": payload.get("symbol", "price")}), f"{payload.get('symbol')} · recent adjusted close")
        render_sources(turn.get("sources") or [])
    elif route == "market_snapshot":
        h = payload.get("history")
        if isinstance(h, pd.DataFrame) and len(h):
            cols = st.columns(4)
            cols[0].metric("Price", f"{payload.get('price', float('nan')):,.2f}", f"{payload.get('return_1d',0):+.2%} 1D")
            cols[1].metric("20D", f"{payload.get('return_20d',0):+.2%}")
            cols[2].metric("20D realized vol", f"{payload.get('realized_vol_20d',0):.1%}")
            cols[3].metric("Move vs 60D", f"{payload.get('move_sigma_60d',0):+.2f}σ")
            _plot_line(h[["close"]].rename(columns={"close": payload.get("symbol", "price")}), f"{payload.get('symbol')} adjusted close")
            ret = h["close"].pct_change().dropna().tail(252)
            if len(ret):
                counts, edges = np.histogram(ret.to_numpy(float), bins=30)
                hist = pd.DataFrame({"daily return": [(edges[i]+edges[i+1])/2 for i in range(len(counts))], "sessions": counts})
                _bar(hist, "daily return", "sessions", "Trailing daily-return distribution")
    elif route == "compare":
        df = payload.get("comparison")
        if isinstance(df, pd.DataFrame) and len(df):
            _plot_line(df, "Normalized performance · start = 100", "Index")
        r = payload.get("returns")
        if isinstance(r, pd.Series):
            show = r.rename("return").reset_index().rename(columns={"index": "symbol"})
            _bar(show, "symbol", "return", "Window return")
    elif route == "analogs":
        df = payload.get("analogs")
        if isinstance(df, pd.DataFrame) and len(df):
            show = df.copy()
            show["similarity"] = show["similarity"].map(lambda x: f"{x:.0%}")
            st.dataframe(show, hide_index=True, width="stretch",
                         column_config={"fwd_1d": st.column_config.NumberColumn(format="%+.2%"),
                                        "fwd_5d": st.column_config.NumberColumn(format="%+.2%"),
                                        "fwd_20d": st.column_config.NumberColumn(format="%+.2%")})
            dist = df[["date", "fwd_20d"]].dropna()
            _bar(dist, "date", "fwd_20d", "20-session outcome after historical analogues")
    elif route == "crucible":
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Verdict", payload.get("verdict", "—"))
        c2.metric("Robustness", f"{payload.get('score',0)}/100")
        c3.metric("Headline Sharpe", f"{payload.get('base_metrics',{}).get('sharpe',float('nan')):.2f}")
        c4.metric("Held-out mean", f"{payload.get('oos_metrics',{}).get('mean_bps',float('nan')):+.2f} bps")
        ver = payload.get("verification") or {}
        if ver:
            st.caption(("✓ Independent math recomputation passed" if ver.get("verified") else "⚠ Independent math recomputation disagreed") + " · deterministic recomputation from raw returns")
        checks = pd.DataFrame([{"attack": k.replace("_", " "), "pass": bool(v)} for k, v in payload.get("checks", {}).items()])
        st.dataframe(checks, hide_index=True, width="stretch")
        t = payload.get("thresholds")
        costs = payload.get("costs")
        eq = payload.get("equity")
        col1, col2 = st.columns(2)
        with col1:
            if isinstance(t, pd.DataFrame): _bar(t, "threshold", "sharpe", "Threshold neighborhood · net Sharpe")
        with col2:
            if isinstance(costs, pd.DataFrame): _bar(costs, "cost_mult", "mean_bps", "Cost attack · mean net bps/day")
        if isinstance(eq, pd.DataFrame): _plot_line(eq, "Red-team equity paths", "Growth of $1")
    elif route == "multiverse":
        b, s = payload.get("base_metrics", {}), payload.get("stress_metrics", {})
        cols = st.columns(4)
        cols[0].metric("Base Sharpe", f"{b.get('sharpe',float('nan')):.2f}")
        cols[1].metric("Stress Sharpe", f"{s.get('sharpe',float('nan')):.2f}", f"{s.get('sharpe',0)-b.get('sharpe',0):+.2f}")
        cols[2].metric("Stress max DD", f"{s.get('max_drawdown',0):.1%}")
        cols[3].metric("P(loss) · horizon", f"{payload.get('stress_sim',{}).get('p_loss',0):.1%}")
        eq = payload.get("historical_equity")
        if isinstance(eq, pd.DataFrame): _plot_line(eq, "Actual history under base vs stressed assumptions", "Cumulative return")
        bands = payload.get("stress_sim", {}).get("bands")
        if isinstance(bands, pd.DataFrame) and len(bands):
            _plot_line(bands[["p05", "median", "p95"]], "Stress-universe Monte Carlo envelope", "Return")
        surface = payload.get("surface")
        if isinstance(surface, pd.DataFrame) and len(surface):
            if px is not None:
                z = surface.set_index("alpha_retention")
                fig = px.imshow(z, aspect="auto", text_auto=".1f", title="Mean net bps/day · alpha retention × cost multiplier")
                fig.update_layout(height=420, margin=dict(l=15, r=15, t=45, b=15), xaxis_title="Cost scenario", yaxis_title="Alpha retention")
                st.plotly_chart(fig, width="stretch")
            else:
                st.dataframe(surface, hide_index=True, width="stretch")
    elif route == "black_box":
        attrib = payload.get("attribution")
        if isinstance(attrib, pd.DataFrame): _bar(attrib, "component", "bps", f"Loss attribution · {payload.get('date','session')}")
        for e in payload.get("evidence_trail", []):
            st.markdown(f"**{e.get('stage')}**  \n{e.get('detail')}")
        if payload.get("note"): st.caption(payload["note"])
    elif route == "ghost":
        c1, c2, c3 = st.columns(3)
        c1.metric("Gate net value", f"${payload.get('gate_net_value',0):+,.0f}")
        c2.metric("Losses avoided", f"${payload.get('avoided_losses',0):,.0f}")
        c3.metric("Gains missed", f"${payload.get('missed_gains',0):,.0f}")
        eq = payload.get("equity_dollars")
        if isinstance(eq, pd.DataFrame): _plot_line(eq, "Actual portfolio vs ghost universes", "Cumulative P&L ($)")
        ledger = payload.get("ledger")
        if isinstance(ledger, pd.DataFrame): _bar(ledger, "effect", "value_usd", "Economic value / opportunity cost of controls")
        summary = payload.get("summary")
        if isinstance(summary, pd.DataFrame):
            st.dataframe(summary[["universe", "pnl_usd", "sharpe", "max_drawdown", "n_days_on"]], hide_index=True, width="stretch",
                         column_config={"pnl_usd": st.column_config.NumberColumn(format="$%+,.0f"),
                                        "max_drawdown": st.column_config.NumberColumn(format="%.1%")})
