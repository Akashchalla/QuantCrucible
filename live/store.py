"""Persistent state: signals, orders, fills, positions, P&L, risk events.

Primary backend is the Timescale/Postgres instance in DATABASE_URL (time-series tables are
hypertables). If no DATABASE_URL is set the same schema runs on a local SQLite file, so the
paper loop and the tests work with zero infrastructure.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from .settings import SETTINGS

TABLES = {
    "live_gate": """
        session_date DATE NOT NULL, ts TIMESTAMPTZ NOT NULL, vix_lag DOUBLE PRECISION, vix3m_lag DOUBLE PRECISION,
        vix_as_of DATE, vix_source TEXT, gate_on BOOLEAN NOT NULL, reason TEXT, n_universe INTEGER,
        PRIMARY KEY (session_date)""",
    "live_signals": """
        ts TIMESTAMPTZ NOT NULL, session_date DATE NOT NULL, symbol TEXT NOT NULL, prev_close DOUBLE PRECISION,
        est_open DOUBLE PRECISION, est_source TEXT, gap DOUBLE PRECISION, relgap DOUBLE PRECISION, pct_rank DOUBLE PRECISION,
        bucket INTEGER, side INTEGER, target_notional DOUBLE PRECISION, target_qty INTEGER, excluded TEXT,
        PRIMARY KEY (session_date, symbol)""",
    "live_orders": """
        order_id TEXT NOT NULL, ts TIMESTAMPTZ NOT NULL, session_date DATE NOT NULL, symbol TEXT NOT NULL,
        side TEXT NOT NULL, qty INTEGER NOT NULL, order_type TEXT NOT NULL, status TEXT NOT NULL, broker TEXT NOT NULL,
        broker_order_id TEXT, note TEXT, PRIMARY KEY (order_id)""",
    "live_fills": """
        fill_id TEXT NOT NULL, order_id TEXT NOT NULL, ts TIMESTAMPTZ NOT NULL, session_date DATE NOT NULL,
        symbol TEXT NOT NULL, side TEXT NOT NULL, qty INTEGER NOT NULL, price DOUBLE PRECISION NOT NULL,
        cost DOUBLE PRECISION NOT NULL, venue TEXT, PRIMARY KEY (fill_id)""",
    "live_positions": """
        session_date DATE NOT NULL, symbol TEXT NOT NULL, qty INTEGER NOT NULL, avg_price DOUBLE PRECISION,
        as_of TIMESTAMPTZ NOT NULL, PRIMARY KEY (session_date, symbol)""",
    "live_pnl": """
        session_date DATE NOT NULL, ts TIMESTAMPTZ NOT NULL, gate_on BOOLEAN, vix_lag DOUBLE PRECISION,
        n_long INTEGER, n_short INTEGER, gross_notional DOUBLE PRECISION, gross_pnl DOUBLE PRECISION,
        cost DOUBLE PRECISION, net_pnl DOUBLE PRECISION, gross_bps DOUBLE PRECISION, net_bps DOUBLE PRECISION,
        est_spread_bps DOUBLE PRECISION, realised_spread_bps DOUBLE PRECISION, basket_overlap DOUBLE PRECISION,
        shortfall_bps DOUBLE PRECISION, detail TEXT, PRIMARY KEY (session_date)""",
    "live_risk_events": """
        ts TIMESTAMPTZ NOT NULL, session_date DATE, level TEXT NOT NULL, step TEXT NOT NULL, check_name TEXT NOT NULL,
        message TEXT NOT NULL""",
    "live_step_log": """
        ts TIMESTAMPTZ NOT NULL, session_date DATE NOT NULL, step TEXT NOT NULL, status TEXT NOT NULL, detail TEXT,
        PRIMARY KEY (session_date, step)""",
}
HYPERTABLES = {"live_signals": "ts", "live_fills": "ts", "live_risk_events": "ts"}


def utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


def new_id() -> str:
    return uuid.uuid4().hex[:16]


_DEFAULT = object()


class Store:
    def __init__(self, url: str | None | object = _DEFAULT, sqlite_path: Path | None = None):
        """url: DATABASE_URL by default; pass None explicitly to force the SQLite backend."""
        url = SETTINGS.database_url if url is _DEFAULT else url
        self.backend_error: str | None = None
        if url:
            try:
                import psycopg
                self.kind = "postgres"
                self.conn = psycopg.connect(url, autocommit=True, connect_timeout=15)
            except Exception as exc:  # demo continuity: cloud DB outage must not kill analysis UI
                if os.environ.get("DATABASE_STRICT", "0") == "1":
                    raise
                self.backend_error = f"{type(exc).__name__}: {str(exc)[:180]}"
                self.kind = "sqlite"
                path = sqlite_path or SETTINGS.sqlite_path
                Path(path).parent.mkdir(parents=True, exist_ok=True)
                self.conn = sqlite3.connect(str(path), detect_types=sqlite3.PARSE_DECLTYPES)
                self.conn.row_factory = sqlite3.Row
        else:
            self.kind = "sqlite"
            path = sqlite_path or SETTINGS.sqlite_path
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            self.conn = sqlite3.connect(str(path), detect_types=sqlite3.PARSE_DECLTYPES)
            self.conn.row_factory = sqlite3.Row
        self.init_schema()

    # ---------------------------------------------------------------- infra
    def _sql(self, q: str) -> str:
        if self.kind == "sqlite":
            q = q.replace("%s", "?").replace("TIMESTAMPTZ", "TEXT").replace("DOUBLE PRECISION", "REAL")
            q = q.replace("BOOLEAN", "INTEGER")
            q = re.sub(r"\bDATE\b", "TEXT", q)
        return q

    def _v(self, x):
        """Normalise a parameter for the driver: numpy scalars -> python, NaN -> NULL,
        pandas timestamps -> datetime; for SQLite also dates/datetimes -> ISO text."""
        if x is not None and hasattr(x, "item") and not isinstance(x, (datetime, date)):
            x = x.item()
        if isinstance(x, pd.Timestamp):
            x = None if pd.isna(x) else x.to_pydatetime()
        if isinstance(x, float) and x != x:
            return None
        if self.kind == "sqlite":
            if isinstance(x, (datetime, date)):
                return x.isoformat()
            if isinstance(x, bool):
                return int(x)
        return x

    def exec(self, q: str, params: tuple = ()) -> None:
        self.conn.execute(self._sql(q), tuple(self._v(p) for p in params))
        if self.kind == "sqlite":
            self.conn.commit()

    def executemany(self, q: str, rows: list[tuple]) -> None:
        if not rows:
            return
        clean = [tuple(self._v(p) for p in r) for r in rows]
        if self.kind == "sqlite":
            self.conn.executemany(self._sql(q), clean)
            self.conn.commit()
        else:
            with self.conn.cursor() as cur:
                cur.executemany(q, clean)

    def df(self, q: str, params: tuple = ()) -> pd.DataFrame:
        cur = self.conn.execute(self._sql(q), tuple(self._v(p) for p in params))
        cols = [c[0] for c in cur.description]
        return pd.DataFrame([tuple(r) for r in cur.fetchall()], columns=cols)

    def init_schema(self) -> None:
        for name, body in TABLES.items():
            self.exec(f"CREATE TABLE IF NOT EXISTS {name} ({body})")
        if self.kind == "postgres":
            for name, col in HYPERTABLES.items():
                try:
                    self.conn.execute(
                        f"SELECT create_hypertable('{name}', '{col}', if_not_exists => TRUE, migrate_data => TRUE)")
                except Exception:  # noqa: BLE001 — timescaledb extension absent or PK incompatible
                    pass

    def close(self) -> None:
        self.conn.close()

    # ---------------------------------------------------------------- writes
    def log_step(self, session: date, step: str, status: str, detail: dict | None = None) -> None:
        self.exec("""INSERT INTO live_step_log (ts, session_date, step, status, detail) VALUES (%s,%s,%s,%s,%s)
                     ON CONFLICT (session_date, step) DO UPDATE SET ts=EXCLUDED.ts, status=EXCLUDED.status, detail=EXCLUDED.detail""",
                  (utcnow(), session, step, status, json.dumps(detail or {}, default=str)))

    def step_status(self, session: date, step: str) -> str | None:
        d = self.df("SELECT status FROM live_step_log WHERE session_date=%s AND step=%s", (session, step))
        return None if d.empty else d["status"].iloc[0]

    def risk_event(self, session: date | None, level: str, step: str, check: str, message: str) -> None:
        self.exec("INSERT INTO live_risk_events (ts, session_date, level, step, check_name, message) VALUES (%s,%s,%s,%s,%s,%s)",
                  (utcnow(), session, level, step, check, message[:2000]))

    def save_gate(self, session: date, vix, gate_on: bool, reason: str, n_universe: int) -> None:
        self.exec("""INSERT INTO live_gate (session_date, ts, vix_lag, vix3m_lag, vix_as_of, vix_source, gate_on, reason, n_universe)
                     VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                     ON CONFLICT (session_date) DO UPDATE SET ts=EXCLUDED.ts, vix_lag=EXCLUDED.vix_lag, vix3m_lag=EXCLUDED.vix3m_lag,
                     vix_as_of=EXCLUDED.vix_as_of, vix_source=EXCLUDED.vix_source, gate_on=EXCLUDED.gate_on, reason=EXCLUDED.reason,
                     n_universe=EXCLUDED.n_universe""",
                  (session, utcnow(), vix.vix, vix.vix3m, vix.as_of, vix.source, gate_on, reason, n_universe))

    def gate(self, session: date) -> dict | None:
        d = self.df("SELECT * FROM live_gate WHERE session_date=%s", (session,))
        return None if d.empty else d.iloc[0].to_dict()

    def save_signals(self, session: date, sig: pd.DataFrame, est_source: str) -> None:
        self.exec("DELETE FROM live_signals WHERE session_date=%s", (session,))
        ts = utcnow()
        rows = [(ts, session, sym, r.prev_close, r.est_open, est_source, r.gap, r.relgap, r.pct_rank,
                 None if pd.isna(r.bucket) else int(r.bucket), int(r.side), float(r.target_notional), int(r.target_qty),
                 r.excluded) for sym, r in sig.iterrows()]
        self.executemany("""INSERT INTO live_signals (ts, session_date, symbol, prev_close, est_open, est_source, gap, relgap, pct_rank,
                            bucket, side, target_notional, target_qty, excluded) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", rows)

    def signals(self, session: date) -> pd.DataFrame:
        d = self.df("SELECT * FROM live_signals WHERE session_date=%s", (session,))
        return d.set_index("symbol") if len(d) else d

    def save_orders(self, orders: list[dict]) -> None:
        self.executemany("""INSERT INTO live_orders (order_id, ts, session_date, symbol, side, qty, order_type, status, broker, broker_order_id, note)
                            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                            ON CONFLICT (order_id) DO UPDATE SET status=EXCLUDED.status, broker_order_id=EXCLUDED.broker_order_id, note=EXCLUDED.note""",
                         [(o["order_id"], o.get("ts", utcnow()), o["session_date"], o["symbol"], o["side"], int(o["qty"]),
                           o["order_type"], o["status"], o["broker"], o.get("broker_order_id"), o.get("note")) for o in orders])

    def orders(self, session: date, order_type: str | None = None) -> pd.DataFrame:
        q, p = "SELECT * FROM live_orders WHERE session_date=%s", [session]
        if order_type:
            q += " AND order_type=%s"
            p.append(order_type)
        return self.df(q, tuple(p))

    def save_fills(self, fills: list[dict]) -> None:
        self.executemany("""INSERT INTO live_fills (fill_id, order_id, ts, session_date, symbol, side, qty, price, cost, venue)
                            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (fill_id) DO NOTHING""",
                         [(f["fill_id"], f["order_id"], f.get("ts", utcnow()), f["session_date"], f["symbol"], f["side"],
                           int(f["qty"]), float(f["price"]), float(f["cost"]), f.get("venue")) for f in fills])

    def fills(self, session: date) -> pd.DataFrame:
        return self.df("SELECT * FROM live_fills WHERE session_date=%s ORDER BY ts", (session,))

    def set_positions(self, session: date, pos: pd.DataFrame) -> None:
        """pos: index=symbol, columns qty, avg_price. Replaces the day's snapshot."""
        self.exec("DELETE FROM live_positions WHERE session_date=%s", (session,))
        ts = utcnow()
        self.executemany("INSERT INTO live_positions (session_date, symbol, qty, avg_price, as_of) VALUES (%s,%s,%s,%s,%s)",
                         [(session, s, int(r.qty), float(r.avg_price), ts) for s, r in pos.iterrows() if int(r.qty) != 0])

    def positions(self, session: date) -> pd.DataFrame:
        d = self.df("SELECT symbol, qty, avg_price FROM live_positions WHERE session_date=%s", (session,))
        return d.set_index("symbol") if len(d) else pd.DataFrame(columns=["qty", "avg_price"])

    def save_pnl(self, session: date, row: dict) -> None:
        cols = ["gate_on", "vix_lag", "n_long", "n_short", "gross_notional", "gross_pnl", "cost", "net_pnl", "gross_bps",
                "net_bps", "est_spread_bps", "realised_spread_bps", "basket_overlap", "shortfall_bps"]
        vals = [row.get(c) for c in cols]
        self.exec(f"""INSERT INTO live_pnl (session_date, ts, {', '.join(cols)}, detail) VALUES (%s,%s,{','.join(['%s']*len(cols))},%s)
                      ON CONFLICT (session_date) DO UPDATE SET ts=EXCLUDED.ts, {', '.join(f'{c}=EXCLUDED.{c}' for c in cols)}, detail=EXCLUDED.detail""",
                  (session, utcnow(), *vals, json.dumps(row.get("detail", {}), default=str)))

    def pnl_history(self, n: int = 60) -> pd.DataFrame:
        return self.df(f"SELECT * FROM live_pnl ORDER BY session_date DESC LIMIT {int(n)}").iloc[::-1].reset_index(drop=True)

    def recent_risk_events(self, n: int = 20) -> pd.DataFrame:
        return self.df(f"SELECT ts, session_date, level, step, check_name, message FROM live_risk_events ORDER BY ts DESC LIMIT {int(n)}")

    def reset_session(self, session: date) -> None:
        """Delete everything recorded for one session (replay housekeeping; never run intraday)."""
        for t in ("live_gate", "live_signals", "live_orders", "live_fills", "live_positions", "live_pnl",
                  "live_risk_events", "live_step_log"):
            self.exec(f"DELETE FROM {t} WHERE session_date=%s", (session,))

    def step_log(self, session: date) -> pd.DataFrame:
        return self.df("SELECT step, status, ts, detail FROM live_step_log WHERE session_date=%s ORDER BY ts", (session,))


@contextmanager
def open_store(**kw):
    s = Store(**kw)
    try:
        yield s
    finally:
        s.close()
