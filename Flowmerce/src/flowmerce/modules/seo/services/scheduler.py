"""Background work. Two jobs:

1. Refresh: runs the Performance tracking stage (Shopify, Search Console, GA4) for each brand when the last
   SUCCESSFUL run is more than 6 hours old. Paused brands are skipped.
2. The content calendar: runs schedule entries a person created (topic research, drafting, and publish requests)
   when their day comes, within the daily Claude limit (services/calendar_plan.py), and the 6-hour rule
   (services/autopilot.py): a scheduled article nobody approved 6 hours before its publish time is approved
   automatically and saved as a HIDDEN Shopify draft. It never publishes: a reviewer still authorizes going live.

After a failed run it does not wait the full 6 hours: it retries with a growing delay (30 min, 1 h, 2 h,
4 h, then every 6 h) so a temporary outage heals quickly without hammering a service that keeps failing."""
from __future__ import annotations

import logging
import threading
import time

from ..config import BRAND_IDS
from ..util import ms_since
from . import autopilot, calendar_plan
from .runs import failures_since_success, last_run, last_successful_run
from .workflow import is_paused, run_stage

log = logging.getLogger(__name__)

EVERY_SECONDS = 15 * 60
REFRESH_HOURS = 6
RETRY_BASE_MINUTES = 30
_started = False


def retry_delay_ms(failures: int) -> float:
    """Wait before the next attempt after `failures` failed runs in a row: 30 min doubling, capped at REFRESH_HOURS."""
    if failures <= 0:
        return REFRESH_HOURS * 3600_000
    return min(RETRY_BASE_MINUTES * 60_000 * 2 ** (failures - 1), REFRESH_HOURS * 3600_000)


def is_due(brand_id: str, stage: str = "performance_tracking") -> bool:
    last = last_run(brand_id, stage)
    if not last:
        return True
    if last["status"] == "running":
        return False
    if last["status"] == "failed":
        return ms_since(last["started_at"]) >= retry_delay_ms(failures_since_success(brand_id, stage))
    ok = last_successful_run(brand_id, stage)
    return not ok or ms_since(ok["started_at"]) >= REFRESH_HOURS * 3600_000


def tick() -> None:
    try:
        autopilot.enforce_deadlines()   # the 6-hour rule: approve and save hidden drafts nobody approved in time
        calendar_plan.run_due()
    except Exception:  # noqa: BLE001 — the refresh below must still run
        log.exception("Content calendar run failed")
    for b in BRAND_IDS:
        if is_paused(b) or not is_due(b):
            continue
        try:
            run_stage("performance_tracking", b, None, "scheduler")
        except Exception as e:  # noqa: BLE001 — recorded on the run and integration status
            log.warning("Scheduled refresh for %s could not start: %s", b, getattr(e, "message", None) or e)


def start_scheduler() -> None:
    global _started
    if _started:
        return
    _started = True

    def loop() -> None:
        time.sleep(5)
        while True:
            try:
                tick()
            except Exception:  # noqa: BLE001
                log.exception("scheduler tick failed")
            time.sleep(EVERY_SECONDS)

    threading.Thread(target=loop, name="blog-ops-scheduler", daemon=True).start()
