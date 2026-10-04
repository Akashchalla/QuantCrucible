"""Market intelligence layer: live-ish market data, Google-grounded company research,
TradingView symbol helpers, historical analogs, and Gemini chart-image understanding.

Numerical price analytics use Massive as the preferred live snapshot source for supported
U.S. equities, with Yahoo/yfinance as the portable historical and fallback source. Google
Search is used for current public explanations/news, not as the authoritative price feed.
"""
from __future__ import annotations

import base64
import json
import math
import re
from functools import lru_cache
from typing import Any

import numpy as np
import pandas as pd
import requests

from .settings import SETTINGS

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

NAME_MAP = {
    "google": "GOOGL", "alphabet": "GOOGL", "googl": "GOOGL", "goog": "GOOG",
    "nvidia": "NVDA", "nvda": "NVDA", "apple": "AAPL", "aapl": "AAPL",
    "microsoft": "MSFT", "msft": "MSFT", "meta": "META", "facebook": "META",
    "amazon": "AMZN", "amzn": "AMZN", "tesla": "TSLA", "tsla": "TSLA",
    "amd": "AMD", "palantir": "PLTR", "pltr": "PLTR", "netflix": "NFLX",
    "gold": "XAUUSD=X", "xauusd": "XAUUSD=X", "xau/usd": "XAUUSD=X",
    "bitcoin": "BTC-USD", "btc": "BTC-USD", "spy": "SPY", "qqq": "QQQ",
}

TV_MAP = {
    "GOOGL": "NASDAQ:GOOGL", "GOOG": "NASDAQ:GOOG", "NVDA": "NASDAQ:NVDA", "AAPL": "NASDAQ:AAPL",
    "MSFT": "NASDAQ:MSFT", "META": "NASDAQ:META", "AMZN": "NASDAQ:AMZN", "TSLA": "NASDAQ:TSLA",
    "AMD": "NASDAQ:AMD", "PLTR": "NASDAQ:PLTR", "NFLX": "NASDAQ:NFLX", "SPY": "AMEX:SPY",
    "QQQ": "NASDAQ:QQQ", "XAUUSD=X": "OANDA:XAUUSD", "BTC-USD": "COINBASE:BTCUSD",
}


def resolve_symbol(text: str | None, default: str = "GOOGL") -> str:
    if not text:
        return default
    raw = text.strip()
    low = raw.lower()
    if low in NAME_MAP:
        return NAME_MAP[low]
    # If a sentence was passed, resolve named entities/tickers conservatively.
    for name, ticker in sorted(NAME_MAP.items(), key=lambda kv: -len(kv[0])):
        if re.search(rf"(?<![a-z0-9]){re.escape(name)}(?![a-z0-9])", low):
            return ticker
    # Explicit exchange:ticker -> strip exchange for yfinance.
    if ":" in raw and re.fullmatch(r"[A-Za-z0-9._=-]+:[A-Za-z0-9._=-]+", raw):
        return raw.split(":", 1)[1].upper()
    if re.fullmatch(r"[A-Za-z0-9.^=_-]{1,15}", raw):
        return raw.upper()
    return default


def tradingview_symbol(symbol: str) -> str:
    symbol = resolve_symbol(symbol, symbol)
    return TV_MAP.get(symbol, f"NASDAQ:{symbol}")


def _yf():
    try:
        import yfinance as yf
        return yf
    except ImportError as e:
        raise RuntimeError("yfinance is required for market analytics; run pip install -r requirements-live.txt") from e


