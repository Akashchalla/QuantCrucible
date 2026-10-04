"""Exchange clock: Eastern time, session dates, auction cut-offs."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

ET = ZoneInfo("America/New_York")

# NYSE/Nasdaq rules: MOO orders accepted until 09:28, MOC until 15:50 (NYSE) / 15:55 (Nasdaq).
MOO_CUTOFF = time(9, 28)
OPEN = time(9, 30)
MOC_CUTOFF = time(15, 50)
CLOSE = time(16, 0)

# Default schedule (ET) for the daily steps.
SCHEDULE = {
    "pre_open": time(8, 45),
    "open_auction": time(9, 27),
    "post_open": time(9, 35),
    "close_auction": time(15, 45),
    "eod": time(16, 20),
}


def now_et() -> datetime:
    return datetime.now(tz=ET)


def session_date(ts: datetime | None = None) -> date:
    ts = ts or now_et()
    return ts.astimezone(ET).date()


def is_weekday(d: date) -> bool:
    return d.weekday() < 5


def prev_weekday(d: date) -> date:
    d = d - timedelta(days=1)
    while not is_weekday(d):
        d -= timedelta(days=1)
    return d


def et(d: date, t: time) -> datetime:
    return datetime.combine(d, t, tzinfo=ET)


def to_utc_iso(dt: datetime) -> str:
    return dt.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%S")


def before(d: date, t: time, ts: datetime | None = None) -> bool:
    return (ts or now_et()) < et(d, t)


def as_timestamp(d: date | str) -> pd.Timestamp:
    return pd.Timestamp(d).normalize()
