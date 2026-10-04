# Quant Crucible — architecture and feature contract

Quant Crucible turns the repository's pre-registered systematic research into an interactive market research workstation. AI is intentionally **sidecar intelligence**: it can inspect, explain, search, visualize and start sandbox experiments, but it cannot mutate signal generation, sizing, risk limits, broker orders, or execution state.

## One agent, two interfaces

Both text and voice call `live.agent.execute_turn()`.

```text
User text ───────────────┐
                         ├─> Gemini planner ─> allow-listed tool route ─> deterministic engine ─> UI action
ElevenLabs STT ──────────┘                                                       │
                                                                                 └─> ElevenLabs TTS
```

A voice request can therefore create the same charts and simulations as a typed request.

## Current public information

For questions such as “Why is Google moving today?”:

```text
Gemini planner
   -> company_research
      -> numerical market snapshot (market-data layer)
      -> Gemini + Google Search grounding (news / primary sources)
      -> answer + grounded URLs
      -> frontend evidence panel
```

Search is not used as an authoritative price feed. The chart and the quant calculations are sourced separately.

## 1. Quant Crucible

Files: `live/crucible.py`, `live/math_verifier.py`

Implemented attacks:

- full-sample and held-out performance
- VIX threshold neighborhood
- 0.5×–4× execution-cost stress
- gross-alpha retention stress
- remove the best 1/3/5/10/20 days
- calendar-year stability
- bootstrap confidence interval of traded-day mean
- break-even cost multiplier
- break-even alpha retention
- independent numerical recomputation

The verdict (`REJECT`, `PROVISIONAL PASS`, `ROBUST PASS`) is computed from explicit checks, not authored by Gemini.

## 2. Market Vision

Files: `live/market_intel.py`, `live/ui_components.py`

- TradingView Advanced Chart embed
- market snapshot and normalized comparisons
- historical analogue search using a state vector of return, trend, volatility, ATR and volume
- Gemini Google Search grounded company research
- Gemini multimodal analysis of uploaded chart screenshots
- strict separation between visual interpretation and authoritative numerical data

## 3. Market Multiverse

File: `live/multiverse.py`

Stress controls:

- VIX environment multiplier
- execution-cost multiplier
- retained gross alpha
- extra slippage
- outcome-volatility multiplier
- projection horizon

Outputs:

- base vs stressed historical equity
- base vs stressed risk metrics
- Monte Carlo percentile bands
- probability of finishing below start
- probability of 10% drawdown
- alpha-retention × cost sensitivity surface
- break-even cost multiplier

## 4. Market Black Box

File: `live/black_box.py`

Research mode reconstructs the evidence trail of a committed daily observation and decomposes:

- long leg vs market
- short leg vs market
- modeled execution cost

Live mode uses the actual store's step logs, fills and risk events. The code explicitly refuses to fabricate intraday timestamps for daily research data.

## 5. Ghost Desk

File: `live/ghost_desk.py`

Counterfactual universes include:

- actual VIX >= 20 rule
- always-on
- VIX >= 15
- VIX >= 25
- no modeled transaction costs

The ledger shows both **avoided losses** and **missed gains**, plus net value of the gate versus always-on.

## Math verification

Quant Crucible does not depend on GPAI because no public developer API is required for the demo. `live/math_verifier.py` independently recomputes key metrics from the raw return series. Gemini can explain, challenge, and contextualize those results, but deterministic Python remains the numerical source of truth.

## Safety / research integrity

- no AI-generated orders
- no AI mutation of the pre-registered rule
- no silent re-opening of held-out research windows
- current web claims can carry sources
- market prices are not scraped from chart pixels
- failed hypotheses and negative counterfactuals remain visible
- every scenario is a sandbox

## Full-duplex voice + visual workspace

The Streamlit Live Desk keeps a portable push-to-talk path, but the judge-facing voice experience is a separate browser client in `voice_ui/`. It uses ElevenLabs **Speech Engine** exactly as intended: ElevenLabs owns realtime STT, turn-taking, interruption handling and TTS; `live.agent.execute_turn()` remains the Gemini + deterministic-tool brain. Every completed voice turn writes a JSON view model that the browser renders as metrics, charts, tables, sources and a tool trace.

### One-time Speech Engine setup

```bash
pip install -r requirements-realtime-voice.txt
ngrok http 3001
python scripts/create_speech_engine.py --ws-url wss://YOUR-NGROK-DOMAIN/ws
# copy the returned ELEVENLABS_SPEECH_ENGINE_ID into .env
```

### Run the full voice stack

Terminal 1 — Speech Engine brain WebSocket:

```bash
python -m live.realtime_voice_server
```

Terminal 2 — secure token + typed-chat API:

```bash
uvicorn live.voice_api:app --host 0.0.0.0 --port 8780
```

Terminal 3 — visual browser client:

```bash
cd voice_ui
npm install
npm run dev
```

Open `http://localhost:5173`. The browser fetches a short-lived ElevenLabs WebRTC conversation token from the local API; the ElevenLabs API key is never exposed to client JavaScript. Selecting a symbol before starting the conversation seeds the voice session context. Spoken and typed turns use the same router and generate the same analytical view model.

### What voice can render

- current-company research + Google-grounded source links
- price and daily-return distribution charts
- normalized multi-symbol performance comparisons
- historical analogue tables and forward-outcome bars
- Crucible threshold/cost/outlier attacks and verdict scorecard
- Multiverse historical stress path + Monte Carlo envelope + sensitivity table
- Black Box loss attribution and evidence trail
- Ghost Desk actual-vs-counterfactual P&L and risk-control value ledger

The gateway writes the latest completed voice turn to `live/state/realtime_voice_last.json`, which lets any frontend observe the same result without duplicating model logic.

