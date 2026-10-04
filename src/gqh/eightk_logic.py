"""Pure rules for the repurchase-8-K put study. No network, no files.

Specified in HYPOTHESIS_8K.md before any filing or option bar was stored.
"""
from __future__ import annotations

import calendar
import re
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from scipy import stats

ET = ZoneInfo("America/New_York")
HORIZONS = (1, 2, 3, 5, 10, 21, 42, 63)
HAIRCUTS = (0.025, 0.05, 0.10)
OTMS = (0.02, 0.05, 0.10)
DELAYS = ("clock", "next", "skip2")
EXPIRY_KS = (1, 2)
HEADLINE = {"delay": "clock", "haircut": 0.05, "otm": 0.05, "expiry_k": 1}
N_VARIANTS = len(DELAYS) * len(HAIRCUTS) * len(OTMS) * len(EXPIRY_KS)
CUTOFF = time(15, 45)
TICKER_RE = re.compile(r"\(([A-Z][A-Z0-9.\-]{0,5})\)")


def third_friday(year: int, month: int) -> pd.Timestamp:
    fridays = [d for d in calendar.Calendar().itermonthdates(year, month)
               if d.month == month and d.weekday() == 4]
    return pd.Timestamp(fridays[2])


def monthly_expiry(entry: pd.Timestamp, k: int = 1, min_days: int = 21) -> pd.Timestamp:
    """The k-th monthly expiry (third Friday) at least `min_days` after entry."""
    entry = pd.Timestamp(entry).normalize()
    found: list[pd.Timestamp] = []
    y, m = entry.year, entry.month
    for step in range(0, 14):
        mm = m + step
        yy, mm = y + (mm - 1) // 12, (mm - 1) % 12 + 1
        fri = third_friday(yy, mm)
        if (fri - entry).days >= min_days:
            found.append(fri)
        if len(found) >= k:
            return found[k - 1]
    raise ValueError(f"no expiry for {entry} k={k}")


def put_symbol(root: str, expiry: pd.Timestamp, strike: float) -> str:
    """Massive OSI-style daily ticker. Strike is 8 digits with 3 implied decimals."""
    strike_i = int(round(float(strike) * 1000))
    exp = pd.Timestamp(expiry)
    return f"O:{root}{exp:%y%m%d}P{strike_i:08d}"


def occ_raw_symbol(osi: str) -> str:
    """Databento OPRA raw_symbol. OCC pads the root to 6 characters.

    O:AAPL240719P00190000 -> 'AAPL  240719P00190000'. The unpadded form is rejected.
    """
    body = osi[2:] if osi.startswith("O:") else osi
    if len(body) < 15:
        return body
    root, rest = body[:-15], body[-15:]
    return f"{root:<6}{rest}"


def strike_from_prior(prior_close: float, otm: float) -> float:
    return float(max(1, round(prior_close * (1.0 - otm))))


_INDEX_CACHE: dict[int, pd.DatetimeIndex] = {}


def _as_index(sessions) -> pd.DatetimeIndex:
    """Normalised session index. Cached on object identity: the study passes one index through every rule."""
    key = id(sessions)
    hit = _INDEX_CACHE.get(key)
    if hit is not None:
        return hit
    idx = pd.DatetimeIndex(pd.to_datetime(sessions))
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    idx = pd.DatetimeIndex(idx.normalize().unique()).sort_values()
    if len(_INDEX_CACHE) > 8:
        _INDEX_CACHE.clear()
    _INDEX_CACHE[key] = idx
    return idx


def next_session(day, sessions, strict: bool = True) -> pd.Timestamp:
    idx = _as_index(sessions)
    day = pd.Timestamp(day).tz_localize(None).normalize()
    later = idx[idx > day] if strict else idx[idx >= day]
    return later[0] if len(later) else pd.NaT


def shift_session(day, sessions, k: int) -> pd.Timestamp:
    idx = _as_index(sessions)
    day = pd.Timestamp(day).tz_localize(None).normalize()
    i = idx.get_indexer([day])[0]
    j = i + k
    if i < 0 or j < 0 or j >= len(idx):
        return pd.NaT
    return idx[j]


