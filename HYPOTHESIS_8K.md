# Hypothesis 8K (pre-registered, written before any backtest)

**Written:** 2026-10-04, before any buyback filing was stored and before any option
price for this study was read. The git commit that adds this file is the
timestamp. The liquidity study in `HYPOTHESIS.md`, `HYPOTHESIS_B.md` and
`HYPOTHESIS_C.md` is a separate, already-finished project. Its out-of-sample
files are not an input to this study and are not recomputed here.

## Edge source

A board that announces a share-repurchase authorization is telling the market
it will be a buyer of its own stock. The counterparty we want is the holder of
downside: after the announcement, implied volatility and the put skew often
stay rich relative to the new floor under the stock (the firm itself is a bid).
Selling a cash-secured, out-of-the-money put is a way to be paid that premium
while the collateral is the cash that would buy the shares if assigned.
We do not claim the announcement is good news for the stock. We claim the
**put is expensive relative to the realised downside over the following weeks**,
because the repurchase bid is slow and the option market does not fully
remove the premium on the day of the filing.

## The hypothesis in one paragraph

> After an 8-K that announces or expands a share-repurchase program, selling a
> 5% out-of-the-money cash-secured put on that issuer earns a higher net
> return, at every fixed horizon below, than selling the same put on an
> ordinary day for the same issuer. The edge exists because the firm has just
> become a buyer of its own shares, so downside is partly absorbed by a
> non-price-sensitive bid, while the put seller is paid a premium that was set
> before that bid was public. **It fails if** the event-minus-control difference
> is not positive at the 21-session horizon after the pre-registered haircut,
> if the 95% interval on that difference covers zero and the point estimate is
> under 10 bps of collateral, if the result exists at one horizon only, or if
> it flips sign when the haircut, the moneyness, or the entry delay moves to a
> neighbour.

## Universe

The 100 common stocks with the highest consolidated dollar volume over the
whole of 2022, measured from Massive grouped daily bars (close × volume),
dropping non-common-stock reference types. The ranking year is entirely before
the sample, so the list does not depend on later prices or on today's market
cap. This is the Massive starter's "100 largest" idea implemented as
point-in-time liquidity rather than a current market-cap sort, because a
current market cap would look ahead.

## Filing rule

A filing is in the sample when the SEC full-text index returns an 8-K whose
text matches `"repurchase program"` or `"repurchase authorization"`, the form
type is 8-K, and the filer's ticker is in the universe. One event per
accession number. Massive's `/v1/reference/sec/filings` list ignores `cik`,
`ticker` and `filing_date` filters (verified before this study: every filtered
call returned the same unfiltered page or an empty page), so discovery uses
the public SEC full-text index. Massive is still the source for the universe,
the stock bars and the option bars. Each accession is stored in TigerData.

## Entry, with no lookahead

The SEC acceptance timestamp is the clock.

- If that timestamp is on a trading day and is before 15:45 America/New_York,
  the put is sold at **that session's close**. The filing was public before
  the close.
- If the timestamp is missing, or is at or after 15:45 New York, or falls on
  a non-session, the put is sold at the **next session's close**. A date-only
  8-K is never traded on the same close.

The strike is set from the **prior session's close**, not from the entry
close: nearest dollar, 5% below that prior close. The expiry is the first
monthly expiry (third Friday) at least 21 calendar days after entry. One
contract, cash-secured by `strike × 100` dollars. Nothing is held past expiry.

## Horizons, all of them

Marks at 1, 2, 3, 5, 10, 21, 42 and 63 sessions after entry, and at expiry
(intrinsic value `max(strike − spot close, 0)`). A horizon that would need a
price after the requested `--end` date is left missing. It is not filled from
outside the window.

## Costs

Option bars are daily closes from Massive (last-trade aggregates, not
executable quotes). Databento OPRA `ohlcv-1d` is used only when Massive
returns no bar for that contract-day, and only after `metadata.get_cost`
accepts the query under a $2 cap per call. Because the close is not a quote,
every entry and every exit pays a haircut of **5% of the option premium**
(sell at `0.95 × close`, buy back at `1.05 × close`). The 2× case is a 10%
haircut each side. Returns are in basis points of cash collateral.

## Control

For each event, the control is the same issuer 21 trading sessions earlier,
built with the same strike rule, the same expiry rule and the same haircut,
**if** that issuer has no repurchase 8-K whose entry falls within 10 sessions
of the control entry. The reported object is event minus control, paired.
Events without a clean control are counted and excluded from the paired test.

## Sample split

In-sample, and the only window used to look at the variant grid:
**2023-01-01 → 2025-12-31**.

Out-of-sample, evaluated **once**, after the in-sample commit, with the
headline parameters only: **2026-01-01 → 2026-08-31**. The grid is not
re-opened out of sample.

The command takes the window as arguments. Dates are not hard-coded in the
call a judge makes:

    python run_eightk.py --start 2023-01-01 --end 2025-12-31

## Variant budget (54, all reported in-sample)

Entry {headline clock, always next session, always two sessions later}
× premium haircut {2.5%, 5%, 10%}
× OTM distance {2%, 5%, 10%}
× expiry {first monthly ≥ 21 days, second monthly ≥ 21 days}
= 54. Headline is clock / 5% / 5% / first monthly. Anything else is disclosed
and was not used to pick the headline.

## It fails if

* At 21 sessions, mean(event − control) ≤ 0 after the 5% haircut.
* The 95% t-interval on that difference covers zero and the point estimate
  is below 10 bps of collateral.
* Fewer than half of the eight fixed horizons have a positive point estimate.
* The 10% haircut, the 10% OTM put, or the two-session delay flips the sign
  of the 21-session difference.
* The out-of-sample 21-session difference flips sign.
