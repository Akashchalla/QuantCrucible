"""Operator dashboard for the VIX-gated gap fade.

    streamlit run live/dashboard.py --server.port 8765 --server.address 0.0.0.0

Read-only over the store and the committed research artefacts, except three actions: the kill
switch, replaying a past session, and optional AI explainability/voice tools. Nothing here places an order.
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from live import clock, dashboard_data as data  # noqa: E402
from live.settings import SETTINGS  # noqa: E402

st.set_page_config(page_title="Gap Fade — paper book", layout="wide")

st.markdown("""
<style>
.block-container { padding-top: 1.4rem; }
div[data-testid="stMetric"] { background: #11161d; border: 1px solid #262e38; border-radius: 10px; padding: 10px 14px; }
div[data-testid="stMetric"] label { color: #9aa4b2; }
</style>
""", unsafe_allow_html=True)


@st.cache_resource
def store():
    from live.store import Store
    return Store()


@st.cache_resource
def feed():
    from live.feeds.massive import MassiveFeed
    return MassiveFeed()


@st.cache_data(ttl=300)
def research():
    return data.research_view()


FILING_EDGE_PORT = 8877


@st.cache_resource
def filing_edge_replay() -> str:
    """Serve the saved Filing Edge pages. Replay only: no Massive calls and no new holdout pass."""
    import functools
    import http.server
    import socketserver
    import threading

    docs = Path(__file__).resolve().parents[1] / "filing_edge" / "docs"

    class _Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, fmt, *args):
            return

    handler = functools.partial(_Quiet, directory=str(docs))

    class _Replay(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True

    try:
        httpd = _Replay(("0.0.0.0", FILING_EDGE_PORT), handler)
    except OSError:
        return f"http://127.0.0.1:{FILING_EDGE_PORT}/"
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{FILING_EDGE_PORT}/"


def _bps(x, signed=True) -> str:
    if x is None or pd.isna(x):
        return "—"
    return f"{x:+.1f}" if signed else f"{x:.1f}"


# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.markdown("**Gap fade · paper book**")
    session = st.date_input("Session", clock.session_date(), max_value=clock.session_date(), key="session_date")
    n_days = st.slider("History (sessions)", 5, 120, 40)
    auto = st.toggle("Auto-refresh every 30s", value=False)
    st.divider()
    view = data.live_view(store(), session, n_days)
    if view["kill_switch"]:
        st.error("Kill switch is ENGAGED. No orders will be sent.")
        if st.button("Release kill switch", type="primary"):
            data.kill(False)
            st.rerun()
    else:
        if st.button("Engage kill switch"):
            data.kill(True)
            st.rerun()
    st.caption(f"store: {view['store_kind']} · broker: {view['broker']} · ${view['notional_per_side']:,.0f} per side")

if auto:
    @st.fragment(run_every=30)
    def _tick():
        st.rerun()
    _tick()

st.title("Paid to hold the bag")
st.caption(f"VIX-gated opening-auction gap fade · session {session} · threshold VIX {view['vix_threshold']:g}")

tab_live, tab_ai, tab_session, tab_research, tab_replay, tab_eightk, tab_filing = st.tabs(
    ["Today", "AI War Room", "Session detail", "Research", "Replay", "8-K daily", "Filing Edge"])

# ---------------------------------------------------------------- today
with tab_live:
    g = view["gate"]
    hist = view["history"]
    traded = hist[hist["gate_on"].astype(bool)] if len(hist) else hist
    tiles = [
        ("Gate", ("ON" if g["on"] else "OFF") if g else "—", (g["source"] if g else "pre-open has not run")),
        ("VIX (t−1)", f"{g['vix']:.2f}" if g else "—", f"as of {g['vix_as_of']}" if g else None),
        ("VIX / VIX3M", f"{g['vix']/g['vix3m']:.3f}" if g and g["vix3m"] else "—",
         ("backwardation" if g["vix"] > g["vix3m"] else "contango") if g and g["vix3m"] else ("no VIX3M" if g else None)),
        ("Universe", f"{g['n_universe']} names" if g else "—", None),
        ("Net, traded sessions", f"${traded['net_pnl'].sum():+,.0f}" if len(traded) else "—",
         f"{len(traded)} sessions, mean {_bps(traded['net_bps'].mean())} bps" if len(traded) else None),
    ]
    for col, (label, value, delta) in zip(st.columns(5), tiles):
        col.metric(label, value, delta)

    if g:
        st.info(g["reason"]) if g["on"] else st.warning(g["reason"])

    left, right = st.columns([3, 2])
    with left:
        st.subheader("P&L by session")
        if len(hist):
            st.line_chart(hist.set_index("session_date")[["cum_net"]].rename(columns={"cum_net": "cumulative net, $"}), height=220)
            show = hist[["session_date", "gate_on", "vix_lag", "gross_bps", "cost_bps", "net_bps", "realised_spread_bps",
                         "basket_overlap", "shortfall_bps", "net_pnl"]].copy()
            show["gate_on"] = show["gate_on"].map(lambda x: "ON" if x else "off")
            show["basket_overlap"] = show["basket_overlap"].map(lambda x: None if pd.isna(x) else f"{x:.0%}")
            st.dataframe(show.rename(columns={"session_date": "date", "gate_on": "gate", "vix_lag": "VIX−1",
                                              "gross_bps": "gross bps", "cost_bps": "cost bps", "net_bps": "net bps",
                                              "realised_spread_bps": "rule book bps", "basket_overlap": "overlap",
                                              "shortfall_bps": "shortfall bps", "net_pnl": "net $"}),
                         hide_index=True, width="stretch",
                         column_config={"date": st.column_config.DateColumn(),
                                        "gross bps": st.column_config.NumberColumn(format="%.1f"),
                                        "cost bps": st.column_config.NumberColumn(format="%.1f"),
                                        "net bps": st.column_config.NumberColumn(format="%+.1f"),
                                        "rule book bps": st.column_config.NumberColumn(format="%+.1f"),
                                        "shortfall bps": st.column_config.NumberColumn(format="%+.1f"),
                                        "net $": st.column_config.NumberColumn(format="$%+,.0f"),
                                        "VIX−1": st.column_config.NumberColumn(format="%.2f")})
        else:
            st.info("No sessions recorded yet. Use the Replay tab to run a past session, or wait for the scheduler.")
    with right:
        st.subheader("Steps today")
        if len(view["steps"]):
            st.dataframe(view["steps"][["step", "status", "ts"]], hide_index=True, width="stretch")
        else:
            st.caption("No steps recorded for this session.")
        st.subheader("Risk events")
        ev = view["risk_events"]
        if len(ev):
            for r in ev.head(8).itertuples():
                (st.error if r.level == "block" else st.warning)(f"{str(r.ts)[:16]} · {r.step}/{r.check_name} — {r.message}")
        else:
            st.caption("None.")

    st.subheader("Positions")
    pos = view["positions"]
    if len(pos):
        marked, err = data.marks(feed(), pos)
        if err:
            st.warning(f"marks unavailable: {err}")
        gross = (marked["qty"].abs() * marked["avg_price"]).sum()
        m1, m2, m3 = st.columns(3)
        m1.metric("Names", f"{(marked['qty'] > 0).sum()} long / {(marked['qty'] < 0).sum()} short")
        m2.metric("Gross", f"${gross:,.0f}")
        if "mark_pnl" in marked:
            pnl = marked["mark_pnl"].sum()
            m3.metric("Marked P&L", f"${pnl:+,.0f}", f"{pnl/gross:.2%} of gross" if gross else None)
        st.dataframe(marked.sort_values("notional", ascending=False), width="stretch",
                     column_config={"avg_price": st.column_config.NumberColumn(format="$%.2f"),
                                    "last": st.column_config.NumberColumn(format="$%.2f"),
                                    "notional": st.column_config.NumberColumn(format="$%,.0f"),
                                    "mark_pnl": st.column_config.NumberColumn(format="$%+,.0f")})
    else:
        st.caption("Flat. The book holds nothing overnight, and nothing at all on days the gate is off.")

# ---------------------------------------------------------------- AI war room
with tab_ai:
    st.subheader("AI War Room · Gemini × ElevenLabs")
    st.caption(
        "Ask the deterministic dashboard by text or voice. ElevenLabs Scribe transcribes voice; "
        "Gemini answers only from stored live/research state; ElevenLabs can read the grounded answer back. "
        "This layer cannot create signals, change parameters, or place orders."
    )
    if not SETTINGS.gemini_api_key:
        st.warning("Set GEMINI_API_KEY to enable grounded Q&A.")
    if not SETTINGS.elevenlabs_api_key:
        st.info("Set ELEVENLABS_API_KEY to enable voice questions, spoken answers, and the two-voice briefing.")

    qcol, vcol = st.columns([3, 2])
    with qcol:
        typed_question = st.text_area(
            "Ask the desk",
            placeholder="Why is the gate off today? What changed versus recent traded sessions? What risk event needs review?",
            height=110,
            key="war_room_question",
        )
        ask_text = st.button("Ask Gemini", type="primary", disabled=not bool(SETTINGS.gemini_api_key))
    with vcol:
        voice_question = st.audio_input("Or record a voice question")
        ask_voice = st.button(
            "Transcribe + ask",
            disabled=(voice_question is None or not SETTINGS.gemini_api_key or not SETTINGS.elevenlabs_api_key),
        )

    if ask_text or ask_voice:
        try:
            from live.ai_war_room import ask as ai_ask, transcribe as ai_transcribe
            question = typed_question.strip()
            if ask_voice and voice_question is not None:
                with st.spinner("Transcribing with ElevenLabs Scribe…"):
                    question = ai_transcribe(voice_question.getvalue(), getattr(voice_question, "type", "audio/wav"))
                st.session_state["war_room_transcript"] = question
            with st.spinner("Gemini is reading the project state…"):
                result = ai_ask(store(), session, question)
            st.session_state["war_room_result"] = result
            st.session_state["war_room_last_question"] = question
            st.session_state.pop("war_room_audio", None)
        except Exception as e:  # noqa: BLE001
            st.error(f"{type(e).__name__}: {str(e)[:350]}")

    if st.session_state.get("war_room_transcript"):
        st.caption(f"Voice transcript: {st.session_state['war_room_transcript']}")

    answer = st.session_state.get("war_room_result")
    if answer:
        st.markdown("### Grounded answer")
        st.write(answer["answer"])
        a, b = st.columns(2)
        with a:
            st.markdown("**Evidence used**")
            for item in answer.get("evidence", []):
                st.markdown(f"- {item}")
        with b:
            st.markdown("**Risk flags**")
            flags = answer.get("risk_flags", [])
            if flags:
                for item in flags:
                    st.markdown(f"- {item}")
            else:
                st.caption("No additional AI-identified flags beyond the supplied state.")
        if answer.get("follow_ups"):
            st.caption("Suggested follow-ups: " + " · ".join(answer["follow_ups"]))
        st.caption(f"Model: {answer.get('model', SETTINGS.gemini_model)} · grounded only in this repository's state")
        if st.button("Speak this answer", disabled=not bool(SETTINGS.elevenlabs_api_key)):
            try:
                from live.ai_war_room import speak as ai_speak
                with st.spinner("Generating low-latency ElevenLabs audio…"):
                    st.session_state["war_room_audio"] = ai_speak(answer["answer"])
            except Exception as e:  # noqa: BLE001
                st.error(f"{type(e).__name__}: {str(e)[:300]}")
        if st.session_state.get("war_room_audio"):
            st.audio(st.session_state["war_room_audio"], format="audio/mp3")

    st.divider()
    st.markdown("### Two-voice risk committee")
    st.caption(
        "A portfolio-manager / risk-officer dialogue generated by ElevenLabs from a deterministic transcript. "
        "The script is built from the store before audio generation, so performance numbers are not invented by a language model."
    )
    if st.button("Generate risk committee audio", disabled=not bool(SETTINGS.elevenlabs_api_key)):
        try:
            from live.ai_war_room import dialogue as ai_dialogue
            with st.spinner("Generating two-speaker ElevenLabs dialogue…"):
                audio, script = ai_dialogue(store(), session)
            st.session_state["risk_committee_audio"] = audio
            st.session_state["risk_committee_script"] = script
        except Exception as e:  # noqa: BLE001
            st.error(f"{type(e).__name__}: {str(e)[:350]}")
    if st.session_state.get("risk_committee_audio"):
        st.audio(st.session_state["risk_committee_audio"], format="audio/mp3")
        with st.expander("Read the exact deterministic transcript"):
            for turn in st.session_state.get("risk_committee_script", []):
                st.markdown(f"**{turn['role']}:** {turn['text']}")


# ---------------------------------------------------------------- session
with tab_session:
    st.subheader(f"Targets and orders · {session}")
    tgt = view["targets"]
    if len(tgt):
        a, b = st.columns(2)
        a.metric("Long leg", f"{(tgt['side'] == 1).sum()} names", f"${(tgt.loc[tgt['side'] == 1, 'target_notional']).sum():,.0f}")
        b.metric("Short leg", f"{(tgt['side'] == -1).sum()} names", f"${-(tgt.loc[tgt['side'] == -1, 'target_notional']).sum():,.0f}")
        st.dataframe(tgt[["est_gap_bps", "relgap", "pct_rank", "side", "target_qty", "target_notional", "est_source"]]
                     .sort_values("relgap"), width="stretch",
                     column_config={"est_gap_bps": st.column_config.NumberColumn("est. gap bps", format="%+.0f"),
                                    "relgap": st.column_config.NumberColumn(format="%+.4f"),
                                    "pct_rank": st.column_config.NumberColumn(format="%.3f"),
                                    "target_notional": st.column_config.NumberColumn(format="$%,.0f")})
    else:
        st.caption("No signal recorded for this session (gate off, or pre-open not run).")
    od = view["orders"]
    if len(od):
        st.dataframe(od[["ts", "symbol", "side", "qty", "order_type", "status", "broker", "note"]], hide_index=True, width="stretch")

# ---------------------------------------------------------------- research
with tab_research:
    st.subheader("The research behind the rule")
    st.caption("Committed results from the pre-registered study. These do not change when the paper book trades.")
    rv = research()
    q = rv["vix_quintiles"]
    if q is not None:
        st.markdown("**Gross gap-fade spread by lagged-VIX quintile, in-sample (2005–2024).** The participation rule trades only when yesterday's VIX ≥ 20, which is roughly the top quintile.")
        st.bar_chart(q.set_index("vix_quintile")[["mean_bps"]].rename(columns={"mean_bps": "mean spread, bps/day"}), height=240)
        st.dataframe(q[["vix_quintile", "vix_lo", "vix_hi", "mean_bps", "se_bps", "ann_sharpe", "n_days"]], hide_index=True, width="stretch",
                     column_config={"mean_bps": st.column_config.NumberColumn("mean bps/day", format="%.1f"),
                                    "se_bps": st.column_config.NumberColumn("s.e.", format="%.2f"),
                                    "ann_sharpe": st.column_config.NumberColumn("gross Sharpe", format="%.2f"),
                                    "vix_lo": st.column_config.NumberColumn(format="%.1f"),
                                    "vix_hi": st.column_config.NumberColumn(format="%.1f")})
    figs = rv["figures"]
    if figs:
        st.markdown("**Figures from the note**")
        choice = st.selectbox("Figure", [f.name for f in figs], index=next((i for i, f in enumerate(figs) if "gapfade_equity_full" in f.name), 0))
        st.image(str(next(f for f in figs if f.name == choice)), width="stretch")
    panel = rv["panel"]
    if panel is not None:
        st.markdown("**Daily gross spread of the rule's book (bps), full sample.** The dashed line is the VIX threshold; markers are the sessions the paper book has replayed.")
        spread = (1e4 * panel.set_index("date")["spread_q"]).rename("gross spread bps")
        st.line_chart(spread.rolling(21).mean().rename("21-day mean, bps/day"), height=220)
        if len(hist):
            replayed = spread.reindex(pd.to_datetime(hist["session_date"]))
            st.caption(f"{len(hist)} replayed sessions vs the full-sample distribution: replayed mean {replayed.mean():+.1f} bps, full-sample mean {spread.mean():+.1f} bps.")

# ---------------------------------------------------------------- replay
with tab_replay:
    st.subheader("Replay a past session")
    st.caption("Runs the full cycle — gate, indicative prices from Nasdaq auction imbalance, orders, fills at the official prints, P&L, reconciliation — and writes it to the store. Idempotent: a session already recorded is left as is; use reset first to recompute it.")
    d = st.date_input("Session to replay", clock.session_date() - timedelta(days=1), max_value=clock.session_date(), key="replay_date")
    col_a, col_b = st.columns([1, 3])
    with col_a:
        go = st.button("Run replay", type="primary")
        reset = st.button("Reset this session")
    with col_b:
        if reset:
            store().reset_session(d)
            st.success(f"cleared {d}")
        if go:
            with st.spinner(f"replaying {d} (Databento imbalance query included, ~10s)…"):
                try:
                    res = data.replay_session(store(), d)
                    st.success(f"{d}: gate {'ON' if res.get('gate_on') else 'OFF'}, gross {_bps(res.get('gross_bps'))} bps, net {_bps(res.get('net_bps'))} bps, rule book {_bps(res.get('realised_spread_bps'))} bps")
                except Exception as e:  # noqa: BLE001 — surface to the operator, keep the app up
                    st.error(f"{type(e).__name__}: {str(e)[:300]}")
    st.divider()
    st.subheader("Briefing")
    st.caption("Gemini writes a short note from the dashboard numbers. It summarises; it decides nothing.")
    if st.button("Write briefing"):
        with st.spinner("writing…"):
            try:
                from live.briefing import write
                st.write(write(store(), session))
            except Exception as e:  # noqa: BLE001
                st.error(f"{type(e).__name__}: {str(e)[:300]}")

# ---------------------------------------------------------------- 8-K puts
with tab_eightk:
    st.subheader("Earlier 8-K study: daily last trades")
    st.caption("This is the last-trade study in HYPOTHESIS_8K.md. It failed its pre-registered test. It is not the Massive submission. The quote-level study is the Filing Edge tab, and that tab only replays saved results.")
    root = Path(__file__).resolve().parents[1] / "results"
    is_path, oos_path = root / "eightk_in_sample.json", root / "eightk_out_of_sample.json"
    if not is_path.exists() and not oos_path.exists():
        st.info("No 8-K results yet. The in-sample window is 2023-01-01 through 2025-12-31. Out of sample, 2026, is run once after that file is committed.")
    else:
        import json as _json
        for label, path in (("In-sample", is_path), ("Out-of-sample", oos_path)):
            if not path.exists():
                st.caption(f"{label}: not run.")
                continue
            doc = _json.loads(path.read_text())
            h = doc.get("horizons_event_minus_control_bps", {}).get("21", {})
            c1, c2, c3, c4 = st.columns(4)
            c1.metric(f"{label} filings", f"{doc.get('n_filings', 0)}")
            c2.metric("Headline events", f"{doc.get('n_events_headline', 0)}")
            c3.metric("With a price", f"{doc.get('n_events_with_entry_price', 0)}")
            mean = h.get("mean")
            c4.metric("21-session edge", f"{mean:+.1f} bps" if isinstance(mean, (int, float)) else "—",
                      f"n={h.get('n', 0)}")
            rows = []
            for horizon, stats in doc.get("horizons_event_minus_control_bps", {}).items():
                rows.append({"horizon": horizon, **stats})
            if rows:
                st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                             column_config={"mean": st.column_config.NumberColumn("event−control bps", format="%+.1f"),
                                            "lo": st.column_config.NumberColumn("95% lo", format="%+.1f"),
                                            "hi": st.column_config.NumberColumn("95% hi", format="%+.1f"),
                                            "t": st.column_config.NumberColumn(format="%+.2f")})
            brief = path.with_name("eightk_briefing_oos.txt" if "out_of_sample" in path.name else "eightk_briefing.txt")
            if brief.exists():
                st.caption(brief.read_text()[:1200])

# ---------------------------------------------------------------- Filing Edge (saved replay)
with tab_filing:
    st.subheader("Filing Edge · Massive study")
    st.caption(
        "Saved replay of the NBBO cash-secured put study. Development difference −186 bps. "
        "Held-out account lost $796 on $1 million. Decision: research only. "
        "Switching Development / Held-out test only changes which saved report is shown. "
        "It does not open the window again."
    )
    replay_url = filing_edge_replay()
    try:
        seen_host = (st.context.headers.get("Host") or "").split(":")[0]
    except Exception:
        seen_host = ""
    host = seen_host if seen_host and seen_host not in ("0.0.0.0",) else "127.0.0.1"
    page = f"http://{host}:{FILING_EDGE_PORT}/"
    st.link_button("Open Filing Edge", page)
    st.iframe(page, height=920)
    st.caption(f"Replay server: {replay_url}")
