"""Massive + SEC + Databento pulls for the 8-K study, cached on disk and in TigerData.

Licensed bars stay in data/raw and data/processed (git-ignored) and in TigerData.
Nothing here is imported by the liquidity study.
"""
from __future__ import annotations

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import requests

from .eightk_logic import occ_raw_symbol, tickers_from_display

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "eightk"
PROC = ROOT / "data" / "processed" / "eightk"
MASSIVE = "https://api.massive.com"
SEC_UA = "gqh-research research@example.com"
DATABENTO_COST_CAP = 2.0
DATABENTO_STUDY_BUDGET = float(os.environ.get("DATABENTO_STUDY_BUDGET", "40"))
_LOCK = threading.Lock()
_DB_SEM = threading.Semaphore(2)
databento_spent = 0.0
databento_calls = 0
databento_skipped_budget = 0
option_sources = {"massive": 0, "databento": 0, "cache": 0, "empty": 0}


def _key() -> str:
    k = os.environ.get("MASSIVE_API_KEY")
    if not k:
        raise RuntimeError("MASSIVE_API_KEY is not set")
    return k


def _get(url: str, params: dict | None = None, headers: dict | None = None, tries: int = 5) -> requests.Response:
    params = dict(params or {})
    for i in range(tries):
        r = requests.get(url, params=params, headers=headers, timeout=60)
        if r.status_code == 429 and i < tries - 1:
            time.sleep(2 ** i)
            continue
        return r
    return r


class Massive:
    def __init__(self):
        self.key = _key()

    def _p(self, params: dict) -> dict:
        out = dict(params)
        out["apiKey"] = self.key
        return out

    def grouped(self, day: str) -> pd.DataFrame:
        r = _get(f"{MASSIVE}/v2/aggs/grouped/locale/us/market/stocks/{day}", self._p({"adjusted": "true"}))
        if r.status_code >= 400:
            raise RuntimeError(f"grouped {day}: {r.status_code}")
        rows = r.json().get("results") or []
        if not rows:
            return pd.DataFrame(columns=["ticker", "close", "volume", "dollar"])
        df = pd.DataFrame(rows)
        df = df.rename(columns={"T": "ticker", "c": "close", "v": "volume"})
        df["dollar"] = df["close"].astype(float) * df["volume"].astype(float)
        return df[["ticker", "close", "volume", "dollar"]]

    def stock_bars(self, ticker: str, start: str, end: str) -> pd.DataFrame:
        r = _get(f"{MASSIVE}/v2/aggs/ticker/{ticker}/range/1/day/{start}/{end}",
                 self._p({"adjusted": "true", "sort": "asc", "limit": 50000}))
        if r.status_code >= 400:
            raise RuntimeError(f"bars {ticker}: {r.status_code} {r.text[:120]}")
        rows = r.json().get("results") or []
        if not rows:
            return pd.DataFrame(columns=["date", "close", "volume"])
        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["t"], unit="ms").dt.normalize()
        return df.rename(columns={"c": "close", "v": "volume"})[["date", "close", "volume"]]

    def option_bars(self, osi: str, start: str, end: str) -> pd.DataFrame:
        r = _get(f"{MASSIVE}/v2/aggs/ticker/{osi}/range/1/day/{start}/{end}",
                 self._p({"adjusted": "true", "sort": "asc", "limit": 50000}))
        if r.status_code == 429:
            raise RuntimeError(f"rate limit {osi}")
        if r.status_code >= 400:
            return pd.DataFrame(columns=["date", "close", "volume"])
        rows = r.json().get("results") or []
        if not rows:
            return pd.DataFrame(columns=["date", "close", "volume"])
        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["t"], unit="ms").dt.normalize()
        return df.rename(columns={"c": "close", "v": "volume"})[["date", "close", "volume"]]

    def instrument_type(self, ticker: str) -> str | None:
        r = _get(f"{MASSIVE}/vX/reference/tickers/{ticker}", self._p({}))
        if r.status_code >= 400:
            return None
        return (r.json().get("results") or {}).get("type")


