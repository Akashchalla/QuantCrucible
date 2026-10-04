"""Daily state check: what the pre-registered rules say for the next session.

    python today.py            # uses cached FRED data in data/processed/
    python today.py --refresh  # re-download VIX / VIX3M from FRED first (no key needed)

Prints the latest VIX close (the only input the rules need), the Module B gate,
the in-sample expected gross premium at that VIX level against the cost toll,
and the Module A sizing reminder. Nothing here is a forecast beyond the tables
already in the note; it is the operational face of the study.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from gqh import config, gapfade  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()
    if args.refresh:
        subprocess.run([sys.executable, str(ROOT / "data" / "download.py"), "--force"], check=True)

    vix = pd.read_csv(ROOT / "data/processed/vix_daily.csv", index_col="date", parse_dates=True)["vix"].dropna()
    vix3m = pd.read_csv(ROOT / "data/processed/vix3m_daily.csv", index_col="date", parse_dates=True)["vix3m"].dropna()
    q = pd.read_csv(ROOT / "results/tables/gapfade_vix_quintiles_is.csv")
    last_date, v = vix.index[-1], float(vix.iloc[-1])
    ts = v / float(vix3m.reindex([last_date]).ffill().iloc[-1]) if len(vix3m) else float("nan")

    row = q[(q["vix_lo"] <= v) & (v <= q["vix_hi"])]
    row = row.iloc[0] if len(row) else q.iloc[-1 if v > q["vix_hi"].max() else 0]
    toll = gapfade.DOLLARS_TRADED_PER_DAY * gapfade.C_BASE_BPS * v / config.VIX_NORM
    gate_on = v >= gapfade.VIX_THRESHOLD

    print(f"Last VIX close           : {v:.2f} on {last_date.date()}  (position for the NEXT session uses this value)")
    print(f"VIX / VIX3M              : {ts:.3f}  ({'backwardation: acute stress' if ts > 1 else 'contango'}; reported, not a rule — see Module C)")
    print(f"In-sample VIX quintile   : Q{int(row['vix_quintile'])} ({row['vix_lo']:.1f}–{row['vix_hi']:.1f})")
    print()
    print("Module B — opening-auction gap fade, S&P 500 names, $1 per side, open→close")
    print(f"  gate (VIX_lag >= {gapfade.VIX_THRESHOLD:g})    : {'ON  — trade the quintile spread at the open, flat at the close' if gate_on else 'OFF — stay flat'}")
    print(f"  expected gross premium : {row['mean_bps']:.1f} bps/day in this VIX quintile (in-sample mean, ± {1.96*row['se_bps']:.1f} 95% CI)")
    print(f"  cost toll at this VIX  : {toll:.1f} bps/day at {gapfade.C_BASE_BPS:g} bps per $ traded  ({toll/2:.1f} at 2.5 bps)")
    print(f"  net expectation        : {row['mean_bps']-toll:+.1f} bps/day at 5 bps, {row['mean_bps']-toll/2:+.1f} at 2.5 bps")
    print()
    print("Module A — daily short-term reversal, large-cap leg")
    print("  sizing                 : constant notional (the pre-registered VIX-levered rule did not beat it; vol-targeting destroys it)")
    print(f"  state                  : {'top VIX quintile — the only state where the modern large-cap premium has been positive (≈14 bps/day since 2004)' if int(row['vix_quintile']) == 5 else 'not in the top VIX quintile — modern large-cap premium ≈ 0 here; hold the book, do not add'}")


if __name__ == "__main__":
    main()
