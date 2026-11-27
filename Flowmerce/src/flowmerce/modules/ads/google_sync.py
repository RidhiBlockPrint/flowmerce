"""Copy one brand's Google Ads account into schema `ads` (read-only toward Google).

The same timing and lock as the Meta sync (sync.py): the first run loads FIRST_LOAD_DAYS days, a
full run every FULL_EVERY_HOURS hours re-reads FULL_RELOAD_DAYS days (Google keeps adding late
purchases to recent days), any other run re-reads QUICK_RELOAD_DAYS days. Days are read in spans of
SPAN_DAYS, oldest first; each kind of figure (campaign, group, search term, keyword, product) of a
span is replaced in one transaction, so a failed run leaves complete days behind.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any

from ..shipping.supabase import SupabaseClient, SupabaseError
from . import data
from .config import FULL_RELOAD_DAYS, GoogleAccount, ads_config, google_account
from .google_ads import KINDS, GoogleAdsClient, GoogleAdsError
from .sync import account_today, plan_days, spans

log = logging.getLogger(__name__)
SPAN_DAYS = 30  # Google answers a month of one report in about a second


def sync_google(
    brand: str,
    client: SupabaseClient | None = None,
    gads: GoogleAdsClient | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Copy the brand's Google Ads account. Returns {state: ok | locked | not_configured | waiting |
    failed, ...} (waiting: the Google tables are not in the database yet). Raises only
    SupabaseError; Google problems are recorded on the account and returned."""
    acc = google_account(brand)
    if acc is None:
        return {"brand": brand, "platform": "google", "state": "not_configured"}
    own = gads is None
    gads = gads or GoogleAdsClient(acc, timeout=ads_config().timeout)
    try:
        return _sync(acc, gads, client, now or datetime.now(UTC))
    finally:
        if own:
            gads.close()


def _failed(acc: GoogleAccount, e: GoogleAdsError, rows: int = 0) -> dict[str, Any]:
    log.warning("Ads: Google sync of %s stopped: %s", acc.brand, e.message)
    return {
        "brand": acc.brand,
        "platform": "google",
        "state": "failed",
        "error": e.message,
        "reason": e.state,
        "rows": rows,
    }


def _sync(
    acc: GoogleAccount, gads: GoogleAdsClient, c: SupabaseClient | None, now: datetime
) -> dict[str, Any]:
    key = acc.key
    try:
        info = gads.account_info()
    except GoogleAdsError as e:
        _record_failure(acc, e, c)
        return _failed(acc, e)
    data.save_account(
        {
            "key": key,
            "brand": acc.brand,
            "platform": "google",
            "external_id": acc.customer_id,
            "name": info["name"],
            "currency": info["currency"],
            "timezone": info["timezone"],
            "updated_at": now.isoformat(),
        },
        c,
    )
    lock = data.begin_sync(key, c)
    if lock is None:
        return {"brand": acc.brand, "platform": "google", "state": "locked"}
    first_day = date.fromisoformat(str(lock["loaded_from"])) if lock.get("loaded_from") else None
    last_full = datetime.fromisoformat(str(lock["full_at"])) if lock.get("full_at") else None
    today = account_today(info["timezone"], now)
    since, full = plan_days(today, first_day, last_full, now)
    rows_written = 0
    saved_to: date | None = None
    try:
        data.save_g_campaigns(
            [{**x, "account_key": key, "synced_at": now.isoformat()} for x in gads.campaigns()], c
        )
        for a, b in spans(since, today, SPAN_DAYS):
            for kind in KINDS:
                rows_written += data.g_replace(key, kind, a, b, gads.daily(kind, a, b), c)
            saved_to = b
    except GoogleAdsError as e:
        if first_day is None and saved_to and saved_to >= today - timedelta(days=FULL_RELOAD_DAYS):
            data.mark_loaded_from(key, since, c)
        data.end_sync(key, False, e.message, False, None, c)
        data.forget(key)
        return _failed(acc, e, rows_written)
    except SupabaseError as e:
        if e.state == "schema_missing":
            # 117_ads_google.sql has not been run yet: say so on the account and wait (not a
            # failure the job should retry every few minutes).
            msg = "The Google tables are missing: run db/central/117_ads_google.sql in Supabase."
            data.end_sync(key, False, msg, False, None, c)
            data.forget(key)
            return {"brand": acc.brand, "platform": "google", "state": "waiting", "error": msg}
        data.end_sync(key, False, "The database could not be written.", False, None, c)
        raise
    data.end_sync(key, True, None, full, since if first_day is None else None, c)
    data.forget(key)
    return {
        "brand": acc.brand,
        "platform": "google",
        "state": "ok",
        "from": since.isoformat(),
        "to": today.isoformat(),
        "full": full,
        "rows": rows_written,
    }


def _record_failure(acc: GoogleAccount, e: GoogleAdsError, c: SupabaseClient | None) -> None:
    """A run that could not even read the account: say so on the account row (when it exists)."""
    try:
        if data.account(acc.key, c) is None:
            return
        lock = data.begin_sync(acc.key, c)
        if lock is not None:
            data.end_sync(acc.key, False, e.message, False, None, c)
    except SupabaseError:
        log.warning("Ads: could not record the failed Google sync of %s", acc.brand)
