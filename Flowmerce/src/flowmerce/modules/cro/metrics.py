"""Order-based CRO figures computed from a store's snapshot (pure, no I/O).

Cancelled orders are left out of sales, AOV and product figures; order health counts them
separately. "Gross sales" = subtotal + discounts, "Net sales" = subtotal - refunded, "Total sales" =
Shopify's current total. "Returns" is Shopify's total refunded amount, which can include refunded
shipping or tax.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .config import MIN_ORDERS_FOR_COMPARISON
from .data import Line, Order, Snapshot
from .periods import Plan, Window, day_window, days_window, metric_block

SALES_KEYS = ("orders", "total", "gross", "discounts", "returns", "net", "shipping", "tax")
REFUND_STATUSES = {"refunded", "partially_refunded"}
PAID_STATUSES = {"paid", "partially_paid"}


def live(orders: Iterable[Order], w: Window) -> list[Order]:
    """Orders placed in the window that were not cancelled."""
    return [o for o in orders if o.cancelled_at is None and w.contains(o.placed_at)]


def order_stats(orders: Iterable[Order], w: Window) -> dict[str, float]:
    """Orders, revenue (total) and AOV in one window."""
    rows = live(orders, w)
    revenue = round(sum(o.total for o in rows), 2)
    return {
        "orders": len(rows),
        "revenue": revenue,
        "aov": round(revenue / len(rows), 2) if rows else 0.0,
    }


def sales_stats(orders: Iterable[Order], w: Window) -> dict[str, float]:
    """The sales breakdown of one window."""
    rows = live(orders, w)
    subtotal = sum(o.subtotal for o in rows)
    discounts = sum(o.discounts for o in rows)
    refunded = sum(o.refunded for o in rows)
    return {
        "orders": len(rows),
        "total": round(sum(o.total for o in rows), 2),
        "gross": round(subtotal + discounts, 2),
        "discounts": round(discounts, 2),
        "returns": round(refunded, 2),
        "net": round(subtotal - refunded, 2),
        "shipping": round(sum(o.shipping for o in rows), 2),
        "tax": round(sum(o.tax for o in rows), 2),
    }


def average(stats: Sequence[dict[str, float]], keys: Iterable[str]) -> dict[str, float | None]:
    """Key-by-key mean of several windows' figures; None for every key when there is no baseline
    (comparison switched off)."""
    if not stats:
        return {k: None for k in keys}
    return {k: round(sum(s.get(k, 0.0) for s in stats) / len(stats), 2) for k in keys}


SalesReport = dict[str, dict[str, float]]  # conversion.sales_daily(): local day -> figures


def report_stats(report: SalesReport, days: Iterable[date]) -> dict[str, float]:
    """Shopify's sales figures (conversion.sales_daily) added up over some local days."""
    picked = [report[d.isoformat()] for d in days if d.isoformat() in report]
    return {k: round(sum(r.get(k, 0.0) for r in picked), 2) for k in SALES_KEYS}


def with_report(stats: dict[str, float], report: dict[str, float]) -> dict[str, float]:
    """Order-copy figures with the money taken from Shopify's sales report (orders stay ours)."""
    return {**stats, **{k: report[k] for k in SALES_KEYS if k != "orders"}}


def order_kpis(
    snap: Snapshot, p: Plan, report: SalesReport | None = None
) -> dict[str, dict[str, object]]:
    """Orders, revenue and AOV for a plan, each with its baseline and the too-early rule. With
    Shopify's sales `report`, revenue is Shopify's total sales (refunds on the day they were
    made); orders and AOV stay from the order copy."""
    current = order_stats(snap.orders, p.current)
    bases = [order_stats(snap.orders, w) for w in p.baselines]
    if report is not None:
        current["revenue"] = report_stats(report, p.current_days)["total"]
        for b, days in zip(bases, p.baseline_days, strict=True):
            b["revenue"] = report_stats(report, days)["total"]
    baseline = average(bases, ("orders", "revenue", "aov"))
    too_early = current["orders"] < MIN_ORDERS_FOR_COMPARISON
    return {
        "orders": metric_block(
            current["orders"], baseline["orders"], too_early, p.baseline_label, 1
        ),
        "revenue": metric_block(
            current["revenue"], baseline["revenue"], too_early, p.baseline_label
        ),
        "aov": metric_block(current["aov"], baseline["aov"], too_early, p.baseline_label),
    }


BREAKDOWN_ROWS = (
    ("gross", "Gross sales"),
    ("discounts", "Discounts"),
    ("returns", "Returns"),
    ("net", "Net sales"),
    ("shipping", "Shipping"),
    ("tax", "Taxes"),
    ("total", "Total sales"),
)


