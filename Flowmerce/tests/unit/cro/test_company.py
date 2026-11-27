"""Home's summary (cro.company): both stores added together, one store passed through unchanged.
Pure functions plus home_period with the store reports faked; no network, no database."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from flowmerce.modules.cro import company, goals, service
from flowmerce.modules.cro.periods import metric_block

PREV = "vs previous period"
D = date(2026, 11, 26)


def day(
    d: str, orders: int, revenue: float, sessions: int | None, done: int | None
) -> dict[str, Any]:
    cvr = round(done / sessions * 100, 2) if sessions and done is not None else None
    return {
        "date": d,
        "orders": orders,
        "revenue": revenue,
        "net": revenue - 10,
        "aov": round(revenue / orders, 2) if orders else None,
        "sessions": sessions,
        "completed_checkout": done,
        "conversion_rate": cvr,
    }


def test_periods_are_store_days() -> None:
    assert company.period_range("today", D) == (D, D)
    assert company.period_range("yesterday", D) == (date(2026, 11, 25),) * 2
    assert company.period_range("7d", D) == (date(2026, 11, 19), date(2026, 11, 25))
    assert company.period_range("30d", D) == (date(2026, 10, 27), date(2026, 11, 25))
    assert company.period_range("mtd", D) == (date(2026, 11, 1), D)
    with pytest.raises(service.InputError):
        company.period_range("week", D)


def test_store_days_join_sales_and_visits_and_work_out_the_average_order() -> None:
    trend = [
        {"date": "2026-11-25", "orders": 5, "revenue": 510.0, "net": 500.0},
        {"date": "2026-11-26", "orders": 2, "revenue": 210.0, "net": 200.0},
    ]
    conv = [
        {"date": "2026-11-25", "sessions": 400, "completed_checkout": 6, "conversion_rate": 1.5}
    ]
    days = company.store_days(trend, conv)
    assert days[0]["sessions"] == 400 and days[0]["aov"] == 102.0
    assert (
        days[1]["sessions"] is None and days[1]["conversion_rate"] is None
    )  # today: no visits yet


def test_days_are_added_and_rates_worked_out_again() -> None:
    a = [day("2026-11-25", 60, 6000.0, 3000, 66), day("2026-11-26", 10, 900.0, None, None)]
    b = [day("2026-11-25", 20, 2000.0, 1000, 14)]
    days = company.combine_days([a, b])
    assert [d["date"] for d in days] == ["2026-11-25"]  # the 26th only one store has
    d = days[0]
    assert (d["orders"], d["revenue"], d["sessions"], d["completed_checkout"]) == (
        80,
        8000.0,
        4000,
        80,
    )
    assert d["conversion_rate"] == 2.0  # 80 / 4000, not the average of 2.20% and 1.40%
    assert d["aov"] == 100.0


def test_no_visits_for_a_day_one_store_has_not_reported() -> None:
    d = company.combine_days(
        [[day("2026-11-25", 60, 5000.0, 3000, 66)], [day("2026-11-25", 20, 1500.0, None, None)]]
    )[0]
    assert d["sessions"] is None and d["conversion_rate"] is None and d["orders"] == 80


def test_series_are_added_by_position() -> None:
    s = company.combine_series(
        [
            [{"date": "2026-11-25", "orders": 3, "revenue": 300.0, "net": 290.0}],
            [{"date": "2026-11-25", "orders": 1, "revenue": 100.0, "net": 95.0}],
        ]
    )
    assert s == [{"date": "2026-11-25", "orders": 4, "revenue": 400.0, "net": 385.0}]
    assert company.combine_series([[{"date": "x", "orders": 1}], []]) == []


def kpis(orders: int, base_orders: int, revenue: float, base_revenue: float) -> dict[str, Any]:
    return {
        "orders": metric_block(orders, base_orders, orders < 20, PREV, 1),
        "revenue": metric_block(revenue, base_revenue, orders < 20, PREV),
    }


WEEK = (date(2026, 11, 19), date(2026, 11, 25))
WEEK_BEFORE = (date(2026, 11, 12), date(2026, 11, 18))


def visits_days() -> list[dict[str, Any]]:
    """Added days: 4,000 visits and 80 checkouts in the week, 5,000 and 75 the week before."""
    out = []
    for i in range(14):
        d = (date(2026, 11, 12) + timedelta(days=i)).isoformat()
        out.append(day(d, 10, 1000.0, 500, 0))
    out[6]["sessions"] = 5000 - 6 * 500  # the week before adds to 5,000 visits
    out[6]["completed_checkout"] = 75
    out[13]["sessions"] = 4000 - 6 * 500  # this week adds to 4,000 visits
    out[13]["completed_checkout"] = 80
    return out


def test_metrics_add_money_and_work_out_rates_from_the_sums() -> None:
    m = company.combine_metrics(
        [kpis(60, 50, 6000.0, 5000.0), kpis(20, 30, 2000.0, 2500.0)],
        visits_days(),
        WEEK,
        WEEK_BEFORE,
        partial=False,
    )
    assert m["orders"]["value"] == 80 and m["orders"]["baseline_value"] == 80
    assert m["revenue"]["value"] == 8000.0 and m["revenue"]["change_pct"] == 6.67
    assert m["aov"]["value"] == 100.0 and m["aov"]["baseline_value"] == 93.75
    assert m["conversion_rate"]["value"] == 2.0 and m["conversion_rate"]["baseline_value"] == 1.5
    assert m["sessions"]["value"] == 4000 and m["sessions"]["baseline_value"] == 5000
    assert m["revenue_per_session"]["value"] == 2.0
    assert m["orders"]["baseline_label"] == PREV


def test_too_early_is_judged_on_the_totals() -> None:
    m = company.combine_metrics(
        [kpis(12, 10, 900.0, 800.0), kpis(11, 10, 700.0, 600.0)], [], WEEK, WEEK_BEFORE, False
    )
    assert m["orders"]["too_early"] is False and m["orders"]["change_pct"] == 15.0


def test_today_has_no_conversion_and_no_revenue_per_visit() -> None:
    m = company.combine_metrics(
        [kpis(30, 20, 3000.0, 2000.0), kpis(10, 10, 900.0, 800.0)],
        [day("2026-11-26", 40, 3900.0, None, None)],
        (D, D),
        (date(2026, 11, 25),) * 2,
        partial=True,
    )
    assert m["conversion_rate"]["value"] is None and "revenue_per_session" not in m


def test_breakdown_lines_are_added_with_their_comparison() -> None:
    def part(gross: float, net: float) -> dict[str, Any]:
        return {
            "baseline_label": PREV,
            "rows": [
                {
                    "key": "gross",
                    "label": "Gross sales",
                    **metric_block(gross, gross - 100, False, PREV),
                },
                {"key": "net", "label": "Net sales", **metric_block(net, None, False, PREV)},
            ],
        }

    gross, net = company.combine_breakdown([part(1000.0, 900.0), part(500.0, 450.0)], False)["rows"]
    assert gross["value"] == 1500.0 and gross["baseline_value"] == 1300.0
    assert net["value"] == 1350.0 and net["baseline_value"] is None


def test_month_goal_adds_goals_and_works_out_the_pace() -> None:
    g = company.month_goal([200_000.0, 100_000.0], [150_000.0, 64_500.0], D)
    assert g is not None
    assert (g["goal"], g["sales"], g["pct"], g["day"], g["days"]) == (
        300_000.0,
        214_500.0,
        71.5,
        26,
        30,
    )
    assert g["pace_pct"] == 82.5  # 214,500 against 300,000 x 26 / 30 = 260,000
    assert company.month_goal([200_000.0, 0.0], [1.0, 1.0], D) is None  # one store has no goal
    assert company.month_goal([200_000.0], [None], D) is None


# ------------------------------------------------------------------ home_period with faked reports
NY, PHX = ZoneInfo("America/New_York"), ZoneInfo("America/Phoenix")
# 27 Nov 2026, 01:00 in New York = 26 Nov 23:00 in Phoenix: the stores are on different days
NOW = datetime(2026, 11, 27, 6, 0, tzinfo=UTC)
Calls = list[tuple[str, str, service.RangeQuery]]
STORE_TODAY = {"ridhi": "2026-11-27", "cpc": "2026-11-26"}


def span(rq: service.RangeQuery) -> list[str]:
    first, last = date.fromisoformat(rq.frm or ""), date.fromisoformat(rq.to or "")
    return [(first + timedelta(days=i)).isoformat() for i in range((last - first).days + 1)]


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> Calls:
    calls: Calls = []
    tz = {"ridhi": NY, "cpc": PHX}
    size = {"ridhi": 3, "cpc": 1}

    def ctx(brand: str) -> tuple[str, ZoneInfo, datetime]:
        if brand not in tz:
            raise service.InputError(f"Unknown brand {brand}")
        return brand.upper(), tz[brand], NOW

    def overview(brand: str, rq: service.RangeQuery) -> dict[str, Any]:
        calls.append(("overview", brand, rq))
        k = size[brand] * len(span(rq))
        return {
            "metrics": kpis(20 * k, 10 * k, 2000.0 * k, 1000.0 * k),
            "health": {"last_order_at": f"2026-11-27T0{size[brand]}:00:00+00:00"},
            "order_data": {"last_run_at": f"2026-11-27T0{size[brand]}:30:00+00:00"},
            "period_label": "Wed 25 Nov",
            "timezone": str(tz[brand]),
            "cvr_error": None,
        }

    def breakdown(brand: str, rq: service.RangeQuery) -> dict[str, Any]:
        k = size[brand]
        row = {"key": "net", "label": "Net sales", **metric_block(100.0 * k, 50.0 * k, False, PREV)}
        return {"rows": [row], "baseline_label": PREV, "too_early": False}

    def trend(brand: str, rq: service.RangeQuery) -> dict[str, Any]:
        calls.append(("trend", brand, rq))
        k = size[brand]
        rows = [{"date": d, "orders": k, "revenue": 10.0 * k, "net": 9.0 * k} for d in span(rq)]
        return {"current": rows, "previous": rows if rq.compare == "previous" else []}

    def conversion(brand: str, rq: service.RangeQuery) -> dict[str, Any]:
        k = size[brand]
        return {
            "trend": [
                {"date": d, "sessions": 100 * k, "completed_checkout": k, "conversion_rate": 1.0}
                for d in span(rq)
                if d < STORE_TODAY[brand]  # today is not reported yet
            ]
        }

    def goal(brand: str) -> dict[str, Any]:
        return {"brand": brand, "monthly_revenue": 30_000.0 * size[brand]}

    monkeypatch.setattr(service, "_ctx", ctx)
    monkeypatch.setattr(service, "overview", overview)
    monkeypatch.setattr(service, "sales_breakdown", breakdown)
    monkeypatch.setattr(service, "sales_trend", trend)
    monkeypatch.setattr(service, "conversion_trend", conversion)
    monkeypatch.setattr(goals, "goal", goal)
    return calls


def test_both_stores_use_the_earlier_stores_today_and_yesterday_by_default(fake: Calls) -> None:
    h = company.home_period(None, None)
    # New York is already on the 27th, Phoenix still on the 26th: both use the 26th as today
    assert (h["today"], h["from"], h["to"]) == ("2026-11-26", "2026-11-25", "2026-11-25")
    assert h["period"] == "yesterday" and h["brands"] == ["ridhi", "cpc"] and h["timezone"] is None
    assert h["metrics"]["orders"]["value"] == 80 and h["metrics"]["revenue"]["value"] == 8000.0
    assert h["metrics"]["conversion_rate"]["value"] == 1.0  # 4 checkouts / 400 visits on the 25th
    assert h["breakdown"]["rows"][0]["value"] == 400.0
    assert len(h["chart"]["current"]) == 14 and h["chart"]["current"][-1]["date"] == "2026-11-25"
    assert h["chart"]["current"][-1]["orders"] == 4 and len(h["chart"]["previous"]) == 14
    assert [b["share"] for b in h["by_brand"]] == [75.0, 25.0]
    assert h["goal"] is not None and h["goal"]["goal"] == 120_000.0 and h["goal"]["day"] == 26
    assert h["last_order_at"] == "2026-11-27T03:00:00+00:00"  # the newest order of either store
    assert h["orders_synced_at"] == "2026-11-27T01:30:00+00:00"  # the older store's last read
    reads = [rq for name, _, rq in fake if name == "overview" and rq.compare == "previous"]
    assert reads and all((rq.frm, rq.to) == ("2026-11-25", "2026-11-25") for rq in reads)


def test_seven_days_and_the_month_to_date(fake: Calls) -> None:
    # Ridhi alone: New York is already on the 27th
    w = company.home_period("ridhi", "7d")
    assert (w["from"], w["to"]) == ("2026-11-20", "2026-11-26")
    m = company.home_period("ridhi", "mtd")
    assert (m["from"], m["to"], m["is_partial"]) == ("2026-11-01", "2026-11-27", True)
    assert len(m["chart"]["current"]) == 27  # longer than 14 days: the chart covers the period


def test_one_store_is_passed_through_unchanged(fake: Calls) -> None:
    h = company.home_period("cpc", "yesterday")
    assert h["brands"] == ["cpc"] and h["by_brand"] == []
    assert h["metrics"]["orders"]["value"] == 20 and h["timezone"] == "America/Phoenix"
    assert {b for _, b, _ in fake} == {"cpc"}


def test_a_bad_period_or_brand_is_refused(fake: Calls) -> None:
    with pytest.raises(service.InputError):
        company.home_period(None, "week")
    with pytest.raises(service.InputError):
        company.home_period("all", None)
