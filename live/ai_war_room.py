"""Gemini + ElevenLabs voice copilot for the live systematic-trading dashboard.

Design principles:
- AI never creates/changes a trading signal, order, sizing rule or risk limit.
- Gemini receives a compact snapshot of deterministic state and must ground every answer in it.
- ElevenLabs is used for voice I/O only: Scribe v2 for questions and low-latency TTS for answers.
- A two-voice "risk committee" briefing is generated from a deterministic script so audio cannot
  silently invent performance numbers.
"""
from __future__ import annotations

import json
import math
import re
from datetime import date
from typing import Any

import pandas as pd
import requests

from .dashboard_data import live_view, research_view
from .settings import SETTINGS
from .store import Store

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
ELEVEN_STT_URL = "https://api.elevenlabs.io/v1/speech-to-text"
ELEVEN_TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice}/stream"
ELEVEN_DIALOGUE_URL = "https://api.elevenlabs.io/v1/text-to-dialogue"

SYSTEM = """You are the AI risk copilot inside a systematic-trading operator dashboard.
You may explain, compare, summarize, identify anomalies, and suggest what a HUMAN should inspect.
You MUST use only the supplied PROJECT_STATE. Never use remembered market facts, news, prices,
company facts, or future information. Never invent a number. Never recommend a trade, change a
parameter, place an order, or imply that you did. If PROJECT_STATE does not contain the answer,
say that clearly.

Return JSON only with this exact shape:
{
  "answer": "concise answer for the operator",
  "evidence": ["2-5 short facts copied or faithfully paraphrased from PROJECT_STATE"],
  "risk_flags": ["important caveats/anomalies, or empty"],
  "follow_ups": ["up to 3 useful grounded questions the operator could ask next"]
}
"""


def _clean(value: Any) -> Any:
    """Make dashboard objects JSON-safe, bounded, and readable for model context."""
    if value is None:
        return None
    if isinstance(value, (date, pd.Timestamp)):
        return str(value)
    if isinstance(value, (bool, str, int)):
        return value
    if isinstance(value, float):
        return None if not math.isfinite(value) else round(value, 6)
    if hasattr(value, "item"):
        try:
            return _clean(value.item())
        except Exception:
            pass
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    return str(value)


def _records(frame: pd.DataFrame | None, columns: list[str] | None = None, limit: int = 12) -> list[dict]:
    if frame is None or not len(frame):
        return []
    f = frame.copy()
    if columns:
        f = f[[c for c in columns if c in f.columns]]
    return [_clean(r) for r in f.head(limit).to_dict(orient="records")]


def project_state(store: Store, session: date) -> dict:
    """Compact deterministic state made available to Gemini. No external facts are included."""
    live = live_view(store, session, n_days=20)
    research = research_view()
    hist = live["history"]
    risk_events = live["risk_events"]
    targets = live["targets"]
    orders = live["orders"]

    state = {
        "session": str(session),
        "strategy_contract": {
            "name": "VIX-gated opening-auction gap fade",
            "vix_threshold": live["vix_threshold"],
            "notional_per_side_usd": live["notional_per_side"],
            "rule": "long bottom quintile of market-relative opening gaps; short top quintile; flat by close",
            "ai_boundary": "AI is explanatory only and cannot change signal, sizing, risk, or execution",
        },
        "today": _clean(live["gate"]),
        "kill_switch": bool(live["kill_switch"]),
        "recent_pnl": _records(hist, ["session_date", "gate_on", "vix_lag", "gross_bps", "cost_bps", "net_bps", "net_pnl", "shortfall_bps"], 12),
        "risk_events": _records(risk_events, ["ts", "level", "step", "check_name", "message"], 12),
        "targets": _records(targets.reset_index() if targets is not None and len(targets) else targets,
                            ["symbol", "est_gap_bps", "relgap", "pct_rank", "side", "target_qty", "target_notional", "est_source"], 10),
        "orders": _records(orders, ["ts", "symbol", "side", "qty", "order_type", "status", "broker", "note"], 10),
        "research": {
            "in_sample": _clean(research.get("in_sample")),
            "out_of_sample": _clean(research.get("out_of_sample")),
            "vix_quintiles": _records(research.get("vix_quintiles"), limit=8),
        },
    }
    # Hard bound context size while keeping the most operationally useful fields.
    encoded = json.dumps(state, separators=(",", ":"), default=str)
    if len(encoded) > 70_000:
        state["research"]["in_sample"] = "omitted from prompt because the committed JSON is large"
        state["research"]["out_of_sample"] = "omitted from prompt because the committed JSON is large"
    return state


