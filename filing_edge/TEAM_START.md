# Four-person demo roles

1. **Research presenter:** hypothesis, ordinary-date controls, fixed development/test windows and the honest no-trade conclusion.
2. **Data and reproducibility:** Massive API, source hashes, the self-contained judge notebook and missing observations.
3. **Risk and product:** account curve, capacity exclusions, downside calculator and glossary.
4. **Sponsor integrations and submission:** Gemini source quotes, live Tiger Data aggregates, ElevenLabs briefing, PDFs and demo sequence.

Use DEMO_SCRIPT.md. Everyone should know the primary limitation: there are only five matched test pairs, and historical classification availability has not been verified. A positive relative difference is not necessarily an absolute profit.

Local app: `python app.py --port 8765`. Rebuild all data with actual APIs: `python scripts/setup_demo.py`; that command explicitly opens the fixed test window after freezing the method. The complete data run needs all configured sponsor credentials; research alone needs only Massive.