def sales_breakdown(
    snap: Snapshot, p: Plan, report: SalesReport | None = None
) -> dict[str, object]:
    """Gross -> discounts -> returns -> net -> shipping -> taxes -> total, each with its
    baseline. With Shopify's sales `report` the money is Shopify's own (refunds on the day they
    were made); the order count and the too-early rule stay from the order copy.
    """
    current = sales_stats(snap.orders, p.current)
    bases = [sales_stats(snap.orders, w) for w in p.baselines]
    if report is not None:
        current = with_report(current, report_stats(report, p.current_days))
        bases = [
            with_report(b, report_stats(report, days))
            for b, days in zip(bases, p.baseline_days, strict=True)
        ]
    baseline = average(bases, SALES_KEYS)
    too_early = current["orders"] < MIN_ORDERS_FOR_COMPARISON
    return {
        "period": p.period,
        "period_label": p.label,
        "compare": p.compare,
        "too_early": too_early,
        "rows": [
            {
                "key": k,
                "label": label,
                **metric_block(current[k], baseline[k], too_early, p.baseline_label),
            }
            for k, label in BREAKDOWN_ROWS
        ],
        "source": "shopify_sales" if report is not None else "orders",
        "note": (
            "From Shopify's sales report: returns count on the day the refund was made, as in "
            "Shopify's own reports."
            if report is not None
            else "Returns is Shopify's total refunded amount for the order, which can include "
            "refunded shipping or tax, not only products."
        ),
    }


def sales_trend(snap: Snapshot, tz: ZoneInfo, today: date, days: int) -> dict[str, object]:
    """Daily total sales for the last `days` complete days and the `days` before them (aligned by
    position).
    """
    yesterday = today - timedelta(days=1)
    current, previous = [], []
    for i in range(days - 1, -1, -1):
        d = yesterday - timedelta(days=i)
        p = d - timedelta(days=days)
        cs, ps = (
            order_stats(snap.orders, day_window(d, tz)),
            order_stats(snap.orders, day_window(p, tz)),
        )
        current.append({"date": d.isoformat(), "revenue": cs["revenue"], "orders": cs["orders"]})
        previous.append({"date": p.isoformat(), "revenue": ps["revenue"], "orders": ps["orders"]})
    return {"days": days, "current": current, "previous": previous}


def daily_series(
    snap: Snapshot, tz: ZoneInfo, days: Sequence[date], report: SalesReport | None = None
) -> list[dict[str, object]]:
    """Orders, total sales and net sales for each local day (cancelled orders left out). With
    Shopify's sales `report`, total and net sales are Shopify's own for the day."""
    out: list[dict[str, object]] = []
    for d in days:
        st = sales_stats(snap.orders, day_window(d, tz))
        if report is not None and d.isoformat() in report:
            st = with_report(st, report[d.isoformat()])
        out.append(
            {
                "date": d.isoformat(),
                "orders": st["orders"],
                "revenue": st["total"],
                "net": st["net"],
            }
        )
    return out


def range_trend(
    snap: Snapshot, tz: ZoneInfo, p: Plan, report: SalesReport | None = None
) -> dict[str, object]:
    """Daily figures for a plan's days and, when it has one, its first comparison period's days
    (lined up by position)."""
    return {
        "days": len(p.current_days),
        "current": daily_series(snap, tz, p.current_days, report),
        "previous": (daily_series(snap, tz, p.baseline_days[0], report) if p.baseline_days else []),
        "baseline_label": p.baseline_label,
        "source": "shopify_sales" if report is not None else "orders",
    }


def order_health(snap: Snapshot, now: datetime, days: int) -> dict[str, object]:
    """Paid / refunded / cancelled / other orders placed in the last `days` days."""
    return {**order_health_in(snap, Window(now - timedelta(days=days), now)), "days": days}


def order_health_in(snap: Snapshot, w: Window) -> dict[str, object]:
    """Paid / refunded / cancelled / other orders placed in a window (cancelled ones included)."""
    rows = [o for o in snap.orders if w.contains(o.placed_at)]
    cancelled = sum(1 for o in rows if o.cancelled_at is not None)
    refunded = sum(
        1 for o in rows if o.cancelled_at is None and o.financial_status in REFUND_STATUSES
    )
    paid = sum(1 for o in rows if o.cancelled_at is None and o.financial_status in PAID_STATUSES)
    other = len(rows) - cancelled - refunded - paid

    def share(n: int) -> dict[str, float]:
        return {"count": n, "pct": round(n / len(rows) * 100, 1) if rows else 0.0}

    return {
        "days": round((w.end - w.start).total_seconds() / 86400),
        "total_orders": len(rows),
        "paid": share(paid),
        "refunded": share(refunded),
        "cancelled": share(cancelled),
        "pending": share(other),
    }