def databento_option_bars(osi: str, start: str, end: str) -> pd.DataFrame:
    """One contract, daily bars. OCC-padded raw symbol. Refuses a call above the per-query cap
    or once the study-wide budget is exhausted. Never pulls a parent `*.OPT` stream."""
    global databento_spent, databento_calls, databento_skipped_budget
    key = os.environ.get("DATABENTO_API_KEY")
    budget = float(os.environ.get("DATABENTO_STUDY_BUDGET", "40"))
    if not key:
        return pd.DataFrame(columns=["date", "close", "volume"])
    with _LOCK:
        if databento_spent >= budget:
            databento_skipped_budget += 1
            return pd.DataFrame(columns=["date", "close", "volume"])
    import databento as db
    symbol = occ_raw_symbol(osi)
    with _DB_SEM:
        client = db.Historical(key)
        cost = float(client.metadata.get_cost(
            dataset="OPRA.PILLAR", schema="ohlcv-1d", symbols=[symbol],
            stype_in="raw_symbol", start=start, end=end))
        with _LOCK:
            budget = float(os.environ.get("DATABENTO_STUDY_BUDGET", "40"))
            if cost > DATABENTO_COST_CAP or databento_spent + cost > budget:
                databento_skipped_budget += 1
                raise RuntimeError(
                    f"Databento query for {symbol} costs ${cost:.2f} "
                    f"(cap ${DATABENTO_COST_CAP:.0f}/call, ${budget:.0f} study)")
            databento_spent += cost
            databento_calls += 1
        df = client.timeseries.get_range(
            dataset="OPRA.PILLAR", schema="ohlcv-1d", symbols=[symbol],
            stype_in="raw_symbol", start=start, end=end).to_df()
    if df.empty:
        return pd.DataFrame(columns=["date", "close", "volume"])
    idx = pd.to_datetime(df.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    return pd.DataFrame({
        "date": idx.normalize(),
        "close": df["close"].astype(float).values,
        "volume": df["volume"].astype(float).values,
    })


def _sec_page(phrase: str, start: str, end: str, frm: int) -> dict:
    last = ""
    for attempt in range(6):
        r = _get("https://efts.sec.gov/LATEST/search-index", {
            "q": f'"{phrase}"', "forms": "8-K", "dateRange": "custom",
            "startdt": start, "enddt": end, "from": frm,
        }, headers={"User-Agent": SEC_UA, "Accept": "application/json"})
        if r.status_code in (429, 500, 502, 503) and attempt < 5:
            last = r.text[:160]
            time.sleep(min(60, 2 ** attempt + 1))
            continue
        if r.status_code >= 400:
            raise RuntimeError(f"SEC search {phrase}: {r.status_code} {r.text[:160]}")
        return r.json()
    raise RuntimeError(f"SEC search {phrase}: still failing after retries ({last})")


def _hits_to_rows(hits: list, phrase: str) -> list[dict]:
    rows = []
    for h in hits:
        src = h.get("_source", {})
        cands: list[str] = []
        for n in src.get("display_names") or []:
            for t in tickers_from_display(n):
                if t not in cands:
                    cands.append(t)
        rows.append({
            "accession": src.get("adsh"),
            "cik": (src.get("ciks") or [None])[0],
            "tickers": "|".join(cands),
            "file_date": src.get("file_date"),
            "form": src.get("form"),
            "items": ",".join(src.get("items") or []),
            "file_type": src.get("file_type"),
            "phrase": phrase,
        })
    return rows


def sec_search(phrase: str, start: str, end: str, pause: float = 0.15) -> list[dict]:
    """All 8-K full-text hits for one phrase. Splits a window the index caps at 10,000."""
    RAW.mkdir(parents=True, exist_ok=True)
    cache = RAW / "sec" / f"{phrase.replace(' ', '_')}_{start}_{end}.csv"
    if cache.exists() and cache.stat().st_size > 0:
        cached = pd.read_csv(cache, dtype=str)
        if cached.empty or "accession" not in cached.columns:
            return []
        return cached.to_dict("records")
    first = _sec_page(phrase, start, end, 0)
    total_obj = (first.get("hits") or {}).get("total") or {}
    total = int(total_obj.get("value") or 0)
    capped = total_obj.get("relation") == "gte" and total >= 10000
    if capped and start < end:
        mid = pd.Timestamp(start) + (pd.Timestamp(end) - pd.Timestamp(start)) / 2
        left_end = (mid - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        right_start = mid.strftime("%Y-%m-%d")
        if left_end >= start and right_start <= end and left_end != end:
            return sec_search(phrase, start, left_end, pause) + sec_search(phrase, right_start, end, pause)
    hits = (first.get("hits") or {}).get("hits") or []
    out = _hits_to_rows(hits, phrase)
    frm = len(hits)
    while hits and frm < total and frm <= 20000:
        time.sleep(pause)
        js = _sec_page(phrase, start, end, frm)
        hits = (js.get("hits") or {}).get("hits") or []
        out.extend(_hits_to_rows(hits, phrase))
        frm += len(hits)
    cache.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(out, columns=["accession", "cik", "tickers", "file_date", "form", "items", "file_type", "phrase"]).to_csv(cache, index=False)
    return out


def _acc_block(block: dict) -> dict[str, str]:
    acc = block.get("accessionNumber") or []
    acc_dt = block.get("acceptanceDateTime") or []
    out = {}
    for a, t in zip(acc, acc_dt):
        if not a:
            continue
        out[a] = t
        out[str(a).replace("-", "")] = t
    return out


def sec_acceptance(cik: str, needed: set[str] | None = None) -> dict[str, str]:
    """accession -> acceptanceDateTime, including older submission pages when `needed` is not in the latest thousand."""
    cik10 = str(cik).zfill(10)
    r = _get(f"https://data.sec.gov/submissions/CIK{cik10}.json", headers={"User-Agent": SEC_UA, "Accept": "application/json"})
    if r.status_code >= 400:
        return {}
    js = r.json()
    filings = js.get("filings") or {}
    out = _acc_block(filings.get("recent") or {})

    def missing() -> bool:
        if not needed:
            return False
        have = {k.replace("-", "") for k in out}
        return any(n.replace("-", "") not in have for n in needed)

    for f in filings.get("files") or []:
        if needed and not missing():
            break
        name = f.get("name")
        if not name:
            continue
        time.sleep(0.12)
        rr = _get(f"https://data.sec.gov/submissions/{name}", headers={"User-Agent": SEC_UA, "Accept": "application/json"})
        if rr.status_code >= 400:
            continue
        block = rr.json()
        if "accessionNumber" not in block:
            block = (block.get("filings") or {}).get("recent") or block
        out.update(_acc_block(block))
    return out


class Tiger:
    """Optional. The study still runs, and still caches to disk, if this is down."""

    def __init__(self):
        self.url = os.environ.get("DATABASE_URL") or None
        self.conn = None
        if self.url:
            import psycopg
            self.conn = psycopg.connect(self.url, autocommit=True, connect_timeout=20)
            self._schema()

    def _schema(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS eightk_filings (
                accession TEXT PRIMARY KEY, cik TEXT, ticker TEXT, file_date DATE,
                acceptance TEXT, items TEXT, phrase TEXT, inserted_at TIMESTAMPTZ DEFAULT now())
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS eightk_option_bars (
                osi TEXT NOT NULL, bar_date DATE NOT NULL, close DOUBLE PRECISION, volume DOUBLE PRECISION,
                source TEXT, PRIMARY KEY (osi, bar_date))
        """)
        try:
            self.conn.execute("SELECT create_hypertable('eightk_option_bars', 'bar_date', if_not_exists => TRUE, migrate_data => TRUE)")
        except Exception:
            pass

    def write_filings(self, rows: list[dict]):
        if not self.conn or not rows:
            return
        clean = []
        for row in rows:
            item = dict(row)
            for k, v in list(item.items()):
                if v is None or (isinstance(v, float) and pd.isna(v)) or (isinstance(v, str) and v == "nan"):
                    item[k] = None
            if item.get("file_date") is not None:
                item["file_date"] = pd.Timestamp(item["file_date"]).date()
            clean.append(item)
        with _LOCK:
            with self.conn.cursor() as cur:
                cur.executemany("""
                    INSERT INTO eightk_filings (accession, cik, ticker, file_date, acceptance, items, phrase)
                    VALUES (%(accession)s, %(cik)s, %(ticker)s, %(file_date)s, %(acceptance)s, %(items)s, %(phrase)s)
                    ON CONFLICT (accession) DO UPDATE SET acceptance = EXCLUDED.acceptance, ticker = EXCLUDED.ticker
                """, clean)

    def write_bars(self, osi: str, df: pd.DataFrame, source: str):
        if not self.conn or df is None or df.empty:
            return
        rows = [{"osi": osi, "bar_date": pd.Timestamp(r.date).date(), "close": float(r.close),
                 "volume": float(r.volume) if pd.notna(r.volume) else None, "source": source}
                for r in df.itertuples()]
        with _LOCK:
            with self.conn.cursor() as cur:
                cur.executemany("""
                    INSERT INTO eightk_option_bars (osi, bar_date, close, volume, source)
                    VALUES (%(osi)s, %(bar_date)s, %(close)s, %(volume)s, %(source)s)
                    ON CONFLICT (osi, bar_date) DO NOTHING
                """, rows)

    def close(self):
        if self.conn:
            self.conn.close()


def build_universe(massive: Massive, year: int = 2022, n: int = 100) -> pd.DataFrame:
    """Top `n` common stocks by consolidated dollar volume over `year`, from Massive grouped dailies."""
    PROC.mkdir(parents=True, exist_ok=True)
    cache = PROC / f"universe_{year}.csv"
    if cache.exists():
        return pd.read_csv(cache)
    sessions = massive.stock_bars("AAPL", f"{year}-01-01", f"{year}-12-31")["date"]
    RAW.mkdir(parents=True, exist_ok=True)
    dollars: dict[str, float] = {}

    def one(day: pd.Timestamp) -> pd.DataFrame:
        path = RAW / "grouped" / f"{day:%Y-%m-%d}.csv"
        if path.exists():
            return pd.read_csv(path)
        last = None
        for attempt in range(4):
            try:
                df = massive.grouped(f"{day:%Y-%m-%d}")
                last = None
                break
            except Exception as e:
                last = e
                time.sleep(2 ** attempt)
        if last is not None:
            raise last
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(path, index=False)
        return df

    days = list(sessions)
    with ThreadPoolExecutor(max_workers=6) as pool:
        futs = [pool.submit(one, d) for d in days]
        for i, fut in enumerate(as_completed(futs), 1):
            df = fut.result()
            if df.empty:
                continue
            for ticker, dollar in zip(df["ticker"], df["dollar"]):
                if isinstance(ticker, str) and ticker.isalpha() and len(ticker) <= 5:
                    dollars[ticker] = dollars.get(ticker, 0.0) + float(dollar)
            if i % 40 == 0:
                print(f"  universe days {i}/{len(days)}", flush=True)
    ranked = sorted(dollars, key=dollars.get, reverse=True)[: n * 4]
    types: dict[str, str | None] = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = {pool.submit(massive.instrument_type, t): t for t in ranked}
        for fut in as_completed(futs):
            t = futs[fut]
            try:
                types[t] = fut.result()
            except Exception:
                types[t] = None
    kept = []
    for t in ranked:
        if len(kept) >= n:
            break
        if types.get(t) == "CS":
            kept.append({"ticker": t, "dollar_volume": dollars[t], "type": "CS", "rank_year": year})
    out = pd.DataFrame(kept)
    out.to_csv(cache, index=False)
    return out


def collect_filings(universe: set[str], start: str, end: str, tiger: Tiger | None) -> pd.DataFrame:
    """Repurchase 8-Ks whose ticker is in the universe, with SEC acceptance times."""
    PROC.mkdir(parents=True, exist_ok=True)
    tag = f"{start}_{end}".replace("-", "")
    cache = PROC / f"filings_{tag}.csv"
    if cache.exists():
        return pd.read_csv(cache, parse_dates=["file_date"])
    frames = []
    # Month slices keep each query under the index cap of 10,000.
    months = pd.period_range(start, end, freq="M")
    for phrase in ("repurchase program", "repurchase authorization"):
        for per in months:
            a = max(pd.Timestamp(start), per.start_time).strftime("%Y-%m-%d")
            b = min(pd.Timestamp(end), per.end_time).strftime("%Y-%m-%d")
            if a > b:
                continue
            hits = sec_search(phrase, a, b)
            if hits:
                frames.append(pd.DataFrame(hits))
            print(f"  filings {phrase} {a[:7]}: {len(hits)}", flush=True)
    empty_cols = ["accession", "cik", "ticker", "file_date", "acceptance", "items", "phrase"]
    if not frames:
        return pd.DataFrame(columns=empty_cols)
    raw = pd.concat(frames, ignore_index=True)
    raw["form"] = raw["form"].astype(str)
    raw = raw[raw["form"].str.startswith("8-K") & raw["accession"].notna()]

    def pick(field: str) -> str | None:
        for t in str(field or "").split("|"):
            if t and t in universe:
                return t
        return None

    raw["ticker"] = [pick(x) for x in raw.get("tickers", pd.Series(dtype=str)).fillna("")]
    raw = raw[raw["ticker"].notna()].drop_duplicates("accession")
    raw["file_date"] = pd.to_datetime(raw["file_date"])
    raw = raw[(raw["file_date"] >= pd.Timestamp(start)) & (raw["file_date"] <= pd.Timestamp(end))]
    if raw.empty:
        out = pd.DataFrame(columns=empty_cols)
        out.to_csv(cache, index=False)
        return out
    acc_maps: dict[str, dict] = {}
    by_cik: dict[str, set[str]] = {}
    for cik, acc in zip(raw["cik"], raw["accession"]):
        if pd.notna(cik) and pd.notna(acc):
            by_cik.setdefault(str(cik), set()).add(str(acc))
    for cik, needed in sorted(by_cik.items()):
        acc_maps[cik] = sec_acceptance(cik, needed)
        time.sleep(0.12)

    def lookup(cik, acc) -> str | None:
        m = acc_maps.get(str(cik), {})
        if acc in m:
            return m[acc]
        return m.get(str(acc).replace("-", ""))

    raw["acceptance"] = [lookup(c, a) for c, a in zip(raw["cik"], raw["accession"])]
    keep = raw[empty_cols]
    keep.to_csv(cache, index=False)
    if tiger:
        tiger.write_filings(keep.to_dict("records"))
    return keep


def _covers(df: pd.DataFrame, start, end, slack_days: int = 4) -> bool:
    if df is None or df.empty or "date" not in df.columns:
        return False
    d0, d1 = pd.to_datetime(df["date"]).min(), pd.to_datetime(df["date"]).max()
    return d0 <= pd.Timestamp(start) + pd.Timedelta(days=slack_days) and d1 >= pd.Timestamp(end) - pd.Timedelta(days=slack_days)


def _range_marker(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".range")


def _marker_covers(path: Path, start, end) -> bool:
    mark = _range_marker(path)
    if not mark.exists():
        return False
    try:
        a, b = mark.read_text().strip().split(",")
    except ValueError:
        return False
    return pd.Timestamp(a) <= pd.Timestamp(start) and pd.Timestamp(b) >= pd.Timestamp(end)


def _write_marker(path: Path, start, end, prev: pd.DataFrame | None):
    a, b = pd.Timestamp(start), pd.Timestamp(end)
    mark = _range_marker(path)
    if mark.exists():
        try:
            oa, ob = mark.read_text().strip().split(",")
            a, b = min(a, pd.Timestamp(oa)), max(b, pd.Timestamp(ob))
        except ValueError:
            pass
    if prev is not None and not prev.empty:
        a = min(a, pd.to_datetime(prev["date"]).min())
        b = max(b, pd.to_datetime(prev["date"]).max())
    mark.parent.mkdir(parents=True, exist_ok=True)
    mark.write_text(f"{a:%Y-%m-%d},{b:%Y-%m-%d}")


def load_stock_panel(massive: Massive, tickers: list[str], start: str, end: str) -> pd.DataFrame:
    PROC.mkdir(parents=True, exist_ok=True)
    (PROC / "stocks").mkdir(parents=True, exist_ok=True)

    def one(t: str) -> pd.DataFrame:
        path = PROC / "stocks" / f"{t}.csv"
        have = pd.read_csv(path, parse_dates=["date"]) if path.exists() else pd.DataFrame(columns=["date", "close", "volume"])
        if not _covers(have, start, end):
            fresh = None
            for attempt in range(4):
                try:
                    fresh = massive.stock_bars(t, start, end)
                    break
                except Exception:
                    if attempt == 3:
                        raise
                    time.sleep(2 ** attempt)
            have = pd.concat([have, fresh], ignore_index=True)
            if not have.empty:
                have = have.drop_duplicates("date").sort_values("date")
                have.to_csv(path, index=False)
        if have.empty:
            return pd.DataFrame(columns=["date", "close", "volume", "ticker"])
        df = have[(have["date"] >= pd.Timestamp(start)) & (have["date"] <= pd.Timestamp(end))].copy()
        df["ticker"] = t
        return df

    frames = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = [pool.submit(one, t) for t in tickers]
        for i, fut in enumerate(as_completed(futs), 1):
            frames.append(fut.result())
            if i % 25 == 0:
                print(f"  stock bars {i}/{len(tickers)}", flush=True)
    if not frames:
        return pd.DataFrame(columns=["date", "ticker", "close", "volume"])
    return pd.concat(frames, ignore_index=True)


def load_option(massive: Massive, osi: str, start: str, end: str, tiger: Tiger | None) -> pd.DataFrame:
    """Massive daily bars first. Databento OPRA ohlcv-1d only when Massive has none."""
    global option_sources
    path = PROC / "options" / f"{osi.replace(':', '_')}.csv"
    if _marker_covers(path, start, end):
        have = pd.read_csv(path, parse_dates=["date"]) if path.exists() else pd.DataFrame(columns=["date", "close", "volume"])
        with _LOCK:
            option_sources["cache"] += 1
        if have.empty:
            return have
        return have[(have["date"] >= pd.Timestamp(start)) & (have["date"] <= pd.Timestamp(end))]
    df = massive.option_bars(osi, start, end)
    source = "massive"
    if df.empty:
        try:
            df = databento_option_bars(osi, start, end)
            source = "databento" if not df.empty else "empty"
        except Exception as e:
            print(f"  databento skip {osi}: {str(e)[:160]}", flush=True)
            df = pd.DataFrame(columns=["date", "close", "volume"])
            source = "empty"
    with _LOCK:
        option_sources[source if source in option_sources else "empty"] += 1
        path.parent.mkdir(parents=True, exist_ok=True)
        prev = pd.read_csv(path, parse_dates=["date"]) if path.exists() else pd.DataFrame()
        both = pd.concat([prev, df], ignore_index=True)
        if not both.empty:
            both = both.drop_duplicates("date").sort_values("date")
            both.to_csv(path, index=False)
        elif not path.exists():
            pd.DataFrame(columns=["date", "close", "volume"]).to_csv(path, index=False)
        _write_marker(path, start, end, prev if not prev.empty else None)
    if tiger is not None and df is not None and not df.empty and source in ("massive", "databento"):
        try:
            tiger.write_bars(osi, df, source)
        except Exception as e:
            print(f"  tiger skip {osi}: {str(e)[:140]}", flush=True)
    if df is None or df.empty:
        return pd.DataFrame(columns=["date", "close", "volume"])
    return df[(df["date"] >= pd.Timestamp(start)) & (df["date"] <= pd.Timestamp(end))] if "date" in df.columns else df
