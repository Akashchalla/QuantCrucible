"""Repurchase 8-K cash-secured put study.

    python run_eightk.py --start 2023-01-01 --end 2025-12-31
    python run_eightk.py --start 2026-01-01 --end 2026-08-31

The second command is the out-of-sample window. It runs once: if
results/eightk_out_of_sample.json already exists, it refuses. A window that
crosses 2026-01-01 is refused so in-sample work cannot see out-of-sample prices.

Headline parameters and the 54-variant grid are fixed in HYPOTHESIS_8K.md.
The grid is computed only when --end is before 2026-01-01.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
import sys
sys.path.insert(0, str(ROOT / "src"))

from gqh.eightk_logic import (  # noqa: E402
    DELAYS, EXPIRY_KS, HAIRCUTS, HEADLINE, HORIZONS, N_VARIANTS, OTMS,
    control_ok, entry_session, equity_stats, kill_checks, mean_ci, monthly_expiry,
    put_symbol, shift_session, strike_from_prior, summarise_pairs,
    trade_horizons,
)
from gqh import eightk_pull  # noqa: E402
from gqh.eightk_pull import Massive, Tiger, build_universe, collect_filings, load_option, load_stock_panel  # noqa: E402

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

SEAL = pd.Timestamp("2026-01-01")
RESULTS = ROOT / "results"


def _series(panel: pd.DataFrame, ticker: str, col: str) -> pd.Series:
    sub = panel[panel["ticker"] == ticker].drop_duplicates("date").set_index("date").sort_index()
    return sub[col].astype(float)


def _opt_series(df: pd.DataFrame) -> pd.Series:
    if df is None or df.empty:
        return pd.Series(dtype=float)
    s = df.drop_duplicates("date").set_index("date").sort_index()["close"].astype(float)
    s.index = pd.to_datetime(s.index).normalize()
    return s


def build_specs(filings: pd.DataFrame, sessions, spot: dict[str, pd.Series], window_end: pd.Timestamp,
                grid: bool) -> list[dict]:
    """One spec per filing × variant. No prices yet, so this is safe to inspect."""
    variants = [HEADLINE] if not grid else [
        {"delay": d, "haircut": h, "otm": o, "expiry_k": k}
        for d in DELAYS for h in HAIRCUTS for o in OTMS for k in EXPIRY_KS
    ]
    specs = []
    for fil in filings.itertuples(index=False):
        spot_s = spot.get(fil.ticker)
        if spot_s is None or spot_s.empty:
            continue
        for var in variants:
            entry = entry_session(fil.file_date, fil.acceptance, sessions, var["delay"])
            if pd.isna(entry) or entry > window_end:
                continue
            prior = shift_session(entry, sessions, -1)
            if pd.isna(prior) or prior not in spot_s.index or not np.isfinite(spot_s.loc[prior]):
                continue
            strike = strike_from_prior(float(spot_s.loc[prior]), var["otm"])
            expiry = monthly_expiry(entry, var["expiry_k"])
            specs.append({
                "accession": fil.accession, "ticker": fil.ticker, "file_date": pd.Timestamp(fil.file_date),
                "acceptance": fil.acceptance, "entry": entry, "prior": prior, "strike": strike,
                "expiry": expiry, "osi": put_symbol(fil.ticker, expiry, strike), **var,
            })
    return specs


def attach_controls(specs: list[dict], sessions) -> list[dict]:
    """Headline-only control link: same issuer, 21 sessions earlier, no nearby filing."""
    by_issuer: dict[str, list] = {}
    for s in specs:
        if s["delay"] == HEADLINE["delay"] and s["haircut"] == HEADLINE["haircut"] and s["otm"] == HEADLINE["otm"] and s["expiry_k"] == HEADLINE["expiry_k"]:
            by_issuer.setdefault(s["ticker"], []).append(s["entry"])
    for s in specs:
        ctrl = shift_session(s["entry"], sessions, -21)
        issuer_entries = by_issuer.get(s["ticker"], [])
        s["control_entry"] = ctrl if control_ok(ctrl, issuer_entries, sessions) else pd.NaT
    return specs


_EVENT_KEYS = ("accession", "ticker", "entry", "strike", "expiry", "osi", "delay", "haircut", "otm", "expiry_k")


def evaluate(specs: list[dict], spot: dict[str, pd.Series], opts: dict[str, pd.Series], sessions) -> pd.DataFrame:
    rows = []
    for s in specs:
        opt = opts.get(s["osi"], pd.Series(dtype=float))
        sp = spot.get(s["ticker"])
        if sp is None:
            continue
        ev = trade_horizons(opt, sp, s["entry"], s["expiry"], s["strike"], s["haircut"], sessions)
        row = {k: s[k] for k in _EVENT_KEYS}
        row["role"] = "event"
        row["control_entry"] = s.get("control_entry")
        row.update({f"bps_{h}": ev[h] for h in ev})
        if len(opt) and s["entry"] in opt.index:
            px = opt.loc[s["entry"]]
            row["entry_px"] = float(px.iloc[-1] if isinstance(px, pd.Series) else px)
        rows.append(row)
    cols = list(_EVENT_KEYS) + ["role", "control_entry", "entry_px"] + [f"bps_{h}" for h in list(map(str, HORIZONS)) + ["expiry"]]
    return pd.DataFrame(rows, columns=cols) if not rows else pd.DataFrame(rows)


def control_specs(event_specs: list[dict], spot, sessions) -> list[dict]:
    out = []
    for s in event_specs:
        if pd.isna(s.get("control_entry")):
            continue
        entry = pd.Timestamp(s["control_entry"])
        sp = spot.get(s["ticker"])
        prior = shift_session(entry, sessions, -1)
        if sp is None or pd.isna(prior) or prior not in sp.index:
            continue
        strike = strike_from_prior(float(sp.loc[prior]), s["otm"])
        expiry = monthly_expiry(entry, s["expiry_k"])
        out.append({
            **s, "entry": entry, "prior": prior, "strike": strike, "expiry": expiry,
            "osi": put_symbol(s["ticker"], expiry, strike), "control_entry": pd.NaT, "role": "control",
            "pair_accession": s["accession"],
        })
    return out


def paired_diffs(events: pd.DataFrame, controls: pd.DataFrame) -> dict[str, list]:
    keys = [str(h) for h in HORIZONS] + ["expiry"]
    diffs = {h: [] for h in keys}
    if events.empty or controls.empty:
        return diffs
    c = controls.set_index(["pair_accession", "delay", "haircut", "otm", "expiry_k"])
    for e in events.itertuples(index=False):
        key = (e.accession, e.delay, e.haircut, e.otm, e.expiry_k)
        if key not in c.index:
            continue
        ctrl = c.loc[key]
        if isinstance(ctrl, pd.DataFrame):
            ctrl = ctrl.iloc[0]
        for h in keys:
            ev = getattr(e, f"bps_{h}")
            cv = ctrl[f"bps_{h}"]
            if np.isfinite(ev) and np.isfinite(cv):
                diffs[h].append(float(ev) - float(cv))
    return diffs


def daily_book(events: pd.DataFrame, opts: dict[str, pd.Series], sessions, hold: int = 21) -> pd.Series:
    """Equal-collateral daily return of the headline short-put book, haircut on entry and exit."""
    idx = pd.DatetimeIndex(sessions)
    pnl = pd.Series(0.0, index=idx)
    coll = pd.Series(0.0, index=idx)
    sub = events[(events["delay"] == HEADLINE["delay"]) & (np.isclose(events["haircut"], HEADLINE["haircut"]))
                 & (np.isclose(events["otm"], HEADLINE["otm"])) & (events["expiry_k"] == HEADLINE["expiry_k"])]
    for e in sub.itertuples(index=False):
        opt = opts.get(e.osi)
        if opt is None or e.entry not in opt.index:
            continue
        exit_day = shift_session(e.entry, sessions, hold)
        if pd.isna(exit_day):
            continue
        window = opt.loc[(opt.index >= e.entry) & (opt.index <= exit_day)]
        window = window[window.index.isin(idx)]
        if window.empty:
            continue
        collateral = e.strike * 100.0
        days = list(window.index)
        for i, day in enumerate(days):
            px = float(window.loc[day])
            if i == 0:
                pnl.loc[day] += (px * (1 - e.haircut) - px) * 100.0
            else:
                prev = float(window.iloc[i - 1])
                step = (prev - px) * 100.0
                if day == days[-1]:
                    step -= px * e.haircut * 100.0
                pnl.loc[day] += step
            coll.loc[day] += collateral
    ret = pnl / coll.replace(0, np.nan)
    return ret.dropna()


def capacity_usd(events: pd.DataFrame, opts_vol: dict[str, pd.Series]) -> float:
    """Median event: 5% of that contract's entry-day volume, in dollars of collateral."""
    vals = []
    sub = events[np.isclose(events["haircut"], HEADLINE["haircut"]) & (events["delay"] == HEADLINE["delay"])
                 & np.isclose(events["otm"], HEADLINE["otm"]) & (events["expiry_k"] == HEADLINE["expiry_k"])]
    for e in sub.itertuples(index=False):
        vol = opts_vol.get(e.osi)
        if vol is None or e.entry not in vol.index:
            continue
        contracts = float(vol.loc[e.entry])
        if contracts > 0:
            vals.append(0.05 * contracts * e.strike * 100.0)
    return float(np.median(vals)) if vals else float("nan")


