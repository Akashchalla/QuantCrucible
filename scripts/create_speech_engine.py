"""Create the ElevenLabs Speech Engine used by Quant Crucible.

Usage:
  python scripts/create_speech_engine.py --ws-url wss://YOUR-DOMAIN/ws

Creation is intentionally minimal to match the current ElevenLabs API. After creation,
we enable the first-message override with a REST PATCH because older SDK builds may not
expose the `overrides` keyword on update().
"""
from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(dotenv_path=ROOT / ".env")


async def amain(ws_url: str) -> None:
    from elevenlabs import AsyncElevenLabs

    api_key = os.getenv("ELEVENLABS_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("ELEVENLABS_API_KEY missing from .env")

    client = AsyncElevenLabs(api_key=api_key)
    engine = await client.speech_engine.create(
        name="Quant Crucible Live Desk",
        speech_engine={"ws_url": ws_url},
    )
    engine_id = getattr(engine, "engine_id", None) or getattr(engine, "speech_engine_id", None)
    if not engine_id:
        raise RuntimeError(f"Speech Engine created but no ID returned: {engine}")

    r = requests.patch(
        f"https://api.elevenlabs.io/v1/speech-engine/{engine_id}",
        headers={"xi-api-key": api_key, "Content-Type": "application/json"},
        json={"speech_engine": {"ws_url": ws_url}, "overrides": {"first_message": True}},
        timeout=30,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"Speech Engine created ({engine_id}) but override PATCH failed HTTP {r.status_code}: {r.text[:300]}")

    print("SUCCESS")
    print(f"ELEVENLABS_SPEECH_ENGINE_ID={engine_id}")
    print("First-message override: enabled")
    print(f"WebSocket: {ws_url}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--ws-url", required=True)
    args = ap.parse_args()
    asyncio.run(amain(args.ws_url))
