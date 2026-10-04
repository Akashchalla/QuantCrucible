# Quant Crucible

Gator Quant Hacks 2026 · Track 03 Systematic Trading

**Paid to Hold the Bag:** short-term equity reversal is the return to supplying
liquidity, and we test whether that premium is larger when liquidity-provider
capital is scarce (proxied by the previous day's VIX).

## Hypothesis

Full version: [HYPOTHESIS.md](HYPOTHESIS.md). Short version: short-term reversal
is a payment for liquidity, and it is larger after VIX is high, because liquidity
providers are capital-constrained. It is tested three ways: daily French
reversal portfolios (A), an S&P 500 opening-auction gap fade (B), and the
variance risk premium vs. realised variance (C). The held-out period
**2024-09-01 → 2026-08-31** is evaluated once, at the end.

## Next steps (Devpost deadline: Sun Oct 4, 11:00 AM)

**By 9:30: bring in the code safely**
- [ ] Copy `.gitignore` from `quant_crucible_FINAL_PRIVATE` first.
- [ ] Copy `src/`, `data/*.py`, `data/sp500_constituents.csv`, `run_all.py`,
      `requirements.txt`, `tests/`, `note/`, `results/`, `HYPOTHESIS_B.md`,
      `HYPOTHESIS_C.md`, `.env.example`.
- [ ] **Never commit:** `.env`, `filing_edge/.env`, `voice_ui/.env`, `.venv/`,
      `__pycache__/`, `live/state/`, or raw data. Run `git status` before every commit.
- [ ] Delete `HYPOTHESIS_AI_COPILOT.md` (it's now covered by `HYPOTHESIS.md`).

**By 10:00: prove it reproduces**
- [ ] Fresh clone in a new folder → `pip install -r requirements.txt` →
      `python run_all.py --oos` → check that the headline numbers match the PDF.
      A mismatch caps the Performance score at 4.
- [ ] `python -m pytest -q tests` passes.

**By 10:30: finalize the note**
- [ ] Choose the repo you submit. The pre-registration commits live in
      `srinivaspenumarthi/cursor_hack`. Either submit that repo or keep the
      link to it in `HYPOTHESIS.md` and the note.
- [ ] Update the GitHub link in `note/quant_note.md` and rebuild the PDF
      (5 pages max, 11pt or larger; references and appendix don't count).
- [ ] Note checklist: hypothesis stated before results, in-sample and out-of-sample results reported separately
      net of costs, Sharpe, max drawdown, turnover, an equity curve, by-year
      breakdown, risk management section, capacity section, **78 variants disclosed**,
      and what failed (the Module A leverage rule).

**By 10:45: submit**
- [ ] Make the repo **public**.
- [ ] Devpost: PDF + repo link, all team members listed.

## Reproduce

```bash
pip install -r requirements.txt
python run_all.py --oos
```

Uses only public data (Kenneth French Data Library, FRED, Yahoo Finance). No API keys are needed.