def window_problem(start: str, end: str, oos_path: Path | None = None) -> str | None:
    """None when the window is allowed. A crossing window or a second OOS run is refused."""
    start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)
    path = RESULTS / "eightk_out_of_sample.json" if oos_path is None else oos_path
    if start_ts < SEAL <= end_ts:
        return "crosses"
    if start_ts >= SEAL and path.exists():
        return "oos_exists"
    return None


def run(start: str, end: str) -> dict:
    start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)
    problem = window_problem(start, end)
    if problem == "crosses":
        raise SystemExit("Refusing a window that crosses 2026-01-01. Run in-sample and out-of-sample as two commands.")
    oos = start_ts >= SEAL
    out_path = RESULTS / ("eightk_out_of_sample.json" if oos else "eightk_in_sample.json")
    if problem == "oos_exists":
        raise SystemExit(f"{out_path} already exists. The out-of-sample window is run once and is not recomputed.")
    massive = Massive()
    tiger = None
    try:
        tiger = Tiger()
        print(f"tigerdata: {'connected' if tiger.conn else 'no DATABASE_URL, disk cache only'}", flush=True)
    except Exception as e:
        print(f"tigerdata unavailable ({str(e)[:120]}); continuing on disk", flush=True)
        tiger = None
    universe = build_universe(massive)
    names = set(universe["ticker"])
    print(f"universe {len(names)}", flush=True)
    filings = collect_filings(names, start, end, tiger)
    print(f"filings in universe {len(filings)}", flush=True)
    lookback = (start_ts - pd.Timedelta(days=180)).strftime("%Y-%m-%d")
    # Never request a stock or option bar past `end`.
    panel = load_stock_panel(massive, sorted(names), lookback, end)
    spot = {t: _series(panel, t, "close") for t in names}
    sessions = pd.DatetimeIndex(sorted(panel["date"].unique()))
    grid = not oos
    specs = build_specs(filings, sessions, spot, end_ts, grid=grid)
    specs = attach_controls(specs, sessions)
    controls = control_specs(specs, spot, sessions)
    print(f"specs {len(specs)} controls {len(controls)}", flush=True)
    needed = {}
    for s in specs + controls:
        needed.setdefault(s["osi"], [s["entry"], s["expiry"]])
        needed[s["osi"]][0] = min(needed[s["osi"]][0], s["entry"])
        needed[s["osi"]][1] = max(needed[s["osi"]][1], s["expiry"])
    opts, vols = {}, {}
    jobs = []
    for osi, (a0, b0) in needed.items():
        a = max(pd.Timestamp(a0) - pd.Timedelta(days=5), start_ts - pd.Timedelta(days=40))
        b = min(pd.Timestamp(b0), end_ts)
        if a <= end_ts:
            jobs.append((osi, a.strftime("%Y-%m-%d"), b.strftime("%Y-%m-%d")))
    print(f"option contracts to fetch {len(jobs)}", flush=True)

    def _fetch(job):
        osi, a, b = job
        last = None
        for attempt in range(4):
            try:
                return osi, load_option(massive, osi, a, b, tiger)
            except Exception as e:
                last = e
                time.sleep(2 ** attempt)
        raise last

    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = [pool.submit(_fetch, j) for j in jobs]
        for i, fut in enumerate(as_completed(futs), 1):
            osi, df = fut.result()
            opts[osi] = _opt_series(df)
            if df is not None and not df.empty:
                v = df.drop_duplicates("date").set_index("date").sort_index()["volume"].astype(float)
                v.index = pd.to_datetime(v.index).normalize()
                vols[osi] = v
            if i % 100 == 0 or i == len(jobs):
                print(f"  option contracts {i}/{len(jobs)}", flush=True)
    events = evaluate(specs, spot, opts, sessions)
    headline_mask = (
        (events["delay"] == HEADLINE["delay"]) & np.isclose(events["haircut"], HEADLINE["haircut"])
        & np.isclose(events["otm"], HEADLINE["otm"]) & (events["expiry_k"] == HEADLINE["expiry_k"])
    ) if len(events) else slice(0)
    headline_events = events[headline_mask] if len(events) else events
    ctrl_rows = []
    for s in controls:
        opt = opts.get(s["osi"], pd.Series(dtype=float))
        sp = spot.get(s["ticker"])
        if sp is None:
            continue
        ev = trade_horizons(opt, sp, s["entry"], s["expiry"], s["strike"], s["haircut"], sessions)
        row = {
            "pair_accession": s["pair_accession"], "delay": s["delay"], "haircut": s["haircut"],
            "otm": s["otm"], "expiry_k": s["expiry_k"], "osi": s["osi"], "entry": s["entry"],
            "expiry": s["expiry"], "strike": s["strike"], "ticker": s["ticker"],
        }
        row.update({f"bps_{h}": ev[h] for h in ev})
        ctrl_rows.append(row)
    ctrl_df = pd.DataFrame(ctrl_rows)
    # The pre-registered test is the headline pair only. The other 53 variants stay in the grid.
    diffs = paired_diffs(headline_events, ctrl_df)
    summary = summarise_pairs(diffs)
    grid_rows = []
    if grid and len(events):
        for (delay, haircut, otm, k), _ in events.groupby(["delay", "haircut", "otm", "expiry_k"], sort=False):
            sub_d = paired_diffs(events[(events["delay"] == delay) & np.isclose(events["haircut"], haircut)
                                        & np.isclose(events["otm"], otm) & (events["expiry_k"] == k)], ctrl_df)
            m = summarise_pairs(sub_d).get("21", {})
            grid_rows.append({"delay": delay, "haircut": float(haircut), "otm": float(otm), "expiry_k": int(k),
                              "diff_21": m.get("mean"), "lo": m.get("lo"), "hi": m.get("hi"), "n": m.get("n"), "t": m.get("t")})
    book = daily_book(events, opts, sessions) if len(events) else pd.Series(dtype=float)
    # 2x cost is the 10% haircut on the headline contract, reported even out of sample
    # by re-pricing the same marks (no new data).
    two_x = _reprice(headline_events, ctrl_df, opts, spot, sessions, haircut=0.10) if len(headline_events) else {}
    result = {
        "study": "8k repurchase cash-secured puts",
        "hypothesis": "HYPOTHESIS_8K.md",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "start": start, "end": end, "out_of_sample": oos,
        "n_variants_pre_registered": N_VARIANTS,
        "n_universe": int(len(names)),
        "n_filings": int(len(filings)),
        "n_events_headline": int(len(headline_events)),
        "n_events_with_entry_price": int(headline_events["bps_1"].notna().sum()) if len(headline_events) and "bps_1" in headline_events else 0,
        "horizons_event_minus_control_bps": summary,
        "grid_21_session": grid_rows,
        "cost_2x_haircut_10pct_21_session": two_x,
        "book_21_session": equity_stats(book),
        "capacity_usd_5pct_of_entry_volume": capacity_usd(events, vols) if len(events) else None,
        "kill": kill_checks(summary, grid_rows),
        "data": {
            "universe": "Massive grouped daily dollar volume, top 100 common stocks in 2022 (letter-only tickers)",
            "filings": "SEC full-text 8-K index (Massive filings filters ignore cik/ticker/date; see HYPOTHESIS_8K.md)",
            "acceptance": "SEC submissions JSON, including older filing pages when the accession is not in the latest thousand",
            "option_bars": "Massive daily aggregates; Databento OPRA ohlcv-1d (OCC-padded raw symbol) only when Massive has no bar",
            "option_bar_sources": dict(eightk_pull.option_sources),
            "databento_calls": int(eightk_pull.databento_calls),
            "databento_spent_usd": float(eightk_pull.databento_spent),
            "databento_skipped_budget": int(eightk_pull.databento_skipped_budget),
            "databento_study_budget_usd": float(eightk_pull.DATABENTO_STUDY_BUDGET),
            "store": "TigerData eightk_filings / eightk_option_bars when DATABASE_URL is set",
        },
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(_clean(result), indent=2, allow_nan=False))
    _write_table(summary, RESULTS / ("eightk_horizons_oos.csv" if oos else "eightk_horizons_is.csv"))
    if grid_rows:
        pd.DataFrame(grid_rows).to_csv(RESULTS / "eightk_variant_grid.csv", index=False)
    if len(book):
        _plot(book, RESULTS / "figures" / ("eightk_equity_oos.png" if oos else "eightk_equity_is.png"))
    _brief(result, oos)
    if tiger:
        tiger.close()
    print(json.dumps({k: result[k] for k in ("n_filings", "n_events_headline", "kill")}, default=_json, indent=2))
    return result


