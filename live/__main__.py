"""python -m live <command>

  init-db                        create tables (Timescale if DATABASE_URL, else SQLite)
  pre-open|open|post-open|close|eod [--date D]   run one step for a session (default: today ET)
  monitor [--date D]             intraday loss-limit check (flattens on breach)
  replay --date D                run the whole cycle on a past session with historical data
  replay-range --start A --end B replay every session in [A, B]
  status [--date D] [--days N]   operator dashboard
  briefing [--date D]            Gemini-written summary of the dashboard
  schedule                       run the daily cycle on a clock (blocking)
  kill | resume                  engage / release the kill switch
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, timedelta

from . import clock
from .settings import SETTINGS


def _date(s: str | None) -> date:
    return date.fromisoformat(s) if s else clock.session_date()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m live", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", choices=["init-db", "pre-open", "open", "post-open", "close", "eod", "monitor", "replay",
                                       "replay-range", "status", "briefing", "schedule", "kill", "resume", "reset"])
    p.add_argument("--date")
    p.add_argument("--start")
    p.add_argument("--end")
    p.add_argument("--days", type=int, default=15)
    p.add_argument("--sqlite", action="store_true", help="ignore DATABASE_URL and use the local SQLite store")
    p.add_argument("-v", "--verbose", action="store_true")
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    if a.command == "kill":
        SETTINGS.kill_switch.write_text("engaged\n")
        print(f"kill switch engaged: {SETTINGS.kill_switch}")
        return 0
    if a.command == "resume":
        SETTINGS.kill_switch.unlink(missing_ok=True)
        print("kill switch released")
        return 0

    from .store import Store
    store = Store(url=None if a.sqlite else SETTINGS.database_url)
    if a.command == "init-db":
        print(f"schema ready on {store.kind}")
        return 0
    if a.command == "reset":
        if not a.date:
            p.error("reset requires --date")
        store.reset_session(_date(a.date))
        print(f"cleared {a.date} on {store.kind}")
        return 0
    if a.command == "status":
        from .monitor import render
        print(render(store, _date(a.date), a.days))
        return 0
    if a.command == "briefing":
        from .briefing import write
        print(write(store, _date(a.date)))
        return 0

    from .pipeline import Pipeline
    if a.command == "schedule":
        from .scheduler import build
        build(Pipeline(store=store)).start()
        return 0
    if a.command in ("replay", "replay-range"):
        pipe = Pipeline(store=store, replay=True)
        if a.command == "replay":
            res = pipe.run_session(_date(a.date))
            print({k: v for k, v in res.items() if k != "detail"})
        else:
            d, end = _date(a.start), _date(a.end)
            while d <= end:
                if d.weekday() < 5:
                    pipe.run_session(d)
                d += timedelta(days=1)
            from .monitor import render
            print(render(store, end, 60))
        return 0

    pipe = Pipeline(store=store)
    step = {"pre-open": "pre_open", "open": "open_auction", "post-open": "post_open", "close": "close_auction",
            "eod": "eod", "monitor": "monitor_intraday"}[a.command]
    res = getattr(pipe, step)(_date(a.date))
    print({k: v for k, v in (res or {}).items() if k not in ("detail", "violations")})
    return 0


if __name__ == "__main__":
    sys.exit(main())
