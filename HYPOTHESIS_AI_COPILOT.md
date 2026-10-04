# Hypothesis: High-Volatility States Strengthen Short-Term Equity Reversal

## Status

Pre-specified research hypothesis. Results are evaluated separately
in-sample and out-of-sample after transaction costs.

## Research Question

Is short-term equity reversal stronger when market volatility is elevated,
and can a volatility-conditioned strategy capture that effect after realistic
trading costs?

## Main Hypothesis

We expect the U.S. equity short-term reversal premium to increase when
lagged VIX is higher.

The economic intuition is that elevated volatility constrains liquidity
providers and increases the compensation required to absorb temporary
order-flow imbalances. If this mechanism is present, stocks experiencing
short-term price dislocations should exhibit stronger subsequent reversal
during high-volatility regimes.

Therefore, a strategy that conditions reversal exposure on lagged VIX
should achieve better risk-adjusted performance than an otherwise comparable
unconditional strategy, after realistic transaction costs.

## Pre-Specified Predictions

1. Subsequent reversal returns should increase with lagged VIX.
2. High-VIX observations should exhibit stronger reversal than low-VIX observations.
3. A VIX-conditioned strategy should outperform unconditional exposure on a
   risk-adjusted basis.
4. The relationship should survive realistic transaction costs.
5. Results should remain directionally consistent in a held-out out-of-sample period.

## Failure Conditions

The hypothesis is not supported if:

- reversal strength does not increase with lagged VIX;
- the VIX-conditioned strategy does not improve risk-adjusted performance;
- the effect disappears after transaction costs;
- held-out results materially contradict the in-sample findings; or
- performance depends primarily on a small number of extreme observations.

## Evaluation

We report in-sample and out-of-sample results separately and include:

- net returns after costs;
- Sharpe ratio;
- maximum drawdown;
- turnover;
- equity curve;
- year-by-year stability;
- cost sensitivity;
- threshold sensitivity;
- bootstrap uncertainty;
- dependence on extreme return days.

Failed or weaker related experiments are retained rather than removed.
