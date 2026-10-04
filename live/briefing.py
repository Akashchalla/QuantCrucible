"""Optional: a short plain-English morning/evening note written by Gemini from the store's
numbers. The model only summarises the figures it is given; it makes no trading decision.
"""
from __future__ import annotations

from datetime import date

import requests

from . import clock
from .monitor import render
from .settings import SETTINGS
from .store import Store

PROMPT = """You are the risk desk's note-writer for a small systematic book: a VIX-gated opening-auction
gap fade in S&P 500 names (long the quintile that gapped down most relative to the market at the open,
short the quintile that gapped up most, flat by the close, only on days when yesterday's VIX closed at
or above 20). Below is the operator dashboard. Write at most 120 words of plain English for a portfolio
manager: whether the book trades today and why, how recent sessions went net of costs, and anything
in the risk events that needs a human. No advice, no speculation about markets; only what the numbers say.

{dashboard}
"""


def write(store: Store, session: date | None = None) -> str:
    if not SETTINGS.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY missing from .env")
    session = session or clock.session_date()
    dashboard = render(store, session)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{SETTINGS.gemini_model}:generateContent"
    r = requests.post(url, params={"key": SETTINGS.gemini_api_key}, timeout=60,
                      json={"contents": [{"parts": [{"text": PROMPT.format(dashboard=dashboard)}]}],
                            "generationConfig": {"temperature": 0.2}})
    if r.status_code >= 400:
        raise RuntimeError(f"gemini {r.status_code}: {r.text[:200]}")
    parts = r.json()["candidates"][0]["content"]["parts"]
    return "".join(p.get("text", "") for p in parts).strip()
