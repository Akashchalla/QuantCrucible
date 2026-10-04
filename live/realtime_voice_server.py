"""Full-duplex ElevenLabs Speech Engine gateway for Quant Crucible.

ElevenLabs owns microphone STT, turn detection, interruption handling and TTS. This
server owns the intelligence layer and calls the same :func:`live.agent.execute_turn`
used by text chat. Every completed turn is written to a small JSON event file so the
browser workspace can render charts/tables in sync with the spoken answer.

Run after creating a Speech Engine resource:
    python -m live.realtime_voice_server
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from . import clock
from .agent import execute_turn
from .presentation import turn_to_view_model
from .settings import SETTINGS
from .store import Store

load_dotenv(SETTINGS.root / ".env")
EVENT_PATH = SETTINGS.root / "live" / "state" / "realtime_voice_last.json"
CONTEXT_PATH = SETTINGS.root / "live" / "state" / "realtime_voice_context.json"


def _safe_event(turn: dict[str, Any], question: str, conversation_id: str | None = None) -> dict[str, Any]:
    return {
        "ts": datetime.now(timezone.utc).isoformat(),
        "conversation_id": conversation_id,
        "question": question,
        "answer": turn.get("answer"),
        "route": turn.get("route"),
        "symbol": turn.get("symbol"),
        "plan": turn.get("plan"),
        "sources": turn.get("sources", []),
        "view_model": turn.get("view_model") or turn_to_view_model(turn),
    }


def write_event(turn: dict[str, Any], question: str, conversation_id: str | None = None) -> None:
    EVENT_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = EVENT_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(_safe_event(turn, question, conversation_id), default=str))
    tmp.replace(EVENT_PATH)


def seed_context(conversation_id: str, default_symbol: str = "GOOGL") -> dict[str, Any]:
    try:
        doc = json.loads(CONTEXT_PATH.read_text()) if CONTEXT_PATH.exists() else {}
        value = dict(doc.get(conversation_id) or {})
        from .market_intel import resolve_symbol
        value["symbol"] = resolve_symbol(str(value.get("symbol") or default_symbol), default_symbol)
        return value
    except Exception:
        return {"symbol": default_symbol}


def seed_symbol(conversation_id: str, default: str = "GOOGL") -> str:
    return str(seed_context(conversation_id, default).get("symbol") or default)


def _save_context(conversation_id: str, **updates: Any) -> None:
    try:
        doc = json.loads(CONTEXT_PATH.read_text()) if CONTEXT_PATH.exists() else {}
    except Exception:
        doc = {}
    current = dict(doc.get(conversation_id) or {})
    current.update({k: v for k, v in updates.items() if v not in (None, "")})
    doc[conversation_id] = current
    CONTEXT_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONTEXT_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc))
    tmp.replace(CONTEXT_PATH)


def _maybe_capture_name(text: str, *, first_user_turn: bool) -> str | None:
    """Capture the requested name without swallowing a real finance question.

    The ElevenLabs first message is handled client-side, so if a user skips the name
    and immediately says "VIX tool" or "Apple stock", that must go to the agent.
    """
    import re
    if not first_user_turn:
        return None
    t = str(text or "").strip()
    low = t.lower()
    finance_hints = {
        "vix", "stock", "market", "price", "risk", "cost", "trade", "trading",
        "paper", "backtest", "strategy", "crucible", "massive", "filing", "option",
        "google", "alphabet", "apple", "aapl", "nvidia", "nvda", "microsoft", "msft",
        "meta", "amazon", "amzn", "tesla", "tsla", "spy", "qqq", "gold", "bitcoin",
        "profit", "pnl", "gate", "position", "order", "evidence", "replay",
    }
    if any(re.search(rf"(?<![a-z0-9]){re.escape(k)}(?![a-z0-9])", low) for k in finance_hints):
        return None
    if any(low.startswith(x) for x in ["what ", "why ", "how ", "show ", "explain ", "run ", "tell ", "compare "]):
        return None
    patterns = [r"(?i)^my name is\s+([A-Za-z][A-Za-z .'-]{0,50}?)[.!?]*$", r"(?i)^i(?:'| a)?m\s+([A-Za-z][A-Za-z .'-]{0,50}?)[.!?]*$"]
    for pat in patterns:
        m = re.match(pat, t)
        if m:
            return m.group(1).strip().split()[0][:40]
    if 1 <= len(t.split()) <= 3 and re.fullmatch(r"[A-Za-z][A-Za-z .'-]{0,40}", t):
        blocked = {"hello", "hi", "yes", "no", "okay", "ok", "sure"}
        if low.rstrip(".") not in blocked:
            return t.split()[0].strip(".,!? ")[:40]
    return None


def _conversation_context(transcript: Any) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for m in list(transcript or [])[-12:]:
        role = getattr(m, "role", "user")
        content = getattr(m, "content", "")
        if content:
            out.append({"role": "assistant" if role == "agent" else str(role), "content": str(content)})
    return out


async def main() -> None:
    try:
        from elevenlabs import AsyncElevenLabs
    except ImportError as e:
        raise SystemExit("Install requirements-realtime-voice.txt first") from e

    api_key = os.getenv("ELEVENLABS_API_KEY")
    engine_id = os.getenv("ELEVENLABS_SPEECH_ENGINE_ID")
    if not api_key or not engine_id:
        raise SystemExit("ELEVENLABS_API_KEY and ELEVENLABS_SPEECH_ENGINE_ID are required")

    client = AsyncElevenLabs(api_key=api_key)
    engine = await client.speech_engine.get(engine_id)
    store = Store()
    symbols_by_conversation: dict[str, str] = {}
    last_processed_turn: dict[str, str] = {}

    def on_init(conversation_id, session):
        ctx = seed_context(str(conversation_id), "GOOGL")
        symbols_by_conversation[str(conversation_id)] = str(ctx.get("symbol") or "GOOGL")
        print(f"[voice] connected {conversation_id}")

    async def on_transcript(transcript, session):
        user_messages = [m for m in list(transcript or []) if getattr(m, "role", "") == "user"]
        latest = user_messages[-1].content if user_messages else ""
        cleaned_latest = str(latest).strip()
        if not cleaned_latest or not any(ch.isalnum() for ch in cleaned_latest):
            await session.send_response("I didn't catch that. Try the question again in a few words.")
            return
        cid = str(getattr(session, "conversation_id", "") or "")
        # Defensive de-duplication: Speech Engine passes full history on each user turn.
        # If the same finalized turn is delivered twice, never run/pay/speak twice.
        turn_key = f"{len(user_messages)}:{cleaned_latest}"
        if last_processed_turn.get(cid) == turn_key:
            print(f"[voice] duplicate turn ignored {cid}")
            return
        last_processed_turn[cid] = turn_key
        # Refresh browser-selected context on every turn. The WebRTC client receives the
        # conversation ID only after connection, so its first context POST can arrive just
        # after on_init but before the first spoken question.
        live_ctx = seed_context(cid, symbols_by_conversation.get(cid, "GOOGL"))
        current_symbol = str(live_ctx.get("symbol") or symbols_by_conversation.get(cid, "GOOGL"))
        symbols_by_conversation[cid] = current_symbol
        context = _conversation_context(transcript)
        # The first voice message asks the user's name. Capture a short answer without
        # wasting a Gemini/quant turn, then continue inside the same conversation.
        if not live_ctx.get("user_name"):
            name = _maybe_capture_name(str(latest), first_user_turn=(len(user_messages) == 1))
            if name:
                _save_context(cid, user_name=name)
                await session.send_response(f"Nice to meet you, {name}. I specialize in quantitative trading, market research, strategy evidence, replay, costs and risk. What should we investigate?")
                return
        try:
            turn = await asyncio.to_thread(
                execute_turn,
                store,
                clock.session_date(),
                str(latest),
                current_symbol,
                context,
                {
                    "date": live_ctx.get("date"),
                    "module": live_ctx.get("module"),
                    "last_route": live_ctx.get("last_route"),
                    "user_name": live_ctx.get("user_name"),
                },
            )
            symbols_by_conversation[cid] = str(turn.get("symbol") or current_symbol)
            # Keep the visual tab (module) separate from the last analytical route.
            # The browser may legitimately set module="live" after rendering a result;
            # that must not erase project_state/crucible/etc. for short follow-ups.
            updates = {"symbol": symbols_by_conversation[cid]}
            if turn.get("route") not in {"clarify", "scope_refusal", None}:
                updates["last_route"] = turn.get("route")
            _save_context(cid, **updates)
            print(f"[voice] route={turn.get('route')} symbol={symbols_by_conversation[cid]}")
            write_event(turn, str(latest), cid)
            # Speech Engine accepts a string and performs low-latency ElevenLabs TTS.
            await session.send_response(turn.get("speech") or turn.get("answer") or "Analysis complete.")
        except asyncio.CancelledError:
            # The SDK may cancel the in-flight turn when the user interrupts.
            raise
        except Exception as e:  # noqa: BLE001
            print("[voice] error", type(e).__name__, e)
            await session.send_response("The analysis tool failed. Please try that question again.")

    def on_close(session):
        cid = str(getattr(session, "conversation_id", "") or "")
        symbols_by_conversation.pop(cid, None)
        last_processed_turn.pop(cid, None)
        print(f"[voice] closed {cid}")

    def on_error(err, session):
        print("[voice] ElevenLabs error", err)

    port = int(os.getenv("ELEVENLABS_SPEECH_ENGINE_PORT", "3001"))
    print(f"Quant Crucible Speech Engine serving :{port}/ws")
    try:
        await engine.serve(
            port=port,
            path="/ws",
            debug=True,
            on_init=on_init,
            on_transcript=on_transcript,
            on_close=on_close,
            on_error=on_error,
        )
    finally:
        store.close()


if __name__ == "__main__":
    asyncio.run(main())