def _product_key(line: Line) -> str:
    return f"id:{line.product_id}" if line.product_id is not None else f"title:{line.title.lower()}"


@dataclass
class ProductSales:
    """One product's sales in a window."""

    product_id: int | None
    name: str
    product_type: str
    quantity: int = 0
    revenue: float = 0.0
    order_ids: set[int] = field(default_factory=set)

    def as_dict(self) -> dict[str, object]:
        """The row the API returns."""
        return {
            "product_id": self.product_id,
            "name": self.name,
            "product_type": self.product_type,
            "quantity": self.quantity,
            "revenue": round(self.revenue, 2),
            "orders": len(self.order_ids),
        }


def product_sales(snap: Snapshot, w: Window) -> list[ProductSales]:
    """Quantity and revenue (quantity x unit price) per product in a window, best first."""
    keep = {o.id for o in live(snap.orders, w)}
    agg: dict[str, ProductSales] = {}
    for ln in snap.lines:
        if ln.order_id not in keep:
            continue
        row = agg.setdefault(
            _product_key(ln), ProductSales(ln.product_id, ln.title, ln.product_type)
        )
        row.quantity += ln.quantity
        row.revenue += ln.quantity * ln.unit_price
        row.order_ids.add(ln.order_id)
    return sorted(agg.values(), key=lambda r: (-r.revenue, r.name))


def product_performance(snap: Snapshot, tz: ZoneInfo, today: date, days: int) -> dict[str, object]:
    """Every product sold in the last `days` days (today included), tagged top / average / low by
    revenue
    thirds."""
    first = today - timedelta(days=days - 1)
    return {**products_in(snap, days_window(first, today, tz)), "days": days}


