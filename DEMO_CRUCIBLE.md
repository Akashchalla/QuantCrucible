# Quant Crucible — 3 minute judge demo

Use the **browser workspace** in `voice_ui/` for the flagship demo. It combines live ElevenLabs conversation, typed Gemini chat, TradingView, Market Vision, generated charts/tables, grounded sources, and the same five deterministic hero engines. The Streamlit dashboard remains a portable fallback.

## Before judges arrive

- Select `GOOGL` in the browser.
- Confirm the Gemini / ElevenLabs / Quant Engine badges are active.
- Click **Start live voice** and grant microphone permission.
- Keep one conspicuous TradingView screenshot ready for the Market Vision upload.

## 0:00 — Live Desk + live market intelligence

Say:

> What's going on with Google today? Show me evidence.

Expected flow: ElevenLabs Speech Engine -> shared Gemini router -> numerical market snapshot + Gemini Google Search grounding -> answer + current price metrics + grounded source links -> ElevenLabs spoken answer.

Interrupt the bot naturally and say:

> Forget the news for a second. Compare Google with Nvidia over the last six months.

The spoken conversation continues while the analytical workspace changes into a normalized performance graph.

## 0:45 — Market Vision

Point to the live TradingView surface, then upload the prepared screenshot in **Gemini Market Vision** and ask:

> What visually stands out here, and what should I test quantitatively next?

The answer appears in the same workspace with visual observations, cautions, and next tests. Explain one sentence only:

> Pixels tell Gemini what I mean; exact prices and returns still come from market data.

## 1:15 — Quant Crucible

Say:

> Red-team our strategy and find the weakest point.

The voice turn launches the committed red-team engine. Highlight the verdict, threshold neighborhood, transaction-cost attack, outlier removal, held-out result, independent math recomputation and attack ledger.

Do **not** hide a rejection. The current committed data can legitimately return `REJECT`.

Line:

> Most AI trading demos try to find a trade. Ours tries to prove the research wrong first.

## 1:55 — Market Multiverse

Say:

> What if volatility doubles and transaction costs triple?

Show the base-vs-stress history, Monte Carlo envelope, probability of loss, break-even costs and sensitivity table.

Then ask a quick follow-up:

> Which assumption hurts us the most?

## 2:25 — Black Box + Ghost Desk

Say:

> Open the black box on our worst committed session.

Show exact P&L reconciliation and the evidence trail. Mention that daily research data never gets a fabricated intraday story.

Then say:

> What did the VIX gate save us, and what gains did it miss?

Ghost Desk shows both losses avoided and opportunity cost, plus actual-vs-counterfactual equity.

Finish:

> Quant Crucible doesn't ask AI what to trade. It lets me talk to the market while deterministic research, math, and risk controls remain the source of truth.
