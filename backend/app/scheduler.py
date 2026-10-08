"""Worker process: `python -m app.scheduler`.

* Every QUOTE_INTERVAL_MIN minutes during market hours (Mon-Fri 9:30-16:00 ET): quotes
* Every 30 minutes during market hours: account balance/positions
* Nightly at NIGHTLY_HOUR_ET:NIGHTLY_MINUTE_ET ET (Mon-Fri): full refresh + AI advisor
"""
import logging

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from .config import settings
from .db import init_db
from .ingest import nightly, pull_account, pull_quotes, run_job

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("scheduler")
TZ = "America/New_York"


def main():
    init_db()
    sched = BlockingScheduler(timezone=TZ)

    if settings.quote_interval_min > 0:
        sched.add_job(lambda: run_job("pull_quotes", pull_quotes),
                      CronTrigger(day_of_week="mon-fri", hour="9-15",
                                  minute=f"*/{settings.quote_interval_min}", timezone=TZ),
                      id="quotes", max_instances=1, coalesce=True)
        # Closing print at 16:05
        sched.add_job(lambda: run_job("pull_quotes", pull_quotes),
                      CronTrigger(day_of_week="mon-fri", hour=16, minute=5, timezone=TZ),
                      id="quotes_close", max_instances=1)

    sched.add_job(lambda: run_job("pull_account", pull_account),
                  CronTrigger(day_of_week="mon-fri", hour="9-16", minute="0,30", timezone=TZ),
                  id="account", max_instances=1, coalesce=True)

    sched.add_job(nightly,
                  CronTrigger(day_of_week="mon-fri", hour=settings.nightly_hour,
                              minute=settings.nightly_minute, timezone=TZ),
                  id="nightly", max_instances=1, coalesce=True, misfire_grace_time=3600)

    log.info("Scheduler started: %s", [j.id for j in sched.get_jobs()])
    sched.start()


if __name__ == "__main__":
    main()
