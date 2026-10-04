"""Reproduce every number and figure in the quant note.

    python run_all.py              # download data if needed, run the in-sample study
    python run_all.py --oos        # ALSO evaluate the held-out period (run once, at the end)

Outputs go to results/ (in_sample.json, out_of_sample.json, tables/, figures/)
and a human-readable results/REPORT.md.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from gqh import config  # noqa: E402
from gqh.data import build_panel, split  # noqa: E402
from gqh.report import write_report  # noqa: E402
from gqh.study import run_in_sample, run_out_of_sample  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--oos", action="store_true", help="evaluate the out-of-sample period (do this once)")
    ap.add_argument("--skip-download", action="store_true", help="use data already in data/processed/")
    ap.add_argument("--out", default="results", help="output directory")
    ap.add_argument("--skip-module-b", action="store_true", help="run only Module A (French portfolios)")
    args = ap.parse_args()

    if not args.skip_download or not (ROOT / "data" / "processed" / "returns_daily.csv").exists():
        subprocess.run([sys.executable, str(ROOT / "data" / "download.py")], check=True)
    if not args.skip_module_b and (not args.skip_download or not (ROOT / "data" / "processed" / "stocks_close.csv.gz").exists()):
        subprocess.run([sys.executable, str(ROOT / "data" / "download_stocks.py")], check=True)

    panel = build_panel()
    panel_is, panel_oos = split(panel)
    out_dir = ROOT / args.out
    out_dir.mkdir(exist_ok=True)

    print(f"\nIn-sample : {panel_is.index[0].date()} -> {panel_is.index[-1].date()}  ({len(panel_is):,} days)")
    print(f"Held out  : {config.OOS_START.date()} -> {panel_oos.index[-1].date() if len(panel_oos) else '?'}  "
          f"({len(panel_oos):,} days){'' if args.oos else '  [LOCKED]'}")

    is_res = run_in_sample(panel_is, out_dir)
    oos_res = run_out_of_sample(panel, out_dir) if args.oos else None
    write_report(is_res, oos_res, out_dir)

    for u in ("st_rev", "big_rev"):
        s = is_res["strategies"][u]
        print(f"\n[{u}] in-sample, net of costs")
        print(f"  constant exposure : Sharpe {s['constant']['sharpe_net']:.2f}   ann ret {s['constant']['ann_return_net']*100:6.2f}%   maxDD {s['constant']['max_drawdown']*100:6.1f}%")
        print(f"  VIX-timed         : Sharpe {s['timed']['sharpe_net']:.2f}   ann ret {s['timed']['ann_return_net']*100:6.2f}%   maxDD {s['timed']['max_drawdown']*100:6.1f}%")
        r = is_res["prediction_1_regression"][u]
        print(f"  slope on VIX_(t-1): {r['slope_bps_per_vix_pt']:.3f} bps/pt, NW t = {r['t_slope_nw']:.2f}")
        print(f"  break-even cost   : timed {s['breakeven_c_base_bps_timed']:.1f} bps, constant {s['breakeven_c_base_bps_constant']:.1f} bps")
        ph = is_res["post_hoc"][u]
        print(f"  post-hoc ({ph['start']}+): constant {ph['constant']['sharpe_net']:.2f} | vol-target {ph['vol_target']['sharpe_net']:.2f} | mean-variance {ph['mean_variance']['sharpe_net']:.2f}")
    if oos_res:
        for u in ("st_rev", "big_rev"):
            s = oos_res["strategies"][u]
            print(f"\n[{u}] OUT-OF-SAMPLE {oos_res['start']} -> {oos_res['end']}, net of costs")
            print(f"  constant exposure : Sharpe {s['constant']['sharpe_net']:.2f}   ann ret {s['constant']['ann_return_net']*100:6.2f}%")
            print(f"  VIX-timed         : Sharpe {s['timed']['sharpe_net']:.2f}   ann ret {s['timed']['ann_return_net']*100:6.2f}%")
            ph = oos_res["post_hoc"].get(u)
            if ph:
                print(f"  post-hoc          : vol-target {ph['vol_target']['sharpe_net']:.2f} | mean-variance {ph['mean_variance']['sharpe_net']:.2f}   "
                      f"(ann ret {ph['mean_variance']['ann_return_net']*100:6.2f}%)")
    print(f"\nwrote {out_dir / 'REPORT.md'}")

    panel_b = run_module_b(out_dir, args.oos) if not args.skip_module_b else None
    run_module_c(panel, panel_b, out_dir, args.oos)


def run_module_b(out_dir: Path, oos: bool):
    from gqh import gapfade
    from gqh.report_b import write_report_b

    panel = gapfade.build_gap_panel()
    panel_is, panel_oos = gapfade.split(panel)
    print(f"\n==== Module B: opening-auction gap fade, S&P 500 names ====")
    print(f"In-sample : {panel_is.index[0].date()} -> {panel_is.index[-1].date()}  ({len(panel_is):,} days)")
    print(f"Held out  : {config.OOS_START.date()} -> {panel_oos.index[-1].date() if len(panel_oos) else '?'}  "
          f"({len(panel_oos):,} days){'' if oos else '  [LOCKED]'}")
    (out_dir / "tables").mkdir(parents=True, exist_ok=True)
    # derived daily portfolio series (not raw prices): lets anyone recompute Module B exactly
    (panel_is if not oos else panel).to_csv(out_dir / "tables" / "gapfade_panel_daily.csv", float_format="%.8f")
    is_res = gapfade.run_in_sample(panel_is, out_dir)
    oos_res = gapfade.run_out_of_sample(panel, out_dir, is_res) if oos else None
    write_report_b(is_res, oos_res, out_dir)

    def show(res: dict, tag: str) -> None:
        T, S = res["hypothesis_tests"], res["strategies"]
        print(f"\n[gap fade] {tag}")
        print(f"  gross Q1-Q5 spread : {T['B1_gross_spread']['mean_bps']:.1f} bps/day, NW t = {T['B1_gross_spread']['t_nw']:.1f}, gross Sharpe {T['B1_gross_spread']['ann_sharpe_gross']:.2f}")
        print(f"  slope on VIX_(t-1) : {T['B2_slope_on_vix']['slope_bps_per_vix_pt']:.2f} bps/pt, NW t = {T['B2_slope_on_vix']['t_slope_nw']:.2f}")
        q = T["B2_vix_quintiles"]
        print(f"  VIX quintile means : " + ", ".join(f"Q{r['vix_quintile']} {r['mean_bps']:.0f}" for r in q if r["n_days"] >= 10) + " bps")
        print(f"  legs (excess)      : long {T['B4_legs']['long_leg_excess_bps']['mean_bps']:.1f} bps, short {T['B4_legs']['short_leg_excess_bps']['mean_bps']:.1f} bps")
        print(f"  net @5bps always-on: Sharpe {S['always_on']['sharpe_net']:.2f}   VIX>=20 participation: Sharpe {S['participation']['sharpe_net']:.2f} "
              f"(on {S['participation']['share_days_on']*100:.0f}% of days), spanning t = {S['B3_participation_vs_always_on']['t_alpha_nw']:.2f}")
        print(f"  break-even c_base  : always-on {S['breakeven_c_base_bps_always_on']:.1f} bps, participation {S['breakeven_c_base_bps_participation']:.1f} bps")

    show(is_res, "in-sample")
    if oos_res:
        show(oos_res, f"OUT-OF-SAMPLE {oos_res['start']} -> {oos_res['end']}")
    print(f"\nwrote {out_dir / 'REPORT_B.md'}")
    return panel


def run_module_c(panel_a, panel_b, out_dir: Path, oos: bool) -> None:
    from gqh import pricing
    from gqh.report_c import write_report_c

    panels = pricing.build_panels(panel_a, panel_b)
    print("\n==== Module C: price of risk (VRP, term structure) vs quantity of risk (realised variance) ====")
    is_res = pricing.run_in_sample(panels, out_dir)
    oos_res = pricing.run_out_of_sample(panels, out_dir) if oos else None
    write_report_c(is_res, oos_res, out_dir)

    def show(res: dict, tag: str) -> None:
        print(f"\n[pricing] {tag}")
        for book in panels:
            c1 = res["c1"][book]["21"]
            R = res["rules"][book]
            print(f"  {pricing.BOOK_LABEL[book]:22s} C1: b_VRP t = {c1['t_vrp_nw']:5.2f}, b_RV t = {c1['t_rv_nw']:5.2f} | "
                  f"net Sharpe: constant {R['constant']['sharpe_net']:5.2f}, VIX rule {R['vix_rule']['sharpe_net']:5.2f}, "
                  f"VRP>median {R['vrp_median']['sharpe_net']:5.2f}, backwardation {R['backwardation']['sharpe_net']:5.2f} "
                  f"(constant 2008+ {R['constant_2008_on']['sharpe_net']:5.2f})")
            if "c2" in res and book in res["c2"]:
                c2 = res["c2"][book]
                print(f"  {'':22s} C2: high-VRP beats low-VRP within RV terciles {c2['rv_terciles_where_high_vrp_beats_low']}/3; "
                      f"high-RV beats low-RV within VRP terciles {c2['vrp_terciles_where_high_rv_beats_low']}/3")

    show(is_res, "in-sample")
    if oos_res:
        show(oos_res, f"OUT-OF-SAMPLE {config.OOS_START.date()} -> {config.OOS_END.date()}")
    print(f"\nwrote {out_dir / 'REPORT_C.md'}")


if __name__ == "__main__":
    main()
