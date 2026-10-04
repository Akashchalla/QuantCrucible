# Quant Crucible — FINAL start-to-finish setup

This private build already contains your configured provider environment. Do not push it to GitHub or a public submission.

## 0. Recommended runtime

Use Python 3.12 if available. Python 3.14 can work, but some packages have had compatibility rough edges.

```bash
brew install python@3.12 node ngrok
```

## 1. Unzip and enter the repository

```bash
cd ~/Downloads
unzip quant_crucible_FINAL_PRIVATE.zip
cd quant_crucible_FINAL_PRIVATE
```

## 2. Create Python environment

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements-realtime-voice.txt
python -m pip install -r filing_edge/requirements-dev.txt
python -m pip install nbformat jupyter
```

If `python3.12` is unavailable, use `python3`.

## 3. Install frontend dependencies

```bash
cd voice_ui
npm install
cd ..
```

## 4. Optional preflight

```bash
source .venv/bin/activate
python scripts/preflight_private.py
```

## 5. Start the complete demo — four terminals

### Terminal 1 — ElevenLabs Speech Engine websocket backend

```bash
cd ~/Downloads/quant_crucible_FINAL_PRIVATE
source .venv/bin/activate
python -m live.realtime_voice_server
```

Expected: port `3001`, websocket path `/ws`.

### Terminal 2 — ngrok

```bash
ngrok http 3001
```

Leave it running. Then, in a temporary shell or Terminal 3 before starting Uvicorn, sync the current ngrok URL to the existing ElevenLabs Speech Engine:

```bash
cd ~/Downloads/quant_crucible_FINAL_PRIVATE
source .venv/bin/activate
python scripts/sync_ngrok_speech_engine.py
```

Run this sync command every time free ngrok gives you a new URL.

### Terminal 3 — Gemini / Quant API

```bash
cd ~/Downloads/quant_crucible_FINAL_PRIVATE
source .venv/bin/activate
lsof -ti tcp:8780 | xargs kill -9 2>/dev/null || true
python -m uvicorn live.voice_api:app --host 127.0.0.1 --port 8780
```

### Terminal 4 — React frontend

```bash
cd ~/Downloads/quant_crucible_FINAL_PRIVATE/voice_ui
lsof -ti tcp:5173 | xargs kill -9 2>/dev/null || true
rm -rf node_modules/.vite dist
npm run dev -- --host 127.0.0.1 --port 5173
```

Open:

```text
http://127.0.0.1:5173
```

Hard refresh if needed: `Cmd + Shift + R`.

## 6. What should be visible

The React workspace includes:

- Live Desk
- Crucible
- Market Vision
- Multiverse
- Black Box
- Ghost Desk
- Explain Day
- Profit Bridge
- Replay
- Research Trial
- Systematic Trading
- Massive Research
- Massive Evidence
- Massive Capital
- Massive Infra

The four Massive views are the existing Filing Edge pages mounted from `filing_edge/docs/`.

## 7. Intelligence architecture

Voice and text use the same `live.agent.execute_turn()` pipeline:

1. Gemini understands/routs the question.
2. Deterministic Quant Crucible tools calculate numerical results.
3. Repository evidence retrieval selects relevant hypotheses, results, risk logic, execution logic, and Filing Edge evidence.
4. Gemini performs a second evidence-grounded synthesis pass.
5. React renders the evidence/visualization and ElevenLabs speaks the same answer.

Unknown relevant questions are clarified instead of silently falling back to a generic market snapshot. Unrelated general-knowledge questions are declined.

## 8. Verify tests

```bash
cd ~/Downloads/quant_crucible_FINAL_PRIVATE
source .venv/bin/activate
python -m pytest -q tests
cd filing_edge
python -m pytest -q
```

Expected for this final merged build:

- Quant Crucible: **55 passed**
- Filing Edge: **38 passed**
- Total: **93 passed**

## 9. If voice connects then immediately disconnects

Check:

```bash
lsof -nP -iTCP:3001 -sTCP:LISTEN
```

Open ngrok inspector:

```text
http://127.0.0.1:4040
```

A healthy ElevenLabs connection reaches `/ws` with websocket status `101`.

If ngrok changed, simply run again:

```bash
python scripts/sync_ngrok_speech_engine.py
```

## 10. Security

This PRIVATE ZIP contains configured credentials. Do not commit it, upload it to GitHub, or submit it publicly. Rotate credentials after the hackathon.