def _gemini_json(question: str, state: dict) -> dict:
    if not SETTINGS.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY missing from .env")
    model = SETTINGS.gemini_model
    if not re.fullmatch(r"[A-Za-z0-9._-]+", model):
        raise RuntimeError("invalid GEMINI_MODEL")
    payload = {
        "systemInstruction": {"parts": [{"text": SYSTEM}]},
        "contents": [{"role": "user", "parts": [{"text": "QUESTION:\n" + question + "\n\nPROJECT_STATE:\n" + json.dumps(state, default=str)}]}],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 1800,
            "responseMimeType": "application/json",
            "responseSchema": {
                "type": "OBJECT",
                "properties": {
                    "answer": {"type": "STRING"},
                    "evidence": {"type": "ARRAY", "items": {"type": "STRING"}},
                    "risk_flags": {"type": "ARRAY", "items": {"type": "STRING"}},
                    "follow_ups": {"type": "ARRAY", "items": {"type": "STRING"}},
                },
                "required": ["answer", "evidence", "risk_flags", "follow_ups"],
            },
        },
    }
    r = requests.post(GEMINI_URL.format(model=model), headers={"x-goog-api-key": SETTINGS.gemini_api_key}, json=payload, timeout=60)
    if r.status_code >= 400:
        raise RuntimeError(f"Gemini HTTP {r.status_code}: {r.text[:180]}")
    try:
        parts = r.json()["candidates"][0]["content"]["parts"]
        doc = json.loads("".join(p.get("text", "") for p in parts))
        if not isinstance(doc.get("answer"), str):
            raise ValueError
        for key in ("evidence", "risk_flags", "follow_ups"):
            if not isinstance(doc.get(key), list) or any(not isinstance(x, str) for x in doc[key]):
                raise ValueError
        doc["model"] = r.json().get("modelVersion", model)
        return doc
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError):
        raise RuntimeError("Gemini returned an invalid structured copilot response") from None


def ask(store: Store, session: date, question: str) -> dict:
    question = (question or "").strip()
    if not question:
        raise ValueError("Ask a question first.")
    if len(question) > 1200:
        raise ValueError("Question is too long (max 1,200 characters).")
    return _gemini_json(question, project_state(store, session))


def transcribe(audio: bytes, mime_type: str = "audio/wav") -> str:
    """ElevenLabs Scribe v2 transcription for a short operator question."""
    if not SETTINGS.elevenlabs_api_key:
        raise RuntimeError("ELEVENLABS_API_KEY missing from .env")
    if not audio or len(audio) > 12_000_000:
        raise ValueError("Voice question must be between 1 byte and 12 MB.")
    files = {"file": ("question.wav", audio, mime_type or "audio/wav")}
    data = {"model_id": SETTINGS.elevenlabs_stt_model}
    r = requests.post(ELEVEN_STT_URL, headers={"xi-api-key": SETTINGS.elevenlabs_api_key}, files=files, data=data, timeout=90)
    if r.status_code >= 400:
        raise RuntimeError(f"ElevenLabs STT HTTP {r.status_code}: {r.text[:160]}")
    text = (r.json().get("text") or "").strip()
    if not text:
        raise RuntimeError("ElevenLabs did not return a transcript.")
    return text


