# Quant Crucible

Gator Quant Hacks 2026 · Track 03 Systematic Trading

**Paid to Hold the Bag:** short-term equity reversal is the return to supplying
liquidity, and we test whether that premium is larger when liquidity-provider
capital is scarce (proxied by the previous day's VIX).

## Hypothesis

See [HYPOTHESIS_AI_COPILOT.md](HYPOTHESIS_AI_COPILOT.md). In one line: the U.S.
equity short-term reversal premium rises with lagged VIX, because impatient
traders pay more for immediacy when market makers and arbitrageurs are
capital-constrained. It fails if reversal returns do not rise with lagged VIX,
if a VIX-conditioned rule does not beat constant exposure net of costs, or if the
held-out period contradicts the in-sample result.

Research modules:

| Module | Instrument | Question |
|---|---|---|
| A | Kenneth French daily short-term reversal portfolios, 1990–2026 | Does the reversal premium rise with lagged VIX? |
| B | S&P 500 opening-auction gap fade (open-to-close) | Does a "participate only when VIX ≥ 20" rule survive auction costs? |
| C | Variance risk premium vs. realised variance | Is the premium paid for the *price* of risk or the *quantity* of risk? |

Out-of-sample window: **2024-09-01 → 2026-08-31**, evaluated once, at the end.

## Next steps (deadline: Sun Oct 4, 11:00 AM on Devpost)

- [ ] Copy the research code from `quant_crucible_FINAL_PRIVATE` into this repo:
      `src/`, `data/*.py`, `data/sp500_constituents.csv`, `run_all.py`,
      `requirements.txt`, `tests/`, `note/`, `results/`, `HYPOTHESIS*.md`, `.env.example`.
- [ ] **Never commit** `.env`, `filing_edge/.env`, `voice_ui/.env`, `.venv/`,
      `__pycache__/`, `live/state/`, or raw downloaded data. Copy `.gitignore` first.
- [ ] Decide which repo is submitted. The note cites the pre-registration commits
      (`0d0093d`, `fbd355a`, `6067ea1`) from `srinivaspenumarthi/cursor_hack`. Either
      submit that repo or link to it here so judges can see that the hypotheses were committed before the results.
- [ ] Update the GitHub link in `note/quant_note.md` and rebuild `note/quant_note.pdf`
      (max 5 pages, 11pt or larger; references and appendix don't count).
- [ ] Fresh clone → `pip install -r requirements.txt` → `python run_all.py --oos`
      and confirm the numbers match the note. A mismatch caps the Performance score at 4.
- [ ] Confirm that the note discloses the number of variants tried, in-sample and out-of-sample results
      reported separately net of costs, Sharpe, max drawdown, turnover, an equity curve,
      and the risk and capacity sections.
- [ ] Make the submitted repo **public** and list every team member on Devpost.
- [ ] Submit the PDF + repo link on gqhacks.devpost.com before 11:00 AM.

## Reproduce

```bash
pip install -r requirements.txt
python run_all.py --oos
```

Uses only public data (Kenneth French Data Library, FRED, Yahoo Finance). No API keys are needed.
