"""Quant Crucible — AI-native systematic trading research workstation.

Run:
    streamlit run live/dashboard.py --server.port 8765

The five hero systems are deterministic where money/math is involved:
1) Crucible red-team, 2) Market Vision, 3) Multiverse, 4) Black Box, 5) Ghost Desk.
Gemini/Google Search and ElevenLabs provide research/orchestration/voice, never order authority.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from live import clock, dashboard_data as data  # noqa: E402
from live.agent import execute_turn  # noqa: E402
from live.black_box import inspect_live_session, inspect_research_day, narration_text, research_sessions  # noqa: E402
from live.crucible import HypothesisSpec, run_red_team  # noqa: E402
from live.ghost_desk import run_ghost_desk  # noqa: E402
from live.market_intel import analyze_chart_image, historical_analogs, resolve_symbol, research_company, snapshot  # noqa: E402
from live.multiverse import Scenario, run_scenario  # noqa: E402
from live.settings import SETTINGS  # noqa: E402
from live.ui_components import render_turn, tradingview  # noqa: E402

st.set_page_config(page_title="Quant Crucible", page_icon="⚡", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
:root { --qc-border:#263241; --qc-muted:#8b98a8; --qc-card:#0c121a; --qc-accent:#6ee7ff; }
.stApp { background: radial-gradient(circle at 15% -10%, #162234 0%, #090d13 36%, #06090e 72%); }
.block-container { padding-top: 1.0rem; max-width: 1600px; }
[data-testid="stSidebar"] { background: linear-gradient(180deg,#0b1119,#070a0f); border-right:1px solid #1b2633; }
div[data-testid="stMetric"] { background: linear-gradient(180deg,#101823,#0b1119); border: 1px solid #243346; border-radius: 14px; padding: 12px 15px; box-shadow:0 8px 26px rgba(0,0,0,.18); }
div[data-testid="stMetric"] label { color:#8796a8 !important; }
.qc-hero { padding:20px 24px; border:1px solid #24364a; border-radius:18px; background:linear-gradient(120deg,rgba(25,45,70,.72),rgba(8,13,20,.72)); margin-bottom:14px; }
.qc-kicker { font-size:.72rem; text-transform:uppercase; letter-spacing:.18em; color:#70d7ff; font-weight:700; }
.qc-title { font-size:2.0rem; line-height:1.1; font-weight:800; margin:.2rem 0 .35rem 0; }
.qc-sub { color:#93a0b0; max-width:1050px; }
.qc-badge { display:inline-block; padding:4px 9px; border:1px solid #2e455d; border-radius:999px; color:#a9bdd2; font-size:.72rem; margin-right:5px; margin-top:8px; }
.qc-proof { padding:10px 12px; border-left:3px solid #4dd7aa; background:#0b1515; border-radius:7px; }
.small-muted { color:#7f8b99; font-size:.82rem; }
</style>
""", unsafe_allow_html=True)


@st.cache_resource
def store():
    from live.store import Store
    return Store()


@st.cache_data(ttl=300)
def research():
    return data.research_view()


def _run_agent(question: str, *, from_voice: bool = False) -> None:
    if not question.strip():
        return
    with st.status("Crucible is investigating…", expanded=True) as status:
        st.write("Resolving intent and selecting an allow-listed analytical tool…")
        try:
            turn = execute_turn(store(), st.session_state["qc_session"], question, st.session_state["qc_symbol"], context=st.session_state.get("qc_chat", [])[-10:])
            st.write(f"Tool route: **{turn['route']}**")
            for step in turn.get("tool_trace", []):
                st.write(f"✓ {step}")
            if turn.get("sources"):
                st.write(f"Google-grounded evidence: **{len(turn['sources'])} sources**")
            st.write("Rendering the analytical workspace…")
            status.update(label="Investigation complete", state="complete", expanded=False)
        except Exception as e:  # noqa: BLE001
            status.update(label="Investigation failed", state="error", expanded=True)
            st.error(f"{type(e).__name__}: {str(e)[:500]}")
            return
    st.session_state["qc_last_turn"] = turn
    st.session_state["qc_symbol"] = turn.get("symbol") or st.session_state["qc_symbol"]
    st.session_state.setdefault("qc_chat", []).append({"role": "user", "content": question})
    st.session_state["qc_chat"].append({"role": "assistant", "content": turn["answer"], "sources": turn.get("sources", [])})
    if SETTINGS.elevenlabs_api_key and (from_voice or st.session_state.get("qc_auto_speak", False)):
        try:
            from live.ai_war_room import speak
            st.session_state["qc_audio"] = speak(turn.get("speech") or turn["answer"])
        except Exception as e:  # noqa: BLE001
            st.session_state["qc_audio_error"] = str(e)[:220]