def entry_session(filing_day, acceptance, sessions, mode: str = "clock") -> pd.Timestamp:
    """When the put is sold. `clock` uses the acceptance timestamp; a missing
    timestamp or one at/after 15:45 New York waits until the next session."""
    filing_day = pd.Timestamp(filing_day).tz_localize(None).normalize()
    if mode == "next":
        return next_session(filing_day, sessions, strict=True)
    if mode == "skip2":
        first = next_session(filing_day, sessions, strict=True)
        return next_session(first, sessions, strict=True) if pd.notna(first) else pd.NaT
    if acceptance is None or (isinstance(acceptance, float) and np.isnan(acceptance)) or pd.isna(acceptance):
        return next_session(filing_day, sessions, strict=True)
    ts = pd.Timestamp(acceptance)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    et = ts.tz_convert(ET)
    day = pd.Timestamp(et.date())
    idx = _as_index(sessions)
    if et.time() < CUTOFF and day in idx:
        return day
    return next_session(day, sessions, strict=True)


def tickers_from_display(name: str) -> list[str]:
    """Every parenthetical ticker, skipping the CIK token. Order preserved."""
    seen: list[str] = []
    for h in TICKER_RE.findall(name or ""):
        if h.startswith("CIK") or h in seen:
            continue
        seen.append(h)
    return seen


def ticker_from_display(name: str) -> str | None:
    """'Sprinklr, Inc.  (CXM)  (CIK 0001569345)' -> CXM. Skips the CIK paren."""
    hits = tickers_from_display(name)
    return hits[0] if hits else None


def pnl_bps(entry_px: float, exit_px: float, haircut: float, strike: float) -> float:
    """Short put, per share prices, haircut each side, in bps of cash collateral."""
    if entry_px is None or exit_px is None or not np.isfinite(entry_px) or not np.isfinite(exit_px):
        return np.nan
    if entry_px < 0 or exit_px < 0 or strike <= 0:
        return np.nan
    credit = entry_px * (1.0 - haircut)
    debit = exit_px * (1.0 + haircut)
    return (credit - debit) / strike * 1e4


def mean_ci(values, alpha: float = 0.05) -> dict:
    x = np.asarray(pd.Series(values).dropna(), dtype=float)
    n = int(x.size)
    if n == 0:
        return {"n": 0, "mean": np.nan, "se": np.nan, "lo": np.nan, "hi": np.nan, "t": np.nan}
    mean = float(x.mean())
    se = float(x.std(ddof=1) / np.sqrt(n)) if n > 1 else np.nan
    if n < 2 or not np.isfinite(se) or se == 0:
        return {"n": n, "mean": mean, "se": se, "lo": np.nan, "hi": np.nan, "t": np.nan}
    tcrit = float(stats.t.ppf(1 - alpha / 2, n - 1))
    tstat = mean / se
    return {"n": n, "mean": mean, "se": se, "lo": mean - tcrit * se, "hi": mean + tcrit * se, "t": float(tstat)}


def control_ok(control_day, issuer_entries: list, sessions, window: int = 10) -> bool:
    """False when another repurchase entry for this issuer sits within `window` sessions."""
    if pd.isna(control_day):
        return False
    for e in issuer_entries:
        if pd.isna(e):
            continue
        a = shift_session(control_day, sessions, -window)
        b = shift_session(control_day, sessions, window)
        ed = pd.Timestamp(e).normalize()
        lo = a if pd.notna(a) else pd.Timestamp(control_day)
        hi = b if pd.notna(b) else pd.Timestamp(control_day)
        if lo <= ed <= hi:
            return False
    return True


def mark_horizon(opt: pd.Series, entry, sessions, h: int) -> float:
    """Option close `h` sessions after entry. Missing if the session is off the index."""
    exit_day = shift_session(entry, sessions, h)
    if pd.isna(exit_day) or exit_day not in opt.index:
        return np.nan
    val = opt.loc[exit_day]
    if isinstance(val, pd.Series):
        val = val.iloc[-1]
    return float(val) if np.isfinite(val) else np.nan


def expiry_session(expiry, sessions) -> pd.Timestamp:
    """Last session on or before the Friday expiry (a holiday rolls back a few days).

    If the window ends well before that Friday, the expiry mark is missing.
    It is not filled with an earlier close.
    """
    day = _on_or_before(expiry, sessions)
    if pd.isna(day):
        return pd.NaT
    if (pd.Timestamp(expiry).normalize() - pd.Timestamp(day)).days > 4:
        return pd.NaT
    return day