def history(symbol: str, period: str = "2y", interval: str = "1d") -> pd.DataFrame:
    ticker = resolve_symbol(symbol)
    yf = _yf()
    df = yf.download(ticker, period=period, interval=interval, auto_adjust=True, progress=False, threads=False)
    if df is None or df.empty:
        raise RuntimeError(f"No market history returned for {ticker}.")
    if isinstance(df.columns, pd.MultiIndex):
        # yfinance may return (Price, Ticker) or the reverse for a single ticker.
        if ticker in df.columns.get_level_values(-1):
            df = df.xs(ticker, axis=1, level=-1, drop_level=True)
        elif ticker in df.columns.get_level_values(0):
            df = df.xs(ticker, axis=1, level=0, drop_level=True)
    df.columns = [str(c).lower().replace(" ", "_") for c in df.columns]
    if "close" not in df:
        raise RuntimeError(f"Market feed did not return a close series for {ticker}.")
    df = df.dropna(subset=["close"]).copy()
    df.index = pd.to_datetime(df.index).tz_localize(None) if getattr(df.index, "tz", None) is not None else pd.to_datetime(df.index)
    return df


def _massive_live_snapshot(ticker: str) -> dict[str, Any] | None:
    """Best-effort Massive consolidated snapshot for ordinary U.S. equity tickers.

    Long historical calculations intentionally remain on the portable history feed. The live
    snapshot is used only when Massive returns authoritative consolidated fields; failures or
    plan-entitlement gaps fall back silently to the historical feed.
    """
    if not SETTINGS.massive_api_key or ticker in {"XAUUSD=X", "BTC-USD"} or ticker.startswith("^"):
        return None
    if not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,9}", ticker):
        return None
    try:
        from .feeds.massive import MassiveFeed
        frame = MassiveFeed().snapshots([ticker])
        if frame is None or frame.empty or ticker not in frame.index:
            return None
        row = frame.loc[ticker]
        last = row.get("last")
        prev = row.get("prev_close")
        if pd.isna(last) or last is None:
            return None
        updated = row.get("updated")
        return {
            "price": float(last),
            "prev_close": None if pd.isna(prev) else float(prev),
            "updated": None if pd.isna(updated) else str(updated),
        }
    except Exception:
        return None


def snapshot(symbol: str, period: str = "1y") -> dict[str, Any]:
    ticker = resolve_symbol(symbol)
    df = history(ticker, period=period)
    close = df["close"].astype(float)
    ret = close.pct_change()
    current = float(close.iloc[-1])
    one = float(close.iloc[-1] / close.iloc[-2] - 1) if len(close) >= 2 else np.nan
    source = "yfinance-history"
    as_of = str(df.index[-1].date())

    live = _massive_live_snapshot(ticker)
    if live:
        current = float(live["price"])
        prev = live.get("prev_close")
        if prev is not None and prev > 0:
            one = float(current / prev - 1.0)
        source = "massive-live+yfinance-history"
        if live.get("updated"):
            as_of = str(live["updated"])

    five = float(current / close.iloc[-6] - 1) if len(close) >= 6 else np.nan
    twenty = float(current / close.iloc[-21] - 1) if len(close) >= 21 else np.nan
    vol20 = float(ret.tail(20).std(ddof=1) * np.sqrt(252)) if len(ret.dropna()) >= 20 else np.nan
    recent_std = ret.tail(60).std(ddof=1)
    z = float(one / recent_std) if len(ret.dropna()) >= 60 and recent_std > 0 else np.nan
    peak = max(float(close.max()), current)
    dd_now = current / peak - 1.0
    vol_pct = np.nan
    if "volume" in df and len(df) >= 40 and pd.notna(df["volume"].iloc[-1]):
        histv = df["volume"].iloc[:-1].dropna().tail(252)
        if len(histv):
            vol_pct = float((histv <= float(df["volume"].iloc[-1])).mean())
    return {
        "symbol": ticker,
        "tradingview_symbol": tradingview_symbol(ticker),
        "as_of": as_of,
        "market_data_source": source,
        "price": current,
        "return_1d": one,
        "return_5d": five,
        "return_20d": twenty,
        "realized_vol_20d": vol20,
        "move_sigma_60d": z,
        "volume_percentile_1y": vol_pct,
        "drawdown_from_period_peak": float(dd_now),
        "history": df,
    }


def normalized_comparison(symbols: list[str], period: str = "6mo") -> pd.DataFrame:
    series = {}
    for s in symbols[:6]:
        t = resolve_symbol(s)
        h = history(t, period=period)
        x = h["close"].astype(float)
        series[t] = 100.0 * x / x.iloc[0]
    out = pd.concat(series, axis=1).dropna(how="all").ffill()
    return out


