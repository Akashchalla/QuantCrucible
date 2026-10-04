"""HTTP companion API for the browser-based Quant Crucible voice workspace.

This server keeps API keys off the browser. It issues short-lived ElevenLabs WebRTC
conversation tokens, exposes the latest full-duplex voice turn for visualization, and
provides typed chat that calls the exact same Quant Crucible agent.

Run:
    uvicorn live.voice_api:app --host 0.0.0.0 --port 8780
"""
from __future__ import annotations

import base64
import binascii
import json
import os
from datetime import date
from pathlib import Path
from typing import Literal

import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from fastapi.responses import PlainTextResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from . import clock
from .agent import execute_turn
from .market_intel import analyze_chart_image, resolve_symbol
from .presentation import turn_to_view_model
from .realtime_voice_server import CONTEXT_PATH, EVENT_PATH, write_event
from .settings import SETTINGS
from .store import Store

TOKEN_URL = "https://api.elevenlabs.io/v1/convai/conversation/token"

app = FastAPI(title="Quant Crucible Voice API", version="1.0.0")
origins = [x.strip() for x in os.getenv("CRUCIBLE_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if x.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# Saved, read-only Massive/Filing Edge replay. Four internal pages are addressable by hash.
_filing_docs = SETTINGS.root / "filing_edge" / "docs"
if _filing_docs.exists():
    app.mount("/filing-edge", StaticFiles(directory=str(_filing_docs), html=True), name="filing-edge")


class ChatMessage(BaseModel):
    role: Literal["user", "assistant", "agent"] = "user"
    content: str = Field(min_length=1, max_length=3000)




class VoiceContextRequest(BaseModel):
    conversation_id: str = Field(min_length=1, max_length=200)
    symbol: str = Field(default="GOOGL", max_length=30)
    selected_date: str | None = Field(default=None, max_length=20)
    module: str | None = Field(default=None, max_length=40)
    user_name: str | None = Field(default=None, max_length=80)



class VisionRequest(BaseModel):
    image_base64: str = Field(min_length=16)
    mime_type: str = Field(default="image/png", max_length=80)
    question: str = Field(default="What is visually important in this chart?", min_length=1, max_length=1500)
    symbol: str = Field(default="GOOGL", max_length=30)


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1800)
    symbol: str = Field(default="GOOGL", max_length=30)
    session: date | None = None
    selected_date: str | None = Field(default=None, max_length=20)
    module: str | None = Field(default=None, max_length=40)
    last_route: str | None = Field(default=None, max_length=40)
    user_name: str | None = Field(default=None, max_length=80)
    history: list[ChatMessage] = Field(default_factory=list, max_length=20)


@app.get("/health")
def health() -> dict:
    return {
        "ok": True,
        "gemini": bool(SETTINGS.gemini_api_key),
        "elevenlabs": bool(SETTINGS.elevenlabs_api_key),
        "speech_engine_id": bool(os.getenv("ELEVENLABS_SPEECH_ENGINE_ID")),
        "market_data": "Massive live + yfinance history/fallback",
        "agent": "shared-live.agent.execute_turn",
    }


@app.get("/api/token")
def get_token() -> dict:
    api_key = SETTINGS.elevenlabs_api_key
    engine_id = os.getenv("ELEVENLABS_SPEECH_ENGINE_ID")
    if not api_key or not engine_id:
        raise HTTPException(503, "ELEVENLABS_API_KEY and ELEVENLABS_SPEECH_ENGINE_ID are required")
    try:
        r = requests.get(
            TOKEN_URL,
            params={"agent_id": engine_id},
            headers={"xi-api-key": api_key},
            timeout=30,
        )
    except requests.RequestException as e:
        raise HTTPException(502, f"ElevenLabs token request failed: {e}") from e
    if r.status_code >= 400:
        raise HTTPException(r.status_code, f"ElevenLabs token HTTP {r.status_code}: {r.text[:220]}")
    doc = r.json()
    if not doc.get("token"):
        raise HTTPException(502, "ElevenLabs token response did not contain a token")
    return {"token": doc["token"], "conversation_id": doc.get("conversation_id")}


@app.post("/api/voice-context")
def voice_context(req: VoiceContextRequest) -> dict:
    from .market_intel import resolve_symbol
    symbol = resolve_symbol(req.symbol, "GOOGL")
    CONTEXT_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        doc = json.loads(CONTEXT_PATH.read_text()) if CONTEXT_PATH.exists() else {}
    except (OSError, json.JSONDecodeError):
        doc = {}
    prior = doc.get(req.conversation_id) or {}
    doc[req.conversation_id] = {
        **prior,
        "symbol": symbol,
        "date": req.selected_date or prior.get("date"),
        "module": req.module or prior.get("module"),
        "user_name": req.user_name or prior.get("user_name"),
    }
    tmp = CONTEXT_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc))
    tmp.replace(CONTEXT_PATH)
    return {"ok": True, **doc[req.conversation_id]}