def _play_audio():
    audio = st.session_state.get("qc_audio")
    if audio:
        try:
            st.audio(audio, format="audio/mp3", autoplay=True)
        except TypeError:
            st.audio(audio, format="audio/mp3")
    if st.session_state.get("qc_audio_error"):
        st.caption("Voice output unavailable: " + st.session_state.pop("qc_audio_error"))


def _metric_pct(v):
    return "—" if v is None or pd.isna(v) else f"{v:+.2%}"


# ----- shared state ------------------------------------------------------------
st.session_state.setdefault("qc_symbol", "GOOGL")
st.session_state.setdefault("qc_session", clock.session_date())
st.session_state.setdefault("qc_chat", [])
st.session_state.setdefault("qc_auto_speak", True)

with st.sidebar:
    st.markdown("### ⚡ Quant Crucible")
    st.caption("See it · Hypothesize it · Break it · Prove it")
    quick = st.selectbox("Market focus", ["GOOGL", "NVDA", "AAPL", "MSFT", "META", "TSLA", "XAUUSD=X", "SPY", "QQQ", "Custom"],
                         index=0 if st.session_state["qc_symbol"] not in ["NVDA","AAPL","MSFT","META","TSLA","XAUUSD=X","SPY","QQQ"] else ["GOOGL", "NVDA", "AAPL", "MSFT", "META", "TSLA", "XAUUSD=X", "SPY", "QQQ", "Custom"].index(st.session_state["qc_symbol"]))
    if quick == "Custom":
        custom = st.text_input("Ticker / market", value=st.session_state["qc_symbol"])
        st.session_state["qc_symbol"] = resolve_symbol(custom, st.session_state["qc_symbol"])
    else:
        st.session_state["qc_symbol"] = quick
    st.session_state["qc_session"] = st.date_input("Paper-book session", st.session_state["qc_session"], max_value=clock.session_date())
    st.toggle("Auto-speak AI answers", key="qc_auto_speak")
    st.divider()
    st.markdown("**Capability status**")
    st.caption(("🟢" if SETTINGS.gemini_api_key else "⚪") + " Gemini + Google Search")
    st.caption(("🟢" if SETTINGS.elevenlabs_api_key else "⚪") + " ElevenLabs voice")
    st.caption(("🟢" if SETTINGS.elevenlabs_speech_engine_id else "⚪") + " Full-duplex Speech Engine")
    st.caption(("🟢" if SETTINGS.massive_api_key else "⚪") + " Massive live feed")
    st.caption(("🟢" if SETTINGS.databento_api_key else "⚪") + " Databento auction / NOII")
    st.caption(("🟢" if SETTINGS.database_url else "⚪") + " Tiger Data / Timescale state store")
    st.caption("🟢 Deterministic quant engine")
    st.caption("🟢 Independent deterministic math verifier")
    with st.expander("Safety boundary"):
        st.write("AI can research, explain, visualize and launch sandbox analyses. It cannot mutate the pre-registered strategy, risk limits, broker orders or execution state.")

st.markdown("""
<div class="qc-hero">
  <div class="qc-kicker">AI-native systematic research workstation</div>
  <div class="qc-title">Quant Crucible</div>
  <div class="qc-sub">A live market desk that can research the web, see chart screenshots, speak, generate analytical views, red-team hypotheses, stress alternate worlds, reconstruct losses, and measure the economic value of risk controls.</div>
  <span class="qc-badge">Gemini</span><span class="qc-badge">Google Search</span><span class="qc-badge">ElevenLabs</span><span class="qc-badge">TradingView</span><span class="qc-badge">Deterministic Python</span>
</div>
""", unsafe_allow_html=True)

(tab_desk, tab_crucible, tab_vision, tab_multi, tab_black, tab_ghost, tab_ops) = st.tabs([
    "🎙 Live Desk", "🧪 Crucible", "👁 Market Vision", "⏳ Multiverse", "🔬 Black Box", "👻 Ghost Desk", "⚙ Operations"
])

