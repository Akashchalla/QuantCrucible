"""Trading universe: the frozen S&P 500 constituent snapshot used by Module B."""
from __future__ import annotations

from datetime import date

import pandas as pd

from .settings import SETTINGS


def load_universe(as_of: date | None = None, path=None) -> pd.DataFrame:
    """Constituents that were index members on `as_of` (point-in-time on the way in).

    Columns: symbol (exchange ticker, e.g. BRK.B), yahoo_symbol, security, sector, date_added.
    Massive uses exchange tickers with a dot (BRK.B); Yahoo uses a dash (BRK-B).
    """
    df = pd.read_csv(path or SETTINGS.universe_csv, parse_dates=["date_added"])
    if as_of is not None:
        df = df[df["date_added"] <= pd.Timestamp(as_of)]
    return df.reset_index(drop=True)


def symbols(as_of: date | None = None) -> list[str]:
    return load_universe(as_of)["symbol"].tolist()