@app.post("/api/chat")
def chat(req: ChatRequest) -> dict:
    store = Store()
    try:
        context = [{"role": m.role, "content": m.content} for m in req.history[-10:]]
        turn = execute_turn(
            store, req.session or clock.session_date(), req.question, req.symbol, context=context,
            ui_context={
                "date": req.selected_date, "module": req.module,
                "last_route": req.last_route, "user_name": req.user_name,
            },
        )
        write_event(turn, req.question, conversation_id="typed-chat")
        return turn["view_model"]
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"{type(e).__name__}: {str(e)[:500]}") from e
    finally:
        store.close()




@app.post("/api/vision")
def vision(req: VisionRequest) -> dict:
    """Analyze a user-supplied chart screenshot with Gemini multimodal reasoning.

    The image is visual context only. Numerical price/return claims still come from the
    market-data snapshot embedded by :func:`analyze_chart_image`.
    """
    raw = req.image_base64
    if "," in raw and raw.lstrip().startswith("data:"):
        raw = raw.split(",", 1)[1]
    try:
        image = base64.b64decode(raw, validate=True)
    except (ValueError, binascii.Error) as e:
        raise HTTPException(400, "image_base64 is not valid base64") from e
    symbol = resolve_symbol(req.symbol, "GOOGL")
    try:
        doc = analyze_chart_image(image, req.mime_type, symbol, req.question)
        turn = {
            "route": "vision",
            "symbol": symbol,
            "question": req.question,
            "answer": doc.get("summary", "Chart analysis complete."),
            "speech": doc.get("summary", "Chart analysis complete."),
            "payload": doc,
            "sources": [],
            "tool_trace": [
                "Gemini multimodal chart inspection",
                "authoritative numerical market snapshot",
                "visual-vs-numerical evidence boundary",
            ],
        }
        turn["view_model"] = turn_to_view_model(turn)
        write_event(turn, req.question, conversation_id="market-vision")
        return turn["view_model"]
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"{type(e).__name__}: {str(e)[:500]}") from e


@app.get("/api/latest-turn")
def latest_turn() -> dict:
    if not EVENT_PATH.exists():
        return {"ready": False, "view_model": None}
    try:
        doc = json.loads(EVENT_PATH.read_text())
    except (OSError, json.JSONDecodeError) as e:
        raise HTTPException(500, f"Could not read latest turn: {e}") from e
    return {"ready": True, **doc}


@app.delete("/api/latest-turn")
def clear_latest_turn() -> dict:
    try:
        EVENT_PATH.unlink(missing_ok=True)
    except OSError as e:
        raise HTTPException(500, str(e)) from e
    return {"ok": True}


@app.get("/api/document/{doc_path:path}", response_class=PlainTextResponse)
def local_document(doc_path: str):
    """Read-only view of allow-listed committed research documents/evidence."""
    allowed = {
        "HYPOTHESIS.md", "HYPOTHESIS_B.md", "HYPOTHESIS_C.md", "HYPOTHESIS_8K.md",
        "QUANT_CRUCIBLE.md", "IMPLEMENTATION_STATUS.md",
        "results/gapfade_out_of_sample.json", "results/pricing_out_of_sample.json",
        "results/eightk_out_of_sample.json", "results/out_of_sample.json",
        "results/REPORT.md", "results/REPORT_B.md", "results/REPORT_C.md",
        "live/signal.py", "live/risk.py", "live/pipeline.py", "live/crucible.py",
        "live/multiverse.py", "live/black_box.py", "live/ghost_desk.py",
        "live/explainability.py", "live/feeds/massive.py", "live/market_intel.py",
        "filing_edge/HYPOTHESIS.md", "filing_edge/README.md", "filing_edge/BUILD_STATUS.md",
        "filing_edge/submission/results-summary.json", "filing_edge/submission/research-manifest.json",
    }
    if doc_path not in allowed:
        raise HTTPException(404, "Document not available")
    path = (SETTINGS.root / doc_path).resolve()
    if not path.exists() or SETTINGS.root.resolve() not in path.parents:
        raise HTTPException(404, "Document not found")
    return PlainTextResponse(path.read_text(errors="replace"), media_type="text/plain; charset=utf-8")


@app.get("/api/systematic-trading-note")
def systematic_trading_note():
    path = SETTINGS.root / "filing_edge" / "submission" / "Systematic_Trading_Note.pdf"
    if not path.exists():
        raise HTTPException(404, "Systematic Trading note not found")
    return FileResponse(path, media_type="application/pdf", filename="Systematic_Trading_Note.pdf")

@app.get("/api/massive-research-note")
def massive_research_note():
    path = SETTINGS.root / "filing_edge" / "submission" / "Massive_Research_Note.pdf"
    if not path.exists():
        raise HTTPException(404, "Massive research note not found")
    return FileResponse(path, media_type="application/pdf", filename="Massive_Research_Note.pdf")


@app.get("/")
def root() -> dict:
    return {
        "name": "Quant Crucible Voice API",
        "voice_ui": "Run `cd voice_ui && npm install && npm run dev` and open http://localhost:5173",
        "health": "/health",
    }
