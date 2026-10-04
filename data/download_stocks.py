"""Download daily adjusted Open/Close for the Module B universe (Yahoo Finance).

Universe: data/sp500_constituents.csv (committed snapshot). Prices are fetched
with `yfinance` (free, no API key), split- and dividend-adjusted, and cached as
two wide CSVs in data/processed/ (git-ignored):

    stocks_open.csv.gz   dates x tickers
    stocks_close.csv.gz  dates x tickers

Run from the repo root:

    python data/download_stocks.py            # skips if cache exists
    python data/download_stocks.py --force    # re-download
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"
CONSTITUENTS = ROOT / "data" / "sp500_constituents.csv"
OPEN_FILE = PROCESSED / "stocks_open.csv.gz"
CLOSE_FILE = PROCESSED / "stocks_close.csv.gz"

START = "2004-06-01"   # buffer before the 2005-01-03 sample start
END = "2026-09-02"     # exclusive; sample ends 2026-08-31
BATCH = 100


def download(force: bool = False) -> None:
    if OPEN_FILE.exists() and CLOSE_FILE.exists() and not force:
        print("  stock price cache present, skipping download")
        return
    import yfinance as yf  # imported lazily so Module A does not need it

    tickers = pd.read_csv(CONSTITUENTS)["yahoo_symbol"].dropna().unique().tolist()
    opens, closes = [], []
    for i in range(0, len(tickers), BATCH):
        chunk = tickers[i : i + BATCH]
        print(f"  yfinance batch {i // BATCH + 1}/{(len(tickers) - 1) // BATCH + 1} ({len(chunk)} tickers)")
        for attempt in range(4):
            try:
                raw = yf.download(
                    chunk, start=START, end=END, interval="1d", auto_adjust=True,
                    progress=False, threads=True, group_by="column",
                )
                break
            except Exception as exc:  # network hiccups; retry with backoff
                wait = 5 * 2**attempt
                print(f"    retry after error: {exc} (sleep {wait}s)")
                time.sleep(wait)
        else:
            raise RuntimeError("yfinance download failed repeatedly")
        opens.append(raw["Open"])
        closes.append(raw["Close"])
    open_df = pd.concat(opens, axis=1).sort_index()
    close_df = pd.concat(closes, axis=1).sort_index()
    open_df.index = pd.to_datetime(open_df.index).tz_localize(None)
    close_df.index = pd.to_datetime(close_df.index).tz_localize(None)
    open_df.index.name = close_df.index.name = "date"
    PROCESSED.mkdir(parents=True, exist_ok=True)
    open_df.to_csv(OPEN_FILE, float_format="%.6f")
    close_df.to_csv(CLOSE_FILE, float_format="%.6f")
    missing = [t for t in tickers if t not in close_df.columns or close_df[t].notna().sum() == 0]
    print(f"  wrote {close_df.shape[0]} days x {close_df.shape[1]} tickers; no data for {len(missing)}: {missing}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    download(force=args.force)


if __name__ == "__main__":
    sys.exit(main())