def _on_or_before(day, sessions) -> pd.Timestamp:
    idx = _as_index(sessions)
    day = pd.Timestamp(day).normalize()
    earlier = idx[idx <= day]
    return earlier[-1] if len(earlier) else pd.NaT


def trade_horizons(opt: pd.Series, spot: pd.Series, entry, expiry, strike: float,
                   haircut: float, sessions) -> dict:
    """bps of collateral at each fixed horizon and at expiry. NaN if the mark is missing."""
    entry = pd.Timestamp(entry).normalize()
    if entry not in opt.index or not np.isfinite(opt.loc[entry] if not isinstance(opt.loc[entry], pd.Series) else opt.loc[entry].iloc[-1]):
        return {str(h): np.nan for h in HORIZONS} | {"expiry": np.nan}
    entry_px = float(opt.loc[entry] if not isinstance(opt.loc[entry], pd.Series) else opt.loc[entry].iloc[-1])
    out = {}
    for h in HORIZONS:
        px = mark_horizon(opt, entry, sessions, h)
        out[str(h)] = pnl_bps(entry_px, px, haircut, strike)
    exp_day = expiry_session(expiry, sessions)
    if pd.isna(exp_day) or exp_day not in spot.index:
        out["expiry"] = np.nan
    else:
        spot_px = float(spot.loc[exp_day] if not isinstance(spot.loc[exp_day], pd.Series) else spot.loc[exp_day].iloc[-1])
        intrinsic = max(strike - spot_px, 0.0)
        out["expiry"] = pnl_bps(entry_px, intrinsic, haircut, strike)
    return out


def summarise_pairs(diffs_by_horizon: dict[str, list]) -> dict:
    return {h: mean_ci(v) for h, v in diffs_by_horizon.items()}


def kill_checks(headline_diffs: dict, grid_rows: list[dict]) -> dict:
    """The pre-registered failure tests. Values are True when the test FAILS."""
    d21 = headline_diffs.get("21", {})
    mean = d21.get("mean", np.nan)
    lo, hi = d21.get("lo", np.nan), d21.get("hi", np.nan)
    signs = []
    for h in HORIZONS:
        m = headline_diffs.get(str(h), {}).get("mean", np.nan)
        if np.isfinite(m):
            signs.append(m > 0)
    pos_share = float(np.mean(signs)) if signs else 0.0

    def row_mean(delay, haircut, otm, k):
        for r in grid_rows:
            if r["delay"] == delay and r["haircut"] == haircut and abs(r["otm"] - otm) < 1e-9 and r["expiry_k"] == k:
                return r.get("diff_21")
        return np.nan
    flips = {
        "haircut_10": row_mean("clock", 0.10, 0.05, 1),
        "otm_10": row_mean("clock", 0.05, 0.10, 1),
        "delay_2": row_mean("skip2", 0.05, 0.05, 1),
    }
    return {
        "diff_21_not_positive": bool(np.isfinite(mean) and mean <= 0) or not np.isfinite(mean),
        "interval_covers_zero_and_small": bool(np.isfinite(lo) and lo <= 0 <= hi and abs(mean) < 10),
        "horizons_not_mostly_positive": pos_share < 0.5,
        "neighbour_sign_flip": {name: bool(np.isfinite(v) and np.isfinite(mean) and mean > 0 and v < 0) for name, v in flips.items()},
        "diff_21_mean_bps": mean,
        "diff_21_ci": [lo, hi],
        "positive_horizon_share": pos_share,
    }


def equity_stats(daily_ret: pd.Series) -> dict:
    r = daily_ret.dropna()
    if r.empty:
        return {"ann_return": np.nan, "ann_vol": np.nan, "sharpe": np.nan, "max_drawdown": np.nan, "n_days": 0}
    ann_ret = float(r.mean() * 252)
    ann_vol = float(r.std(ddof=1) * np.sqrt(252)) if len(r) > 1 else np.nan
    wealth = (1 + r.fillna(0)).cumprod()
    peak = wealth.cummax()
    dd = float((wealth / peak - 1).min())
    sharpe = float(ann_ret / ann_vol) if ann_vol and np.isfinite(ann_vol) and ann_vol > 0 else np.nan
    return {"ann_return": ann_ret, "ann_vol": ann_vol, "sharpe": sharpe, "max_drawdown": dd, "n_days": int(len(r))}
