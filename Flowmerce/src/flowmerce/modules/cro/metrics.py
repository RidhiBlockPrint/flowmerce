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


def order_kpis(snap: Snapshot, p: Plan) -> dict[str, dict[str, object]]:
    """Orders, revenue and AOV for a plan, each with its baseline and the too-early rule."""
    current = order_stats(snap.orders, p.current)
    baseline = average(
        [order_stats(snap.orders, w) for w in p.baselines], ("orders", "revenue", "aov")
    )
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


def sales_breakdown(snap: Snapshot, p: Plan) -> dict[str, object]:
    """Gross -> discounts -> returns -> net -> shipping -> taxes -> total, each with its
    baseline.
    """
    current = sales_stats(snap.orders, p.current)
    baseline = average([sales_stats(snap.orders, w) for w in p.baselines], SALES_KEYS)
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
        "note": (
            "Returns is Shopify's total refunded amount for the order, which can include refunded "
            "shipping or tax, not only products."
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


def daily_series(snap: Snapshot, tz: ZoneInfo, days: Sequence[date]) -> list[dict[str, object]]:
    """Orders, total sales and net sales for each local day (cancelled orders left out)."""
    out: list[dict[str, object]] = []
    for d in days:
        st = sales_stats(snap.orders, day_window(d, tz))
        out.append(
            {
                "date": d.isoformat(),
                "orders": st["orders"],
                "revenue": st["total"],
                "net": st["net"],
            }
        )
    return out


def range_trend(snap: Snapshot, tz: ZoneInfo, p: Plan) -> dict[str, object]:
    """Daily figures for a plan's days and, when it has one, its first comparison period's days
    (lined up by position)."""
    return {
        "days": len(p.current_days),
        "current": daily_series(snap, tz, p.current_days),
        "previous": daily_series(snap, tz, p.baseline_days[0]) if p.baseline_days else [],
        "baseline_label": p.baseline_label,
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
