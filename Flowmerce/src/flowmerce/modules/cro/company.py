"""Home's summary (GET /api/cro/home-period): one store or both stores added, for a period.

Home is one dashboard for All, Ridhi and CPC (owner, 2026-11-27; layout "A · Bento" chosen the same
day from design-mockups/home-ceo/). It shows a period (today, yesterday, the last 7 or 30 complete
days, or the month to date) against the period just before it. This module reads each store's own
CRO reports (the functions the CRO page uses: overview, sales breakdown, sales trend, conversion)
and its monthly goal, and for both stores adds them up:

  * counts and money are added: orders, sales, visits (sessions), completed checkouts, goals;
  * rates are worked out again from the sums, never averaged: conversion = completed checkouts /
    visits, average order = sales / orders, revenue per visit = sales / visits;
  * the too-early rule is judged on the totals (20 orders, 500 visits);
  * each store counts its days in its own time zone, as on the CRO page; a day is only shown when
    every store has reached it, and both stores use the earlier store's "today".

For one store the CRO page's own figures are returned unchanged.
"""

from __future__ import annotations

import calendar
from collections.abc import Callable, Sequence
from datetime import date, timedelta
from typing import Any

from . import goals, service
from .config import MIN_ORDERS_FOR_COMPARISON, MIN_SESSIONS_FOR_COMPARISON
from .periods import metric_block
from .shopify import AnalyticsError

BRANDS = ("ridhi", "cpc")
PERIODS = ("today", "yesterday", "7d", "30d", "mtd")
CHART_DAYS = 14  # the sales chart shows at least 14 days, ending on the period's last day
HISTORY_DAYS = 28  # conversion history behind the conversion tile's usual band


def _num(v: Any) -> float:
    return float(v or 0)


def _ratio(a: float | None, b: float | None, scale: float = 1.0) -> float | None:
    """a / b (times `scale`) to 2 decimals, or None when either is missing or b is 0."""
    if a is None or not b:
        return None
    return round(a / b * scale, 2)


def period_range(period: str, today: date) -> tuple[date, date]:
    """The first and last day of a period, in store days: today; yesterday; the last 7 or 30
    complete days (yesterday back); the month to date (today included)."""
    if period == "today":
        return today, today
    if period == "yesterday":
        y = today - timedelta(days=1)
        return y, y
    if period in ("7d", "30d"):
        n = 7 if period == "7d" else 30
        return today - timedelta(days=n), today - timedelta(days=1)
    if period == "mtd":
        return today.replace(day=1), today
    raise service.InputError(f"period must be one of {', '.join(PERIODS)}")


def store_days(
    trend: Sequence[dict[str, Any]], conv: Sequence[dict[str, Any]]
) -> list[dict[str, Any]]:
    """One store's days: orders and sales from its sales trend, with visits, completed checkouts
    and conversion from its conversion report (None for a day Shopify has not reported, such as
    today), and the day's average order."""
    by_date = {r["date"]: r for r in conv}
    out: list[dict[str, Any]] = []
    for r in trend:
        c = by_date.get(r["date"])
        revenue = round(_num(r.get("revenue")), 2)
        orders = int(r["orders"] or 0)
        out.append(
            {
                "date": r["date"],
                "orders": orders,
                "revenue": revenue,
                "net": round(_num(r.get("net")), 2),
                "aov": _ratio(revenue, orders),
                "sessions": int(c["sessions"]) if c else None,
                "completed_checkout": int(c["completed_checkout"]) if c else None,
                "conversion_rate": c.get("conversion_rate") if c else None,
            }
        )
    return out