def _reprice(events, controls, opts, spot, sessions, haircut: float) -> dict:
    """Same contracts already in memory, wider haircut, event minus control."""
    diffs = []
    if events is None or controls is None or events.empty or controls.empty:
        return {"paired_mean_bps_21": mean_ci([]), "haircut": haircut, "n": 0}
    c = controls.set_index(["pair_accession", "delay", "haircut", "otm", "expiry_k"])
    for e in events.itertuples(index=False):
        key = (e.accession, e.delay, e.haircut, e.otm, e.expiry_k)
        if key not in c.index:
            continue
        ctrl = c.loc[key]
        if isinstance(ctrl, pd.DataFrame):
            ctrl = ctrl.iloc[0]
        sp = spot.get(e.ticker)
        if sp is None:
            continue
        ev = trade_horizons(opts.get(e.osi, pd.Series(dtype=float)), sp, e.entry, e.expiry, e.strike, haircut, sessions).get("21", np.nan)
        cv = trade_horizons(
            opts.get(ctrl["osi"], pd.Series(dtype=float)), sp, ctrl["entry"], ctrl["expiry"],
            float(ctrl["strike"]), haircut, sessions).get("21", np.nan)
        if np.isfinite(ev) and np.isfinite(cv):
            diffs.append(float(ev) - float(cv))
    return {"paired_mean_bps_21": mean_ci(diffs), "haircut": haircut}


