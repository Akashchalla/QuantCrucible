> Historical version 1 specification, preserved for audit. The submitted version 2 method and evaluated holdout are documented in README.md, protocol-v2.json and submission/research-manifest.json. Statements below about an unopened holdout describe the original pilot stage.

# Draft research specification — 2026-10-03

Status: written before our first backtest. Not frozen: exact taxonomy tags, matching criteria, execution assumptions and sample feasibility remain unresolved. Record all changes before freezing; do not portray this draft as a completed preregistration.

## Research question

Does disclosure context change the incremental return from selling a cash-secured put after a share-repurchase authorization?

## Proposed mechanism

An authorization without adverse co-disclosures may convey willingness to allocate capital to shares while downside protection remains costly. Protection buyers may pay for residual uncertainty and downside risk. This is a hypothesis, not evidence of irrational pricing: premiums may fairly compensate for crash risk, and authorizations may never be executed.

## Primary proposal

Use one buyback-authorization category and one cash-secured-put strategy. Compare events without a predefined set of adverse co-disclosures against matched ordinary days for the same issuer. Separately report buyback events with those co-disclosures as a context comparison. Use accession-number joins so we retain all tags from the same filing. Do not equate absence of an adverse tag with absence of adverse information.

Map the adverse set to economic concepts before inspecting returns: downward guidance revisions, financial distress, and material accounting problems, subject to actual taxonomy definitions and coverage. Do not invent API tag names. Manually review a deterministic development-only sample, blinded to subsequent returns. If coverage is too sparse, report the context comparison as inconclusive rather than selecting a new profitable filter.

## Prespecified starting choices, subject to feasibility before freeze

- Universe: the starter's fixed 100-company universe; explicitly disclose survivorship and selection bias.
- Development events: 2024-01-01 through 2025-12-31.
- Test events: 2026-01-01 through 2026-08-31; not yet accessed.
- Headline expiry: 3–6 months; target 120 calendar days as in starter.
- Put strike: at or below 95% of the defined reference spot; report achieved moneyness. Explain that pre-filing strike selection can differ from entry-day moneyness.
- Report every required filing-relative horizon: 1, 2, 3, 5, 10, 21, 42, 63 sessions, plus expiry. A horizon before eligible entry is not tradable and must be marked unavailable, not assigned zero or moved silently.
- Headline research comparison: 21-session event-minus-baseline net return on full strike collateral; show every horizon without choosing the best after inspection.
- Entry: after both public disclosure and usable category availability. Historical availability is unresolved. Compare documented/assumed one- and two-session delays and label assumptions. Filing-date-only entry is insufficient evidence of availability.
- Costs: entry and exit leg-specific execution haircuts plus fees; values and rationale to be fixed before performance evaluation. Show doubled-cost results. Daily bars cannot establish actual bid/ask spreads.
- Sensitivity: starter's 3%, 5%, 10% strike grid and three expiry buckets; delays and cost stress. Record all configurations evaluated; do not select the best test-period result.

## Research controls

Freeze the exact ordinary-day matching and exclusion rules before evaluating returns. Use same issuer and a reasonably narrow calendar neighborhood, comparable maturity and moneyness, and comparable pre-entry risk when measurable. Exclusions based on future event knowledge must be labeled retrospective research controls, not trading filters.

Separate event-study P&L from an implementable portfolio: overlapping events do not create free extra capital. Portfolio rules must reserve full strike collateral, limit issuer concentration, avoid overlapping positions in the same issuer, and define treatment of assignment, missing marks and expiry. Statistical uncertainty must account for repeated issuers and overlapping calendar windows; simple independent-event resampling is inadequate as the sole evidence.

Development trades whose outcomes extend into the test window must be censored or excluded from development statistics. Every horizon needs a maturity count as of the fixed data cutoff. Recent test events cannot supply future expiry outcomes.

## Failure conditions

- Net advantage vanishes at realistic timing/cost assumptions.
- Matched ordinary days explain the apparent effect.
- Effect depends on isolated issuers or a narrow parameter peak.
- The apparent benefit is compensation for larger tail losses rather than improved risk-adjusted outcomes.
- Coverage, tagging accuracy, or uncertainty prevents a useful conclusion.

No observed results, backtests or final configuration exist yet. Final freeze should record the code/config hash and a Git commit before results are generated.

## Development pilot lock — implementation addendum

Before market-return evaluation, the taxonomy audit found 36 in-universe filings across 26 issuers in 2024–2025, all without the predefined adverse tags. We retain the adverse group definition and report that comparison as untestable. `guidance_issuance_or_update` is not classified as adverse because that label also covers favorable and unchanged guidance. This is a feasibility pilot, not a final strategy preregistration.

The primary tag is `share_repurchase_program`, which includes updates as well as new authorizations. The exact adverse list and all numerical choices are in config.json. Controls use the first eligible backward offset among 35, 50, 65 and 80 sessions for the same issuer, with a ±10-session exclusion around known buyback filings; controls before development start are unavailable. This is retrospective buyback-event exclusion, not comprehensive ordinary-day risk matching. No other filing types or earnings calendar are excluded.

Reference spot is an approximate European put–call parity calculation using fresh pre-filing American-option daily closes, a fixed 4% rate and no dividend correction. Contract selection uses that reference, not entry-day spot. The contracts endpoint uses `as_of` with `expired=false`: live tests confirmed this selects contracts active at the historical reference date. The prior incorrect `expired=true` combination returned no eligible historical contracts and was corrected before evaluating returns.

We assume tags become usable on the session after the filing session anchor; this is not verified historical availability. Entry and exit are same-date positive-volume daily closes, never forward-filled. Entry haircut is a reduction in proceeds and exit haircut an increase in repurchase cost. The headline haircut is 5% of each option premium, not 5 bps of underlying notional; sensitivity uses 2.5% and 10%. Fees are $0.65 per contract per side. Return denominator is full strike collateral.

Every horizon and every fixed sensitivity cell is reported. There is no selection of the best cell. Comparing differences between groups can improve as costs rise if the control group incurs larger costs; inspect absolute event and control returns alongside the difference. Expiry is only a last-trade-price proxy. Missing marks and trades crossing the 2025-12-31 outcome boundary are excluded with reason counts. The planned first full coverage pilot attempts all 36 events, subject to a bounded request budget, with no outcome-based expansion.

The freeze artifact records UTC time, the exact configuration, configuration hash, coverage hash and research-source hash. A Git commit is still pending. Bootstrap intervals are exploratory envelopes of separate issuer and calendar-quarter cluster resampling, not a definitive two-way-cluster confidence procedure. Few clusters and overlapping holding periods remain limitations. Synthetic data test software behavior only. The 2026 test period remains unopened and the sealed judge runner is not implemented in this prototype.
