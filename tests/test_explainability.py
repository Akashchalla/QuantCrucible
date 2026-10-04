from datetime import date
from pathlib import Path

from live.agent import execute_turn
from live.settings import SETTINGS
from live.store import Store


def _store(tmp_path: Path) -> Store:
    return Store(url=None, sqlite_path=tmp_path / "live.sqlite")


def test_explain_day_contract(tmp_path, monkeypatch):
    monkeypatch.setattr(SETTINGS, "gemini_api_key", None)
    s = _store(tmp_path)
    try:
        t = execute_turn(s, date.today(), "Explain this day. What happened that day?", "GOOGL", ui_context={"module": "explain_day"})
        assert t["route"] == "explain_day"
        assert t["view_model"]["tables"]
    finally:
        s.close()


def test_profit_bridge_labels_hypothetical(tmp_path, monkeypatch):
    monkeypatch.setattr(SETTINGS, "gemini_api_key", None)
    s = _store(tmp_path)
    try:
        t = execute_turn(s, date.today(), "Where did our profit go?", "GOOGL", ui_context={"module": "profit_bridge"})
        assert t["route"] == "profit_bridge"
        rows = t["payload"]["bridge"].to_dict("records")
        assert any("HYPOTHETICAL" in r["status"] for r in rows)
    finally:
        s.close()


def test_replay_has_point_in_time_actions(tmp_path, monkeypatch):
    monkeypatch.setattr(SETTINGS, "gemini_api_key", None)
    s = _store(tmp_path)
    try:
        t = execute_turn(s, date.today(), "Start before the market opens for historical replay.", "GOOGL", ui_context={"module": "replay"})
        assert t["route"] == "replay"
        assert len(t["view_model"]["actions"]) == 3
    finally:
        s.close()


def test_research_trial_exposes_limitations(tmp_path, monkeypatch):
    monkeypatch.setattr(SETTINGS, "gemini_api_key", None)
    s = _store(tmp_path)
    try:
        t = execute_turn(s, date.today(), "Could missing delisted stocks affect the results?", "GOOGL", ui_context={"module": "research_trial"})
        assert t["route"] == "research_trial"
        assert "surviv" in t["answer"].lower()
        assert t["sources"]
    finally:
        s.close()


def test_scope_refuses_unrelated_question(tmp_path, monkeypatch):
    monkeypatch.setattr(SETTINGS, "gemini_api_key", None)
    s = _store(tmp_path)
    try:
        t = execute_turn(s, date.today(), "Who is PM?", "GOOGL", ui_context={"module": "live"})
        assert t["route"] == "scope_refusal"
        assert "specialized" in t["answer"].lower()
    finally:
        s.close()
