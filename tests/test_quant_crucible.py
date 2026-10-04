"""Offline contracts for the five Quant Crucible hero features."""
from __future__ import annotations

import numpy as np
import pandas as pd

from live.agent import _fallback_plan
from live.black_box import inspect_research_day, research_sessions
from live.crucible import HypothesisSpec, run_red_team
from live.ghost_desk import run_ghost_desk
from live.market_intel import resolve_symbol, tradingview_symbol
from live.multiverse import Scenario, run_scenario


def test_crucible_runs_committed_red_team():
    r = run_red_team(HypothesisSpec())
    assert r["verdict"] in {"REJECT", "PROVISIONAL PASS", "ROBUST PASS"}
    assert 0 <= r["score"] <= 100
    assert len(r["checks"]) >= 8
    assert {"threshold", "sharpe", "mean_bps"} <= set(r["thresholds"].columns)
    assert len(r["bootstrap"]["samples"]) >= 500


def test_multiverse_returns_scenario_surface_and_paths():
    r = run_scenario(Scenario(n_paths=120, horizon_sessions=20))
    assert r["stress_sim"]["bands"].shape[0] == 20
    assert 0 <= r["stress_sim"]["p_loss"] <= 1
    assert "alpha_retention" in r["surface"].columns
    assert {"base", "stressed"} <= set(r["historical_equity"].columns)


def test_black_box_attribution_reconciles():
    worst = research_sessions(1)
    r = inspect_research_day(worst.index[0])
    assert abs(r["attribution"]["bps"].sum() - r["net_bps"]) < 1e-8
    assert "not an invented" in r["note"]


def test_ghost_desk_is_honest_about_both_sides():
    r = run_ghost_desk(notional_per_side=1_000_000)
    assert r["avoided_losses"] >= 0 and r["missed_gains"] >= 0
    assert len(r["summary"]) >= 4
    # Net value must reconcile to actual minus always-on counterfactual.
    assert abs(r["gate_net_value"] - (r["actual_dollars"] - r["always_dollars"])) < 1e-6


def test_market_symbol_and_voice_router_contracts():
    assert resolve_symbol("Google") == "GOOGL"
    assert resolve_symbol("gold") == "XAUUSD=X"
    assert tradingview_symbol("XAUUSD=X") == "OANDA:XAUUSD"
    assert _fallback_plan("Red-team the strategy", "GOOGL")["route"] == "crucible"
    assert _fallback_plan("What if volatility doubles and transaction costs triple?", "GOOGL")["route"] == "multiverse"
    assert _fallback_plan("Why is Google moving today?", "NVDA")["route"] == "company_research"


def test_frontend_view_model_is_json_serializable():
    import json
    from live.presentation import turn_to_view_model

    crucible = run_red_team(HypothesisSpec())
    vm = turn_to_view_model({
        "route": "crucible",
        "payload": crucible,
        "answer": "Red-team complete.",
        "symbol": "SPY",
        "question": "Red-team the strategy",
        "tool_trace": ["run_red_team"],
    })
    json.dumps(vm)
    assert vm["metrics"]
    assert vm["charts"]
    assert vm["tables"]
    assert vm["toolTrace"] == ["run_red_team"]


def test_contextual_followup_routes_compare_correctly():
    plan = _fallback_plan("compare with Meta", "GOOGL")
    assert plan["route"] == "compare"
    assert "GOOGL" in plan["symbols"]
    assert "META" in plan["symbols"]


def test_voice_api_health_contract_has_no_secrets():
    from live.voice_api import health

    h = health()
    assert h["ok"] is True
    assert h["agent"] == "shared-live.agent.execute_turn"
    assert "api_key" not in h
    assert "token" not in h


def test_market_vision_view_contract():
    import json
    from live.presentation import turn_to_view_model

    vm = turn_to_view_model({
        "route": "vision",
        "symbol": "GOOGL",
        "question": "What is important here?",
        "answer": "A breakout is visually present, but pixels are not a price feed.",
        "payload": {
            "snapshot": {
                "price": 200.0, "return_1d": -0.02, "return_20d": 0.05,
                "realized_vol_20d": 0.30, "move_sigma_60d": -1.4,
            },
            "observed_visual_features": ["large range candle"],
            "cautions": ["confirm with market data"],
            "suggested_next_actions": ["run an event study"],
        },
        "tool_trace": ["Gemini multimodal chart inspection"],
    })
    json.dumps(vm)
    assert vm["route"] == "vision"
    assert len(vm["metrics"]) == 5
    assert vm["tables"][0]["title"] == "Market Vision evidence"
