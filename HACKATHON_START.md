# Quant Crucible — start here

## 1. Configure keys

```bash
cp .env.example .env
```

Required for the flagship experience:

```dotenv
GEMINI_API_KEY=...
ELEVENLABS_API_KEY=...
```

Math verification is performed independently and deterministically in Python. Gemini handles orchestration and explanation, so no GPAI API is required.

### Provider preflight

After installing dependencies, validate the configured services without printing any secret values:

```bash
python scripts/preflight_private.py
```

The report checks Gemini authentication, Massive market status, ElevenLabs authentication, Databento metadata access, Tiger Data/Timescale connectivity, and confirms that Alpaca is intentionally in simulated-paper mode. Network-unavailable environments will show connection errors without exposing credentials.

## 2. Portable all-in-one Streamlit build

```bash
pip install -r requirements-live.txt
streamlit run live/dashboard.py --server.port 8765
```

This includes all five hero systems, TradingView, Google-grounded company research, screenshot vision, charts, and push-to-talk ElevenLabs voice.

## 3. Flagship full-duplex voice workspace

Install Python + browser dependencies:

```bash
pip install -r requirements-realtime-voice.txt
cd voice_ui && npm install && cd ..
```

Expose port 3001 once, then create the Speech Engine resource:

```bash
ngrok http 3001
python scripts/create_speech_engine.py --ws-url wss://YOUR-NGROK-DOMAIN/ws
```

Copy the printed `ELEVENLABS_SPEECH_ENGINE_ID` into `.env`.

Run these processes:

```bash
# terminal 1
python -m live.realtime_voice_server

# terminal 2
uvicorn live.voice_api:app --host 0.0.0.0 --port 8780

# terminal 3
cd voice_ui && npm run dev
```

Open `http://localhost:5173`.

## 4. Verify the deterministic core with no API keys

```bash
PYTHONPATH=. python scripts/smoke_crucible.py
PYTHONPATH=. pytest -q tests/test_quant_crucible.py tests/test_live.py tests/test_gapfade.py tests/test_no_lookahead.py tests/test_pricing.py tests/test_eightk.py
cd filing_edge && PYTHONPATH=. pytest -q
```

Expected in this packaged build: **55 core/new-feature tests + 38 Filing Edge tests**.

## Five hero experiences

1. **Quant Crucible** — adversarial strategy validation; deterministic verdict.
2. **Market Vision** — live TradingView + Gemini screenshot reasoning + numerical market evidence.
3. **Market Multiverse** — scenario replay, Monte Carlo bands, stress sensitivity.
4. **Market Black Box** — evidence-backed loss reconstruction and exact reconciliation.
5. **Ghost Desk** — counterfactual risk controls, showing both capital saved and gains missed.

Both voice and typed chat call the same `live.agent.execute_turn()` brain and generate the same JSON analytical workspace.

## Evidence modes in the React workspace

The live browser workspace now exposes these modes directly (voice and text share the same session/context):

- Live Desk — current company/market investigation with grounded sources.
- Crucible — adversarial robustness tests.
- Market Vision — TradingView + Gemini screenshot interrogation.
- Multiverse — explicitly hypothetical stress scenarios.
- Black Box — recorded session/research loss reconstruction.
- Ghost Desk — value/opportunity cost of risk controls.
- Explain Day — why the strategy traded/stayed out and what evidence is recorded.
- Profit Bridge — gross -> costs/execution -> net, including a labeled doubled-cost counterfactual.
- Replay — point-in-time historical narrator; unavailable future/intraday evidence stays hidden.
- Research Trial — challenge claims, OOS integrity, survivorship, failed/fragile experiments, and options evidence.

The voice greeting is intentionally short and asks the user's name. The assistant is scoped to quantitative trading,
market/company research, and this project's evidence; unrelated general-knowledge prompts are declined. The agent is read-only.
