# Hypothesis B (pre-registered, written before any backtest of this module)

**Written:** 2026-10-03, after Module A (`HYPOTHESIS.md`, `results/REPORT.md`)
was finished and its out-of-sample window had been opened, and **before any
single-stock price data was downloaded or any gap-fade number was computed.**
The git commit that adds this file is the timestamp.

## Why a second module

Module A established, on 36 years of Kenneth French portfolios, that the
short-term reversal premium is state-dependent: it is earned when lagged VIX
is high and is essentially absent otherwise. It also showed that **levering
up** reversal exposure in high-VIX states does not raise the Sharpe ratio,
because the book's own volatility scales with VIX.

Module B takes the same mechanism — liquidity provision is paid when
risk-bearing capital is scarce — to the place where a practitioner's
order-imbalance is most concentrated: the **opening auction**. Overnight news
and order flow create gaps between yesterday's close and today's open; the
open is where impatient traders (overnight news reactors, retail at-the-open
orders, index flows) demand immediacy, and where the Berkman–Koch–Tuttle–Zhang
(2012) and Lou–Polk–Skouras (2019) evidence shows a systematic intraday
reversal of the overnight move. Our practitioner material (the uploaded
strategy matrix) is a gap-fade system: it fades pre-market highs/lows toward
VWAP. Module B tests that idea at daily resolution on public data.

The lesson of Module A changes the rule we pre-register: **do not size up in
high-VIX states, but only participate in them.** Costs per trade are roughly
fixed; the premium is state-dependent; so the net expected return is positive
only above a VIX threshold. The rule is a participation rule, not a leverage
rule.

## The hypothesis in one paragraph

> Among US large-cap stocks, the intraday (open-to-close) return of stocks
> that gapped **down** at the open exceeds that of stocks that gapped **up**,
> relative to the market's own gap, because the open is a liquidity event and
> the gap partly reflects price pressure rather than information. The size of
> this reversal **rises with the previous day's VIX**, as in Module A.
> **If true**, (i) a long gap-down / short gap-up quintile spread held from the
> open to the close has a positive mean, (ii) its mean increases with lagged
> VIX, and (iii) after realistic auction costs the spread is **not** profitable
> unconditionally but **is** profitable on days when lagged VIX ≥ 20.
> **It fails if** the gross spread is not positive, if the slope on lagged VIX
> is not positive, or if the participation rule does not beat always-on net of
> costs.

## Universe, data and point-in-time rules (public, no API key)

| Item | Choice |
|---|---|
| Universe | Current S&P 500 constituents from Wikipedia's *List of S&P 500 companies*, snapshotted to `data/sp500_constituents.csv` (committed). Each stock enters the sample **only from its "Date added"** to the index (point-in-time inclusion, so a stock is never traded before it was a large cap). |
| Survivorship | Stocks removed from the index are **not** in the file, so the universe has survivorship bias. This is disclosed, not hidden. Because the strategy is dollar-neutral, holds for ~6.5 hours and re-forms daily, long-run drift of survivors should matter little; prediction B4 below is the diagnostic that checks it. |
| Prices | Yahoo Finance daily bars via `yfinance`, split- and dividend-adjusted `Open` and `Close`. Yahoo may revise history; the download is cached, not committed, and the README says so. |
| Conditioning | VIX close `VIXCLS` (FRED), lagged one trading day with a strict as-of merge (same code as Module A). |
| Sample | 2005-01-03 → 2026-08-31. Days with fewer than 100 eligible stocks are skipped. |
| Out-of-sample | **2024-09-01 → 2026-08-31** (same window as Module A, the 2-year cap binds), evaluated **once**, with a separate `--oos` run and commit. |

## Signal and portfolios

For stock *i* on day *t*:

    gap_{i,t}   = Open_{i,t} / Close_{i,t-1} − 1
    relgap_{i,t}= gap_{i,t} − median_j gap_{j,t}          (market gap removed)
    r_{i,t}     = Close_{i,t} / Open_{i,t} − 1            (open-to-close return)

Each day, sort eligible stocks on `relgap` into quintiles. Equal-weight.
**Spread** = Q1 (largest gap down) **minus** Q5 (largest gap up), $1 per side.
Both legs are entered at the official opening price and exited at the official
closing price. There is **no overnight position, ever.**

Execution assumption, stated plainly: entry at the official open requires
market-on-open orders submitted before 9:30 using pre-market indicative
prices. Daily data cannot measure the slippage between the indicative and the
official print; it is absorbed in the cost assumption below and is the main
limitation of the module.

## Pre-specified trading rule (headline)

    participate_t = 1 if VIX_{t-1} ≥ 20 else 0
    position_t    = participate_t × ($1 long Q1, $1 short Q5)

`20` is the same unfitted constant as Module A. Benchmark: always-on
(`participate_t = 1`).

## Pre-specified cost model

One-way cost per dollar traded on day *t*:

    c_t = c_base × (VIX_{t-1} / 20),   c_base = 5 bps (headline)

Each $1 per side is bought at the open and sold at the close (or vice-versa),
so dollars traded per day = 4 per $1-per-side spread; daily cost = 4·c_t
≈ 20 bps on a VIX-20 day. Also reported: `c_base` ∈ {2.5, 10} bps, and the
break-even `c_base` at which net mean is zero. Everything reported is net
unless labelled gross.

## Testable predictions (in-sample only)

* **B1** Gross spread mean > 0 with Newey–West t > 2.
* **B2** Regression of the gross spread on `VIX_{t-1}` has slope > 0 with NW
  t > 2; top VIX quintile mean > bottom VIX quintile mean.
* **B3** Net of headline costs, the participation rule has a higher Sharpe
  than always-on, and its net mean is positive with NW t > 2.
* **B4** Both legs contribute: Q1 intraday return exceeds the equal-weighted
  universe intraday return, and Q5 falls short of it. (If only the long leg
  works, survivorship drift is the likelier explanation and we say so.)
* **B5** Plateau: thresholds {15, 20, 25} and {quintile, decile} sorts give the
  same sign for B3.

## It fails if

* B1 fails → there is no gap-fade premium in large caps at daily resolution;
  the practitioner edge, if any, lives inside the first minutes and needs
  intraday data we do not have.
* B2 fails → the mechanism is not the Module A mechanism.
* B3 fails → the premium exists but is a market maker's premium; we report
  the break-even cost and stop.
* Only the long leg works (B4) → survivorship, not liquidity provision.

## Variant budget (disclosed up front)

Threshold {15, 20, 25} × sort {quintile, decile} × `c_base` {2.5, 5, 10} = 18,
plus always-on × {quintile, decile} × 3 costs = 6. **24 variants**, all
reported. Anything beyond this is listed in the note with a count.

## References (additional to Module A)

* Berkman, H., Koch, P., Tuttle, L. & Zhang, Y. (2012). *Paying Attention:
  Overnight Returns and the Hidden Cost of Buying at the Open.* JFQA 47(4).
* Lou, D., Polk, C. & Skouras, S. (2019). *A Tug of War: Overnight Versus
  Intraday Expected Returns.* Journal of Financial Economics 134(1).
* Heston, S., Korajczyk, R. & Sadka, R. (2010). *Intraday Patterns in the
  Cross-section of Stock Returns.* Journal of Finance 65(4).