def speak(text: str) -> bytes:
    """Low-latency ElevenLabs TTS for a Gemini copilot answer."""
    if not SETTINGS.elevenlabs_api_key:
        raise RuntimeError("ELEVENLABS_API_KEY missing from .env")
    voice = SETTINGS.elevenlabs_voice_id
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", voice):
        raise RuntimeError("invalid ELEVENLABS_VOICE_ID")
    body = {
        "text": text[:3500],
        "model_id": SETTINGS.elevenlabs_tts_model,
        "voice_settings": {"stability": 0.55, "similarity_boost": 0.75, "speed": 1.03},
    }
    r = requests.post(ELEVEN_TTS_URL.format(voice=voice), params={"output_format": "mp3_44100_128"},
                      headers={"xi-api-key": SETTINGS.elevenlabs_api_key, "accept": "audio/mpeg"}, json=body, timeout=90)
    if r.status_code >= 400:
        raise RuntimeError(f"ElevenLabs TTS HTTP {r.status_code}: {r.text[:160]}")
    if len(r.content) < 500:
        raise RuntimeError("ElevenLabs returned an invalid audio payload.")
    return r.content


def risk_committee_script(store: Store, session: date) -> list[dict]:
    """Deterministic two-speaker script. Numbers come from the store, not an LLM."""
    v = live_view(store, session, n_days=20)
    gate = v["gate"]
    hist = v["history"]
    traded = hist[hist["gate_on"].astype(bool)] if hist is not None and len(hist) else hist
    gate_line = "Pre-open gate state is not available yet."
    if gate:
        gate_line = f"The gate is {'on' if gate['on'] else 'off'}. Lagged VIX is {gate['vix']:.2f} versus the threshold {v['vix_threshold']:.0f}. {gate['reason']}"
    perf_line = "There are no recorded traded sessions in the recent history."
    if traded is not None and len(traded):
        perf_line = f"Across {len(traded)} recent gate-on sessions, cumulative net P and L is {traded['net_pnl'].sum():+.0f} dollars and mean net return is {traded['net_bps'].mean():+.1f} basis points per session."
    risks = v["risk_events"]
    risk_line = "No recent risk events are recorded."
    if risks is not None and len(risks):
        top = risks.iloc[0]
        risk_line = f"The most recent risk event is {top.get('level','review')}: {top.get('check_name','check')}. {top.get('message','')}"
    return [
        {"role": "Portfolio manager", "text": "Give me the operating state for this session."},
        {"role": "Risk officer", "text": gate_line},
        {"role": "Portfolio manager", "text": "How has the rule behaved in the sessions we actually recorded?"},
        {"role": "Risk officer", "text": perf_line},
        {"role": "Portfolio manager", "text": "What needs human attention before we trust the dashboard?"},
        {"role": "Risk officer", "text": risk_line + " AI is explanation only; the pre-registered strategy and risk controls remain deterministic."},
    ]


def dialogue(store: Store, session: date) -> tuple[bytes, list[dict]]:
    """Generate an expressive two-voice risk-committee clip with ElevenLabs Text to Dialogue."""
    if not SETTINGS.elevenlabs_api_key:
        raise RuntimeError("ELEVENLABS_API_KEY missing from .env")
    script = risk_committee_script(store, session)
    voices = [SETTINGS.elevenlabs_voice_id, SETTINGS.elevenlabs_risk_voice_id]
    inputs = []
    for i, turn in enumerate(script):
        inputs.append({"text": turn["text"], "voice_id": voices[i % 2]})
    r = requests.post(ELEVEN_DIALOGUE_URL, params={"output_format": "mp3_44100_128"},
                      headers={"xi-api-key": SETTINGS.elevenlabs_api_key, "accept": "audio/mpeg"},
                      json={"inputs": inputs, "model_id": SETTINGS.elevenlabs_dialogue_model}, timeout=120)
    if r.status_code >= 400:
        raise RuntimeError(f"ElevenLabs dialogue HTTP {r.status_code}: {r.text[:160]}")
    if len(r.content) < 800:
        raise RuntimeError("ElevenLabs returned an invalid dialogue audio payload.")
    return r.content, script
