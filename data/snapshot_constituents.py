"""Snapshot the current S&P 500 constituent list (Wikipedia) to a committed CSV.

Run once; the committed file is the universe definition used by Module B so
that the reproduction does not depend on Wikipedia edits after the snapshot.
"""
from __future__ import annotations

import io
import pathlib
import sys

import pandas as pd
import requests

URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
OUT = pathlib.Path(__file__).resolve().parent / "sp500_constituents.csv"


def main() -> None:
    html = requests.get(URL, headers={"User-Agent": "Mozilla/5.0 (research script)"}, timeout=60).text
    table = pd.read_html(io.StringIO(html))[0]
    df = pd.DataFrame(
        {
            "symbol": table["Symbol"].str.strip(),
            "yahoo_symbol": table["Symbol"].str.strip().str.replace(".", "-", regex=False),
            "security": table["Security"],
            "sector": table["GICS Sector"],
            "date_added": pd.to_datetime(table["Date added"], errors="coerce").dt.date,
        }
    ).sort_values("symbol")
    df["snapshot_date"] = pd.Timestamp.utcnow().date()
    df.to_csv(OUT, index=False)
    print(f"wrote {len(df)} constituents to {OUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
