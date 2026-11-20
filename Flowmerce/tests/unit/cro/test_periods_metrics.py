"""CRO periods and order figures: pure functions, no network, no database."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from flowmerce.modules.cro import metrics
from flowmerce.modules.cro.data import Line, Order, Snapshot
from flowmerce.modules.cro.periods import day_window, metric_block, pct_change, plan

LA = ZoneInfo("America/Los_Angeles")
# Thursday 19 Nov 2026, 10:00 in Los Angeles
NOW = datetime(2026, 11, 19, 18, 0, tzinfo=UTC)


def order(
    oid: int,
    at: datetime,
    total: float = 100.0,
    *,
    cancelled: bool = False,
    status: str = "paid",
    **money: float,
) -> Order:
    return Order(
        id=oid,
        name=f"#{oid}",
        placed_at=at,
        cancelled_at=at if cancelled else None,
        financial_status=status,
        currency="USD",
        total=total,
        subtotal=money.get("subtotal", total),
        discounts=money.get("discounts", 0.0),
        shipping=money.get("shipping", 0.0),
        tax=money.get("tax", 0.0),
        refunded=money.get("refunded", 0.0),
    )


def line(
    oid: int,
    at: datetime,
    title: str,
    qty: int = 1,
    price: float = 50.0,
    pid: int | None = 1,
    ptype: str = "",
    tags: str = "",
) -> Line:
    return Line(
        order_id=oid,
        placed_at=at,
        product_id=pid,
        title=title,
        product_type=ptype,
        tags=tags,
        quantity=qty,
        unit_price=price,
    )


def snap(orders: list[Order], lines: list[Line] | None = None) -> Snapshot:
    return Snapshot("RBP", tuple(orders), tuple(lines or []), NOW, NOW - timedelta(days=63))


def local(d: date, hour: int = 12) -> datetime:
    return datetime(d.year, d.month, d.day, hour, tzinfo=LA).astimezone(UTC)


# ------------------------------------------------------------------------------------------ periods
def test_yesterday_against_four_same_weekdays() -> None:
    p = plan("yesterday", "4week_avg", LA, NOW)
    assert p.target_day == date(2026, 11, 18)
    assert p.label.startswith("Yesterday (Wed 18 Nov")
    assert p.baseline_label == "vs 4-week Wed average"
    assert [d[0] for d in p.baseline_days] == [
        date(2026, 11, 11),
        date(2026, 11, 4),
        date(2026, 10, 28),
        date(2026, 10, 21),
    ]
    assert all(d[0].weekday() == 2 for d in p.baseline_days)
    # local midnight to midnight
    assert p.current == day_window(date(2026, 11, 18), LA)
    assert p.current.start == datetime(2026, 11, 18, 8, 0, tzinfo=UTC)


def test_unknown_values_fall_back_to_defaults() -> None:
    p = plan("bogus", "bogus", LA, NOW)
    assert (p.period, p.compare) == ("yesterday", "4week_avg")


def test_today_compares_same_elapsed_time_last_week() -> None:
    p = plan("today", "4week_avg", LA, NOW)
    assert p.is_partial and p.compare == "last_week"
    elapsed = p.current.end - p.current.start
    assert elapsed == timedelta(hours=10)
    (base,) = p.baselines
    assert base.end - base.start == elapsed
    assert base.start == day_window(date(2026, 11, 12), LA).start


def test_last7_against_prior7() -> None:
    p = plan("last7", "last_week", LA, NOW)
    assert p.current_days[0] == date(2026, 11, 12) and p.current_days[-1] == date(2026, 11, 18)
    assert p.baseline_days[0][0] == date(2026, 11, 5) and p.baseline_days[0][-1] == date(
        2026, 11, 11
    )
    assert p.baselines[0].end == p.current.start


def test_metric_block_too_early_gives_no_change() -> None:
    assert metric_block(10, 20, True, "x")["change_pct"] is None
    assert metric_block(10, 20, True, "x")["change_abs"] is None
    assert metric_block(30, 20, False, "x")["change_pct"] == 50.0
    assert pct_change(5, 0) is None and pct_change(None, 3) is None


# ------------------------------------------------------------------------------------------ order
# figures
def test_cancelled_orders_leave_sales_out() -> None:
    d = date(2026, 11, 18)
    s = snap(
        [order(1, local(d), 100), order(2, local(d), 50), order(3, local(d), 999, cancelled=True)]
    )
    stats = metrics.order_stats(s.orders, day_window(d, LA))
    assert stats == {"orders": 2, "revenue": 150.0, "aov": 75.0}


def test_sales_breakdown_formulas() -> None:
    d = date(2026, 11, 18)
    o = order(1, local(d), 120, subtotal=90, discounts=10, shipping=20, tax=10, refunded=30)
    stats = metrics.sales_stats([o], day_window(d, LA))
    assert stats["gross"] == 100.0  # subtotal + discounts
    assert stats["net"] == 60.0  # subtotal - refunded
    assert stats["total"] == 120.0 and stats["returns"] == 30.0


def test_order_kpis_too_early_under_twenty_orders() -> None:
    d = date(2026, 11, 18)
    s = snap([order(i, local(d)) for i in range(5)])
    kpis = metrics.order_kpis(s, plan("yesterday", "last_week", LA, NOW))
    assert kpis["orders"]["value"] == 5 and kpis["orders"]["too_early"] is True
    assert kpis["orders"]["change_pct"] is None


def test_order_kpis_compares_against_average() -> None:
    d = date(2026, 11, 18)
    orders = [order(i, local(d)) for i in range(30)]
    # 20 orders on each of the four previous Wednesdays
    for w in range(1, 5):
        orders += [order(1000 * w + i, local(d - timedelta(days=7 * w))) for i in range(20)]
    kpis = metrics.order_kpis(snap(orders), plan("yesterday", "4week_avg", LA, NOW))
    assert kpis["orders"]["baseline_value"] == 20.0
    assert kpis["orders"]["change_pct"] == 50.0


def test_order_health_counts() -> None:
    at = NOW - timedelta(days=1)
    s = snap(
        [
            order(1, at),
            order(2, at, status="refunded"),
            order(3, at, cancelled=True),
            order(4, at, status="pending"),
            order(5, NOW - timedelta(days=40)),
        ]
    )
    h = metrics.order_health(s, NOW, 30)
    assert h["total_orders"] == 4
    assert (
        h["paid"]["count"],
        h["refunded"]["count"],
        h["cancelled"]["count"],
        h["pending"]["count"],
    ) == (1, 1, 1, 1)


def test_product_performance_groups_and_skips_cancelled() -> None:
    d = date(2026, 11, 18)
    at = local(d)
    s = snap(
        [order(1, at), order(2, at), order(3, at, cancelled=True)],
        [
            line(1, at, "Quilt", 2, 100, pid=1),
            line(2, at, "Pillow", 1, 20, pid=2),
            line(2, at, "Throw", 1, 50, pid=3),
            line(3, at, "Quilt", 9, 100, pid=1),
        ],
    )
    rows = metrics.product_performance(s, LA, NOW.astimezone(LA).date(), 30)["products"]
    assert [r["name"] for r in rows] == ["Quilt", "Throw", "Pillow"]
    assert rows[0]["revenue"] == 200.0 and rows[0]["quantity"] == 2
    assert rows[0]["performance_status"] == "top" and rows[-1]["performance_status"] == "low"


def test_keyword_matches_title_type_or_tags_and_ignores_cancelled() -> None:
    a, b, c = NOW - timedelta(hours=30), NOW - timedelta(hours=5), NOW - timedelta(hours=1)
    s = snap(
        [order(1, a), order(2, b), order(3, c, cancelled=True)],
        [
            line(1, a, "Bedspread", ptype="Quilts"),
            line(2, b, "Cover", tags="kantha, QUILT"),
            line(3, c, "Hand block quilt"),
        ],
    )
    last = metrics.last_order_with(s, "quilt")
    assert last is not None and last.id == 2
    assert metrics.last_order_with(s, "sofa") is None


def test_declining_products() -> None:
    today = NOW.astimezone(LA).date()
    old, new = local(today - timedelta(days=10)), local(today - timedelta(days=2))
    s = snap(
        [order(1, old), order(2, new)],
        [line(1, old, "Quilt", 8, 100, pid=1), line(2, new, "Quilt", 2, 100, pid=1)],
    )
    (d,) = metrics.declining_products(s, LA, NOW)
    assert d["name"] == "Quilt" and d["drop_percent"] == 75.0
    assert (d["prior_units"], d["recent_units"]) == (8, 2)


def test_declining_products_ignores_low_sellers() -> None:
    today = NOW.astimezone(LA).date()
    old = local(today - timedelta(days=10))
    s = snap(
        [order(1, old)],
        [
            line(1, old, "Two quilts", 2, 160, pid=1),  # $320 but only 2 units: noise
            line(1, old, "Cheap napkins", 9, 20, pid=2),  # 9 units but only $180: noise
            line(1, old, "Tablecloth", 5, 60, pid=3),  # 5 units and $300: counts
        ],
    )
    assert [d["name"] for d in metrics.declining_products(s, LA, NOW)] == ["Tablecloth"]


def test_sales_trend_aligns_previous_period() -> None:
    today = NOW.astimezone(LA).date()
    s = snap(
        [
            order(1, local(today - timedelta(days=1)), 10),
            order(2, local(today - timedelta(days=8)), 7),
        ]
    )
    t = metrics.sales_trend(s, LA, today, 7)
    assert t["current"][-1] == {"date": "2026-11-18", "revenue": 10.0, "orders": 1}
    assert t["previous"][-1] == {"date": "2026-11-11", "revenue": 7.0, "orders": 1}
    assert len(t["current"]) == len(t["previous"]) == 7
