"""CRO calendar ranges, comparisons, daily series and the Home summary. No network."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from flowmerce.modules.cro import conversion, data, metrics, service
from flowmerce.modules.cro.data import Order, Snapshot
from flowmerce.modules.cro.periods import RangeError, day_window, parse_day, range_plan
from flowmerce.modules.shipping.supabase import SupabaseError

NY = ZoneInfo("America/New_York")
NOW = datetime(2026, 11, 20, 15, 0, tzinfo=UTC)  # Fri 20 Nov 2026, 10:00 in New York


def order(oid: int, at: datetime, total: float = 100.0, refunded: float = 0.0) -> Order:
    return Order(oid, f"#{oid}", at, None, "paid", "USD", total, total, 0.0, 0.0, 0.0, refunded)


def at(d: date, hour: int = 12) -> datetime:
    return datetime(d.year, d.month, d.day, hour, tzinfo=NY).astimezone(UTC)


def test_previous_period_of_the_same_length() -> None:
    p = range_plan(date(2026, 11, 1), date(2026, 11, 15), "previous", NY, NOW)
    assert len(p.current_days) == 15 and not p.is_partial
    assert p.baseline_days[0][0] == date(2026, 10, 17) and p.baseline_days[0][-1] == date(
        2026, 10, 31
    )
    assert p.baselines[0].end == p.current.start
    assert (
        p.label == "1 Nov 2026 - 15 Nov 2026 (15 days)"
        and p.baseline_label == "vs previous 15 days"
    )


def test_single_day_against_four_weekdays_and_last_week() -> None:
    p = range_plan(date(2026, 11, 19), date(2026, 11, 19), "4week_avg", NY, NOW)
    assert [d[0] for d in p.baseline_days] == [
        date(2026, 11, 12),
        date(2026, 11, 5),
        date(2026, 10, 29),
        date(2026, 10, 22),
    ]
    assert p.label == "Thu 19 Nov 2026"
    w = range_plan(date(2026, 11, 19), date(2026, 11, 19), "last_week", NY, NOW)
    assert (
        w.baseline_days == ((date(2026, 11, 12),),) and w.baseline_label == "vs same Thu last week"
    )


def test_four_week_average_only_for_one_day_and_none_has_no_baseline() -> None:
    p = range_plan(date(2026, 11, 10), date(2026, 11, 16), "4week_avg", NY, NOW)
    assert p.compare == "previous"
    n = range_plan(date(2026, 11, 10), date(2026, 11, 16), "none", NY, NOW)
    assert n.baselines == () and n.baseline_days == ()


def test_a_range_reaching_today_runs_until_now_and_compares_the_same_elapsed_time() -> None:
    p = range_plan(date(2026, 11, 18), date(2026, 11, 30), "last_week", NY, NOW)
    assert p.is_partial and p.current_days[-1] == date(2026, 11, 20)  # the future is cut off
    assert p.current.end == NOW
    (base,) = p.baselines
    assert base.end - base.start == p.current.end - p.current.start
    assert "so far" in p.label


def test_bad_ranges_are_refused() -> None:
    with pytest.raises(RangeError):
        range_plan(date(2026, 11, 15), date(2026, 11, 1), "previous", NY, NOW)
    with pytest.raises(RangeError):
        range_plan(date(2026, 12, 1), date(2026, 12, 2), "previous", NY, NOW)
    with pytest.raises(RangeError):
        range_plan(date(2025, 1, 1), date(2026, 11, 19), "previous", NY, NOW)
    with pytest.raises(RangeError):
        parse_day("19/11/2026")
    assert parse_day("") is None and parse_day("2026-11-19") == date(2026, 11, 19)


def test_no_comparison_gives_no_change() -> None:
    d = date(2026, 11, 19)
    snap = Snapshot(
        "RBP", tuple(order(i, at(d)) for i in range(25)), (), NOW, NOW - timedelta(days=90)
    )
    k = metrics.order_kpis(snap, range_plan(d, d, "none", NY, NOW))
    assert k["orders"]["value"] == 25 and k["orders"]["baseline_value"] is None
    assert k["orders"]["change_pct"] is None


def test_daily_series_and_trend_line_up() -> None:
    days = [date(2026, 11, 18), date(2026, 11, 19)]
    snap = Snapshot(
        "RBP",
        (
            order(1, at(days[0]), 120, refunded=20),
            order(2, at(days[1]), 80),
            order(3, at(date(2026, 11, 16)), 50),
        ),
        (),
        NOW,
        NOW - timedelta(days=90),
    )
    assert metrics.daily_series(snap, NY, days) == [
        {"date": "2026-11-18", "orders": 1, "revenue": 120.0, "net": 100.0},
        {"date": "2026-11-19", "orders": 1, "revenue": 80.0, "net": 80.0},
    ]
    t = metrics.range_trend(snap, NY, range_plan(days[0], days[1], "previous", NY, NOW))
    assert [r["date"] for r in t["previous"]] == ["2026-11-16", "2026-11-17"]
    assert t["previous"][0]["orders"] == 1


def test_shopifyql_uses_explicit_dates_and_leaves_today_out() -> None:
    conversion.clear_cache()
    seen: list[str] = []

    def gql(_q: str, v: dict[str, Any] | None = None) -> dict[str, Any]:
        seen.append((v or {})["q"])
        rows = [
            {"day": "2026-11-18", "sessions": "100", "sessions_that_completed_checkout": "2"},
            {"day": "2026-11-19", "sessions": "300", "sessions_that_completed_checkout": "9"},
        ]
        return {"shopifyqlQuery": {"parseErrors": None, "tableData": {"columns": [], "rows": rows}}}

    rows = conversion.daily_between(
        "T", date(2026, 11, 18), date(2026, 11, 20), date(2026, 11, 20), gql
    )
    assert "SINCE 2026-11-18 UNTIL 2026-11-19" in seen[0]
    assert conversion.totals(rows)["conversion_rate"] == 2.75  # 11 / 400
    assert (
        conversion.daily_between(
            "T", date(2026, 11, 20), date(2026, 11, 20), date(2026, 11, 20), gql
        )
        == []
    )
    conversion.clear_cache()


def test_home_never_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "store_timezone", lambda _s: NY)

    def down(_store: str, force: bool = False) -> Snapshot:
        raise SupabaseError("connection_failed", "Could not reach Supabase (ConnectError).")

    monkeypatch.setattr(data, "snapshot", down)
    out = service.home(None)
    assert [(s["brand"], s["state"]) for s in out["stores"]] == [
        ("ridhi", "connection_failed"),
        ("cpc", "connection_failed"),
    ]
    with pytest.raises(service.InputError):
        service.home("nope")


def test_home_summary_figures(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime.now(UTC)
    today = now.astimezone(NY).date()
    y = today - timedelta(days=1)
    orders = [order(i, at(y, 1) + timedelta(minutes=i), 50) for i in range(30)]
    snap = Snapshot("RBP", tuple(orders), (), now, now - timedelta(days=63))
    monkeypatch.setattr(service, "store_timezone", lambda _s: NY)
    monkeypatch.setattr(data, "snapshot", lambda _s, force=False: snap)
    monkeypatch.setattr(
        data, "sync_state", lambda _s: {"cursor": "c", "last_run_at": "t", "last_status": "ok"}
    )
    monkeypatch.setattr(data, "first_order_day", lambda _s: "2026-09-20")

    def no_reports(*_a: Any, **_k: Any) -> Any:
        from flowmerce.modules.cro.shopify import AnalyticsError

        raise AnalyticsError("reports_access_missing", "no")

    monkeypatch.setattr(conversion, "daily", no_reports)
    (s,) = service.home("ridhi")["stores"]
    assert s["state"] == "ok" and s["yesterday"]["orders"]["value"] == 30
    assert s["yesterday"]["net_sales"]["value"] == 1500.0
    assert s["conversion"] is None and s["conversion_state"] == "reports_access_missing"
    assert len(s["trend"]) == 14 and s["trend"][-1]["date"] == y.isoformat()
    assert s["order_data"]["available_from"] == "2026-09-20"
    assert day_window(y, NY).contains(orders[0].placed_at)
