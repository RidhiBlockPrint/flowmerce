"""Copy one brand's Meta ad account into schema `ads` (read-only toward Meta).

One run: take the account's lock, read its details and sign-in expiry, read campaigns, ad sets and
ads (noting budget changes), then the daily figures per ad:
  * the first run loads FIRST_LOAD_DAYS days;
  * a full run (every FULL_EVERY_HOURS hours) re-reads FULL_RELOAD_DAYS days, because Meta keeps
    adding late purchases to recent days, and refreshes each ad's lifetime totals;
  * any other run re-reads the last QUICK_RELOAD_DAYS days.
Days are read 7 at a time, oldest first, and each span replaces the stored rows in one transaction,
so a failed run leaves complete days behind. Two processes never sync one account at once (database
lock).
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from ..shipping.supabase import SupabaseClient, SupabaseError
from . import data
from .config import (
    FIRST_LOAD_DAYS,
    FULL_EVERY_HOURS,
    FULL_RELOAD_DAYS,
    QUICK_RELOAD_DAYS,
    MetaAccount,
    ads_config,
    meta_account,
)
from .meta import MetaClient, MetaError, ad_copy, ad_row, minor_to_major

log = logging.getLogger(__name__)
SPAN_DAYS = 7


def account_today(tz: str, now: datetime | None = None) -> date:
    """Today in the ad account's time zone."""
    try:
        zone = ZoneInfo(tz)
    except Exception:  # noqa: BLE001 - an unknown zone name: fall back to UTC rather than fail the sync
        zone = ZoneInfo("UTC")
    return (now or datetime.now(UTC)).astimezone(zone).date()


def plan_days(
    today: date, first_day: date | None, last_full: datetime | None, now: datetime
) -> tuple[date, bool]:
    """The first day to (re-)read and whether this is a full run. Pure, so the rules are easy to
    test."""
    if first_day is None:
        return today - timedelta(days=FIRST_LOAD_DAYS - 1), True
    if last_full is None or now - last_full >= timedelta(hours=FULL_EVERY_HOURS):
        return today - timedelta(days=FULL_RELOAD_DAYS - 1), True
    return today - timedelta(days=QUICK_RELOAD_DAYS - 1), False


def spans(since: date, until: date, size: int = SPAN_DAYS) -> list[tuple[date, date]]:
    """since..until cut into spans of `size` days, oldest first."""
    out = []
    d = since
    while d <= until:
        end = min(until, d + timedelta(days=size - 1))
        out.append((d, end))
        d = end + timedelta(days=1)
    return out


def campaign_rows(
    key: str,
    raw: list[dict[str, Any]],
    stored: dict[str, dict[str, Any]],
    changes: dict[str, datetime],
    now: datetime,
) -> list[dict[str, Any]]:
    """Meta campaigns as ads.campaigns rows. budget_changed_at: the newest of Meta's activity log, a
    budget that differs from the stored one (seen now), and what was stored before."""
    out = []
    for c in raw:
        cid = str(c["id"])
        budget = minor_to_major(c.get("daily_budget"))
        old = stored.get(cid) or {}
        times: list[datetime] = []
        if old.get("budget_changed_at"):
            times.append(datetime.fromisoformat(str(old["budget_changed_at"])))
        if cid in changes:
            times.append(changes[cid])
        if (
            old
            and old.get("daily_budget") is not None
            and budget is not None
            and abs(float(old["daily_budget"]) - budget) >= 0.01
        ):
            times.append(now)
        out.append(
            {
                "id": cid,
                "account_key": key,
                "name": str(c.get("name") or ""),
                "objective": c.get("objective"),
                "status": str(c.get("effective_status") or ""),
                "daily_budget": budget,
                "lifetime_budget": minor_to_major(c.get("lifetime_budget")),
                "bid_strategy": c.get("bid_strategy"),
                "created_time": c.get("created_time"),
                "budget_changed_at": max(times).isoformat() if times else None,
                "synced_at": now.isoformat(),
            }
        )
    return out