def _features(df: pd.DataFrame) -> pd.DataFrame:
    c = df["close"].astype(float)
    r = c.pct_change()
    out = pd.DataFrame(index=df.index)
    out["ret1"] = r
    out["ret5"] = c.pct_change(5)
    out["vol20"] = r.rolling(20).std(ddof=1) * np.sqrt(252)
    out["dist_ma20"] = c / c.rolling(20).mean() - 1
    if "high" in df and "low" in df:
        tr = pd.concat([(df["high"] - df["low"]).abs(), (df["high"] - c.shift()).abs(), (df["low"] - c.shift()).abs()], axis=1).max(axis=1)
        out["atr20"] = tr.rolling(20).mean() / c
    else:
        out["atr20"] = r.abs().rolling(20).mean()
    if "volume" in df:
        lv = np.log1p(df["volume"].astype(float))
        out["volume_z"] = (lv - lv.rolling(60).mean()) / lv.rolling(60).std(ddof=1)
    else:
        out["volume_z"] = 0.0
    return out.replace([np.inf, -np.inf], np.nan).dropna()


def historical_analogs(symbol: str, n: int = 8, period: str = "10y") -> dict[str, Any]:
    ticker = resolve_symbol(symbol)
    df = history(ticker, period=period)
    f = _features(df)
    if len(f) < 150:
        raise RuntimeError("Not enough history for analog search.")
    target_date = f.index[-1]
    target = f.iloc[-1]
    candidate = f.iloc[:-30].copy()  # don't pick the immediate recent neighborhood
    mu, sd = candidate.mean(), candidate.std(ddof=1).replace(0, 1)
    zcand = (candidate - mu) / sd
    ztarget = (target - mu) / sd
    dist = np.sqrt(((zcand - ztarget) ** 2).mean(axis=1))
    ranked = dist.sort_values()
    chosen = []
    for dt, d in ranked.items():
        if all(abs((dt - prev).days) >= 20 for prev, _ in chosen):
            chosen.append((dt, float(d)))
        if len(chosen) >= n:
            break
    close = df["close"].astype(float)
    rows = []
    denom = max([d for _, d in chosen] + [1e-9])
    for dt, d in chosen:
        if dt not in close.index:
            continue
        loc = close.index.get_loc(dt)
        row = {"date": dt.date(), "distance": d, "similarity": float(max(0.0, 1.0 - d / (denom * 1.15)))}
        for h in (1, 5, 20):
            row[f"fwd_{h}d"] = float(close.iloc[loc + h] / close.iloc[loc] - 1) if loc + h < len(close) else np.nan
        rows.append(row)
    return {"symbol": ticker, "target_date": str(target_date.date()), "features": target.to_dict(), "analogs": pd.DataFrame(rows)}


def _gemini_request(payload: dict, timeout: int = 90) -> dict:
    if not SETTINGS.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY missing from .env")
    model = SETTINGS.gemini_model
    if not re.fullmatch(r"[A-Za-z0-9._-]+", model):
        raise RuntimeError("invalid GEMINI_MODEL")
    r = requests.post(GEMINI_URL.format(model=model), headers={"x-goog-api-key": SETTINGS.gemini_api_key}, json=payload, timeout=timeout)
    if r.status_code >= 400:
        raise RuntimeError(f"Gemini HTTP {r.status_code}: {r.text[:300]}")
    return r.json()


def _text(js: dict) -> str:
    try:
        return "".join(p.get("text", "") for p in js["candidates"][0]["content"]["parts"]).strip()
    except Exception:
        return ""


def _grounding_sources(js: dict) -> list[dict[str, str]]:
    out, seen = [], set()
    try:
        gm = js["candidates"][0].get("groundingMetadata", {})
        for chunk in gm.get("groundingChunks", []) or []:
            web = chunk.get("web") or {}
            uri, title = web.get("uri"), web.get("title")
            if uri and uri not in seen:
                seen.add(uri)
                out.append({"title": title or uri, "url": uri})
    except Exception:
        pass
    return out