# =============================================================================
# LIVE DESK — one conversation, voice + text + generated visual workspace
# =============================================================================
with tab_desk:
    left, right = st.columns([0.95, 1.35], gap="large")
    with left:
        st.subheader("Live market copilot")
        st.caption("Text and voice hit the same Gemini router and the same deterministic tools. Ask for a chart, comparison, current company research, a red-team, a scenario, an autopsy, or a ghost counterfactual.")

        for msg in st.session_state.get("qc_chat", [])[-8:]:
            with st.chat_message(msg["role"]):
                st.write(msg["content"])
                if msg.get("sources"):
                    st.caption(f"{len(msg['sources'])} Google-grounded sources attached")

        with st.form("desk_question", clear_on_submit=True):
            q = st.text_area("Ask Crucible", placeholder="Why is Google moving today? Show me if the move is unusual and compare it with Nvidia.", height=88, label_visibility="collapsed")
            ask = st.form_submit_button("Ask Gemini", type="primary", disabled=not bool(SETTINGS.gemini_api_key))
        if ask:
            _run_agent(q)
            st.rerun()

        v = st.audio_input("Speak to the desk")
        if st.button("Ask with voice", disabled=(v is None or not SETTINGS.gemini_api_key or not SETTINGS.elevenlabs_api_key), use_container_width=True):
            try:
                from live.ai_war_room import transcribe
                with st.spinner("ElevenLabs Scribe is listening…"):
                    transcript = transcribe(v.getvalue(), getattr(v, "type", "audio/wav"))
                st.session_state["qc_voice_transcript"] = transcript
                _run_agent(transcript, from_voice=True)
                st.rerun()
            except Exception as e:  # noqa: BLE001
                st.error(f"{type(e).__name__}: {str(e)[:400]}")
        if st.session_state.get("qc_voice_transcript"):
            st.caption("Last voice transcript: “" + st.session_state["qc_voice_transcript"] + "”")

        with st.expander("⚡ Full-duplex, interruptible voice + visual workspace"):
            st.write("The portable recorder above is zero-infrastructure. For the judge demo, use the included ElevenLabs Speech Engine browser client: realtime STT, turn-taking, interruption-aware TTS, typed chat, and the same generated charts.")
            st.code("""python -m live.realtime_voice_server
uvicorn live.voice_api:app --host 0.0.0.0 --port 8780
cd voice_ui && npm install && npm run dev""", language="bash")
            st.caption("Speech Engine also needs its :3001 WebSocket exposed over WSS (for example with ngrok) and ELEVENLABS_SPEECH_ENGINE_ID configured. See QUANT_CRUCIBLE.md.")

        st.markdown("**Try these**")
        prompts = [
            "What's going on with Google today? Show evidence.",
            "Compare Google versus Nvidia over the last six months.",
            "Find historical states similar to gold right now.",
            "Red-team our strategy and tell me the weakest point.",
            "What if volatility doubles and transaction costs triple?",
            "Open the black box on our worst traded research day.",
            "What did the VIX gate actually save us, and what gains did it miss?",
        ]
        for i, p in enumerate(prompts):
            if st.button(p, key=f"qp_{i}", use_container_width=True, disabled=not bool(SETTINGS.gemini_api_key)):
                _run_agent(p)
                st.rerun()

    with right:
        st.subheader("Generated analytical workspace")
        turn = st.session_state.get("qc_last_turn")
        if turn:
            st.markdown(f"**{turn.get('route','analysis').replace('_',' ').title()} · {turn.get('symbol', st.session_state['qc_symbol'])}**")
            st.write(turn.get("answer"))
            if turn.get("tool_trace"):
                st.caption("  →  ".join(turn["tool_trace"]))
            render_turn(turn)
            _play_audio()
        else:
            st.info("Ask the desk something. The right side becomes a generated chart/table/evidence workspace instead of returning only text.")
            try:
                tradingview(st.session_state["qc_symbol"], height=520)
            except Exception:
                pass

