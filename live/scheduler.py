"""Runs the daily steps at their Eastern-time slots on weekdays, skipping exchange holidays.
Intraday the loss-limit monitor runs every 5 minutes between the auctions.
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from . import clock
from .pipeline import Pipeline

log = logging.getLogger("live.scheduler")


def _guarded(pipe: Pipeline, step: str):
    def run():
        session = clock.session_date()
        try:
            if not pipe.feed.is_session(session):
                log.info("%s: %s is an exchange holiday", step, session)
                return
            res = getattr(pipe, step)(session)
            log.info("%s %s -> %s", step, session, {k: v for k, v in (res or {}).items() if k != "violations"})
        except Exception:  # noqa: BLE001 — keep the scheduler alive, record the failure
            log.exception("%s failed", step)
            pipe.store.risk_event(session, "block", step, "exception", "step raised; see logs")
    return run


def build(pipe: Pipeline | None = None) -> BlockingScheduler:
    pipe = pipe or Pipeline()
    sch = BlockingScheduler(timezone=str(clock.ET))
    for step, t in clock.SCHEDULE.items():
        sch.add_job(_guarded(pipe, step), CronTrigger(day_of_week="mon-fri", hour=t.hour, minute=t.minute, timezone=clock.ET),
                    id=step, misfire_grace_time=300)
    sch.add_job(_guarded(pipe, "monitor_intraday"), CronTrigger(day_of_week="mon-fri", hour="9-15", minute="*/5", timezone=clock.ET),
                id="monitor_intraday", misfire_grace_time=120)
    return sch


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    sch = build()
    log.info("scheduler up; jobs: %s", [j.id for j in sch.get_jobs()])
    sch.start()


if __name__ == "__main__":
    main()
