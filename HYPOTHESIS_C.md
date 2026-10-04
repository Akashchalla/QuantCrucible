# Hypothesis C (pre-registered, written before any computation of this module)

**Written:** 2026-10-03 18:15 UTC, after Modules A and B were finished and their
held-out windows opened, and **before any variance-risk-premium or term-structure
series was computed or regressed.** The git commit that adds this file is the
timestamp.

## The open problem Modules A and B left

Both modules found that the liquidity-provision premium rises with lagged VIX,
and both found that sizing *into* high VIX does not raise the Sharpe ratio,
because the books' own volatility rises with VIX. VIX conflates two things:

* the **quantity of risk** a liquidity provider must hold — realised variance,
  which raises the book's volatility one-for-one and is not, by itself, a reason
  to be paid more per unit of risk; and
* the **price of bearing risk** — how much the market pays, above realised
  variance, for someone to hold it. That is the variance risk premium
  (Bollerslev, Tauchen & Zhou 2009), VIX² minus realised variance, and it is
  the quantity the Grossman–Miller / Brunnermeier–Pedersen mechanism actually
  speaks about: it is high when risk-bearing capital is scarce relative to the
  risk that must be held.

If the mechanism is right, the reversal premium **per unit of risk** should
load on the *price* component, not the *quantity* component. That would be a
state variable that can select days without automatically selecting volatile
days — the thing a VIX-level rule cannot do.

A second, independent, public proxy for acute scarcity of risk capital is the
**VIX term structure**: when 1-month VIX exceeds 3-month VIX (backwardation),
dealers are paying up for near-term protection, which is a stress signal
distinct from the level.

## The hypothesis in one paragraph

> The short-horizon liquidity-provision premium (Module A's daily reversal
> books and Module B's opening-auction gap fade) is compensation for the
> **price** of risk-bearing, not the **quantity** of risk. Decomposing lagged
> VIX² into realised variance and the variance risk premium, the premium should
> load on the variance risk premium; holding realised variance fixed, higher
> VRP should mean a higher Sharpe ratio, whereas higher realised variance at a
> fixed VRP should not. A participation rule driven by VRP (or by term-structure
> backwardation) should therefore beat both constant exposure and the VIX-level
> rules of Modules A and B on net Sharpe, because it keeps the high-premium days
> and discards days that are merely volatile. **It fails if** the VRP
> coefficient is not positive once realised variance is controlled for, or if
> the VRP rule does not beat constant exposure net of costs.

## Data (public, no API key, already in the pipeline except one FRED series)

| Series | Source | Use |
|---|---|---|
| VIX close `VIXCLS` | FRED | VIX²_{t−1}, annualised variance in %² units |
| Market excess return `Mkt-RF` (daily) | Kenneth French | realised variance RV_{t−1} = 252 × mean of (100·r)² over the 21 trading days ending t−1 (63-day window as a disclosed variant) |
| 3-month VIX `VXVCLS` (from 2007-12-04) | FRED | term-structure ratio VIX_{t−1} / VIX3M_{t−1} |

    VRP_{t-1} = VIX²_{t-1} − RV_{t-1}

Everything is lagged with the strict as-of merge used throughout (values dated
strictly before day *t*). The books are exactly those of Modules A (big-cap leg,
ST_Rev factor; constant-exposure cost model, c_base 5 / 10 bps) and B
(quintile gap-fade spread; 4 × 5 bps × VIX_{t−1}/20 per day). Nothing about the
books changes; only the state variable that switches them on.

## Pre-specified rules

    VRP rule        : on iff VRP_{t-1} > trailing-252-day median of VRP (causal, ends t-1)
    VRP>0 rule      : on iff VRP_{t-1} > 0
    Backwardation   : on iff VIX_{t-1} / VIX3M_{t-1} > 1          (sample 2008-01 onward)

Position when on: $1 per side (w = 1); when off: flat. Benchmarks: constant
exposure (A), always-on (B), and the Module A/B VIX rules (regime rule for A,
VIX ≥ 20 participation for B). All net of the pre-registered costs.

## Testable predictions (in-sample, same windows as A and B)

* **C1 (decomposition).** In `r_t = a + b_VRP·VRP_{t−1} + b_RV·RV_{t−1} + e`,
  with Newey–West errors, `b_VRP > 0` with t > 2 for the big-cap leg and for
  ST_Rev; reported for the gap fade.
* **C2 (price, not quantity).** Sort days into realised-variance terciles, and
  within each into VRP terciles. The annualised Sharpe of the book is higher in
  the top VRP tercile than in the bottom VRP tercile **within every RV tercile**
  (3 of 3 for the big-cap leg counts as a pass; 2 of 3 as weak). Conversely,
  within VRP terciles, Sharpe does not rise with RV.
* **C3 (rule).** Net Sharpe of the VRP rule > net Sharpe of constant exposure
  for the big-cap leg and ST_Rev, with a positive spanning-regression alpha on
  constant exposure (HAC t > 2); and > the VIX ≥ 20 participation rule for the
  gap fade.
* **C4 (independent proxy).** Over 2008–2024, the backwardation rule's net
  Sharpe > constant exposure for the big-cap leg.

## It fails if

* C1 fails → the premium is about the quantity of risk; VIX cannot be improved
  on with these proxies, and the Module A conclusion (constant notional) stands.
* C1 passes but C3 fails → the decomposition is statistically real but too noisy
  to trade; we report the gap between the two.
* The rule's gains vanish out of sample → state selection was in-sample luck.

## Out-of-sample protocol

Unchanged: **2024-09-01 → 2026-08-31**, evaluated once for all C rules together,
in a separate commit after the in-sample commit.

## Variant budget (disclosed up front)

RV window {21, 63} × rule {VRP median, VRP > 0, backwardation} × book
{big-cap, ST_Rev, gap fade} = **18 variants**, all reported. Anything beyond is
listed with a count.

## References (additional)

* Bollerslev, T., Tauchen, G. & Zhou, H. (2009). *Expected Stock Returns and
  Variance Risk Premia.* Review of Financial Studies 22(11).
* Carr, P. & Wu, L. (2009). *Variance Risk Premiums.* RFS 22(3).
* Adrian, T., Etula, E. & Muir, T. (2014). *Financial Intermediaries and the
  Cross-Section of Asset Returns.* Journal of Finance 69(6).
* Cheng, I.-H. (2019). *The VIX Premium.* RFS 32(1).
