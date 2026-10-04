"""Download and parse all public data used in the study.

Sources (both free, no API key):
  * Kenneth R. French Data Library  — daily factor and portfolio returns (CRSP based)
  * FRED (St. Louis Fed)             — CBOE VIX close, series VIXCLS

Raw downloads are cached in data/raw/ (git-ignored). Tidy CSVs are written to
data/processed/ (git-ignored). Run from the repo root:

    python data/download.py            # downloads only what is missing
    python data/download.py --force    # re-download everything
"""
from __future__ import annotations

import argparse
import io
import sys
import zipfile
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"

FRENCH_BASE = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"
FRENCH_FILES = {
    # key -> zip file name on the French site
    "st_rev": "F-F_ST_Reversal_Factor_daily_CSV.zip",
    "six_me_prior": "6_Portfolios_ME_Prior_1_0_Daily_CSV.zip",
    "ff5": "F-F_Research_Data_5_Factors_2x3_daily_CSV.zip",
    "mom": "F-F_Momentum_Factor_daily_CSV.zip",
}
FRED_VIX_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=VIXCLS"
FRED_VIX3M_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=VXVCLS"  # CBOE 3-month VIX, from 2007-12

HEADERS = {"User-Agent": "gqh-reversal-study/1.0 (academic hackathon; public data)"}


def _fetch(url: str, dest: Path, force: bool) -> bytes:
    if dest.exists() and not force:
        return dest.read_bytes()
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"  downloading {url}")
    resp = requests.get(url, headers=HEADERS, timeout=120)
    resp.raise_for_status()
    dest.write_bytes(resp.content)
    return resp.content


def parse_french_csv(text: str) -> pd.DataFrame:
    """Parse the FIRST data block of a Ken French CSV.

    French files start with prose, then a header row beginning with ',' and
    daily rows 'YYYYMMDD, v1, v2, ...'. Later blocks (equal-weighted returns,
    counts) and the copyright footer are ignored. Values are in percent.
    """
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.startswith(","):
            start = i
            break
    if start is None:
        raise ValueError("no header row found in French CSV")
    header = [h.strip() or "date" for h in lines[start].split(",")]
    rows = []
    for line in lines[start + 1:]:
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != len(header) or not parts[0].isdigit() or len(parts[0]) != 8:
            if rows:
                break  # end of the first block
            continue
        rows.append(parts)
    df = pd.DataFrame(rows, columns=header)
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
    df = df.set_index("date").astype(float)
    # French's missing-value sentinels
    df = df.mask(df <= -99.0)
    return df / 100.0  # percent -> decimal


def load_french(key: str, force: bool = False) -> pd.DataFrame:
    fname = FRENCH_FILES[key]
    raw = _fetch(FRENCH_BASE + fname, RAW / fname, force)
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        inner = [n for n in zf.namelist() if n.lower().endswith(".csv")][0]
        text = zf.read(inner).decode("latin-1")
    return parse_french_csv(text)


def load_vix(force: bool = False, url: str = FRED_VIX_URL, fname: str = "VIXCLS.csv") -> pd.Series:
    raw = _fetch(url, RAW / fname, force)
    df = pd.read_csv(io.BytesIO(raw))
    df.columns = ["date", "vix"]
    df["date"] = pd.to_datetime(df["date"])
    df["vix"] = pd.to_numeric(df["vix"], errors="coerce")  # FRED uses '.' for holidays
    return df.dropna().set_index("date")["vix"]


def build_processed(force: bool = False) -> pd.DataFrame:
    PROCESSED.mkdir(parents=True, exist_ok=True)
    print("Ken French Data Library")
    st_rev = load_french("st_rev", force)["ST_Rev"].rename("st_rev")
    six = load_french("six_me_prior", force)
    big_rev = (six["BIG LoPRIOR"] - six["BIG HiPRIOR"]).rename("big_rev")
    small_rev = (six["SMALL LoPRIOR"] - six["SMALL HiPRIOR"]).rename("small_rev")
    ff5 = load_french("ff5", force).rename(columns={"Mkt-RF": "mkt_rf"})
    ff5.columns = [c.lower() for c in ff5.columns]
    mom = load_french("mom", force)["Mom"].rename("mom")
    print("FRED")
    vix = load_vix(force)
    vix3m = load_vix(force, FRED_VIX3M_URL, "VXVCLS.csv").rename("vix3m")

    returns = pd.concat([st_rev, big_rev, small_rev, ff5, mom], axis=1)
    returns.index.name = "date"
    returns.to_csv(PROCESSED / "returns_daily.csv", float_format="%.6f")
    vix.to_frame().to_csv(PROCESSED / "vix_daily.csv", float_format="%.2f")
    vix3m.to_frame().to_csv(PROCESSED / "vix3m_daily.csv", float_format="%.2f")

    print(f"  returns: {returns.index.min().date()} -> {returns.index.max().date()}  ({len(returns):,} rows)")
    print(f"  vix:     {vix.index.min().date()} -> {vix.index.max().date()}  ({len(vix):,} rows)")
    return returns


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true", help="re-download even if cached")
    args = ap.parse_args()
    try:
        build_processed(force=args.force)
    except requests.RequestException as exc:
        sys.exit(f"download failed: {exc}\nCheck your network connection and re-run.")
