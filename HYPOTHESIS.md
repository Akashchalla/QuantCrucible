# Quant Crucible — Hypothesis

**Paid to Hold the Bag: the short-term reversal premium is a payment for
liquidity, and it is largest when liquidity-provider capital is scarce.**

> **Provenance.** This file brings together three hypotheses that were each
> committed *before their first backtest* in `srinivaspenumarthi/cursor_hack`:
>
> | Module | Original file | Commit | Committed (UTC) |
> |---|---|---|---|
> | A | `HYPOTHESIS.md` | `0d0093d` | 2026-10-03 10:54 |
> | B | `HYPOTHESIS_B.md` | `fbd355a` | 2026-10-03 11:53 |
> | C | `HYPOTHESIS_C.md` | `6067ea1` | 2026-10-03 18:14 |
>
> Those commits are the timestamp evidence. This copy changes no rule, threshold,
> cost or prediction. Where the two differ, the originals take precedence.

---

## 1. The economic story

**Edge type:** liquidity provision.

| | |
|---|---|
| **Who is on the other side** | A trader who needs to trade *now*, such as a fund meeting redemptions, a forced de-leverager, a hurried rebalancer or an overnight-news reactor at the open. They accept a worse price for immediacy, and the temporary price pressure then reverts. |
| **Why it persists** | Someone always needs to trade in a hurry. The capital that would compete the premium away (dealer and arbitrageur balance sheet) is the capital that is scarce when the premium is highest: VaR limits bind, margins rise and capital is pulled. |
| **Why VIX** | Lagged VIX is a public proxy for how constrained that capital is (Grossman–Miller 1988; Brunnermeier–Pedersen 2009; Nagel 2012). |

**One sentence:**

> U.S. equity short-term reversal returns are higher on days after VIX is high,
> because impatient traders pay more for immediacy when liquidity providers are
> capital-constrained. If true, reversal returns rise with lagged VIX, and a rule
> that conditions on lagged VIX beats constant exposure net of costs. It fails if
> the slope is not positive, if the rule does not beat constant exposure after
> costs, if a known factor explains it, or if the held-out period reverses it.

We do **not** claim a free lunch. The claim is that this is a risk-bearing
premium whose *size varies with the state of the market*, and that the losses
cluster in exactly the stress periods when it is paid.

---

## 2. Three tests of the same mechanism

### Module A: daily reversal portfolios (36 years)

- **Data:** Kenneth French daily Short-Term Reversal factor `ST_Rev` (the
  cleanest test), plus the tradeable big-cap leg `BIG LoPRIOR − BIG HiPRIOR`;
  VIX close `VIXCLS` from FRED; FF5 + Momentum as controls. Sample from 1990-01-02.
- **Rule:** `w_t = min(VIX_{t−1} / 20, 3)` per $1 long / $1 short.
  The 20 is the textbook long-run VIX average and was **not fitted**. The 3 is a leverage cap.
- **Benchmark:** constant exposure, `w_t = 1`.
- **Predictions:**
  1. In `ST_Rev_t = a + b·VIX_{t−1}`, `b > 0` with Newey–West t > 2.
  2. Mean reversal return rises across VIX quintiles.
  3. Timed net Sharpe > constant net Sharpe.
  4. Positive FF5 + Momentum alpha, market beta near zero.
  5. Plateau: normaliser {15, 20, 25} × cap {2, 3, 4} agree in sign.

### Module B: opening-auction gap fade (S&P 500, 2005–2026)

- **Signal:** overnight gap relative to the median gap that day. Long the
  largest-gap-down quintile, short the largest-gap-up quintile. Enter at the
  official open and exit at the official close. **Never held overnight.**
- **Rule:** *participate, don't lever.* Trade only if `VIX_{t−1} ≥ 20`.
  The threshold is the same unfitted 20.
- **Benchmark:** always-on.
- **Predictions:** gross spread > 0 (B1), slope on lagged VIX > 0 (B2),
  participation beats always-on net of costs (B3), both legs contribute rather
  than only the long leg, which tests for survivorship (B4), and the result holds
  across thresholds {15, 20, 25} and quintile/decile sorts (B5).

### Module C: price of risk vs. quantity of risk

VIX mixes two things: how much risk there is (realised variance, RV) and how
much the market pays to bear it (the variance risk premium,
`VRP = VIX² − RV`). The mechanism says the premium should follow the
**price**, not the quantity.

- **Rules:** on when VRP is above its trailing-252-day median; on when VRP > 0;
  on when the VIX term structure is in backwardation (`VIX / VIX3M > 1`).
- **Predictions:** `b_VRP > 0` controlling for RV (C1); within every RV tercile,
  Sharpe is higher in the top VRP tercile (C2); the VRP rule beats constant
  exposure net of costs (C3); backwardation beats constant exposure (C4).

---

## 3. A fair test

| Safeguard | How |
|---|---|
| **No lookahead** | Every signal uses values dated strictly before day *t*, through an as-of merge. VIX is the *previous* close. Enforced by `tests/test_no_lookahead.py`. |
| **Costs in every number** | One-way cost `c_t = c_base × VIX_{t−1}/20`, since spreads widen when VIX is high. `c_base` = 5 bps for big-cap and the gap fade, 10 bps for the all-cap factor. Also reported: flat costs, costs ×2, and the break-even `c_base`. |
| **Held-out period** | **2024-09-01 → 2026-08-31** (most recent 2 years). Opened **once**, after the in-sample work, in a separate commit via `run_all.py --oos`. |
| **Variants disclosed** | Pre-registered grids: A = 36, B = 24, C = 18, so **78 variants** in total, all reported. Anything else we tried is listed in the note with a count. |
| **Known data biases** | The Module B universe is today's S&P 500 constituents, so it has survivorship bias. We disclose this and check it with B4. Yahoo prices may be revised, so they are cached, not committed. |

---

## 4. What would prove us wrong

| Result | Conclusion |
|---|---|
| Slope on lagged VIX ≤ 0 or not significant | The state-dependence story is wrong. |
| Conditioned rule does not beat constant exposure net of costs | VIX carries no usable timing information. |
| Alpha disappears after FF5 + Momentum | We are holding a known factor. |
| Break-even cost below ~3 bps | Only a market maker can earn it, so it is not a fund strategy. |
| Only the long leg works (B) | Survivorship, not liquidity provision. |
| Sign flips out-of-sample | In-sample luck or a regime change. |

Failed predictions are reported alongside the ones that pass.

---

## References

- Grossman, S. & Miller, M. (1988). *Liquidity and Market Structure.* JF 43(3).
- Jegadeesh, N. (1990). *Evidence of Predictable Behavior of Security Returns.* JF 45(3).
- Brunnermeier, M. & Pedersen, L. H. (2009). *Market Liquidity and Funding Liquidity.* RFS 22(6).
- Bollerslev, T., Tauchen, G. & Zhou, H. (2009). *Expected Stock Returns and Variance Risk Premia.* RFS 22(11).
- Nagel, S. (2012). *Evaporating Liquidity.* RFS 25(7).
- Berkman, H., Koch, P., Tuttle, L. & Zhang, Y. (2012). *Paying Attention: Overnight Returns and the Hidden Cost of Buying at the Open.* JFQA 47(4).
- Bailey, D. & López de Prado, M. (2014). *The Deflated Sharpe Ratio.*
- Moreira, A. & Muir, T. (2017). *Volatility-Managed Portfolios.* JF 72(4).
- Lou, D., Polk, C. & Skouras, S. (2019). *A Tug of War: Overnight Versus Intraday Expected Returns.* JFE 134(1).