def _plot(book: pd.Series, path: Path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    path.parent.mkdir(parents=True, exist_ok=True)
    wealth = (1 + book.fillna(0)).cumprod()
    fig, ax = plt.subplots(figsize=(7.2, 2.4))
    ax.plot(wealth.index, wealth.values, color="#1f4b99", lw=1.2)
    ax.set_title("Cash-secured puts after repurchase 8-Ks, 21-session hold, net of 5% premium haircut")
    ax.set_ylabel("growth of $1")
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def _write_table(summary: dict, path: Path):
    rows = []
    for h, s in summary.items():
        rows.append({"horizon": h, **s})
    pd.DataFrame(rows).to_csv(path, index=False)


def _brief(result: dict, oos: bool):
    """Gemini writes a short note from the numbers. ElevenLabs reads it if a key is set.
    Neither one changes a parameter."""
    key = os.environ.get("GEMINI_API_KEY")
    h21 = result["horizons_event_minus_control_bps"].get("21", {})
    text_in = (
        f"Study window {result['start']} to {result['end']}. "
        f"Filings in the top-100 universe: {result['n_filings']}. "
        f"Headline events: {result['n_events_headline']}. "
        f"21-session event-minus-control mean {h21.get('mean')} bps, "
        f"95% interval {h21.get('lo')} to {h21.get('hi')}, n={h21.get('n')}. "
        f"Kill flags: {json.dumps(result['kill'], default=_json)}. "
        "Write at most 120 words. No advice. Only these numbers."
    )
    spoken = text_in
    if key:
        model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
        try:
            r = __import__("requests").post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                params={"key": key}, timeout=60,
                json={"contents": [{"parts": [{"text": text_in}]}], "generationConfig": {"temperature": 0.2}})
            if r.status_code < 400:
                parts = r.json()["candidates"][0]["content"]["parts"]
                spoken = "".join(p.get("text", "") for p in parts).strip() or spoken
        except Exception as e:
            spoken = text_in + f"\n(gemini unavailable: {str(e)[:80]})"
    path = RESULTS / ("eightk_briefing_oos.txt" if oos else "eightk_briefing.txt")
    path.write_text(spoken)
    el = os.environ.get("ELEVENLABS_API_KEY")
    if not el:
        print("elevenlabs: ELEVENLABS_API_KEY empty, wrote the script only", flush=True)
        return
    try:
        voice = os.environ.get("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")
        rr = __import__("requests").post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice}",
            headers={"xi-api-key": el, "accept": "audio/mpeg"},
            json={"text": spoken[:2500], "model_id": "eleven_multilingual_v2"}, timeout=60)
        if rr.status_code < 400:
            audio = RESULTS / ("eightk_briefing_oos.mp3" if oos else "eightk_briefing.mp3")
            audio.write_bytes(rr.content)
            print(f"elevenlabs: wrote {audio}", flush=True)
        else:
            print(f"elevenlabs: {rr.status_code} {rr.text[:120]}", flush=True)
    except Exception as e:
        print(f"elevenlabs: {str(e)[:120]}", flush=True)


def _clean(o):
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, pd.Timestamp):
        return o.isoformat()
    return o


def _json(o):
    if isinstance(o, (np.floating,)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, float) and not np.isfinite(o):
        return None
    return str(o)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--start", required=True, help="window start YYYY-MM-DD")
    p.add_argument("--end", required=True, help="window end YYYY-MM-DD")
    args = p.parse_args()
    run(args.start, args.end)


if __name__ == "__main__":
    main()