def sync_brand(
    brand: str,
    client: SupabaseClient | None = None,
    meta: MetaClient | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Copy the brand's Meta account. Returns {state: ok | locked | not_configured | failed, ...}.
    Raises only SupabaseError (the database cannot be reached); Meta problems are recorded on the
    account and returned."""
    acc = meta_account(brand)
    if acc is None:
        return {"brand": brand, "state": "not_configured"}
    own = meta is None
    meta = meta or MetaClient(acc, timeout=ads_config().timeout)
    try:
        return _sync(acc, meta, client, now or datetime.now(UTC))
    finally:
        if own:
            meta.close()


def _sync(
    acc: MetaAccount, meta: MetaClient, c: SupabaseClient | None, now: datetime
) -> dict[str, Any]:
    key = acc.key
    try:
        info = meta.account_info()
        token = meta.token_info()
    except MetaError as e:
        _record_failure(acc, e, c)
        return {"brand": acc.brand, "state": "failed", "error": e.message, "reason": e.state}
    tz = str(info.get("timezone_name") or "UTC")
    data.save_account(
        {
            "key": key,
            "brand": acc.brand,
            "platform": "meta",
            "external_id": acc.account_id,
            "name": str(info.get("name") or ""),
            "currency": str(info.get("currency") or "USD"),
            "timezone": tz,
            "account_status": info.get("account_status"),
            "token_expires_at": token.expires_at.isoformat() if token.expires_at else None,
            "updated_at": now.isoformat(),
        },
        c,
    )
    lock = data.begin_sync(key, c)
    if lock is None:
        return {"brand": acc.brand, "state": "locked"}
    first_day = date.fromisoformat(str(lock["loaded_from"])) if lock.get("loaded_from") else None
    last_full = datetime.fromisoformat(str(lock["full_at"])) if lock.get("full_at") else None
    today = account_today(tz, now)
    since, full = plan_days(today, first_day, last_full, now)
    rows_written = 0
    saved_to: date | None = None  # last day of the newest span saved in this run
    try:
        stored = data.budgets(key, c)
        changes = meta.budget_changes(now - timedelta(days=4))
        data.save_structure(
            "campaigns", campaign_rows(key, meta.campaigns(), stored, changes, now), c
        )
        data.save_structure(
            "ad_sets",
            [
                {
                    "id": str(s["id"]),
                    "account_key": key,
                    "campaign_id": str(s.get("campaign_id") or ""),
                    "name": str(s.get("name") or ""),
                    "status": str(s.get("effective_status") or ""),
                    "daily_budget": minor_to_major(s.get("daily_budget")),
                    "optimization_goal": s.get("optimization_goal"),
                    "synced_at": now.isoformat(),
                }
                for s in meta.ad_sets()
            ],
            c,
        )
        data.save_ads(
            [{**ad_row(key, a), **ad_copy(a), "synced_at": now.isoformat()} for a in meta.ads()],
            c,
        )
        for a, b in spans(since, today):
            rows_written += data.replace_daily(key, a, b, meta.daily(a, b), c)
            saved_to = b
        if full:
            data.save_lifetime(key, meta.lifetime(), now, c)
    except MetaError as e:
        # A first load that stopped part-way still counts when the days it saved reach into the
        # last FULL_RELOAD_DAYS: the next run is a full one and re-reads those days, closing the
        # gap, instead of starting the whole first load again.
        if first_day is None and saved_to and saved_to >= today - timedelta(days=FULL_RELOAD_DAYS):
            data.mark_loaded_from(key, since, c)
        data.end_sync(key, False, e.message, False, None, c)
        data.forget(key)
        log.warning("Ads: Meta sync of %s stopped: %s", acc.brand, e.message)
        return {
            "brand": acc.brand,
            "state": "failed",
            "error": e.message,
            "reason": e.state,
            "rows": rows_written,
        }
    except SupabaseError:
        data.end_sync(key, False, "The database could not be written.", False, None, c)
        raise
    data.end_sync(key, True, None, full, since if first_day is None else None, c)
    data.forget(key)
    return {
        "brand": acc.brand,
        "state": "ok",
        "from": since.isoformat(),
        "to": today.isoformat(),
        "full": full,
        "rows": rows_written,
    }


def _record_failure(acc: MetaAccount, e: MetaError, c: SupabaseClient | None) -> None:
    """A run that could not even read the account: say so on the account row (when it exists)."""
    try:
        if data.account(acc.key, c) is None:
            return
        lock = data.begin_sync(acc.key, c)
        if lock is not None:
            data.end_sync(acc.key, False, e.message, False, None, c)
    except SupabaseError:
        log.warning("Ads: could not record the failed Meta sync of %s", acc.brand)
    log.warning("Ads: Meta sync of %s failed: %s", acc.brand, e.message)