# =============================================================================
# CRUCIBLE
# =============================================================================
with tab_crucible:
    st.subheader("🧪 Quant Crucible · attack the hypothesis before capital does")
    st.caption("The model does not choose the verdict. These attacks run over the committed daily panel and the held-out window using deterministic Python.")
    c1, c2, c3, c4 = st.columns(4)
    threshold = c1.number_input("VIX threshold", 10.0, 40.0, 20.0, 0.5)
    cost = c2.number_input("Headline one-way cost (bps)", 0.0, 25.0, 5.0, 0.5)
    sort = c3.selectbox("Cross-sectional sort", ["quintile", "decile"])
    require_oos = c4.toggle("Require positive held-out", value=True)
    spec = HypothesisSpec(threshold=threshold, cost_bps=cost, sort=sort, require_positive_oos=require_oos)
    lock = hashlib.sha256(json.dumps(spec.__dict__, sort_keys=True).encode()).hexdigest()[:16]
    st.markdown(f"<div class='qc-proof'><b>Hypothesis lock</b> · <code>{lock}</code> · parameters are frozen for this run before results render.</div>", unsafe_allow_html=True)

    if st.button("🔒 Seal hypothesis + launch red team", type="primary"):
        with st.spinner("Running cost, threshold, outlier, bootstrap, year-stability and held-out attacks…"):
            st.session_state["crucible_result"] = run_red_team(spec)
    cres = st.session_state.get("crucible_result")
    if cres:
        render_turn({"route": "crucible", "payload": cres})
        st.markdown("### Deterministic findings")
        for x in cres["findings"]:
            st.markdown(f"- {x}")
        with st.expander("Bootstrap distribution"):
            b = pd.Series(cres["bootstrap"]["samples"], name="mean bps")
            hist = pd.cut(b, bins=30).value_counts().sort_index()
            st.bar_chart(hist)
        st.caption("A robust pass is evidence of resilience under the implemented attacks — not proof that future alpha exists.")

# =============================================================================
# MARKET VISION
# =============================================================================
with tab_vision:
    st.subheader("👁 Market Vision · live chart + grounded research + visual understanding")
    vleft, vright = st.columns([1.35, 0.9], gap="large")
    with vleft:
        tradingview(st.session_state["qc_symbol"], height=590)
    with vright:
        st.markdown(f"### {st.session_state['qc_symbol']}")
        if st.button("Quant snapshot", use_container_width=True):
            try:
                s = snapshot(st.session_state["qc_symbol"])
                st.session_state["vision_turn"] = {"route": "market_snapshot", "payload": s, "symbol": s["symbol"]}
            except Exception as e: st.error(str(e))
        if st.button("Find historical analogues", use_container_width=True):
            try:
                a = historical_analogs(st.session_state["qc_symbol"])
                st.session_state["vision_turn"] = {"route": "analogs", "payload": a, "symbol": a["symbol"]}
            except Exception as e: st.error(str(e))
        research_q = st.text_input("Ask current company/market question", placeholder="Why is this moving today? What changed after earnings?")
        if st.button("Research with Google", type="primary", use_container_width=True, disabled=not bool(SETTINGS.gemini_api_key)):
            try:
                with st.spinner("Gemini is grounding the answer with Google Search…"):
                    r = research_company(st.session_state["qc_symbol"], research_q or f"What is the most important current trading context for {st.session_state['qc_symbol']}?")
                st.session_state["vision_turn"] = {"route": "company_research", "payload": r, "answer": r["answer"], "sources": r["sources"], "symbol": r["symbol"]}
            except Exception as e: st.error(str(e))

    if st.session_state.get("vision_turn"):
        vt = st.session_state["vision_turn"]
        if vt.get("answer"): st.write(vt["answer"])
        render_turn(vt)

    st.divider()
    st.markdown("### Point at a chart — screenshot vision")
    st.caption("Upload a TradingView/chart screenshot and ask about what you are pointing at. Gemini treats the image as visual context; precise statistics still come from market data.")
    img = st.file_uploader("Chart screenshot", type=["png", "jpg", "jpeg", "webp"])
    iq = st.text_input("Question about the screenshot", value="What visually stands out here, and what should I test quantitatively?")
    if st.button("Analyze chart with Gemini Vision", disabled=(img is None or not SETTINGS.gemini_api_key)):
        try:
            with st.spinner("Gemini is inspecting the chart…"):
                vd = analyze_chart_image(img.getvalue(), img.type, st.session_state["qc_symbol"], iq)
            st.session_state["vision_image"] = vd
        except Exception as e: st.error(str(e))
    if st.session_state.get("vision_image"):
        vd = st.session_state["vision_image"]
        st.success(vd["summary"])
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Observed visual features**")
            for x in vd["observed_visual_features"]: st.markdown(f"- {x}")
        with c2:
            st.markdown("**Cautions**")
            for x in vd["cautions"]: st.markdown(f"- {x}")
        st.caption("Next: " + " · ".join(vd["suggested_next_actions"]))

