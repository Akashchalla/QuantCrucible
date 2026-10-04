# Review of the official Massive starter

Reviewed October 3, 2026 by reading the downloaded notebook; no notebook cells were executed and no API key was used. Cell indices below are zero-based JSON cell indices.

Source: https://www.gqhacks.com/massive/gqh-massive-8k-options-starter.ipynb

These are limitations to address when extending a teaching starter, not claims about sponsor data quality.

| Finding | Evidence | Planned treatment |
|---|---|---|
| Page-limit conflict | Cell 4 says at most two pages; website says at most five and defers conflicts to notebook/organizer announcements | Ask organizer; prepare two-page core plus supporting material |
| Test window runs automatically | Cell 32 fetches and evaluates test events; only sealed window has RUN_HOLDOUT gate | Separate explicit evaluation command; no Run All during development |
| Headline tables are gross | Cell 22 computes gross P&L; cell 38 applies costs only to selected strategy at h=21 | Apply costs at every required horizon and to both event and baseline samples |
| Cost simplification | Cell 38 charges twice the entry premium times a haircut, not entry and exit premiums separately | Account for each actual leg and both sides of modeled execution |
| Timing fix comes late | Cell 40 changes development event dates after earlier results, asks for repricing; run_study in cell 42 does not use it | One timing function before pricing, applied identically in all windows |
| Category availability not modeled | Filing acceptance time is distinct from vendor's next-day tag load | Document vendor availability assumption and delay sensitivity |
| Stale prices allowed | Leg.mark in cell 20 carries the most recent trade for up to three sessions | Separate valuation from fill eligibility; no fills at stale carried marks |
| P&L denominator is spot | Cell 22 reports cash-secured-put P&L divided by inferred spot | Preserve labeled comparative measure if useful; capital returns use full strike collateral |
| Repeated events treated as independent | Cell 24 bootstraps individual rows | Account for issuer dependence and calendar overlap; disclose limited effective sample |
| Static universe and inferred spot | Cell 10 fixes September 2026 universe; cells 18/20 infer spot by parity | Disclose selection bias; audit parity assumptions, dividends, American exercise and stale/asynchronous trades |
| Sealed function differs from full study | Cell 42 returns gross scoreboard without matched placebo or unified costs/timing | Build one shared pipeline and use it for development, final test and judges |
| Development outcomes can cross boundary | Price requests extend to expiry; evaluate uses latest available session, not development cutoff | Enforce outcome cutoffs separately from event-date windows |
| Expiry marks and assignment need care | evaluate marks legs using last trades; no full assignment lifecycle | Do not label stale last-trade prices as settlement; specify supported marking/settlement and collateral treatment |
| Sparse data can break display logic | Fixed sample(5), empty-data paths, and ranking assumptions | Explicit empty and small-sample outcomes; no fabricated rows |

Additional conceptual cautions: a filing may follow an earlier public announcement, so a pre-filing chain is not necessarily pre-news. The ATM straddle/spot ratio is a rough move proxy, not a universal profitability rule for all five strategies. A synthetic long call/short put is not a fully funded stock holding without financing, dividends and exercise considerations.

The revised backtest has not yet been implemented. Access and coverage are the next checks.