def research_company(symbol: str, question: str, include_snapshot: bool = True) -> dict[str, Any]:
    ticker = resolve_symbol(symbol)
    snap = None
    market_history = None
    if include_snapshot:
        try:
            s = snapshot(ticker)
            market_history = s.get("history")
            if isinstance(market_history, pd.DataFrame):
                market_history = market_history.tail(180).copy()
            snap = {k: v for k, v in s.items() if k != "history"}
        except Exception as e:  # price feed should not block web research
            snap = {"symbol": ticker, "market_data_error": str(e)[:160]}
    prompt = f"""You are the current-market research analyst inside Quant Crucible.
The user asks: {question}
Resolved market symbol: {ticker}
Market-data snapshot (authoritative for numbers when present): {json.dumps(snap, default=str)}

Use Google Search for CURRENT public information when the question is time-sensitive. Prefer primary sources
(company investor relations, SEC/regulators) and high-quality financial reporting. Organize the answer as
VERIFIED FACTS, POSSIBLE EXPLANATIONS, and UNKNOWNS when causality is being discussed. Never present a
plausible catalyst as proven causation. Do not give personalized investment advice or tell the user to buy/sell.
Use exact event/publication dates and times when they are actually available in the search evidence; explicitly
say when publication time is unavailable. Any price/return/volatility number must come from MARKET_SNAPSHOT
or the deterministic market-data tools, never from a remembered/search-snippet number. Keep it concise but useful.
"""
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "tools": [{"google_search": {}}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 2200},
    }
    js = _gemini_request(payload)
    answer = _text(js)
    if not answer:
        raise RuntimeError("Gemini returned no market-research text")
    return {"symbol": ticker, "answer": answer, "sources": _grounding_sources(js), "snapshot": snap,
            "market_history": market_history, "model": js.get("modelVersion", SETTINGS.gemini_model)}


def analyze_chart_image(image_bytes: bytes, mime_type: str, symbol: str, question: str) -> dict[str, Any]:
    if not image_bytes or len(image_bytes) > 15_000_000:
        raise ValueError("Chart image must be non-empty and under 15 MB.")
    ticker = resolve_symbol(symbol)
    snap = None
    try:
        s = snapshot(ticker)
        snap = {k: v for k, v in s.items() if k != "history"}
    except Exception as e:
        snap = {"symbol": ticker, "market_data_error": str(e)[:120]}
    system = """Analyze the supplied trading/chart screenshot as visual evidence, not as an oracle.
Describe only patterns visibly supported by the image. Use the supplied numerical market snapshot for prices
or return statistics; do not read tiny chart pixels as authoritative data. Do not give buy/sell advice.
Return JSON with keys summary, observed_visual_features, cautions, suggested_next_actions."""
    payload = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [
            {"text": f"Symbol: {ticker}\nQuestion: {question}\nMARKET_SNAPSHOT: {json.dumps(snap, default=str)}"},
            {"inline_data": {"mime_type": mime_type or "image/png", "data": base64.b64encode(image_bytes).decode("ascii")}},
        ]}],
        "generationConfig": {
            "temperature": 0.1, "maxOutputTokens": 1600, "responseMimeType": "application/json",
            "responseSchema": {"type": "OBJECT", "properties": {
                "summary": {"type": "STRING"},
                "observed_visual_features": {"type": "ARRAY", "items": {"type": "STRING"}},
                "cautions": {"type": "ARRAY", "items": {"type": "STRING"}},
                "suggested_next_actions": {"type": "ARRAY", "items": {"type": "STRING"}},
            }, "required": ["summary", "observed_visual_features", "cautions", "suggested_next_actions"]},
        },
    }
    js = _gemini_request(payload)
    try:
        doc = json.loads(_text(js))
    except json.JSONDecodeError as e:
        raise RuntimeError("Gemini returned invalid chart-analysis JSON") from e
    doc.update({"symbol": ticker, "snapshot": snap, "model": js.get("modelVersion", SETTINGS.gemini_model)})
    return doc
