"""Sync the existing ElevenLabs Speech Engine to the currently-running ngrok tunnel.

Run after `ngrok http 3001`:
    python scripts/sync_ngrok_speech_engine.py

This reads ngrok's local inspector API, finds the HTTPS tunnel, converts it to a WSS
/websocket endpoint, and patches the configured ElevenLabs Speech Engine. Secrets are
read from .env and are never printed.
"""
from __future__ import annotations

import os
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(dotenv_path=ROOT / ".env")

api_key = os.getenv("ELEVENLABS_API_KEY", "").strip()
engine_id = os.getenv("ELEVENLABS_SPEECH_ENGINE_ID", "").strip()
if not api_key:
    raise SystemExit("ELEVENLABS_API_KEY is missing from .env")
if not engine_id:
    raise SystemExit("ELEVENLABS_SPEECH_ENGINE_ID is missing from .env. Create it with scripts/create_speech_engine.py first.")

try:
    tunnels = requests.get("http://127.0.0.1:4040/api/tunnels", timeout=5).json().get("tunnels", [])
except Exception as exc:
    raise SystemExit(f"Could not read ngrok inspector at http://127.0.0.1:4040. Is ngrok running? ({exc})")

public_url = next((t.get("public_url", "") for t in tunnels if str(t.get("public_url", "")).startswith("https://")), "")
if not public_url:
    raise SystemExit("No HTTPS ngrok tunnel found. Start: ngrok http 3001")

ws_url = "wss://" + public_url.removeprefix("https://").rstrip("/") + "/ws"
r = requests.patch(
    f"https://api.elevenlabs.io/v1/speech-engine/{engine_id}",
    headers={"xi-api-key": api_key, "Content-Type": "application/json"},
    json={"speech_engine": {"ws_url": ws_url}, "overrides": {"first_message": True}},
    timeout=30,
)
if r.status_code >= 400:
    raise SystemExit(f"ElevenLabs PATCH failed HTTP {r.status_code}: {r.text[:500]}")
print("SUCCESS")
print(f"Speech Engine: {engine_id}")
print(f"WebSocket: {ws_url}")
print("First-message override: enabled")
