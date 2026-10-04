# Hypothesis (pre-specified research hypothesis)

**Written:** 2026-10-03, before the data pipeline was run or any result was seen.

**Public repository note:** This public repository was assembled after the
research analysis. The public Git commit records publication of this
pre-specified hypothesis; it should not be interpreted as the original
pre-registration timestamp. Any deviations from this specification are
disclosed in the research note.

## Edge source: liquidity provision

Short-term reversal — buying stocks that fell over the past month and selling
stocks that rose — is the return to supplying immediacy. The counterparty is an
investor who needs to trade *now* (a fund facing redemptions, a forced
de-leverager, a hurried rebalancer) and pays, through the price, for someone
to take the other side. The temporary price pressure then reverts.

We do not claim the reversal premium is a free lunch. We claim it is a
**risk-bearing premium earned by liquidity providers, and that its size depends
on how scarce liquidity-provider capital is.** When market volatility is high,
market makers and arbitrageurs are constrained (VaR limits bind, margins rise,
capital is withdrawn), so the price they demand for immediacy rises. This is
the mechanism in Grossman–Miller (1988), Brunnermeier–Pedersen (2009) and,
empirically, Nagel (2012), who shows reversal returns are strongly predicted by
lagged VIX.

## The hypothesis in one paragraph

> We expect the US equity short-term reversal premium to be **larger when the
> prior day's VIX is higher**, because impatient traders must pay more for
> immediacy when the capital of liquidity providers is constrained. The edge
> persists because someone always needs to trade in a hurry, and the capital
> that would compete it away is precisely what is scarce when the premium is
> highest. **If true**, the expected daily return of a reversal portfolio should
> rise monotonically with lagged VIX, and a strategy that scales its reversal
> exposure by lagged VIX should earn a higher Sharpe ratio than one that holds a
> constant exposure, after transaction costs that themselves rise with VIX.
> **It fails if** the slope of reversal returns on lagged VIX is not positive,
> if the timed strategy does not beat constant exposure in-sample, if the
> result is explained by market beta or other standard factors, or if realistic
> costs for a non-market-maker eliminate the edge.

## Universe and instruments (public, citable data)

| Role | Series | Source |
|---|---|---|
| Hypothesis test (most powerful) | Daily Short-Term Reversal factor `ST_Rev` (long low prior-month return, short high prior-month return, average of small and big; portfolios re-formed daily) | Kenneth French Data Library |
| Tradeable implementation | Big-cap reversal leg: `BIG LoPRIOR − BIG HiPRIOR` from the daily 6 Portfolios formed on Size and Short-Term Reversal (value-weighted) | Kenneth French Data Library |
| Conditioning variable | CBOE VIX close, series `VIXCLS` | FRED (St. Louis Fed) |
| Factor controls | Fama–French 5 factors + Momentum, daily | Kenneth French Data Library |

Both reversal series are reported at every stage. The `ST_Rev` factor is the
cleanest test of the economic hypothesis; the big-cap leg is what a fund could
actually trade at size, and is what the capacity and cost analysis is about.

## Horizon and frequency

Daily. The reversal portfolio is held for one day and re-formed daily
(that is how the French portfolios are built). The timing signal is one day
old. The conditioning horizon is "tomorrow's reversal return given today's VIX".

## Pre-specified trading rule (headline)

Position in the reversal portfolio on day *t*, per $1 long / $1 short:

    w_t = min( VIX_{t-1} / 20 , 3 )

* `VIX_{t-1}` is the VIX **close of the previous trading day**, so the position
  for day *t* is known before day *t* opens. No same-bar information is used.
* `20` is a normalising constant chosen because it is the long-run average
  level of VIX quoted in every textbook; it is **not** fitted. `w = 1` at
  VIX 20 makes the timed strategy directly comparable to constant exposure.
* `3` is a leverage cap: the risk-management rule that the strategy never runs
  more than 3× its normal exposure, however high VIX goes.

Benchmark: `w_t = 1` (constant exposure to the same reversal portfolio).

## Pre-specified cost model

Costs rise with volatility; spreads widen exactly when VIX is high. So the
one-way cost per dollar traded on day *t* is

    c_t = c_base × (VIX_{t-1} / 20)

with `c_base` = 5 bps for the big-cap leg and 10 bps for the all-cap factor.
Dollars traded on day *t* = turnover of the reversal portfolio itself
(assumed one-way daily turnover `τ` of the gross book, pre-set at 14% from
the 20-day formation window: consecutive sorting variables have correlation
19/20, which implies roughly 12–15% of each side leaves the portfolio per day)
plus the timing turnover `|w_t − w_{t−1}|` × gross. Every reported number is
net of this. We also report: flat costs (not VIX-scaled), costs ×2, and the
**break-even `c_base`** at which the net Sharpe reaches zero.

## Testable predictions (in-sample only)

1. Regression `ST_Rev_t = a + b·VIX_{t-1} + e` has `b > 0` with Newey–West
   t-statistic above 2.
2. Mean reversal return is monotonically increasing across VIX quintiles.
3. Timed strategy net Sharpe > constant-exposure net Sharpe.
4. Alpha of the timed strategy on FF5 + Momentum is positive and significant;
   its market beta is near zero.
5. Neighbouring parameter choices agree: normaliser ∈ {15, 20, 25} and cap
   ∈ {2, 3, 4} all give the same sign of improvement (a plateau, not a spike).

## It fails if

* `b ≤ 0`, or not significant → the state-dependence story is wrong.
* Timed Sharpe ≤ constant Sharpe → VIX carries no timing information.
* The alpha disappears after factor controls → we are just long/short a known factor.
* Break-even `c_base` is below ~3 bps for the big-cap leg → only a market maker
  with near-zero costs can earn it; we report it as a market-maker's premium,
  not a fund strategy.
* Out-of-sample sign flips → the in-sample result was luck or the regime changed.

## Out-of-sample protocol

Track rule: hold out the most recent 20% or 2 years, whichever is shorter.
Sample starts 1990-01-02 (first VIX observation). 20% of ~36.7 years is ~7.3
years, so the **2-year cap binds**: out-of-sample is **2024-09-01 →
2026-08-31** (the last month of French data at the time of writing).
The intended protocol was to evaluate the out-of-sample period **once**, at
the end, using the rule above without changing the specification. The code
keeps the held-out evaluation behind a separate `--oos` flag. The public
repository contains the resulting OOS artifacts, so its Git history should not
be interpreted as proof of the original holdout timing.

## Variant budget (disclosed up front)

Headline is fixed above. The sensitivity grid is pre-registered as:
normaliser {15, 20, 25} × cap {2, 3, 4} × universe {all-cap factor, big-cap
leg} × rule {linear, regime: w = 1 if VIX above trailing-1y median else 0}
= **36 variants**, all reported. Anything tried beyond this grid is listed in
the note's "what we also tried" box with a count.

## References

* Nagel, S. (2012). *Evaporating Liquidity.* Review of Financial Studies 25(7).
* Grossman, S. & Miller, M. (1988). *Liquidity and Market Structure.* Journal of Finance 43(3).
* Brunnermeier, M. & Pedersen, L. H. (2009). *Market Liquidity and Funding Liquidity.* RFS 22(6).
* Jegadeesh, N. (1990). *Evidence of Predictable Behavior of Security Returns.* Journal of Finance 45(3).
* Moreira, A. & Muir, T. (2017). *Volatility-Managed Portfolios.* Journal of Finance 72(4).
* Bailey, D. & López de Prado, M. (2014). *The Deflated Sharpe Ratio.*
