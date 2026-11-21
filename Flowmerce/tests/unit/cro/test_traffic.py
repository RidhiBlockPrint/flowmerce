"""CRO traffic: what changed, location, weekday x hour, trends and the Overview visit tiles.

No network: Shopify is a fake GraphQL function that answers by query text."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from flowmerce.modules.cro import conversion, metrics, service, shopify, traffic
from flowmerce.modules.cro.data import Line, Order, Snapshot
from flowmerce.modules.cro.periods import days_window, plan, range_plan

NY = ZoneInfo("America/New_York")
WEEK = (date(2026, 11, 14), date(2026, 11, 20))
BEFORE = (date(2026, 11, 7), date(2026, 11, 13))


def fake(answer: Any) -> Any:
    """A GraphQL function whose rows come from answer(query); an Exception becomes a parse error."""

    def gql(_q: str, v: dict[str, Any] | None = None) -> dict[str, Any]:
        out = answer(str((v or {}).get("q")))
        if isinstance(out, Exception):
            return {"shopifyqlQuery": {"parseErrors": [str(out)], "tableData": None}}
        return {"shopifyqlQuery": {"parseErrors": None, "tableData": {"columns": [], "rows": out}}}

    return gql


@pytest.fixture(autouse=True)
def _clean_cache() -> Any:
    conversion.clear_cache()
    yield
    conversion.clear_cache()


def seg(label: str, sessions: int, done: int) -> dict[str, float]:
    return {"sessions": sessions, "sessions_that_completed_checkout": done}


def test_change_splits_into_traffic_and_conversion() -> None:
    now = {"mobile": seg("mobile", 1500, 45)}  # 3.0%
    before = {"mobile": seg("mobile", 1000, 20)}  # 2.0%
    rows, movers = traffic.changes("device", now, before, 7)
    r = rows[0]
    # traffic: +500 visits at 2% = +10; conversion: 1,500 visits x +1 pt = +15; together +25
    assert (r["traffic_effect"], r["conversion_effect"]) == (10.0, 15.0)
    assert r["purchases"] - r["previous_purchases"] == 25
    assert r["label"] == "Mobile" and r["sessions_change_pct"] == 50.0
    top = traffic.top_movers(movers, 1500)
    assert [m["kind"] for m in top] == ["conversion", "traffic"]
    assert top[0]["text"].startswith("Mobile conversion rose from 2.0% to 3.0%")
    assert top[0]["good"] is True
    assert traffic.top_movers(movers, 499) == []  # too few visits to explain anything


def test_small_segments_are_not_movers_and_channels_get_revenue() -> None:
    now = {"email": seg("email", 50, 5), "social": seg("social", 900, 18)}
    before = {"email": seg("email", 40, 1), "social": seg("social", 1000, 30)}
    sales = {"social": {"total_sales": 1800.0, "orders": 18}}
    old = {"social": {"total_sales": 3000.0, "orders": 30}}
    rows, movers = traffic.changes("channel", now, before, 7, sales, old)
    social = next(r for r in rows if r["key"] == "social")
    assert social["revenue_per_session"] == 2.0 and social["previous_revenue_per_session"] == 3.0
    assert social["revenue_per_session_change_pct"] == -33.3
    assert {m["segment"] for m in movers} == {"Social"}  # email has under 300 visits a week
    assert next(r for r in rows if r["key"] == "email")["revenue_per_session"] is None


def test_where_changed_reads_shopify_and_reports_failed_extras() -> None:
    def answer(q: str) -> Any:
        assert "human_or_bot_session = 'Human'" in q or "FROM sales" in q
        if "FROM sales" in q:
            return ValueError("no sales access")
        field = "session_device_type" if "session_device_type" in q else "referrer_source"
        big = "2026-11-14" in q
        return [
            {
                field: "mobile" if field == "session_device_type" else "social",
                "sessions": "1500" if big else "1000",
                "sessions_that_completed_checkout": "45" if big else "20",
            },
        ]

    out = traffic.where_changed("TEST", WEEK, BEFORE, fake(answer))
    assert out["total_sessions"] == 1500 and out["revenue_available"] is False
    assert set(out["errors"]) == {"sales_cur", "sales_prev"}
    assert out["device"][0]["conversion_effect"] == 15.0
    assert "revenue_per_session" not in out["channel"][0]


def test_where_changed_fails_when_sessions_fail() -> None:
    with pytest.raises(shopify.AnalyticsError):
        traffic.where_changed("TEST", WEEK, BEFORE, fake(lambda q: ValueError("down")))


def test_geo_rows_and_states() -> None:
    def answer(q: str) -> Any:
        if "session_region" in q:
            assert "session_country_code = 'US'" in q
            return [
                {
                    "session_region": "California",
                    "sessions": "500",
                    "sessions_with_cart_additions": "50",
                    "sessions_that_completed_checkout": "10",
                }
            ]
        now = "2026-11-14" in q
        return [
            {
                "session_country": "United States",
                "sessions": "900" if now else "800",
                "sessions_with_cart_additions": "90",
                "sessions_that_completed_checkout": "27" if now else "16",
            },
            {
                "session_country": "India",
                "sessions": "100" if now else "5",
                "sessions_with_cart_additions": "1",
                "sessions_that_completed_checkout": "0",
            },
        ]

    out = traffic.geo("TEST", WEEK, BEFORE, fake(answer))
    us, india = out["countries"]
    assert (us["conversion_rate"], us["previous_conversion_rate"], us["conversion_change_pts"]) == (
        3.0,
        2.0,
        1.0,
    )
    assert us["share_pct"] == 90.0 and india["share_pct"] == 10.0
    assert india["conversion_change_pts"] is None  # 5 visits before: too few to compare
    assert out["us_states"][0]["label"] == "California"


def test_heat_grid_puts_utc_hours_in_store_time() -> None:
    rows = [
        # 01:00 UTC on Sat 14 Nov is 20:00 on Fri 13 Nov in New York: outside the window.
        {"hour": "2026-11-14T01:00:00Z", "sessions": "40", "sessions_that_completed_checkout": "4"},
        # 15:00 UTC = 10:00 Saturday in New York; asked twice (overlapping pieces), counted once.
        {"hour": "2026-11-14T15:00:00Z", "sessions": "40", "sessions_that_completed_checkout": "2"},
        {"hour": "2026-11-14T15:00:00Z", "sessions": "40", "sessions_that_completed_checkout": "2"},
        {"hour": "2026-11-15T16:00:00Z", "sessions": "5", "sessions_that_completed_checkout": "1"},
    ]
    grid = traffic.heat_grid(rows, NY, *WEEK)
    cell = {(c["weekday"], c["hour"]): c for c in grid["cells"]}
    assert cell[(5, 10)]["sessions"] == 40 and cell[(5, 10)]["cvr"] == 5.0
    assert cell[(6, 11)]["cvr"] is None  # 5 visits: too few for a rate
    assert grid["hours_with_data"] == 2 and len(grid["cells"]) == 7 * 24
    assert cell[(4, 20)]["sessions"] == 0


def test_heatmap_asks_in_week_pieces() -> None:
    seen: list[str] = []

    def answer(q: str) -> Any:
        seen.append(q)
        return [
            {
                "hour": "2026-11-14T15:00:00Z",
                "sessions": "30",
                "sessions_that_completed_checkout": "3",
            }
        ]

    traffic.heatmap("TEST", date(2026, 10, 24), date(2026, 11, 20), NY, fake(answer))
    assert len(seen) == 4 and all("TIMESERIES hour" in q for q in seen)
    conversion.clear_cache()
    with pytest.raises(shopify.AnalyticsError):
        traffic.heatmap("TEST", *WEEK, NY, fake(lambda q: []))


def test_trends_aov_and_channel_shares() -> None:
    def answer(q: str) -> Any:
        if "sales_channel" in q:
            return [
                {"sales_channel": "Online Store", "total_sales": "900", "orders": "9"},
                {"sales_channel": "Shop", "total_sales": "100", "orders": "1"},
            ]
        return [{"day": "2026-11-14", "average_order_value": "101.878", "orders": "70"}]

    out = traffic.trends("TEST", WEEK, None, fake(answer))
    assert out["aov"] == [{"date": "2026-11-14", "aov": 101.88, "orders": 70}]
    assert [c["share_pct"] for c in out["channels"]] == [90.0, 10.0]
    assert out["previous_aov"] == []


# ----------------------------------------------------------------------------- service windows
NOW = datetime(2026, 11, 21, 15, 0, tzinfo=UTC)  # Saturday 21 Nov, 10:00 in New York


def test_session_windows_leave_today_out_and_line_up_the_comparison() -> None:
    today = date(2026, 11, 21)
    p = range_plan(date(2026, 11, 15), today, "previous", NY, NOW)
    cur, base = service._windows(p, today)
    assert cur == (date(2026, 11, 15), date(2026, 11, 20))
    assert base == (date(2026, 11, 8), date(2026, 11, 13))
    only_today = range_plan(today, today, "last_week", NY, NOW)
    assert service._windows(only_today, today)[0] == (today, today)
    none = range_plan(date(2026, 11, 14), date(2026, 11, 20), "none", NY, NOW)
    assert service._windows(none, today)[1] is None


def test_visit_tiles_only_for_complete_days() -> None:
    p = plan("last7", "", NY, NOW)
    kpis: dict[str, Any] = {
        "revenue": {"value": 2000.0, "baseline_value": 1500.0},
        "conversion_rate": {"sessions": 1000, "baseline_sessions": 1000.0},
    }
    service._visit_blocks(kpis, p)
    assert kpis["sessions"]["value"] == 1000
    assert (
        kpis["revenue_per_session"]["value"],
        kpis["revenue_per_session"]["baseline_value"],
    ) == (
        2.0,
        1.5,
    )
    partial = range_plan(date(2026, 11, 15), date(2026, 11, 21), "previous", NY, NOW)
    kpis.pop("sessions"), kpis.pop("revenue_per_session")
    service._visit_blocks(kpis, partial)
    assert "sessions" in kpis and "revenue_per_session" not in kpis
    empty: dict[str, Any] = {"conversion_rate": {"sessions": None}}
    service._visit_blocks(empty, p)
    assert "sessions" not in empty


# ----------------------------------------------------------------------------- order copy figures
def _order(oid: int, at: datetime, subtotal: float, cancelled: bool = False) -> Order:
    return Order(
        oid,
        f"#{oid}",
        at,
        at if cancelled else None,
        "paid",
        "USD",
        subtotal,
        subtotal,
        0.0,
        0.0,
        0.0,
        0.0,
    )


def _line(oid: int, at: datetime, qty: int) -> Line:
    return Line(oid, at, 1, "Quilt", "Quilts", "", qty, 10.0)


def test_order_values_and_free_shipping() -> None:
    at = datetime(2026, 11, 18, 17, tzinfo=UTC)
    values = [10, 30, 45, 49, 80, 120, 400]
    orders = tuple(_order(i, at, v) for i, v in enumerate(values)) + (_order(99, at, 70, True),)
    lines = tuple(_line(i, at, q) for i, q in enumerate([1, 1, 2, 3, 1, 6, 1])) + (
        _line(99, at, 9),
    )
    snap = Snapshot("TEST", orders, lines, at, at - timedelta(days=60))
    w = days_window(date(2026, 11, 18), date(2026, 11, 18), NY)
    out = metrics.order_values(snap, w, 50.0)
    assert out["orders"] == 7 and out["median"] == 49
    bars = {b["label"]: b for b in out["bars"]}
    assert bars["$25-49"]["orders"] == 3 and bars["$300+"]["orders"] == 1
    assert bars["$25-49"]["near_threshold"] is True and bars["$0-24"]["near_threshold"] is False
    # just under $50 = $40 up to $49.99: 45 and 49
    assert (out["near_threshold_orders"], out["near_threshold_share"]) == (2, 28.6)
    assert out["at_or_above_threshold_share"] == 42.9
    items = out["items"]
    assert items["single_item_share"] == 57.1 and items["bars"][4]["orders"] == 1  # 6 -> "5+"
    plain = metrics.order_values(snap, w, None)
    assert plain["near_threshold_share"] is None and not any(
        b["near_threshold"] for b in plain["bars"]
    )


def test_orders_by_hour_in_store_time() -> None:
    at = datetime(2026, 11, 18, 17, tzinfo=UTC)  # Wednesday 12:00 in New York
    snap = Snapshot("TEST", (_order(1, at, 50), _order(2, at, 50, True)), (), at, at)
    out = metrics.orders_by_hour(snap, NY, days_window(date(2026, 11, 18), date(2026, 11, 18), NY))
    cell = next(c for c in out["cells"] if c["orders"])  # type: ignore[attr-defined]
    assert (cell["weekday"], cell["hour"], out["total_orders"]) == (2, 12, 1)


def test_free_shipping_threshold_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from flowmerce.modules.cro.config import free_shipping_threshold

    monkeypatch.setenv("CRO_FREE_SHIPPING_RBP", "75")
    monkeypatch.setenv("CRO_FREE_SHIPPING_CPC", "nope")
    assert free_shipping_threshold("RBP") == 75.0
    assert free_shipping_threshold("CPC") is None
    monkeypatch.delenv("CRO_FREE_SHIPPING_RBP")
    assert free_shipping_threshold("RBP") is None
