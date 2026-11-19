"""Background refresh: calls ops.refresh_from_shopify_orders() every SHIPPING_REFRESH_MINUTES (default 15).

* Runs in one daemon thread per process, never in a request, so no page waits for it.
* The database itself refuses two refreshes at the same moment (unique lock on running sync_runs rows).
* Any error is logged and recorded as a failed run; the thread keeps going and the SEO module is unaffected.
"""
from __future__ import annotations

import logging
import threading

from .config import shipping_config
from .supabase import SupabaseError

log = logging.getLogger("flowmerce.shipping")
_stop = threading.Event()
_thread: threading.Thread | None = None


def _loop(minutes: int) -> None:
    from . import service
    if _stop.wait(20):              # let the server finish starting first
        return
    while not _stop.is_set():
        try:
            res = service.refresh("job:shipping_refresh")
            log.info("shipping refresh ok: %s", res.get("result"))
            from . import board
            board.snapshot(force=True)  # reload the Shipping page's data here, so no page waits for it
            board.warm()                # and build the page's figures from it
        except SupabaseError as e:
            log.warning("shipping refresh failed (%s): %s", e.state, e.message)
        except Exception:           # never let the thread die
            log.exception("shipping refresh crashed")
        if _stop.wait(minutes * 60):
            return


def start_refresher() -> bool:
    global _thread
    cfg = shipping_config()
    if not cfg.configured or cfg.refresh_minutes <= 0 or (_thread and _thread.is_alive()):
        return False
    _stop.clear()
    _thread = threading.Thread(target=_loop, args=(cfg.refresh_minutes,), name="shipping-refresh", daemon=True)
    _thread.start()
    return True


def stop_refresher() -> None:
    _stop.set()
