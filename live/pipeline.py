"""The daily cycle. Each step is idempotent per session and leaves an audit record.

`replay=True` runs the same code path on a past session using historical data (Databento
NOII for the 09:27 indicative price when available, otherwise the official open flagged as
such), which is how the loop is tested outside market hours.
"""
from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import date, time

import numpy as np
import pandas as pd

from . import clock, risk
from .broker import make_broker
from .broker.base import closing_orders, orders_from_targets
from .feeds.massive import MassiveFeed, NotEntitled
from .feeds.vix import VixState, lagged_vix
from .settings import SETTINGS, Settings
from .signal import build_signals, ideal_book, implementation_shortfall, spread_bps
from .store import Store
from .universe import load_universe

log = logging.getLogger("live")


class Pipeline:
    def __init__(self, store: Store | None = None, feed: MassiveFeed | None = None, broker=None,
                 settings: Settings = SETTINGS, replay: bool = False):
        self.s = settings
        self.store = store or Store()
        self.feed = feed or MassiveFeed()
        self.broker = broker or make_broker(self.store, settings)
        self.replay = replay

    # ------------------------------------------------------------ helpers
    def _symbols(self, session: date) -> list[str]:
        return load_universe(session, self.s.universe_csv)["symbol"].tolist()

    def _record(self, session: date, step: str, violations: list[risk.Violation]) -> None:
        for v in violations:
            self.store.risk_event(session, v.level, step, v.check, v.message)
            (log.warning if v.level == "block" else log.info)("%s %s: %s", step, v.check, v.message)

    def _vix(self, session: date) -> VixState:
        g = self.store.gate(session)
        if g is None:
            g = self.pre_open(session)
        return VixState(pd.Timestamp(g["vix_as_of"]).date() if g["vix_as_of"] else None, g["vix_lag"], g["vix3m_lag"], g["vix_source"])

    def _official(self, session: date, symbols: list[str]) -> pd.DataFrame:
        """Official open/close. Intraday (live) the daily bar may not exist yet; fall back to snapshots."""
        px = self.feed.official_prices(session, symbols)
        if px["open"].notna().sum() < self.s.min_names and not self.replay:
            snap = self.feed.snapshots(symbols)
            px = pd.DataFrame({"open": snap["today_open"], "close": snap["last"], "volume": np.nan}).astype(float)
            px.attrs["source"] = "snapshot"
        else:
            px.attrs["source"] = "daily-bar"
        return px

    # ------------------------------------------------------------ 08:45
    def pre_open(self, session: date, force: bool = False) -> dict:
        if not force and (g := self.store.gate(session)) is not None:
            return g
        vix = lagged_vix(session)
        uni = self._symbols(session)
        gate_on = bool(vix.vix >= self.s.vix_threshold)
        reason = f"VIX_(t-1)={vix.vix:.2f} ({vix.as_of}, {vix.source}) {'>=' if gate_on else '<'} {self.s.vix_threshold:g}"
        self.store.save_gate(session, vix, gate_on, reason, len(uni))
        self.store.log_step(session, "pre_open", "ok", {"gate_on": gate_on, "reason": reason, "n_universe": len(uni),
                                                        "term_ratio": vix.term_ratio})
        log.info("pre_open %s: %s -> gate %s", session, reason, "ON" if gate_on else "OFF")
        return self.store.gate(session)

    # ------------------------------------------------------------ 09:27
    def _indicative(self, session: date, symbols: list[str], prev_close: pd.Series) -> tuple[pd.Series, str, float | None]:
        """Best pre-open estimate of the opening price per symbol, its source, and its age in seconds."""
        est, source, age = pd.Series(np.nan, index=symbols, dtype=float), [], None
        if self.s.databento_api_key:
            try:
                from .feeds.databento_feed import DatabentoFeed
                dbf = DatabentoFeed(cost_cap=self.s.databento_cost_cap_usd)
                noii = (dbf.opening_indicative(session, symbols, at=clock.SCHEDULE["open_auction"]) if self.replay
                        else dbf.opening_indicative_live(symbols))
                if len(noii):
                    est.loc[noii.index.intersection(symbols)] = noii["ref_price"].reindex(est.index).dropna()
                    source.append(f"noii:{int(est.notna().sum())}")
            except Exception as e:  # noqa: BLE001 — fall through to the next source
                log.warning("databento indicative unavailable: %s", str(e)[:160])
        missing = est[est.isna()].index.tolist()
        if missing and not self.replay:
            snap = self.feed.snapshots(missing)
            today = pd.Timestamp(session, tz="UTC")
            fresh = snap["last_ts"].notna() & (snap["last_ts"] >= today)
            pre = snap["last"].where(fresh)
            fmv = snap["fmv"]
            use = pre.fillna(fmv)
            est.loc[use.dropna().index] = use.dropna()
            n_pre, n_fmv = int(pre.notna().sum()), int((pre.isna() & fmv.notna()).sum())
            source.append(f"premarket_trade:{n_pre}")
            source.append(f"fmv:{n_fmv}")
            if fresh.any():
                age = float((pd.Timestamp.now(tz="UTC") - snap.loc[fresh, "last_ts"].max()).total_seconds())
        elif missing and self.replay:
            off = self.feed.official_prices(session, missing)["open"]
            est.loc[off.dropna().index] = off.dropna()
            source.append(f"official_open(replay):{int(off.notna().sum())}")
        return est, ",".join(source) or "none", age

    def open_auction(self, session: date) -> dict:
        step = "open_auction"
        if self.store.step_status(session, step) in ("submitted", "skipped_gate"):
            return {"status": self.store.step_status(session, step), "note": "already done"}
        gate = self.store.gate(session) or self.pre_open(session)
        vix = self._vix(session)
        symbols = self._symbols(session)
        prev = self.feed.previous_session(session)
        prev_close = self.feed.grouped_daily(prev)["close"].reindex(symbols)

        if not gate["gate_on"]:
            self.store.log_step(session, step, "skipped_gate", {"reason": gate["reason"]})
            log.info("open_auction %s: gate OFF — no orders (%s)", session, gate["reason"])
            return {"status": "skipped_gate", "reason": gate["reason"]}

        est, est_source, age = self._indicative(session, symbols, prev_close)
        sig = build_signals(prev_close, est)
        n_priced = int((sig["prev_close"].notna() & sig["est_open"].notna()).sum())
        already = len(self.store.orders(session, "MOO")) > 0
        hist = self.store.pnl_history(5)
        trailing = float(hist["net_pnl"].sum() / (2 * self.s.notional_per_side)) if len(hist) else None
        viol = risk.pre_trade(session, gate_on=bool(gate["gate_on"]), vix_as_of=vix.as_of, n_priced=n_priced,
                              n_universe=len(symbols), sig=sig, indicative_age_s=age, already_submitted=already,
                              realised_loss_pct=trailing, s=self.s)
        self._record(session, step, viol)
        self.store.save_signals(session, sig, est_source)
        live = sig[sig["side"] != 0]
        detail = {"est_source": est_source, "n_priced": n_priced, "n_long": int((live["side"] == 1).sum()),
                  "n_short": int((live["side"] == -1).sum()),
                  "gross_target": float((live["target_qty"].abs() * live["est_open"]).sum()),
                  "violations": [asdict(v) for v in viol]}
        if risk.blocked(viol):
            self.store.log_step(session, step, "blocked", detail)
            log.warning("open_auction %s: BLOCKED %s", session, [v.check for v in viol if v.level == "block"])
            return {"status": "blocked", **detail}
        orders = self.broker.submit(orders_from_targets(session, sig, "MOO"))
        detail["n_orders"] = len(orders)
        self.store.log_step(session, step, "submitted", detail)
        log.info("open_auction %s: %d MOO orders, long %d / short %d, gross $%s (%s)", session, len(orders),
                 detail["n_long"], detail["n_short"], f"{detail['gross_target']:,.0f}", est_source)
        return {"status": "submitted", **detail}

    # ------------------------------------------------------------ 09:35
    def post_open(self, session: date) -> dict:
        step = "post_open"
        if self.store.step_status(session, "open_auction") != "submitted":
            self.store.log_step(session, step, "skipped", {"reason": "no orders this session"})
            return {"status": "skipped"}
        vix = self._vix(session)
        symbols = self._symbols(session)
        px = self._official(session, symbols)
        if hasattr(self.broker, "fill_auction"):
            fills = self.broker.fill_auction(session, "MOO", px["open"], vix.vix, "open-auction")
        else:
            fills = self.broker.fills(session)
        book = self.broker.positions(session) if self.broker.name == "paper" else self.broker.positions()
        self.store.set_positions(session, book)
        viol = risk.reconcile(self.store.positions(session), book)
        sig = self.store.signals(session)
        real = ideal_book(sig["prev_close"], px["open"].reindex(sig.index))
        chosen = sig.index[sig["side"] != 0]
        overlap = float((sig.loc[chosen, "side"] == real.loc[chosen, "side"]).mean()) if len(chosen) else None
        self._record(session, step, viol)
        detail = {"n_fills": int(len(fills)), "n_positions": int(len(book)), "basket_overlap": overlap,
                  "price_source": px.attrs.get("source"), "gross_filled": float((book["qty"].abs() * book["avg_price"]).sum()) if len(book) else 0.0}
        self.store.log_step(session, step, "blocked" if risk.blocked(viol) else "ok", detail)
        log.info("post_open %s: %d fills, %d positions, basket overlap %s", session, len(fills), len(book),
                 f"{overlap:.0%}" if overlap is not None else "n/a")
        return {"status": "ok", **detail}

    # ------------------------------------------------------------ intraday
    def monitor_intraday(self, session: date, flatten: bool = True) -> dict:
        pos = self.store.positions(session)
        if pos.empty:
            return {"status": "flat"}
        snap = self.feed.snapshots(pos.index.tolist())
        last = snap["last"].astype(float)
        mark = float(((last - pos["avg_price"]) * pos["qty"]).sum())
        gross = float((pos["qty"].abs() * pos["avg_price"]).sum())
        viol = risk.intraday_loss_check(mark, gross, self.s)
        self._record(session, "intraday", viol)
        out = {"status": "ok", "mark_pnl": mark, "gross": gross, "pct": mark / gross if gross else 0.0}
        if risk.blocked(viol) and flatten:
            orders = closing_orders(session, pos, "MKT")
            if hasattr(self.broker, "fill_market"):
                self.broker.fill_market(session, orders, last, self._vix(session).vix)
            else:
                self.broker.submit(orders)
            self.store.set_positions(session, self.broker.positions(session) if self.broker.name == "paper" else self.broker.positions())
            self.store.log_step(session, "flatten", "ok", {"n_orders": len(orders), "mark_pnl": mark})
            out["status"] = "flattened"
        return out

    # ------------------------------------------------------------ 15:45
    def close_auction(self, session: date) -> dict:
        step = "close_auction"
        if self.store.step_status(session, step) == "submitted":
            return {"status": "submitted", "note": "already done"}
        pos = self.store.positions(session)
        if pos.empty:
            self.store.log_step(session, step, "skipped", {"reason": "no positions"})
            return {"status": "skipped"}
        orders = self.broker.submit(closing_orders(session, pos, "MOC"))
        self.store.log_step(session, step, "submitted", {"n_orders": len(orders)})
        log.info("close_auction %s: %d MOC orders", session, len(orders))
        return {"status": "submitted", "n_orders": len(orders)}

    # ------------------------------------------------------------ 16:20
    def eod(self, session: date) -> dict:
        step = "eod"
        gate = self.store.gate(session) or self.pre_open(session)
        vix = self._vix(session)
        symbols = self._symbols(session)
        px = self._official(session, symbols)
        traded = self.store.step_status(session, "open_auction") == "submitted"

        fills = pd.DataFrame()
        if traded:
            if hasattr(self.broker, "fill_auction"):
                self.broker.fill_auction(session, "MOC", px["close"], vix.vix, "close-auction")
            fills = self.broker.fills(session)
            book = self.broker.positions(session) if self.broker.name == "paper" else self.broker.positions()
            self.store.set_positions(session, book)
            viol = risk.flat_check(book) + risk.reconcile(self.store.positions(session), book)
            self._record(session, step, viol)

        # P&L from fills (book is flat, so realised = total)
        row = {"gate_on": bool(gate["gate_on"]), "vix_lag": vix.vix, "n_long": 0, "n_short": 0, "gross_notional": 0.0,
               "gross_pnl": 0.0, "cost": 0.0, "net_pnl": 0.0, "gross_bps": 0.0, "net_bps": 0.0}
        if len(fills):
            signed = fills["qty"].where(fills["side"] == "buy", -fills["qty"]).astype(float)
            cash = -(signed * fills["price"]).sum()
            open_fills = fills[fills["venue"].astype(str).str.contains("open")]
            entry_signed = open_fills["qty"].where(open_fills["side"] == "buy", -open_fills["qty"])
            row.update({
                "n_long": int((entry_signed > 0).sum()), "n_short": int((entry_signed < 0).sum()),
                "gross_notional": float((open_fills["qty"] * open_fills["price"]).sum()),
                "gross_pnl": float(cash), "cost": float(fills["cost"].sum()),
            })
            row["net_pnl"] = row["gross_pnl"] - row["cost"]
            row["gross_bps"] = 1e4 * row["gross_pnl"] / self.s.notional_per_side
            row["net_bps"] = 1e4 * row["net_pnl"] / self.s.notional_per_side

        # what the rule's book did today, traded or not (monitoring the premium while out)
        prev = self.feed.previous_session(session)
        prev_close = self.feed.grouped_daily(prev)["close"].reindex(symbols)
        ideal = ideal_book(prev_close, px["open"])
        ret_oc = px["close"] / px["open"] - 1
        _, _, ideal_spread = spread_bps(ret_oc, ideal["side"])
        row["realised_spread_bps"] = None if ideal_spread != ideal_spread else float(ideal_spread)
        detail = {"price_source": px.attrs.get("source"), "n_ideal": int((ideal["side"] != 0).sum())}
        if traded:
            sig = self.store.signals(session)
            sf = implementation_shortfall(sig, px["open"], px["close"])
            row.update({"est_spread_bps": sf["traded_spread_bps"], "basket_overlap": sf["basket_overlap"],
                        "shortfall_bps": sf["shortfall_bps"]})
            detail.update(sf)
        row["detail"] = detail
        self.store.save_pnl(session, row)
        self.store.log_step(session, step, "ok", {k: v for k, v in row.items() if k != "detail"})
        log.info("eod %s: gate %s, gross %.1f bps, cost %.1f bps, net %.1f bps; rule book spread %.1f bps",
                 session, "ON" if row["gate_on"] else "OFF", row["gross_bps"], 1e4 * row["cost"] / self.s.notional_per_side,
                 row["net_bps"], row["realised_spread_bps"] or float("nan"))
        return row

    # ------------------------------------------------------------ replay
    def run_session(self, session: date) -> dict:
        if not self.feed.is_session(session) or len(self.feed.grouped_daily(session)) == 0:
            log.info("%s is not a session; nothing to do", session)
            return {"status": "not_a_session"}
        self.pre_open(session)
        self.open_auction(session)
        self.post_open(session)
        self.close_auction(session)
        return self.eod(session)