# =============================================================================
# MULTIVERSE
# =============================================================================
with tab_multi:
    st.subheader("⏳ Market Multiverse · enter an alternate execution universe")
    st.caption("Stress execution costs, volatility and alpha decay, then replay the full committed history and bootstrap forward paths.")
    a, b, c = st.columns(3)
    vix_mult = a.slider("VIX environment multiplier", 0.5, 4.0, 1.5, 0.1)
    cost_mult = b.slider("Execution-cost multiplier", 0.0, 8.0, 2.0, 0.25)
    alpha_ret = c.slider("Gross-alpha retained", 0.0, 1.2, 0.70, 0.05)
    d, e, f = st.columns(3)
    slip = d.slider("Extra slippage (bps/day)", 0.0, 50.0, 5.0, 1.0)
    vol_mult = e.slider("Outcome-volatility multiplier", 0.5, 4.0, 1.25, 0.05)
    horizon = f.slider("Forward horizon (sessions)", 20, 252, 60, 10)
    presets = st.columns(3)
    if presets[0].button("Liquidity drought", use_container_width=True):
        st.session_state["multiverse_result"] = run_scenario(Scenario(vix_multiplier=1.8, cost_multiplier=3.0, alpha_retention=.8, extra_slippage_bps=12, volatility_multiplier=1.4, horizon_sessions=60))
    if presets[1].button("Volmageddon", use_container_width=True):
        st.session_state["multiverse_result"] = run_scenario(Scenario(vix_multiplier=2.5, cost_multiplier=2.5, alpha_retention=.65, extra_slippage_bps=15, volatility_multiplier=2.0, horizon_sessions=60))
    if presets[2].button("Alpha decay", use_container_width=True):
        st.session_state["multiverse_result"] = run_scenario(Scenario(vix_multiplier=1.0, cost_multiplier=1.0, alpha_retention=.4, extra_slippage_bps=3, volatility_multiplier=1.0, horizon_sessions=60))
    if st.button("Enter this universe", type="primary"):
        sc = Scenario(vix_multiplier=vix_mult, cost_multiplier=cost_mult, alpha_retention=alpha_ret,
                      extra_slippage_bps=slip, volatility_multiplier=vol_mult, horizon_sessions=horizon)
        with st.spinner("Replaying history + bootstrapping alternate paths…"):
            st.session_state["multiverse_result"] = run_scenario(sc)
    if st.session_state.get("multiverse_result"):
        render_turn({"route": "multiverse", "payload": st.session_state["multiverse_result"]})
        sc = st.session_state["multiverse_result"]["scenario"]
        st.caption("Universe: " + " · ".join(f"{k}={v}" for k, v in sc.items() if k not in ("name","n_paths")))

# =============================================================================
# BLACK BOX
# =============================================================================
with tab_black:
    st.subheader("🔬 Market Black Box · explain losses without inventing a story")
    mode = st.radio("Evidence source", ["Committed research worst days", "Live paper-book session"], horizontal=True)
    if mode == "Committed research worst days":
        worst = research_sessions(20)
        options = [d.date() for d in worst.index]
        chosen = st.selectbox("Session", options, format_func=lambda d: f"{d} · {worst.loc[pd.Timestamp(d),'net_bps']:+.1f} bps")
        report = inspect_research_day(chosen)
        render_turn({"route": "black_box", "payload": report})
        st.dataframe(worst[["vix_lag", "gross_bps", "cost_bps", "net_bps", "mkt_gap", "n"]].reset_index().rename(columns={"date":"session"}), hide_index=True, use_container_width=True)
    else:
        live_report = inspect_live_session(store(), st.session_state["qc_session"])
        if not live_report["has_intraday_evidence"]:
            st.info("No recorded fills/steps for this session yet. Replay a session in Operations to create a real execution timeline.")
        else:
            st.dataframe(live_report["timeline"], hide_index=True, use_container_width=True)
            st.dataframe(live_report["fill_attribution"], hide_index=True, use_container_width=True)
        report = live_report
    if st.button("Narrate this black box", disabled=not bool(SETTINGS.elevenlabs_api_key)):
        try:
            from live.ai_war_room import speak
            st.session_state["black_audio"] = speak(narration_text(report))
        except Exception as e: st.error(str(e))
    if st.session_state.get("black_audio"):
        st.audio(st.session_state["black_audio"], format="audio/mp3")