def products_in(snap: Snapshot, w: Window) -> dict[str, object]:
    """Every product sold in a window, tagged top / average / low by revenue thirds."""
    products = product_sales(snap, w)
    rows: list[dict[str, object]] = []
    if products:
        revenues = sorted((p.revenue for p in products), reverse=True)
        top_cut = revenues[max(0, len(revenues) // 3 - 1)]
        low_cut = revenues[max(0, (2 * len(revenues)) // 3)]
        for p in products:
            status = (
                "top" if p.revenue >= top_cut else ("low" if p.revenue <= low_cut else "average")
            )
            rows.append({**p.as_dict(), "performance_status": status})
    return {"products": rows}


# A product counts as "declining" only when it sold enough the week before for a drop to mean
# something: at least this many units AND this much revenue. Without the floor, a quilt going from
# 2 sales to 0 showed as a 100% drop (owner decision 2026-11-19, checked on both stores' data).
DECLINE_MIN_UNITS = 5
DECLINE_MIN_REVENUE = 300.0


def declining_products(
    snap: Snapshot, tz: ZoneInfo, now: datetime, limit: int = 3
) -> list[dict[str, object]]:
    """Products whose revenue in the last 7 days fell 30% or more against the 7 days before, among
    products that sold at least DECLINE_MIN_UNITS units and DECLINE_MIN_REVENUE the week before."""
    today = now.astimezone(tz).date()
    recent = Window(day_window(today - timedelta(days=6), tz).start, now)
    prior = days_window(today - timedelta(days=13), today - timedelta(days=7), tz)
    recent_by = {(p.product_id, p.name): p for p in product_sales(snap, recent)}
    out: list[tuple[float, dict[str, object]]] = []
    for p in product_sales(snap, prior):
        if p.quantity < DECLINE_MIN_UNITS or p.revenue < DECLINE_MIN_REVENUE:
            continue
        now_p = recent_by.get((p.product_id, p.name))
        after = now_p.revenue if now_p else 0.0
        drop = round((p.revenue - after) / p.revenue * 100, 1)
        if drop >= 30:
            out.append(
                (
                    drop,
                    {
                        "name": p.name,
                        "prior_revenue": round(p.revenue, 2),
                        "recent_revenue": round(after, 2),
                        "prior_units": p.quantity,
                        "recent_units": now_p.quantity if now_p else 0,
                        "drop_percent": drop,
                    },
                )
            )
    out.sort(key=lambda d: -d[0])
    return [d for _, d in out[:limit]]


def matches_keyword(line: Line, keyword: str) -> bool:
    """True when the product's title, type or tags contain the keyword (case-insensitive)."""
    k = keyword.strip().lower()
    return bool(k) and k in f"{line.title} {line.product_type} {line.tags}".lower()


def last_order_with(snap: Snapshot, keyword: str) -> Order | None:
    """The newest non-cancelled order that has a line matching the keyword."""
    ids = {ln.order_id for ln in snap.lines if matches_keyword(ln, keyword)}
    hits = [o for o in snap.orders if o.id in ids and o.cancelled_at is None]
    return max(hits, key=lambda o: o.placed_at) if hits else None


def last_order_at(snap: Snapshot) -> datetime | None:
    """When the newest order in the snapshot was placed."""
    return max((o.placed_at for o in snap.orders), default=None)


ORDER_VALUE_STEP = 25.0  # bar width of the order-value chart
ORDER_VALUE_TOP = 300.0  # everything from here up is one "$300+" bar
NEAR_THRESHOLD = 0.20  # "just under free shipping" = within 20% below the amount


def order_values(snap: Snapshot, w: Window, threshold: float | None) -> dict[str, object]:
    """How much orders were worth (subtotal after discounts, before shipping and tax) in $25 bars,
    and, with a free-shipping `threshold`, the share of orders just under it and at or above it.
    Also items per order (1, 2, 3, 4, 5+). Cancelled orders left out."""
    rows = live(snap.orders, w)
    values = [o.subtotal for o in rows]
    n = len(values)
    counts: dict[float, int] = {}
    for v in values:
        b = ORDER_VALUE_TOP if v >= ORDER_VALUE_TOP else (v // ORDER_VALUE_STEP) * ORDER_VALUE_STEP
        counts[b] = counts.get(b, 0) + 1
    near_from = threshold * (1 - NEAR_THRESHOLD) if threshold else None
    bars = []
    b = 0.0
    while b <= ORDER_VALUE_TOP:
        top = b + ORDER_VALUE_STEP
        bars.append(
            {
                "from": b,
                "label": f"${int(b)}+" if b == ORDER_VALUE_TOP else f"${int(b)}-{int(top - 1)}",
                "orders": counts.get(b, 0),
                "share": round(counts.get(b, 0) / n * 100, 1) if n else 0.0,
                "near_threshold": bool(
                    threshold and near_from is not None and b < threshold and top > near_from
                ),
            }
        )
        b = top
    ordered = sorted(values)
    median = (
        (ordered[n // 2] if n % 2 else (ordered[n // 2 - 1] + ordered[n // 2]) / 2) if n else None
    )
    near = len([v for v in values if threshold and near_from and near_from <= v < threshold])
    above = sum(1 for v in values if threshold and v >= threshold)
    keep = {o.id for o in rows}
    qty: dict[int, int] = {}
    for ln in snap.lines:
        if ln.order_id in keep:
            qty[ln.order_id] = qty.get(ln.order_id, 0) + ln.quantity
    pieces = [qty.get(o.id, 0) for o in rows]
    per_order = {k: sum(1 for q in pieces if min(q, 5) == k) for k in range(1, 6)}
    return {
        "orders": n,
        "average": round(sum(values) / n, 2) if n else None,
        "median": round(median, 2) if median is not None else None,
        "bars": bars,
        "threshold": threshold,
        "near_threshold_from": round(near_from, 2) if near_from is not None else None,
        "near_threshold_orders": near if threshold else None,
        "near_threshold_share": round(near / n * 100, 1) if threshold and n else None,
        "at_or_above_threshold_share": round(above / n * 100, 1) if threshold and n else None,
        "items": {
            "average": round(sum(pieces) / n, 2) if n else None,
            "single_item_share": round(per_order[1] / n * 100, 1) if n else None,
            "bars": [
                {
                    "label": "5+" if k == 5 else str(k),
                    "orders": per_order[k],
                    "share": round(per_order[k] / n * 100, 1) if n else 0.0,
                }
                for k in range(1, 6)
            ],
        },
    }


def orders_by_hour(snap: Snapshot, tz: ZoneInfo, w: Window) -> dict[str, object]:
    """Orders by weekday x hour in the store's time (the heatmap when Shopify's hourly visits
    cannot be read). Cancelled orders left out."""
    grid = {(d, h): 0 for d in range(7) for h in range(24)}
    for o in live(snap.orders, w):
        t = o.placed_at.astimezone(tz)
        grid[(t.weekday(), t.hour)] += 1
    return {
        "metric": "orders",
        "weekdays": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
        "cells": [
            {"weekday": d, "hour": h, "sessions": 0, "orders": n, "cvr": None}
            for (d, h), n in sorted(grid.items())
        ],
        "hours_with_data": sum(1 for n in grid.values() if n),
        "average_cvr": None,
        "total_orders": sum(grid.values()),
    }
