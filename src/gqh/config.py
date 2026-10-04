"""Fixed study constants. Everything here was set in HYPOTHESIS.md before any
backtest was run. Changing a value here is a disclosed variant, not a tweak."""
from __future__ import annotations

import pandas as pd

# ---- sample ---------------------------------------------------------------
SAMPLE_START = pd.Timestamp("1990-01-02")      # first VIX observation on FRED
IS_END = pd.Timestamp("2024-08-31")            # last in-sample day
OOS_START = pd.Timestamp("2024-09-01")         # first out-of-sample day
OOS_END = pd.Timestamp("2026-08-31")           # last day of French data at time of writing
# Track rule: hold out min(most recent 20%, 2 years). 20% of 36.7y = 7.3y > 2y,
# so the 2-year cap binds.

# ---- headline rule --------------------------------------------------------
VIX_NORM = 20.0        # w = 1 at VIX 20 (textbook long-run average, not fitted)
LEVERAGE_CAP = 3.0     # never more than 3x normal exposure
REGIME_WINDOW = 252    # trailing window for the 'regime' variant's VIX median

# ---- cost model -----------------------------------------------------------
TAU = 0.14             # one-way daily turnover of the reversal book (fraction of gross)
C_BASE_BPS = {         # one-way cost in bps per $ traded, at VIX = 20
    "big_rev": 5.0,    # large caps
    "st_rev": 10.0,    # all-cap factor (half of it is small caps)
    "small_rev": 20.0, # small caps (reported for completeness only)
}
COST_SCALES_WITH_VIX = True

# ---- pre-registered sensitivity grid --------------------------------------
GRID_NORMS = (15.0, 20.0, 25.0)
GRID_CAPS = (2.0, 3.0, 4.0)
GRID_UNIVERSES = ("st_rev", "big_rev")
GRID_RULES = ("linear", "regime")

TRADING_DAYS = 252
