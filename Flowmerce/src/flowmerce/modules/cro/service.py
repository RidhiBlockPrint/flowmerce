"""What each CRO page asks for, put together from the order snapshot, ShopifyQL and the cro tables.

Every function takes a brand id ('ridhi' or 'cpc'). Input checks live here so the routes stay thin;
a bad value raises InputError with a message the page can show.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..shipping.supabase import SupabaseError
from . import (
    alarms,
    conversion,
    data,
    experiments,
    landing,
    metrics,
    payments,
    recommendations,
    shopify,
    traffic,
)
from . import customers as customers_mod
from . import products as products_mod
from . import site_health as site_health_mod
from .config import (
    MIN_ORDERS_FOR_COMPARISON,
    MIN_SESSIONS_FOR_COMPARISON,
    free_shipping_threshold,
    store_for,
)
from .metrics import SalesReport
from .periods import (
    Plan,
    RangeError,
    days_window,
    metric_block,
    parse_day,
    plan,
    range_plan,
)
from .shopify import AnalyticsError

log = logging.getLogger(__name__)
# Reads one answer needs are made at the same time. Tasks here may use data's own pools, never
# this one, so nothing waits on a task queued behind itself. A page asks ~17 answers at once, so the
# pool is large enough that one answer's reads never queue behind another's.
_pool = ThreadPoolExecutor(max_workers=24, thread_name_prefix="cro-read")
# Shopify reads started early so a later call finds them cached or in flight (conversion.run shares
# one read between callers). Tasks here never use _pool.
_prefetch_pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="cro-prefetch")


def _prefetch(fn: Callable[[], Any]) -> None:
    """Start a Shopify read in the background; its errors surface when the real call repeats it."""

    def quiet() -> None:
        try:
            fn()
        except Exception:  # noqa: BLE001, S110 - the real call raises and explains it
            pass

    _prefetch_pool.submit(quiet)


def _together(*calls: Callable[[], Any]) -> list[Any]:
    """Run the calls at the same time; results in order (the first error is raised)."""
    futures = [_pool.submit(f) for f in calls]
    return [f.result() for f in futures]


# Page reads, kept for data.READ_CACHE_SECONDS and forgotten on every write (see data.recent).
def _sync_state(store: str) -> dict[str, Any] | None:
    return data.recent(("sync_state", store), lambda: data.sync_state(store))


def _alarms_enabled(store: str) -> bool:
    return data.recent(("alarms_enabled", store), lambda: data.alarms_enabled(store))


def _rules(store: str) -> list[dict[str, Any]]:
    return data.recent(("alarm_rules", store), lambda: data.alarm_rules(store))


def _alerts(store: str, limit: int) -> list[dict[str, Any]]:
    return data.recent(("alerts", store, str(limit)), lambda: data.alerts(store, limit))


AREAS = ("theme", "app", "price", "promo", "ad", "other")
KINDS = ("cvr_drop", "no_product_orders")


class InputError(ValueError):
    """A request value that cannot be used; the message says why."""


def store_timezone(store: str) -> ZoneInfo:
    """The store's timezone as Shopify reports it.

    When Shopify cannot be asked: ops.stores.timezone, then UTC (both said in the logs, because
    local days then may not match Shopify's)."""
    try:
        return ZoneInfo(shopify.shop_info(store)["timezone"])
    except Exception:  # noqa: BLE001 - a missing timezone must not break the page
        log.warning("CRO: could not read the timezone of %s from Shopify; using ops.stores", store)
    try:
        from ..shipping.supabase import client

        rows = (
            client().select("stores", [("select", "timezone"), ("id", f"eq.{store}")], limit=1).rows
        )
        return ZoneInfo(str(rows[0]["timezone"]))
    except SupabaseError, IndexError, KeyError, ZoneInfoNotFoundError:
        log.warning("CRO: no timezone for %s in ops.stores either; using UTC", store)
        return ZoneInfo("UTC")


def today_for(store: str) -> date:
    """The store's current local date."""
    return datetime.now(UTC).astimezone(store_timezone(store)).date()


def _ctx(brand: str) -> tuple[str, ZoneInfo, datetime]:
    try:
        store = store_for(brand)
    except ValueError as e:
        raise InputError(str(e)) from None
    return store, store_timezone(store), datetime.now(UTC)


def _today(tz: ZoneInfo, now: datetime) -> date:
    return now.astimezone(tz).date()


def order_data_state(row: dict[str, Any] | None) -> dict[str, Any]:
    """How complete CRO's order copy is, from the store's cro.sync_state row (pure).

    The first load is complete once a sync has finished (last_run_at) and saved a cursor. Until then
    the order figures only cover part of the period, and the pages say so."""
    row = row or {}
    complete = bool(row.get("cursor")) and bool(row.get("last_run_at"))
    if complete and row.get("last_status") == "failed":
        note = "The last order sync failed; figures may be behind: " + str(
            row.get("last_error") or ""
        )
    elif complete:
        note = ""
    elif row.get("running_since"):
        note = "The first order load is still running; order figures are incomplete."
    else:
        note = "The first order load has not finished yet; order figures are incomplete."
    return {
        "first_load_complete": complete,
        "running": bool(row.get("running_since")),
        "last_status": row.get("last_status"),
        "last_run_at": row.get("last_run_at"),
        "synced_up_to": row.get("cursor"),
        "note": note[:400],
    }


def _order_data(store: str, state: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        **order_data_state(state if state is not None else _sync_state(store)),
        "available_from": data.first_order_day(store),
    }


# ------------------------------------------------------------------------------------------
# periods
@dataclass(frozen=True)
class RangeQuery:
    """What the page asked for: a calendar range (`frm`/`to`, YYYY-MM-DD, store-local days) with a
    comparison, or one of the named periods when no range is given."""

    frm: str | None = None
    to: str | None = None
    compare: str = ""
    period: str = "yesterday"
    last: int | None = None  # "the last N days" when no range is given
    last_includes_today: bool = True


def _plan(brand: str, rq: RangeQuery) -> tuple[str, ZoneInfo, datetime, Plan]:
    store, tz, now = _ctx(brand)
    try:
        start, end = parse_day(rq.frm), parse_day(rq.to)
        if start or end:
            first = start or end
            last = end or start
            assert first is not None and last is not None  # noqa: S101 - narrowed above
            p = range_plan(first, last, rq.compare, tz, now)
        elif rq.last:
            today = _today(tz, now)
            last = today if rq.last_includes_today else today - timedelta(days=1)
            p = range_plan(last - timedelta(days=rq.last - 1), last, rq.compare, tz, now)
        else:
            p = plan(rq.period, rq.compare or "4week_avg", tz, now)
    except RangeError as e:
        raise InputError(str(e)) from None
    return store, tz, now, p


def _orders_for(store: str, p: Plan) -> data.Snapshot:
    """Orders covering the plan's current and comparison windows."""
    earliest = min([p.current.start, *(w.start for w in p.baselines)])
    return data.snapshot_since(store, earliest)


def _range_info(p: Plan) -> dict[str, Any]:
    days = p.current_days
    return {
        "period": p.period,
        "period_label": p.label,
        "compare": p.compare,
        "baseline_label": p.baseline_label,
        "is_partial": p.is_partial,
        "from": days[0].isoformat() if days else None,
        "to": days[-1].isoformat() if days else None,
    }


def _sales_report(store: str, p: Plan, today: date, *, trend: bool = False) -> SalesReport | None:
    """Shopify's own sales figures (ShopifyQL `sales`) for the plan's days, or None when the order
    copy must be used instead: Shopify did not answer, or (for KPI cards and the breakdown) the
    plan reaches today, whose comparison stops at the same time of day, which a daily report
    cannot do. For the trend (`trend=True`) the complete days still use the report: today and the
    comparison days lined up with it stay on the order copy."""
    if p.is_partial and not trend:
        return None
    days = [d for d in (*p.current_days, *(d for ds in p.baseline_days for d in ds)) if d < today]
    if not days:
        return None
    try:
        report = conversion.sales_daily(store, min(days), max(days))
    except Exception as e:  # noqa: BLE001 - any failure: the order copy is shown instead
        log.warning("CRO sales report unavailable for %s: %s", store, getattr(e, "message", e))
        return None
    if p.is_partial:
        for ds in p.baseline_days:
            report.pop(ds[-1].isoformat(), None)  # cut at today's time of day: keep the order copy
    return report


# ------------------------------------------------------------------------------------------
# overview
def _cvr_block(store: str, p: Plan, orders: float, today: date) -> dict[str, Any]:
    """Conversion rate for the plan's complete days with its baseline, from ShopifyQL. Today is
    left out (Shopify reports sessions for complete days only)."""
    all_days = [*p.current_days, *(d for days in p.baseline_days for d in days)]
    rows = conversion.daily_between(store, min(all_days), max(all_days), today)
    by_day = {r["date"]: r for r in rows}

    def period_cvr(days: tuple[date, ...]) -> tuple[float | None, int]:
        picked = [by_day[d.isoformat()] for d in days if d.isoformat() in by_day]
        sessions = sum(r["sessions"] for r in picked)
        done = sum(r["completed_checkout"] for r in picked)
        return (round(done / sessions * 100, 2) if sessions else None), sessions

    value, sessions = period_cvr(p.current_days)
    bases = [(v, s) for v, s in map(period_cvr, p.baseline_days) if v is not None and s]
    base_values = [v for v, _ in bases]
    baseline = round(sum(base_values) / len(base_values), 2) if base_values else None
    base_sessions = round(sum(s for _, s in bases) / len(bases), 1) if bases else None
    block = metric_block(value, baseline, sessions < MIN_SESSIONS_FOR_COMPARISON, p.baseline_label)
    note = " (today left out)" if p.is_partial and len(p.current_days) > 1 else ""
    return {
        **block,
        "sessions": sessions or None,
        "baseline_sessions": base_sessions,
        "base_label": f"{int(orders)} orders from {sessions:,} sessions{note}"
        if sessions
        else "sessions pending",
    }


def _visit_blocks(kpis: dict[str, Any], p: Plan) -> None:
    """Add visits and revenue per visit to the KPI cards when Shopify reported sessions. Revenue per
    visit is only given for complete days: a range that reaches today has today's revenue but not
    today's visits."""
    cvr = kpis.get("conversion_rate") or {}
    sessions, base = cvr.get("sessions"), cvr.get("baseline_sessions")
    if not sessions:
        return
    early = sessions < MIN_SESSIONS_FOR_COMPARISON
    kpis["sessions"] = metric_block(sessions, base, early, p.baseline_label, 1)
    if p.is_partial:
        return
    rev = kpis["revenue"]
    value = round(float(rev["value"] or 0) / sessions, 2)
    before = (
        round(float(rev["baseline_value"]) / base, 2)
        if base and rev.get("baseline_value") is not None
        else None
    )
    kpis["revenue_per_session"] = metric_block(value, before, early, p.baseline_label)


def overview(brand: str, rq: RangeQuery) -> dict[str, Any]:
    """KPI cards: orders, revenue, AOV and conversion rate for the chosen range, each against its
    comparison."""
    store, tz, now, p = _plan(brand, rq)
    today = _today(tz, now)
    if not (p.is_partial and len(p.current_days) == 1):
        days = [*p.current_days, *(d for ds in p.baseline_days for d in ds)]
        _prefetch(lambda: conversion.daily_between(store, min(days), max(days), today))
    snap = _orders_for(store, p)
    report = _sales_report(store, p, today)
    kpis: dict[str, Any] = metrics.order_kpis(snap, p, report)
    cvr_error = None
    if p.is_partial and len(p.current_days) == 1:
        kpis["conversion_rate"] = {
            **metric_block(None, None, True, p.baseline_label),
            "sessions": None,
            "base_label": "Shopify reports sessions for complete days only",
        }
    else:
        try:
            kpis["conversion_rate"] = _cvr_block(
                store, p, float(kpis["orders"]["value"] or 0), _today(tz, now)
            )
        except AnalyticsError as e:
            cvr_error = {"state": e.state, "message": e.message}
            kpis["conversion_rate"] = {
                **metric_block(None, None, True, p.baseline_label),
                "sessions": None,
                "base_label": "not available",
            }
    _visit_blocks(kpis, p)
    last = metrics.last_order_at(snap)
    return {
        "brand": brand,
        **_range_info(p),
        "timezone": str(tz),
        "as_of": now.astimezone(tz).isoformat(),
        "metrics": kpis,
        "health": {"last_order_at": last.isoformat() if last else None},
        "revenue_source": "shopify_sales" if report is not None else "orders",
        "cvr_error": cvr_error,
        "data_since": snap.since.isoformat(),
        "order_data": _order_data(store),
    }


def sales_breakdown(brand: str, rq: RangeQuery) -> dict[str, Any]:
    """Gross to total sales for the chosen range."""
    store, tz, now, p = _plan(brand, rq)
    report = _sales_report(store, p, _today(tz, now))
    return {
        "brand": brand,
        **metrics.sales_breakdown(_orders_for(store, p), p, report),
        **_range_info(p),
        "order_data": _order_data(store),
    }


def sales_trend(brand: str, rq: RangeQuery) -> dict[str, Any]:
    """Daily orders, total and net sales of the range and of its comparison period."""
    store, tz, now, p = _plan(brand, rq)
    report = _sales_report(store, p, _today(tz, now), trend=True)
    return {
        "brand": brand,
        **metrics.range_trend(_orders_for(store, p), tz, p, report),
        **_range_info(p),
        "order_data": _order_data(store),
    }


def order_health(brand: str, rq: RangeQuery) -> dict[str, Any]:
    """Paid / refunded / cancelled / pending orders placed in the range."""
    store, _, _, p = _plan(brand, rq)
    return {
        "brand": brand,
        **metrics.order_health_in(_orders_for(store, p), p.current),
        **_range_info(p),
        "order_data": _order_data(store),
    }


def products(brand: str, rq: RangeQuery) -> dict[str, Any]:
    """Every product sold in the range with its performance group."""
    store, _, _, p = _plan(brand, rq)
    return {
        "brand": brand,
        **metrics.products_in(_orders_for(store, p), p.current),
        **_range_info(p),
        "days": len(p.current_days),
        "order_data": _order_data(store),
    }


# ------------------------------------------------------------------------------------------
# conversion
def conversion_trend(brand: str, rq: RangeQuery) -> dict[str, Any]:
    """Daily funnel of the range's complete days, the range's totals and its comparison's totals."""
    store, tz, now, p = _plan(brand, rq)
    today = _today(tz, now)
    days = p.current_days
    # The four Shopify reads below go out together (they used to run one after another).
    complete_last = min(days[-1], today - timedelta(days=1))
    if p.baseline_days:
        b0, b1 = p.baseline_days[0][0], p.baseline_days[0][-1]
        _prefetch(lambda: conversion.daily_between(store, b0, b1, today))
        if complete_last >= days[0]:
            _prefetch(
                lambda: conversion.funnel_by_device(store, b0, min(b1, today - timedelta(days=1)))
            )
    if complete_last >= days[0]:
        _prefetch(lambda: conversion.funnel_by_device(store, days[0], complete_last))
    rows = conversion.daily_between(store, days[0], days[-1], today)
    base_rows = (
        conversion.daily_between(store, p.baseline_days[0][0], p.baseline_days[0][-1], today)
        if p.baseline_days
        else []
    )
    total = conversion.totals(rows)
    base = conversion.totals(base_rows) if base_rows else None

    def device_split(r: list[dict[str, Any]]) -> dict[str, Any] | None:
        if not r:
            return None
        first, last = date.fromisoformat(r[0]["date"]), date.fromisoformat(r[-1]["date"])
        return conversion.funnel_by_device(store, first, last)

    by_device = device_split(rows)
    base_by_device = device_split(base_rows) if rows else None
    change = None
    if base and base["conversion_rate"] and total["conversion_rate"] is not None:
        change = round(
            (total["conversion_rate"] - base["conversion_rate"]) / base["conversion_rate"] * 100, 2
        )
    return {
        "brand": brand,
        **_range_info(p),
        "days": len(rows),
        "trend": rows,
        "baseline_trend": base_rows,
        "total": total,
        "baseline_total": base,
        "conversion_change_pct": change,
        "funnel": by_device,
        "baseline_funnel": base_by_device,
        "today_left_out": p.is_partial,
    }


def funnel(brand: str) -> dict[str, Any]:
    """Yesterday's funnel (the most recent complete day)."""
    store, tz, now = _ctx(brand)
    rows = conversion.daily(store, _today(tz, now), 1)
    return {"brand": brand, **(rows[-1] if rows else conversion.funnel_row("", {}))}


def segments(brand: str, dimension: str, rq: RangeQuery) -> dict[str, Any]:
    """Device or channel split of the range against its comparison (complete days only)."""
    store, tz, now, p = _plan(brand, rq)
    cur, base = _windows(p, _today(tz, now))
    try:
        return {
            "brand": brand,
            **_range_info(p),
            **conversion.segments_between(store, dimension, cur, base),
        }
    except ValueError as e:
        raise InputError(str(e)) from None


# ------------------------------------------------------------------------------------------
# traffic, landing pages, site health, checkout extras
Days = tuple[date, date]
REC_DAYS = 28  # recommendations read the last 28 complete days


def _windows(p: Plan, today: date) -> tuple[Days, Days | None]:
    """The plan's days for Shopify session reports and its first comparison's, lined up. Today is
    left out (Shopify's figures for it are not complete) unless the range is only today."""
    last = min(p.current_days[-1], today - timedelta(days=1))
    if last < p.current_days[0]:
        last = p.current_days[0]  # a range of only today: Shopify's partial figures
    base = None
    if p.baseline_days:
        shift = p.current_days[0] - p.baseline_days[0][0]
        base = (p.baseline_days[0][0], last - shift)
    return (p.current_days[0], last), base


def _window_info(cur: Days, base: Days | None) -> dict[str, Any]:
    return {
        "window": {
            "from": cur[0].isoformat(),
            "to": cur[1].isoformat(),
            "base_from": base[0].isoformat() if base else None,
            "base_to": base[1].isoformat() if base else None,
        }
    }


def _session_report(
    brand: str, rq: RangeQuery, read: Callable[[str, Days, Days | None], dict[str, Any]]
) -> dict[str, Any]:
    store, tz, now, p = _plan(brand, rq)
    cur, base = _windows(p, _today(tz, now))
    return {"brand": brand, **_range_info(p), **_window_info(cur, base), **read(store, cur, base)}


def product_insights(brand: str, rq: RangeQuery) -> dict[str, Any]:
    """The Products tab: Shopify's sales and refunds per product, GA4 product views and the product
    groups, price bands and products bought together, for the range's complete days."""
    store, tz, now, p = _plan(brand, rq)
    cur, base = _windows(p, _today(tz, now))
    snap = _orders_for(store, p)
    return {
        "brand": brand,
        **_range_info(p),
        **_window_info(cur, base),
        **products_mod.insights(store, tz, cur, snap),
        "order_data": _order_data(store),
    }


def discount_codes(brand: str, rq: RangeQuery) -> dict[str, Any]:
    """Orders with vs without a discount code, and per code (Shopify), for the range."""
    return _session_report(brand, rq, products_mod.discount_codes)


def landing_pages(brand: str, rq: RangeQuery) -> dict[str, Any]:
    """Landing pages, page types and bounce by source and device for the range."""
    return _session_report(brand, rq, landing.landing_pages)


def landing_grids(brand: str, rq: RangeQuery) -> dict[str, Any]:
    """Top landing pages x traffic source and page types x device."""
    return _session_report(brand, rq, lambda store, cur, _base: landing.grids(store, cur))


def traffic_changes(brand: str, rq: RangeQuery) -> dict[str, Any]:
    """Device and channel changes against the comparison (the period just before when the range
    has none), with revenue per visit by channel and the top movers."""

    def read(store: str, cur: Days, base: Days | None) -> dict[str, Any]:
        n = cur[1] - cur[0] + timedelta(days=1)
        return traffic.where_changed(store, cur, base or (cur[0] - n, cur[1] - n))

    return _session_report(brand, rq, read)


def geo(brand: str, rq: RangeQuery) -> dict[str, Any]:
    """Conversion by country and US state."""
    return _session_report(brand, rq, traffic.geo)


def site_health(brand: str, rq: RangeQuery) -> dict[str, Any]:
    """Page speed and site search."""
    return _session_report(brand, rq, site_health_mod.site_health)


def overview_trends(brand: str, rq: RangeQuery) -> dict[str, Any]:
    """Average order value by day and sales by sales channel."""
    return _session_report(brand, rq, traffic.trends)


def free_shipping_amount(store: str) -> tuple[float | None, str | None]:
    """(amount, where it came from): the amount saved in CRO settings, else
    CRO_FREE_SHIPPING_<store> in .env, else (None, None)."""
    saved = data.recent(("free_shipping", store), lambda: data.free_shipping(store))
    if saved:
        return saved, "settings"
    env = free_shipping_threshold(store)
    return (env, "env") if env else (None, None)


def checkout_extras(brand: str, rq: RangeQuery) -> dict[str, Any]:
    """Payment methods and success rate (Shopify), and order values and items per order (order
    copy). A Shopify failure leaves `payments` None with its reason; the order figures still
    show."""
    store, tz, now, p = _plan(brand, rq)
    cur, base = _windows(p, _today(tz, now))
    pay: dict[str, Any] | None = None
    pay_error = None
    try:
        pay = payments.payments(store, cur, base)
    except AnalyticsError as e:
        pay_error = {"state": e.state, "message": e.message}
    snap = _orders_for(store, p)
    threshold, source = free_shipping_amount(store)
    return {
        "brand": brand,
        **_range_info(p),
        **_window_info(cur, base),
        "payments": pay,
        "payments_error": pay_error,
        "order_values": metrics.order_values(snap, p.current, threshold),
        "previous_order_values": (
            metrics.order_values(snap, p.baselines[0], threshold) if p.baselines else None
        ),
        "free_shipping_source": source,
        "order_data": _order_data(store),
    }


def buy_heatmap(brand: str, days: int) -> dict[str, Any]:
    """Conversion by weekday x hour over the last `days` complete days. When Shopify's hourly
    visits cannot be read, the order copy's orders by hour are shown instead (and say so)."""
    store, tz, now = _ctx(brand)
    last = _today(tz, now) - timedelta(days=1)
    first = last - timedelta(days=days - 1)
    info = {"brand": brand, "days": days, "from": first.isoformat(), "to": last.isoformat()}
    try:
        return {**info, **traffic.heatmap(store, first, last, tz), "source": "shopify_sessions"}
    except AnalyticsError as e:
        snap = data.snapshot(store)
        return {
            **info,
            **metrics.orders_by_hour(snap, tz, days_window(first, last, tz)),
            "source": "orders",
            "note": "Shopify's hourly visits could not be read, so this shows when orders were "
            f"placed instead of conversion rate ({e.state}).",
        }


# ------------------------------------------------------------------------------------------
# Home
def _home_store(brand: str) -> dict[str, Any]:
    store, tz, now = _ctx(brand)
    snap = data.snapshot(store)
    y = plan("yesterday", "4week_avg", tz, now)
    t = plan("today", "last_week", tz, now)

    def block(p: Plan) -> dict[str, Any]:
        cur = metrics.sales_stats(snap.orders, p.current)
        bases = [metrics.sales_stats(snap.orders, w) for w in p.baselines]
        base = metrics.average(bases, ("orders", "net"))
        early = cur["orders"] < MIN_ORDERS_FOR_COMPARISON
        return {
            "label": p.label,
            "orders": metric_block(cur["orders"], base["orders"], early, p.baseline_label, 1),
            "net_sales": metric_block(cur["net"], base["net"], early, p.baseline_label),
        }

    today = _today(tz, now)
    cvr: dict[str, Any] | None = None
    cvr_state = None
    try:
        rows = conversion.daily(store, today, 2)
        cmp = conversion.cvr_comparison(rows, today)
        cvr = {
            "value": cmp["yesterday_cvr"],
            "previous": cmp["previous_cvr"],
            "date": cmp["yesterday_date"],
        }
    except AnalyticsError as e:
        cvr_state = e.state
    days = tuple(today - timedelta(days=i) for i in range(14, 0, -1))
    return {
        "brand": brand,
        "state": "ok",
        "timezone": str(tz),
        "yesterday": block(y),
        "today": block(t),
        "conversion": cvr,
        "conversion_state": cvr_state,
        "trend": metrics.daily_series(snap, tz, days),
        "last_order_at": (lambda d: d.isoformat() if d else None)(metrics.last_order_at(snap)),
        "order_data": _order_data(store),
    }


def home(brand: str | None) -> dict[str, Any]:
    """Sales summary for Home: per store, yesterday and today so far (orders and net sales against
    their comparison), yesterday's conversion rate and the last 14 days. Never raises: a store that
    cannot be read says why, so Home keeps working."""
    brands = [brand] if brand else ["ridhi", "cpc"]
    for b in brands:
        try:
            store_for(b)
        except ValueError as e:  # a bad brand is the caller's error, not a store state
            raise InputError(str(e)) from None
    futures = [(b, _pool.submit(_home_store, b)) for b in brands]  # both stores at once
    out = []
    for b, f in futures:
        try:
            out.append(f.result())
        except SupabaseError as e:
            out.append({"brand": b, "state": e.state, "reason": e.message})
        except Exception as e:  # noqa: BLE001 - Home must never fail because of CRO
            log.exception("CRO home summary for %s failed", b)
            out.append({"brand": b, "state": "error", "reason": str(e)[:300]})
    return {"stores": out}


# ------------------------------------------------------------------------------------------
# recommendations
def recommendation_list(brand: str) -> dict[str, Any]:
    """Recommendations the current figures support, ranked by estimated impact, with the team's
    status. The impact-ranked checks read the last 28 complete days (landing pages, devices, traffic
    sources, payments) against the 28 before; the order-based checks read the order copy. Sources
    that cannot be read are listed in `skipped`."""
    store, tz, now = _ctx(brand)
    today = _today(tz, now)
    snap = data.snapshot(store)
    skipped: list[str] = []
    cvr = fun = None
    last = today - timedelta(days=1)
    cur: Days = (last - timedelta(days=REC_DAYS - 1), last)
    base: Days = (cur[0] - timedelta(days=REC_DAYS), cur[0] - timedelta(days=1))
    compare_label = f"{base[0]:%d %b} - {base[1]:%d %b}"

    def read(name: str, fn: Callable[[], Any]) -> Any:
        try:
            return fn()
        except AnalyticsError as e:
            skipped.append(f"{name} ({e.state})")
            return None

    def statuses_read() -> tuple[dict[str, dict[str, Any]], dict[str, Any] | None]:
        try:
            return data.recent(("rec_status", store), lambda: data.rec_statuses(store)), None
        except SupabaseError as e:
            return {}, {
                "state": e.state,
                "message": "Statuses cannot be saved yet: run db/central/114_cro_tracking.sql in "
                "Supabase."
                if e.state == "schema_missing"
                else e.message,
            }

    # Every read at once: Shopify's figures and the small Supabase reads (they used to run one after
    # another, about 0.4 s each).
    rows, land, pay, report, leaky, state, rules, (statuses, status_error) = _together(
        lambda: read("conversion rate and funnel", lambda: conversion.daily(store, today, 7)),
        lambda: read("landing pages", lambda: landing.landing_pages(store, cur, base)),
        lambda: read("payments", lambda: payments.payments(store, cur, base)),
        lambda: read("sales report", lambda: conversion.sales_daily(store, cur[0], cur[1])),
        lambda: products_mod.leaky_for(store, tz, cur, snap),
        lambda: _order_data(store),
        lambda: _rules(store),
        statuses_read,
    )
    if rows is not None:
        cvr = conversion.cvr_comparison(rows, today)
        fun = rows[-1] if rows else None
    orders = int(sum(d["orders"] for d in report.values())) if report else 0
    aov = (
        round(sum(d["gross"] - d["discounts"] for d in report.values()) / orders, 2)
        if report and orders
        else None
    )
    extra, store_cvr, visits = recommendations.impact_items(
        landing=land, payments=pay, aov=aov, compare_label=compare_label
    )
    extra += recommendations.leaky_items(leaky)
    if leaky["state"] != "ready":
        skipped.append(f"leaky products ({leaky['message']})")
    if not state["first_load_complete"]:
        # Partial orders would look like stalled or declining sales: order-based checks wait.
        skipped.append("order-based checks (the first order load has not finished)")
        recs = recommendations.build(
            product_alarms=[],
            cvr=cvr,
            funnel=fun,
            today_revenue=None,
            declines=[],
            health=None,
            extra=extra,
        )
    else:
        gap_status = []
        for r in rules:
            if r["kind"] == "no_product_orders" and r.get("is_active"):
                fig = alarms.gap_figures(r, snap, now)
                fig.pop("_last_placed", None)
                gap_status.append(
                    {
                        **fig,
                        "status": "alarm_active" if fig["status"] == "triggered" else fig["status"],
                    }
                )
        pacing = metrics.order_kpis(snap, plan("today", "last_week", tz, now))["revenue"]
        recs = recommendations.build(
            product_alarms=gap_status,
            cvr=cvr,
            funnel=fun,
            today_revenue=pacing,
            declines=metrics.declining_products(snap, tz, now),
            health=metrics.order_health(snap, now, 30),
            extra=extra,
        )
    for r in recs:
        saved = statuses.get(r["key"]) or {}
        r["status"] = saved.get("status") or "open"
        r["status_updated_at"] = saved.get("updated_at")
    open_recs = [r for r in recs if r["status"] not in ("done", "ignored")]
    return {
        "brand": brand,
        "window": {
            "from": cur[0].isoformat(),
            "to": cur[1].isoformat(),
            "base_from": base[0].isoformat(),
            "base_to": base[1].isoformat(),
        },
        "store_conversion_rate": store_cvr,
        "sessions": visits,
        "aov": aov,
        "orders": orders,
        "total_open_impact": round(sum(r["impact"] or 0 for r in open_recs), 2),
        "recommendations": recs,
        "statuses_available": status_error is None,
        "status_error": status_error,
        "skipped": skipped,
        "order_data": state,
    }


def set_rec_status(brand: str, body: dict[str, Any], by: str) -> dict[str, Any]:
    """Save the team's status for one recommendation key."""
    store, _, _ = _ctx(brand)
    key = str(body.get("key") or "").strip()
    status = str(body.get("status") or "")
    if not 1 <= len(key) <= 300:
        raise InputError("Give the recommendation's key.")
    if status not in recommendations.STATUSES:
        raise InputError(f"status must be one of: {', '.join(recommendations.STATUSES)}.")
    data.set_rec_status(store, key, status, by)
    return {"key": key, "status": status}


# ------------------------------------------------------------------------------------------
# experiments
def _with_result(row: dict[str, Any], today: date) -> dict[str, Any]:
    out = {
        **row,
        "metric_label": experiments.METRICS[row["metric"]]["label"],
        "better": experiments.METRICS[row["metric"]]["better"],
    }
    try:
        out["result"] = experiments.result(row, today)
    except AnalyticsError as e:
        out["result"] = {"state": "error", "verdict": "error", "error": e.message}
    return out


def experiment_list(brand: str) -> dict[str, Any]:
    """Every experiment of the store with its result, the tile counts and the change log of the
    days the experiments cover."""
    store, tz, now = _ctx(brand)
    today = _today(tz, now)
    rows = data.recent(("experiments", store), lambda: data.experiments(store))
    items = list(_pool.map(lambda r: _with_result(r, today), rows))
    since = min((str(r["start_date"])[:10] for r in rows), default=today.isoformat())
    first = (date.fromisoformat(since) - timedelta(days=60)).isoformat()
    log = _change_log_since(store, today, first)
    return {
        "brand": brand,
        "experiments": items,
        "summary": experiments.summary(items),
        "metrics": [{"key": k, **v} for k, v in experiments.METRICS.items()],
        "change_log": log,
    }


def save_experiment(
    brand: str, body: dict[str, Any], by: str, exp_id: int | None = None
) -> dict[str, Any]:
    """Create an experiment, or change one of this store's."""
    store, tz, now = _ctx(brand)
    try:
        fields = experiments.clean(body)
    except ValueError as e:
        raise InputError(str(e)) from None
    if exp_id is None:
        row = data.add_experiment({**fields, "store": store, "created_by": by[:200]})
    else:
        if data.experiment(store, exp_id) is None:
            raise InputError("No such experiment for this store.")
        data.update_experiment(store, exp_id, fields)
        row = data.experiment(store, exp_id) or {**fields, "id": exp_id, "store": store}
    return _with_result(row, _today(tz, now))


def delete_experiment(brand: str, exp_id: int) -> bool:
    """Remove one of this store's experiments."""
    store, _, _ = _ctx(brand)
    return data.delete_experiment(store, exp_id)


# ------------------------------------------------------------------------------------------ alarms
def alarm_list(brand: str) -> dict[str, Any]:
    """Every alarm rule with its open alert and when it last fired."""
    store, _, _ = _ctx(brand)
    recent, all_rules, enabled = _together(
        lambda: _alerts(store, 200), lambda: _rules(store), lambda: _alarms_enabled(store)
    )
    rules = []
    for r in all_rules:
        mine = [a for a in recent if a["rule_id"] == r["id"]]
        rules.append(
            {
                **r,
                "open_alert": next((a for a in mine if a.get("resolved_at") is None), None),
                "last_triggered_at": mine[0]["triggered_at"] if mine else None,
            }
        )
    return {"brand": brand, "alarms_enabled": enabled, "rules": rules}


def _threshold(kind: str, value: Any) -> float:
    try:
        t = float(value)
    except TypeError, ValueError:
        raise InputError("The threshold must be a number.") from None
    if t <= 0 or (kind == "cvr_drop" and t > 100) or t > 10_000:
        raise InputError(
            "The threshold must be above 0 (and at most 100 for a conversion-rate drop)."
        )
    return round(t, 2)


def _keyword(value: Any) -> str:
    k = str(value or "").strip()
    if not 1 <= len(k) <= 100:
        raise InputError("Give a product keyword of 1 to 100 characters.")
    return k


def _title(value: Any) -> str:
    t = str(value or "").strip()
    if not 1 <= len(t) <= 200:
        raise InputError("Give a title of 1 to 200 characters.")
    return t


def create_rule(brand: str, body: dict[str, Any], by: str) -> dict[str, Any]:
    """Add a rule (for example a product keyword alarm for CPC)."""
    store, _, _ = _ctx(brand)
    kind = body.get("kind")
    if kind not in KINDS:
        raise InputError("kind must be cvr_drop or no_product_orders.")
    row = {
        "store": store,
        "kind": kind,
        "title": _title(body.get("title")),
        "threshold": _threshold(kind, body.get("threshold")),
        "product_keyword": _keyword(body.get("product_keyword"))
        if kind == "no_product_orders"
        else None,
        "is_active": bool(body.get("is_active", True)),
        "updated_by": by[:200],
    }
    return data.create_rule(row)


def update_rule(brand: str, rule_id: int, body: dict[str, Any], by: str) -> dict[str, Any] | None:
    """Change a rule's title, threshold, keyword or on/off switch. None when the rule is not this
    store's.
    """
    store, _, _ = _ctx(brand)
    rule = data.alarm_rule(store, rule_id)
    if rule is None:
        return None
    values: dict[str, Any] = {}
    if "is_active" in body:
        if not isinstance(body["is_active"], bool):
            raise InputError("is_active must be true or false.")
        values["is_active"] = body["is_active"]
    if "threshold" in body:
        values["threshold"] = _threshold(rule["kind"], body["threshold"])
    if "title" in body:
        values["title"] = _title(body["title"])
    if "product_keyword" in body:
        if rule["kind"] != "no_product_orders":
            raise InputError("Only a product alarm has a keyword.")
        values["product_keyword"] = _keyword(body["product_keyword"])
    if not values:
        raise InputError("Nothing to change.")
    data.update_rule(store, rule_id, {**values, "updated_by": by[:200]})
    return data.alarm_rule(store, rule_id)


def alert_list(brand: str, limit: int) -> dict[str, Any]:
    """The store's recent alerts with their rule title."""
    store, _, _ = _ctx(brand)
    rules, recent = _together(lambda: _rules(store), lambda: _alerts(store, limit))
    titles = {r["id"]: r["title"] for r in rules}
    return {"brand": brand, "alerts": [{**a, "rule": titles.get(a["rule_id"])} for a in recent]}


def settings(brand: str) -> dict[str, Any]:
    """Per-store CRO settings and where the data comes from."""
    store, tz, _ = _ctx(brand)
    enabled, state, first_day, free_ship = _together(
        lambda: _alarms_enabled(store),
        lambda: _sync_state(store),
        lambda: data.first_order_day(store),
        lambda: free_shipping_amount(store)[0],
    )
    return {
        "brand": brand,
        "store": store,
        "timezone": str(tz),
        "alarms_enabled": enabled,
        "shopify_configured": shopify.configured(store),
        "sync": state,
        "order_data": {**order_data_state(state), "available_from": first_day},
        "free_shipping_threshold": free_ship,
        "email_alerts": False,
    }


def customers(brand: str, rq: RangeQuery) -> dict[str, Any]:
    """New vs returning customers (Shopify) for the range's complete days, with the comparison."""
    store, tz, now, p = _plan(brand, rq)
    cur, base = _windows(p, _today(tz, now))
    nr: dict[str, Any] | None = None
    nr_error = None
    try:
        nr = customers_mod.new_vs_returning(store, cur, base)
    except AnalyticsError as e:
        nr_error = {"state": e.state, "message": e.message}
    return {
        "brand": brand,
        **_range_info(p),
        **_window_info(cur, base),
        "new_vs_returning": nr,
        "new_vs_returning_error": nr_error,
        "order_data": _order_data(store),
    }


def set_settings(brand: str, body: dict[str, Any], by: str) -> dict[str, Any]:
    """Switch alarms on or off, and/or save the free-shipping amount (null clears it)."""
    store, _, _ = _ctx(brand)
    if "alarms_enabled" not in body and "free_shipping_threshold" not in body:
        raise InputError("Send alarms_enabled and/or free_shipping_threshold.")
    if "alarms_enabled" in body:
        if not isinstance(body["alarms_enabled"], bool):
            raise InputError("alarms_enabled must be true or false.")
        data.set_alarms_enabled(store, body["alarms_enabled"], by)
    if "free_shipping_threshold" in body:
        raw = body["free_shipping_threshold"]
        amount: float | None = None
        if raw not in (None, ""):
            try:
                amount = round(float(raw), 2)
            except TypeError, ValueError:
                raise InputError("The free-shipping amount must be a number.") from None
            if not 0 < amount < 100_000:
                raise InputError("The free-shipping amount must be above 0 and below 100,000.")
        data.set_free_shipping(store, amount, by)
    return settings(brand)


# ------------------------------------------------------------------------------------------ change
# log
CHANGE_LOG_DAYS = 400  # one cached read serves every page's window (60, 63, 90 and 365 days)


def _change_log_since(store: str, today: date, since: str) -> list[dict[str, Any]]:
    """The store's change-log entries on or after `since`, cut from one wide cached read (the pages
    ask for different windows; each used to be its own Supabase read of about 0.4 s)."""
    wide = min(since, (today - timedelta(days=CHANGE_LOG_DAYS)).isoformat())
    rows = data.recent(("change_log", store, wide), lambda: data.change_log(store, wide))
    return [e for e in rows if str(e.get("entry_date") or "")[:10] >= since]


def change_log(brand: str, days: int) -> dict[str, Any]:
    """Change-log entries of the last `days` days."""
    store, tz, now = _ctx(brand)
    today = _today(tz, now)
    since = (today - timedelta(days=days)).isoformat()
    return {"brand": brand, "areas": list(AREAS), "entries": _change_log_since(store, today, since)}


def add_change(brand: str, body: dict[str, Any], by: str) -> dict[str, Any]:
    """Record a store change."""
    store, tz, now = _ctx(brand)
    try:
        day = date.fromisoformat(str(body.get("entry_date") or _today(tz, now).isoformat()))
    except ValueError:
        raise InputError("entry_date must be a date like 2026-11-19.") from None
    change = str(body.get("change") or "").strip()
    if not 1 <= len(change) <= 1000:
        raise InputError("Describe the change in 1 to 1000 characters.")
    area = body.get("area") if body.get("area") in AREAS else "other"
    owner = str(body.get("owner") or "").strip()[:200] or None
    return data.add_change(
        {
            "store": store,
            "entry_date": day.isoformat(),
            "change": change,
            "area": area,
            "owner": owner,
            "created_by": by[:200],
        }
    )


def delete_change(brand: str, entry_id: int) -> bool:
    """Remove a change-log entry of this store."""
    store, _, _ = _ctx(brand)
    return data.delete_change(store, entry_id)


# ------------------------------------------------------------------------------------------ warm
# Shopify allows each store 1,000 report (ShopifyQL) points a minute; a query costs 2-22 (measured
# 2026-11-21: a 28-day funnel 18, landing pages 22, hourly visits 10). A full warm-up round with
# nothing cached costs about as much as that, so after each read that went to Shopify the round
# waits WARM_PAUSE seconds and pages opened meanwhile keep most of the budget. Cached reads do not
# wait.
WARM_PAUSE = 2.0
WARM_CACHED = 0.3  # a read faster than this came from the cache


def warm_views(brand: str, pause: float = WARM_PAUSE) -> dict[str, Any]:
    """Read what the CRO pages show by default, so the first visit (and the first after a sync or a
    restart) answers from the cache: every tab for the default range (yesterday against the 4-week
    same-weekday average) and the Overview's other cards. One read at a time, so the background job
    never sends Shopify a burst; settled days stay cached for 6 hours (conversion.FINAL_TTL), so
    after the first round only today's and yesterday's figures are read again. Never raises: a read
    that fails is counted and the page will try again itself."""
    store, tz, now = _ctx(brand)
    today = _today(tz, now)
    y = today - timedelta(days=1)

    def iso(d: date) -> str:
        return d.isoformat()

    day = RangeQuery(frm=iso(y), to=iso(y), compare="4week_avg")
    last28 = RangeQuery(frm=iso(y - timedelta(days=27)), to=iso(y), compare="previous")
    strip = RangeQuery(frm=iso(today - timedelta(days=13)), to=iso(today), compare="none")
    month = RangeQuery(frm=iso(today.replace(day=1)), to=iso(today), compare="previous")
    week2 = RangeQuery(frm=iso(y - timedelta(days=13)), to=iso(y), compare="previous")
    speed = RangeQuery(
        frm=iso(today - timedelta(days=8)), to=iso(today - timedelta(days=2)), compare="previous"
    )
    reads: list[tuple[str, Callable[[], Any]]] = [
        # the Overview, in the order it matters
        ("overview", lambda: overview(brand, day)),
        ("conversion", lambda: conversion_trend(brand, day)),
        ("conversion 28", lambda: conversion_trend(brand, last28)),
        ("sales trend 28", lambda: sales_trend(brand, last28)),
        ("strip sales", lambda: sales_trend(brand, strip)),
        ("strip conversion", lambda: conversion_trend(brand, strip)),
        ("month", lambda: overview(brand, month)),
        ("traffic changes", lambda: traffic_changes(brand, day)),
        ("trends", lambda: overview_trends(brand, last28)),
        ("heatmap", lambda: buy_heatmap(brand, 28)),
        ("sales breakdown", lambda: sales_breakdown(brand, day)),
        ("site health 7", lambda: site_health(brand, speed)),
        ("recommendations", lambda: recommendation_list(brand)),
        # the other tabs on the default range
        ("segments device", lambda: segments(brand, "device", day)),
        ("segments channel", lambda: segments(brand, "channel", day)),
        ("geo", lambda: geo(brand, day)),
        ("landing pages", lambda: landing_pages(brand, day)),
        ("landing grids", lambda: landing_grids(brand, day)),
        ("site health", lambda: site_health(brand, day)),
        ("checkout trend", lambda: conversion_trend(brand, week2)),
        ("checkout extras", lambda: checkout_extras(brand, day)),
        ("products", lambda: product_insights(brand, day)),
        ("discount codes", lambda: discount_codes(brand, day)),
        ("customers", lambda: customers(brand, day)),
    ]
    started = time.monotonic()
    failed: list[str] = []
    fetched = 0
    for name, read in reads:
        t0 = time.monotonic()
        try:
            read()
        except Exception as e:  # noqa: BLE001 - a warm-up read must never stop the job
            failed.append(name)
            log.info("CRO warm-up %s for %s: %s", name, brand, getattr(e, "message", e))
        if time.monotonic() - t0 > WARM_CACHED:
            fetched += 1
            time.sleep(pause)
    return {
        "reads": len(reads),
        "from_shopify": fetched,
        "failed": failed,
        "seconds": round(time.monotonic() - started, 1),
    }