def combine_days(stores: Sequence[Sequence[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Every store's days added up by date: only dates every store has, visits only when every
    store has them, and conversion and average order worked out again from the sums."""
    by_date: dict[str, list[dict[str, Any]]] = {}
    for days in stores:
        for d in days:
            by_date.setdefault(d["date"], []).append(d)
    out: list[dict[str, Any]] = []
    for day in sorted(by_date):
        rows = by_date[day]
        if len(rows) != len(stores):
            continue
        visits = all(r.get("sessions") is not None for r in rows)
        sessions = sum(int(r["sessions"]) for r in rows) if visits else None
        done = sum(int(r.get("completed_checkout") or 0) for r in rows) if visits else None
        orders = sum(int(r["orders"]) for r in rows)
        revenue = round(sum(_num(r.get("revenue")) for r in rows), 2)
        out.append(
            {
                "date": day,
                "orders": orders,
                "revenue": revenue,
                "net": round(sum(_num(r.get("net")) for r in rows), 2),
                "aov": _ratio(revenue, orders),
                "sessions": sessions,
                "completed_checkout": done,
                "conversion_rate": _ratio(done, sessions, 100) if visits else None,
            }
        )
    return out


def combine_series(stores: Sequence[Sequence[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Sales trend rows (date, orders, revenue, net) of several stores added up by position; the
    stores' series cover the same days, so the first store's dates are kept."""
    if not stores or any(len(s) != len(stores[0]) for s in stores):
        return []
    return [
        {
            "date": rows[0]["date"],
            "orders": sum(int(r["orders"] or 0) for r in rows),
            "revenue": round(sum(_num(r.get("revenue")) for r in rows), 2),
            "net": round(sum(_num(r.get("net")) for r in rows), 2),
        }
        for rows in zip(*stores, strict=True)
    ]


def _added(blocks: Sequence[dict[str, Any]]) -> tuple[float | None, float | None]:
    """The sum of the blocks' values and of their comparison values (None if any is missing)."""

    def total(key: str) -> float | None:
        vals: list[Any] = [b.get(key) for b in blocks]
        if any(v is None for v in vals):
            return None
        return round(sum(_num(v) for v in vals), 2)

    return total("value"), total("baseline_value")


def _visits(days: Sequence[dict[str, Any]], first: date, last: date) -> tuple[int, int]:
    """Visits and completed checkouts of the reported days from `first` to `last`."""
    picked = [
        d
        for d in days
        if first.isoformat() <= d["date"] <= last.isoformat() and d.get("sessions") is not None
    ]
    return sum(int(d["sessions"]) for d in picked), sum(
        int(d.get("completed_checkout") or 0) for d in picked
    )


def combine_metrics(
    parts: Sequence[dict[str, Any]],
    days: Sequence[dict[str, Any]],
    current: tuple[date, date],
    previous: tuple[date, date],
    partial: bool,
) -> dict[str, Any]:
    """The overview's KPI blocks for several stores (`parts`: each store's overview `metrics`).
    Conversion and visits come from the added `days` (combine_days) of the `current` period and the
    `previous` one; today has no visits yet, and revenue per visit is left out while the period
    reaches today (`partial`), as on the CRO page."""
    label = str(parts[0]["orders"]["baseline_label"])
    orders, orders_b = _added([p["orders"] for p in parts])
    revenue, revenue_b = _added([p["revenue"] for p in parts])
    early = (orders or 0) < MIN_ORDERS_FOR_COMPARISON
    out: dict[str, Any] = {
        "orders": metric_block(orders, orders_b, early, label, 1),
        "revenue": metric_block(revenue, revenue_b, early, label),
        "aov": metric_block(_ratio(revenue, orders), _ratio(revenue_b, orders_b), early, label),
    }
    sessions, done = _visits(days, *current)
    base_sessions, base_done = _visits(days, *previous)
    if not sessions:
        out["conversion_rate"] = {
            **metric_block(None, None, True, label),
            "sessions": None,
            "base_label": "Shopify reports sessions for complete days only",
        }
        return out
    early_s = sessions < MIN_SESSIONS_FOR_COMPARISON
    base_s = base_sessions or None
    out["conversion_rate"] = {
        **metric_block(_ratio(done, sessions, 100), _ratio(base_done, base_s, 100), early_s, label),
        "sessions": sessions,
        "baseline_sessions": base_s,
        "base_label": f"{int(orders or 0)} orders from {sessions:,} sessions",
    }
    out["sessions"] = metric_block(sessions, base_s, early_s, label, 1)
    if not partial:
        out["revenue_per_session"] = metric_block(
            _ratio(revenue, sessions), _ratio(revenue_b, base_s), early_s, label
        )
    return out


def combine_breakdown(parts: Sequence[dict[str, Any]], too_early: bool) -> dict[str, Any]:
    """The sales breakdown (gross, discounts, returns, net, shipping, tax, total) of several stores,
    each line added up with its comparison. `too_early` comes from the added orders."""
    first = parts[0]
    label = str(first.get("baseline_label") or "")
    rows = []
    for row in first["rows"]:
        same = [next(r for r in p["rows"] if r["key"] == row["key"]) for p in parts]
        value, base = _added(same)
        block = metric_block(value, base, too_early, label)
        rows.append({"key": row["key"], "label": row["label"], **block})
    return {"rows": rows, "baseline_label": label, "too_early": too_early}


def month_goal(
    goal_values: Sequence[float], month_sales: Sequence[float | None], today: date
) -> dict[str, Any] | None:
    """The month's sales goal (the stores' goals added) against the month's sales so far, and the
    pace: sales so far against the goal's share for the days gone (today counted). None when a
    store has no goal (a partial goal would look reached too early) or its sales are unknown."""
    if not goal_values or any(g <= 0 for g in goal_values) or any(s is None for s in month_sales):
        return None
    goal = round(sum(goal_values), 2)
    sales = round(sum(_num(s) for s in month_sales), 2)
    days = calendar.monthrange(today.year, today.month)[1]
    expected = goal * today.day / days
    return {
        "month": today.strftime("%B"),
        "goal": goal,
        "sales": sales,
        "pct": round(sales / goal * 100, 1),
        "pace_pct": round(sales / expected * 100, 1) if expected else None,
        "day": today.day,
        "days": days,
    }


def _read(brand: str, period: str, today: date) -> dict[str, Any]:
    """One store's reports for Home: the period against the one before, the chart's days (and the
    days before them), the daily visits behind the conversion band, and the month so far."""
    first, last = period_range(period, today)
    n = (last - first).days + 1
    chart_first = last - timedelta(days=max(CHART_DAYS, n) - 1)
    prev_first = first - timedelta(days=n)
    span_first = min(last - timedelta(days=HISTORY_DAYS - 1), chart_first, prev_first)

    def rq(a: date, b: date, compare: str) -> service.RangeQuery:
        return service.RangeQuery(frm=a.isoformat(), to=b.isoformat(), compare=compare)

    def conversion() -> dict[str, Any]:
        try:
            return service.conversion_trend(brand, rq(span_first, last, "none"))
        except AnalyticsError as e:
            return {"trend": [], "error": {"state": e.state, "message": e.message}}

    month_first = today.replace(day=1)
    calls: list[Callable[[], Any]] = [
        lambda: service.overview(brand, rq(first, last, "previous")),
        lambda: service.sales_breakdown(brand, rq(first, last, "previous")),
        lambda: service.sales_trend(brand, rq(chart_first, last, "previous")),
        lambda: service.sales_trend(brand, rq(span_first, last, "none")),
        conversion,
        lambda: (
            service.overview(brand, rq(month_first, today, "none")) if period != "mtd" else None
        ),
        lambda: goals.goal(brand),
    ]
    overview, breakdown, chart, span, conv, month, goal = service._together(*calls)
    month = month or overview
    return {
        "brand": brand,
        "overview": overview,
        "breakdown": breakdown,
        "chart": {"current": chart["current"], "previous": chart["previous"]},
        "days": store_days(span["current"], conv.get("trend") or []),
        "month_sales": month["metrics"]["revenue"]["value"],
        "goal": float(goal.get("monthly_revenue") or 0),
        "cvr_error": overview.get("cvr_error") or conv.get("error"),
        "range": (first, last),
    }


def home_period(brand: str | None, period: str | None) -> dict[str, Any]:
    """Home for one store (`brand`) or both (`brand` None) for a period (default: yesterday):
    the KPI blocks against the period before, the sales breakdown, the sales chart (at least 14
    days, with the days before them), the daily figures behind the small tiles, each brand's share
    of sales (both stores) and the month's goal. The module docstring says how stores are added."""
    period = period or "yesterday"
    if period not in PERIODS:
        raise service.InputError(f"period must be one of {', '.join(PERIODS)}")
    brands = [brand] if brand else list(BRANDS)
    ctx = {b: service._ctx(b) for b in brands}  # an unknown brand is an InputError
    today = min(service._today(tz, now) for _, tz, now in ctx.values())
    parts = service._together(*(lambda b=b: _read(b, period, today) for b in brands))
    first, last = parts[0]["range"]
    n = (last - first).days + 1
    partial = last == today
    if len(parts) == 1:
        p = parts[0]
        metrics, breakdown, days = p["overview"]["metrics"], p["breakdown"], p["days"]
        chart = p["chart"]
        by_brand: list[dict[str, Any]] = []
    else:
        days = combine_days([p["days"] for p in parts])
        metrics = combine_metrics(
            [p["overview"]["metrics"] for p in parts],
            days,
            (first, last),
            (first - timedelta(days=n), first - timedelta(days=1)),
            partial,
        )
        breakdown = combine_breakdown(
            [p["breakdown"] for p in parts],
            (metrics["orders"]["value"] or 0) < MIN_ORDERS_FOR_COMPARISON,
        )
        chart = {
            "current": combine_series([p["chart"]["current"] for p in parts]),
            "previous": combine_series([p["chart"]["previous"] for p in parts]),
        }
        total = _num(metrics["revenue"]["value"])
        by_brand = [
            {
                "brand": p["brand"],
                "revenue": p["overview"]["metrics"]["revenue"]["value"],
                "orders": p["overview"]["metrics"]["orders"]["value"],
                "share": _ratio(_num(p["overview"]["metrics"]["revenue"]["value"]), total, 100),
            }
            for p in parts
        ]
    last_orders = [p["overview"]["health"].get("last_order_at") for p in parts]
    synced = [(p["overview"].get("order_data") or {}).get("last_run_at") for p in parts]
    first_part = parts[0]["overview"]
    return {
        "brands": brands,
        "period": period,
        "from": first.isoformat(),
        "to": last.isoformat(),
        "today": today.isoformat(),
        "is_partial": partial,
        "period_label": first_part.get("period_label"),
        "baseline_label": metrics["orders"]["baseline_label"],
        "timezone": first_part.get("timezone") if len(parts) == 1 else None,
        "metrics": metrics,
        "breakdown": {
            "rows": breakdown["rows"],
            "baseline_label": breakdown.get("baseline_label"),
            "too_early": breakdown.get("too_early"),
        },
        "chart": chart,
        "days": days,
        "by_brand": by_brand,
        "goal": month_goal([p["goal"] for p in parts], [p["month_sales"] for p in parts], today),
        "last_order_at": max((x for x in last_orders if x), default=None),
        "orders_synced_at": min((x for x in synced if x), default=None),
        "cvr_error": next((p["cvr_error"] for p in parts if p["cvr_error"]), None),
    }
