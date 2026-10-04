# Filing Edge

**Tagline:** Before capital, evidence.

## Inspiration
A convincing backtest can conceal stale prices, impossible fills, unavailable information and unlimited capital. We wanted a research system that makes those assumptions visible and can reject its own idea.

## What it does
Filing Edge studies whether selling cash-secured puts after corporate buyback disclosures differs from comparable ordinary dates. It joins source filings to historical options, tests costs and delays, applies cash and liquidity limits, and produces a traceable research-only or allocation-review decision. It does not submit brokerage orders.

## How we built it
Python, a small WSGI API, vanilla JavaScript, Massive filings/options/NBBO, Tiger Data PostgreSQL with Timescale hypertables and continuous aggregates, Gemini explanations with exact-quote validation, and ElevenLabs report narration. A self-contained notebook reproduces the frozen research with only a Massive key.

## What we learned
More realistic execution and comparison rules can overturn an attractive pilot. Our held-out result had too few matched pairs to establish an edge, and the funded simulation lost money. We kept those findings, preserved the earlier pilot, and made the no-trade decision part of the product.

## Sponsor entries
- Massive: primary research dataset and historical execution evidence.
- Tiger Data: persisted experiment provenance, option-series time data and aggregate-backed dashboard queries.
- Gemini: source-grounded filing explanations, isolated from signal selection.
- ElevenLabs: AI-labeled audio briefing with an exact numeric transcript and cached playback.

## Limitations and next steps
Verify point-in-time disclosure arrival, replace the static issuer universe, validate the parity estimate, model actual early assignment and perform paper execution. The existing test period has been inspected and must not be reused as a fresh holdout.

## Team and links
Enter the four team members in the submission form. Source: https://github.com/srinivaspenumarthi/hack. Attach the two-page Massive note, five-page Systematic Trading note and judge notebook. Saved-results demo: https://srinivaspenumarthi.github.io/hack/. Use the local authenticated app for live API generation and database queries. AI assistance was used in implementation and documentation; Gemini and ElevenLabs are explicitly identified in the product.
