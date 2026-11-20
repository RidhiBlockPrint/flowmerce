"""Background job: every CRO_SYNC_MINUTES (default 15) copy new Shopify orders into schema `cro`,
reload the page snapshot, then check the alarms of each store. At start-up it first loads both
stores' snapshots and timezones, so the first visit to Home or the CRO page does not wait for them.

* One daemon thread per process, never inside a request.
* Two processes cannot sync one store at once (database lock) nor open duplicate alerts (unique
  indexes).
* Any error is logged; the thread keeps going and SEO and Shipping are unaffected.
"""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime
from typing import Any

from ..shipping.config import shipping_config
from ..shipping.supabase import SupabaseError
from . import alarms, data, service, sync
from .config import STORE_BRAND, cro_config

log = logging.getLogger(__name__)
_stop = threading.Event()
_thread: threading.Thread | None = None
last_run: dict[str, Any] = {"state": "not_run_yet"}


def run_once() -> dict[str, Any]:
    """One sync + alarm round for every store. Never raises."""
    global last_run
    out: dict[str, Any] = {"at": datetime.now(UTC).isoformat(), "stores": {}}
    for store, brand in STORE_BRAND.items():
        try:
            res = sync.sync_store(store)
            if res["state"] == "ok":
                data.snapshot(store, force=True)
            res["alarms"] = alarms.check_store(store, service.today_for(store))
        except SupabaseError as e:
            res = {"store": store, "state": "failed", "error": e.message[:300]}
        except Exception as e:  # noqa: BLE001 - never let the thread die
            log.exception("CRO round for %s crashed", brand)
            res = {"store": store, "state": "failed", "error": str(e)[:300]}
        out["stores"][store] = res
    last_run = out
    return out


def warm() -> None:
    """Load every store's order snapshot (at the same time), then the Home summary, which caches
    each store's timezone and yesterday's conversion figures. Never raises."""
    data.warm(list(STORE_BRAND))
    try:
        service.home(None)
    except Exception:  # noqa: BLE001 - the first page visit will try again
        log.warning("CRO: could not prepare the Home summary at start-up", exc_info=True)


def _loop(minutes: int) -> None:
    warm()
    if _stop.wait(30):  # let the server (and Shipping's first refresh) start first
        return
    while not _stop.is_set():
        res = run_once()
        log.info("CRO round: %s", {s: r.get("state") for s, r in res["stores"].items()})
        if _stop.wait(minutes * 60):
            return


def enabled() -> bool:
    """Whether this process may run the job: SCHEDULER is not false (the switch the smoke test and
    other short-lived runs use), CRO_SYNC_MINUTES > 0 and Supabase is configured."""
    from ..seo.config import config

    return bool(config.scheduler) and cro_config().sync_minutes > 0 and shipping_config().configured


def start() -> bool:
    """Start the background job when enabled() and it is not already running."""
    global _thread
    minutes = cro_config().sync_minutes
    if not enabled() or (_thread and _thread.is_alive()):
        return False
    _stop.clear()
    _thread = threading.Thread(target=_loop, args=(minutes,), name="cro-sync", daemon=True)
    _thread.start()
    return True


def stop() -> None:
    """Ask the background job to stop."""
    _stop.set()
