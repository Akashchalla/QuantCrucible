from __future__ import annotations

from pathlib import Path

from live.agent import _fallback_plan
from live.realtime_voice_server import _maybe_capture_name


def test_exact_reported_voice_failures_route_without_clarification():
    cases = {
        "Repaying costs and risks.": "project_state",
        "Live paper trading system.": "project_state",
        "V- VIX tool.": "project_state",
        "Um, what's the Apple, um...": "market_snapshot",
        "AAPL": "market_snapshot",
    }
    for utterance, expected in cases.items():
        plan = _fallback_plan(utterance, "GOOGL")
        assert plan["route"] == expected, (utterance, plan)
    assert _fallback_plan("Um, what's the Apple, um...", "GOOGL")["symbol"] == "AAPL"


def test_short_followups_use_last_analytical_route_not_visual_live_tab():
    ui = {"module": "live", "last_route": "project_state"}
    assert _fallback_plan("Show me the evidence", "GOOGL", ui_context=ui)["route"] == "project_state"
    assert _fallback_plan("Explain that", "GOOGL", ui_context=ui)["route"] == "project_state"
    assert _fallback_plan("Why?", "GOOGL", ui_context=ui)["route"] == "project_state"

    ui = {"module": "live", "last_route": "crucible"}
    assert _fallback_plan("Explain more simply", "GOOGL", ui_context=ui)["route"] == "crucible"

    ui = {"module": "live", "last_route": "research_trial"}
    assert _fallback_plan("Go deeper", "GOOGL", ui_context=ui)["route"] == "research_trial"


def test_name_capture_never_swallows_finance_question():
    assert _maybe_capture_name("Srinivas", first_user_turn=True) == "Srinivas"
    assert _maybe_capture_name("My name is Srinivas", first_user_turn=True) == "Srinivas"
    assert _maybe_capture_name("VIX tool", first_user_turn=True) is None
    assert _maybe_capture_name("Apple stock", first_user_turn=True) is None
    assert _maybe_capture_name("What is Apple doing?", first_user_turn=True) is None
    assert _maybe_capture_name("Srinivas", first_user_turn=False) is None


def test_live_cost_and_risk_phrasing_is_high_confidence():
    for q in ["costs", "risk", "execution cost", "slippage", "kill switch", "risk controls"]:
        p = _fallback_plan(q, "GOOGL")
        assert p["route"] == "project_state", (q, p)
        assert p["_locked"] is True


def test_counterfactual_risk_language_still_goes_to_ghost():
    for q in ["what if we had no gate", "without the gate", "opportunity cost of the VIX gate", "counterfactual risk controls"]:
        assert _fallback_plan(q, "GOOGL")["route"] == "ghost"


def test_voice_context_visual_tab_does_not_erase_last_route(tmp_path, monkeypatch):
    import json
    import live.voice_api as api

    path = tmp_path / "ctx.json"
    path.write_text(json.dumps({"cid": {"symbol": "GOOGL", "module": "live", "last_route": "project_state"}}))
    monkeypatch.setattr(api, "CONTEXT_PATH", path)
    req = api.VoiceContextRequest(conversation_id="cid", symbol="GOOGL", module="live")
    out = api.voice_context(req)
    assert out["last_route"] == "project_state"
    assert json.loads(path.read_text())["cid"]["last_route"] == "project_state"


def test_project_state_view_model_surfaces_live_evidence():
    from live.presentation import turn_to_view_model

    vm = turn_to_view_model({
        "route": "project_state",
        "symbol": "GOOGL",
        "question": "VIX tool",
        "answer": "grounded",
        "payload": {
            "strategy_contract": {
                "name": "VIX-gated opening-auction gap fade",
                "vix_threshold": 30,
                "notional_per_side_usd": 1_000_000,
            },
            "today": {"on": False, "vix": 31.4},
            "kill_switch": False,
            "recent_pnl": [{"session_date": "2026-10-01", "net_bps": 3.2}],
            "risk_events": [{"level": "review", "message": "example"}],
            "targets": [],
            "orders": [],
        },
    })
    labels = {m["label"] for m in vm["metrics"]}
    assert {"VIX threshold", "Lagged VIX", "Gate", "Per-side notional", "Kill switch"} <= labels
    assert any(t["title"] == "Recent live paper P&L" for t in vm["tables"])
    assert any(t["title"] == "Live strategy contract" for t in vm["tables"])
