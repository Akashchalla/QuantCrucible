"""Pre-trade and post-trade risk controls. Every check returns a Violation or nothing; the
pipeline refuses to submit if any check at level 'block' fires, and records every outcome
in live_risk_events so the audit trail exists even on quiet days.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

from .settings import SETTINGS, Settings


@dataclass
class Violation:
    check: str
    level: str          # 'block' | 'warn'
    message: str


def kill_switch_engaged(s: Settings = SETTINGS) -> bool:
    return s.kill_switch.exists()


def pre_trade(session: date, *, gate_on: bool, vix_as_of: date | None, n_priced: int, n_universe: int,
              sig: pd.DataFrame, indicative_age_s: float | None, already_submitted: bool,
              realised_loss_pct: float | None = None, s: Settings = SETTINGS) -> list[Violation]:
    v: list[Violation] = []
    if kill_switch_engaged(s):
        v.append(Violation("kill_switch", "block", f"{s.kill_switch} exists — manual halt"))
    if already_submitted:
        v.append(Violation("duplicate_session", "block", "orders already submitted for this session"))
    if not gate_on:
        v.append(Violation("vix_gate", "block", "participation rule says stay out (VIX_{t-1} below threshold)"))
    if vix_as_of is None or (session - vix_as_of) > timedelta(days=s.stale_vix_days):
        v.append(Violation("stale_vix", "block", f"VIX as of {vix_as_of} is older than {s.stale_vix_days} days"))
    if n_priced < s.min_names:
        v.append(Violation("universe_coverage", "block", f"only {n_priced}/{n_universe} names priced; need {s.min_names}"))
    if indicative_age_s is not None and indicative_age_s > s.max_indicative_age_s:
        v.append(Violation("stale_indicative", "block", f"indicative prices are {indicative_age_s:.0f}s old"))

    live = sig[sig["side"] != 0]
    gross = (live["target_qty"].abs() * live["est_open"]).sum()
    if gross > s.max_gross_notional:
        v.append(Violation("gross_limit", "block", f"gross ${gross:,.0f} > ${s.max_gross_notional:,.0f}"))
    per_name = (live["target_qty"].abs() * live["est_open"])
    cap = s.max_name_pct_of_side * s.notional_per_side * 1.02
    if (per_name > cap).any():
        v.append(Violation("name_limit", "block", f"{int((per_name > cap).sum())} names exceed ${cap:,.0f}"))
    n_long, n_short = int((live["side"] == 1).sum()), int((live["side"] == -1).sum())
    if n_long == 0 or n_short == 0:
        v.append(Violation("one_sided", "block", f"long {n_long} / short {n_short}: book must be dollar-neutral"))
    elif abs(n_long - n_short) > 0.2 * max(n_long, n_short):
        v.append(Violation("imbalanced_baskets", "warn", f"long {n_long} / short {n_short}"))
    long_notional = live.loc[live["side"] == 1, "target_qty"].mul(live.loc[live["side"] == 1, "est_open"]).sum()
    short_notional = -live.loc[live["side"] == -1, "target_qty"].mul(live.loc[live["side"] == -1, "est_open"]).sum()
    if max(long_notional, short_notional) and abs(long_notional - short_notional) > 0.05 * max(long_notional, short_notional):
        v.append(Violation("dollar_neutrality", "warn", f"long ${long_notional:,.0f} vs short ${short_notional:,.0f}"))
    # A trailing-loss breaker is deliberately NOT an automatic block: the research (note §5.2,
    # §5.4) shows that cutting exposure after losses — i.e. after volatility — removes the
    # premium. Multi-day drawdowns page a human (who can engage the kill switch) instead.
    if realised_loss_pct is not None and realised_loss_pct <= -s.review_drawdown_pct:
        v.append(Violation("drawdown_review", "warn",
                           f"trailing 5-session net {realised_loss_pct:.2%} of gross — human review; engage KILL to halt"))
    return v


def blocked(violations: list[Violation]) -> bool:
    return any(x.level == "block" for x in violations)


def reconcile(book: pd.DataFrame, broker: pd.DataFrame) -> list[Violation]:
    """Compare the store's positions with the broker's. Both: index=symbol, column qty."""
    b = book["qty"].astype(int) if len(book) else pd.Series(dtype=int)
    k = broker["qty"].astype(int) if len(broker) else pd.Series(dtype=int)
    allsym = b.index.union(k.index)
    diff = b.reindex(allsym).fillna(0).astype(int) - k.reindex(allsym).fillna(0).astype(int)
    bad = diff[diff != 0]
    if bad.empty:
        return []
    return [Violation("reconciliation", "block", f"{len(bad)} positions differ book-vs-broker: "
                      + ", ".join(f"{s}:{int(d):+d}" for s, d in bad.head(10).items()))]


def flat_check(positions: pd.DataFrame) -> list[Violation]:
    if len(positions) and (positions["qty"] != 0).any():
        n = int((positions["qty"] != 0).sum())
        return [Violation("overnight_position", "block", f"{n} positions still open after the close — book must be flat")]
    return []


def intraday_loss_check(mark_pnl: float, gross_notional: float, s: Settings = SETTINGS) -> list[Violation]:
    if gross_notional <= 0:
        return []
    pct = mark_pnl / gross_notional
    if pct <= -s.daily_loss_limit_pct:
        return [Violation("daily_loss_limit", "block", f"marked P&L {pct:.2%} of gross breaches {-s.daily_loss_limit_pct:.1%}: flatten")]
    if pct <= -0.5 * s.daily_loss_limit_pct:
        return [Violation("daily_loss_warning", "warn", f"marked P&L {pct:.2%} of gross")]
    return []