# =============================================================================
# GHOST DESK
# =============================================================================
with tab_ghost:
    st.subheader("👻 Ghost Desk · quantify the value and opportunity cost of controls")
    st.caption("Run the portfolio in parallel universes that were never executed: always-on, lower gate, higher gate, and no modeled costs.")
    notional = st.number_input("Per-side notional for dollar translation", 10_000.0, 100_000_000.0, float(SETTINGS.notional_per_side), 50_000.0)
    if st.button("Summon ghost portfolios", type="primary") or "ghost_result" not in st.session_state:
        st.session_state["ghost_result"] = run_ghost_desk(notional_per_side=notional)
    render_turn({"route": "ghost", "payload": st.session_state["ghost_result"]})
    st.info("A risk control is not automatically good because it prevented losses. Ghost Desk shows missed gains too, so the economic value can be negative.")

# =============================================================================
# OPERATIONS — retain the original paper-book/research workflows
# =============================================================================
with tab_ops:
    st.subheader("⚙ Deterministic paper-book operations")
    view = data.live_view(store(), st.session_state["qc_session"], 40)
    ops1, ops2, ops3 = st.tabs(["Paper book", "Research evidence", "Replay / Filing Edge"])
    with ops1:
        g = view["gate"]
        cols = st.columns(5)
        cols[0].metric("Gate", ("ON" if g and g["on"] else "OFF") if g else "—")
        cols[1].metric("VIX t−1", f"{g['vix']:.2f}" if g else "—")
        cols[2].metric("Universe", f"{g['n_universe']}" if g else "—")
        cols[3].metric("Kill switch", "ENGAGED" if view["kill_switch"] else "clear")
        hist = view["history"]
        cols[4].metric("Recorded sessions", str(len(hist)))
        if len(hist):
            st.line_chart(hist.set_index("session_date")[["cum_net"]].rename(columns={"cum_net":"Cumulative net $"}), height=260)
            st.dataframe(hist, hide_index=True, use_container_width=True)
        st.markdown("**Risk events**")
        if len(view["risk_events"]): st.dataframe(view["risk_events"], hide_index=True, use_container_width=True)
        else: st.caption("No recent risk events.")
        if view["kill_switch"]:
            if st.button("Release kill switch"):
                data.kill(False); st.rerun()
        else:
            if st.button("Engage kill switch"):
                data.kill(True); st.rerun()
    with ops2:
        rv = research()
        if rv["vix_quintiles"] is not None:
            st.bar_chart(rv["vix_quintiles"].set_index("vix_quintile")[["mean_bps"]].rename(columns={"mean_bps":"Gross spread bps/day"}))
            st.dataframe(rv["vix_quintiles"], hide_index=True, use_container_width=True)
        if rv["panel"] is not None:
            rolling = (rv["panel"].set_index("date")["spread_q"] * 1e4).rolling(21).mean()
            st.line_chart(rolling.rename("21D gross spread bps/day"), height=260)
    with ops3:
        d = st.date_input("Replay session", clock.session_date() - timedelta(days=1), max_value=clock.session_date(), key="qc_replay")
        c1, c2 = st.columns(2)
        if c1.button("Run deterministic replay", type="primary"):
            try:
                with st.spinner("Running gate → signal → risk → auction → fill → P&L → reconciliation…"):
                    res = data.replay_session(store(), d)
                st.success(str(res))
            except Exception as e: st.error(f"{type(e).__name__}: {str(e)[:400]}")
        if c2.button("Reset replay session"):
            store().reset_session(d); st.success(f"Cleared {d}")
        st.markdown("**Filing Edge saved replay**")
        st.caption("The repository still contains the original Massive filing study and saved judge-facing replay in `filing_edge/docs/`.")
        docs = Path(__file__).resolve().parents[1] / "filing_edge" / "docs" / "index.html"
        st.code(str(docs), language=None)

st.caption("Quant Crucible is a research/paper-trading workstation. AI outputs are explanations and sandbox analyses, not investment advice or broker authority.")
