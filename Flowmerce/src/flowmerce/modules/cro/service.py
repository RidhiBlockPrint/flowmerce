"""What each CRO page asks for, put together from the order snapshot, ShopifyQL and the cro tables.

Every function takes a brand id ('ridhi' or 'cpc'). Input checks live here so the routes stay thin;
a bad value raises InputError with a message the page can show.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..shipping.supabase import SupabaseError
from . import alarms, conversion, data, metrics, recommendations, shopify
from .config import MIN_ORDERS_FOR_COMPARISON, MIN_SESSIONS_FOR_COMPARISON, store_for
from .periods import Plan, RangeError, metric_block, parse_day, plan, range_plan
from .shopify import AnalyticsError

log = logging.getLogger(__name__)
# Reads one answer needs are made at the same time. Tasks here may use data's own pools, never
# this one, so nothing waits on a task queued behind itself.
_pool = ThreadPoolExecutor(max_workers=6, thread_name_prefix="cro-read")


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
    except (SupabaseError, IndexError, KeyError, ZoneInfoNotFoundError):
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
    base_values = [
        v for v, s in (period_cvr(days) for days in p.baseline_days) if v is not None and s
    ]
    baseline = round(sum(base_values) / len(base_values), 2) if base_values else None
    block = metric_block(value, baseline, sessions < MIN_SESSIONS_FOR_COMPARISON, p.baseline_label)
    note = " (today left out)" if p.is_partial and len(p.current_days) > 1 else ""
    return {
        **block,
        "sessions": sessions or None,
        "base_label": f"{int(orders)} orders from {sessions:,} sessions{note}"
        if sessions
        else "sessions pending",
    }


def overview(brand: str, rq: RangeQuery) -> dict[str, Any]:
    """KPI cards: orders, revenue, AOV and conversion rate for the chosen range, each against its
    comparison."""
    store, tz, now, p = _plan(brand, rq)
    snap = _orders_for(store, p)
    kpis: dict[str, Any] = metrics.order_kpis(snap, p)
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
    last = metrics.last_order_at(snap)
    return {
        "brand": brand,
        **_range_info(p),
        "timezone": str(tz),
        "as_of": now.astimezone(tz).isoformat(),
        "metrics": kpis,
        "health": {"last_order_at": last.isoformat() if last else None},
        "cvr_error": cvr_error,
        "data_since": snap.since.isoformat(),
        "order_data": _order_data(store),
    }


def sales_breakdown(brand: str, rq: RangeQuery) -> dict[str, Any]:
    """Gross to total sales for the chosen range."""
    store, _, _, p = _plan(brand, rq)
    return {
        "brand": brand,
        **metrics.sales_breakdown(_orders_for(store, p), p),
        **_range_info(p),
        "order_data": _order_data(store),
    }


def sales_trend(brand: str, rq: RangeQuery) -> dict[str, Any]:
    """Daily orders, total and net sales of the range and of its comparison period."""
    store, tz, _, p = _plan(brand, rq)
    return {
        "brand": brand,
        **metrics.range_trend(_orders_for(store, p), tz, p),
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
    rows = conversion.daily_between(store, days[0], days[-1], today)
    base_rows = (
        conversion.daily_between(store, p.baseline_days[0][0], p.baseline_days[0][-1], today)
        if p.baseline_days
        else []
    )
    total = conversion.totals(rows)
    base = conversion.totals(base_rows) if base_rows else None
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
        "total": total,
        "baseline_total": base,
        "conversion_change_pct": change,
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
    today = _today(tz, now)
    last = min(p.current_days[-1], today - timedelta(days=1))
    if last < p.current_days[0]:
        last = p.current_days[0]  # a range of only today: Shopify's partial figures
    base = None
    if p.baseline_days:
        shift = p.current_days[0] - p.baseline_days[0][0]
        base = (p.baseline_days[0][0], last - shift)
    try:
        return {
            "brand": brand,
            **_range_info(p),
            **conversion.segments_between(store, dimension, (p.current_days[0], last), base),
        }
    except ValueError as e:
        raise InputError(str(e)) from None


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
    """Recommendations the current figures support. Sources that cannot be read are listed in
    `skipped`.
    """
    store, tz, now = _ctx(brand)
    today = _today(tz, now)
    snap = data.snapshot(store)
    skipped: list[str] = []
    cvr = fun = None
    try:
        rows = conversion.daily(store, today, 7)
        cvr = conversion.cvr_comparison(rows, today)
        fun = rows[-1] if rows else None
    except AnalyticsError as e:
        skipped.append(f"conversion rate and funnel ({e.state})")
    state = _order_data(store)
    if not state["first_load_complete"]:
        # Partial orders would look like stalled or declining sales: order-based checks wait.
        skipped.append("order-based checks (the first order load has not finished)")
        recs = recommendations.build(
            product_alarms=[], cvr=cvr, funnel=fun, today_revenue=None, declines=[], health=None
        )
        return {"brand": brand, "recommendations": recs, "skipped": skipped, "order_data": state}
    gap_status = []
    for r in _rules(store):
        if r["kind"] == "no_product_orders" and r.get("is_active"):
            fig = alarms.gap_figures(r, snap, now)
            fig.pop("_last_placed", None)
            gap_status.append(
                {**fig, "status": "alarm_active" if fig["status"] == "triggered" else fig["status"]}
            )
    pacing = metrics.order_kpis(snap, plan("today", "last_week", tz, now))["revenue"]
    recs = recommendations.build(
        product_alarms=gap_status,
        cvr=cvr,
        funnel=fun,
        today_revenue=pacing,
        declines=metrics.declining_products(snap, tz, now),
        health=metrics.order_health(snap, now, 30),
    )
    return {"brand": brand, "recommendations": recs, "skipped": skipped, "order_data": state}


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
    except (TypeError, ValueError):
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
    enabled, state, first_day = _together(
        lambda: _alarms_enabled(store),
        lambda: _sync_state(store),
        lambda: data.first_order_day(store),
    )
    return {
        "brand": brand,
        "store": store,
        "timezone": str(tz),
        "alarms_enabled": enabled,
        "shopify_configured": shopify.configured(store),
        "sync": state,
        "order_data": {**order_data_state(state), "available_from": first_day},
        "email_alerts": False,
    }


def set_settings(brand: str, body: dict[str, Any], by: str) -> dict[str, Any]:
    """Switch alarms on or off for the store."""
    store, _, _ = _ctx(brand)
    if not isinstance(body.get("alarms_enabled"), bool):
        raise InputError("alarms_enabled must be true or false.")
    data.set_alarms_enabled(store, body["alarms_enabled"], by)
    return settings(brand)


# ------------------------------------------------------------------------------------------ change
# log
def change_log(brand: str, days: int) -> dict[str, Any]:
    """Change-log entries of the last `days` days."""
    store, tz, now = _ctx(brand)
    since = (_today(tz, now) - timedelta(days=days)).isoformat()
    entries = data.recent(("change_log", store, since), lambda: data.change_log(store, since))
    return {"brand": brand, "areas": list(AREAS), "entries": entries}


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
