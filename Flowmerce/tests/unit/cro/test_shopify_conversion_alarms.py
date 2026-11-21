"""CRO Shopify mapping, ShopifyQL handling, conversion figures, alarm rules and recommendations.

No network: Shopify is a fake GraphQL function."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from flowmerce.modules.cro import alarms, conversion, recommendations, shopify


def node(**over: Any) -> dict[str, Any]:
    base = {
        "legacyResourceId": "5001",
        "name": "#RBP1",
        "createdAt": "2026-11-18T10:00:00Z",
        "updatedAt": "2026-11-18T11:00:00Z",
        "cancelledAt": None,
        "test": False,
        "displayFinancialStatus": "PAID",
        "currentTotalPriceSet": {"shopMoney": {"amount": "120.50", "currencyCode": "USD"}},
        "currentSubtotalPriceSet": {"shopMoney": {"amount": "100"}},
        "currentTotalDiscountsSet": {"shopMoney": {"amount": "5"}},
        "currentShippingPriceSet": {"shopMoney": {"amount": "15"}},
        "currentTotalTaxSet": {"shopMoney": {"amount": "5.5"}},
        "totalRefundedSet": {"shopMoney": {"amount": "0"}},
        "lineItems": {
            "nodes": [
                {
                    "title": "Quilt",
                    "quantity": 2,
                    "originalUnitPriceSet": {"shopMoney": {"amount": "50"}},
                    "product": {
                        "legacyResourceId": "77",
                        "productType": "Quilts",
                        "tags": ["kantha", "queen"],
                    },
                },
                {
                    "title": "Custom item",
                    "quantity": 1,
                    "originalUnitPriceSet": {"shopMoney": {"amount": "3"}},
                    "product": None,
                },
            ]
        },
    }
    base.update(over)
    return base


def test_order_row_maps_money_and_lines() -> None:
    row = shopify.order_row("RBP", node())
    assert row is not None
    assert (row["id"], row["total"], row["subtotal"], row["tax"]) == (5001, 120.5, 100.0, 5.5)
    assert row["lines"][0] == {
        "line_no": 1,
        "product_id": 77,
        "title": "Quilt",
        "product_type": "Quilts",
        "tags": "kantha, queen",
        "quantity": 2,
        "unit_price": 50.0,
    }
    assert row["lines"][1]["product_id"] is None
    assert "email" not in row and "customer" not in str(row).lower()


def test_test_orders_are_skipped() -> None:
    assert shopify.order_row("RBP", node(test=True)) is None


def test_shopifyql_rows_as_lists_or_objects() -> None:
    def gql(_q: str, _v: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "shopifyqlQuery": {
                "parseErrors": None,
                "tableData": {
                    "columns": [{"name": "day"}, {"name": "sessions"}],
                    "rows": [["2026-11-17", "10"], {"day": "2026-11-18", "sessions": "12"}],
                },
            }
        }

    assert shopify.shopifyql(gql, "q") == [
        {"day": "2026-11-17", "sessions": "10"},
        {"day": "2026-11-18", "sessions": "12"},
    ]


def test_missing_read_reports_is_explained() -> None:
    def gql(_q: str, _v: dict[str, Any] | None = None) -> dict[str, Any]:
        raise RuntimeError(
            "Shopify: Access denied for shopifyqlQuery field. Required access: `read_reports`"
        )

    with pytest.raises(shopify.AnalyticsError) as e:
        shopify.shopifyql(gql, "q")
    assert e.value.state == "reports_access_missing"


def test_parse_errors_are_reported() -> None:
    def gql(_q: str, _v: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"shopifyqlQuery": {"parseErrors": ["bad"], "tableData": None}}

    with pytest.raises(shopify.AnalyticsError) as e:
        shopify.shopifyql(gql, "q")
    assert e.value.state == "query_error"


def test_funnel_rates_from_counts() -> None:
    r = conversion.funnel_row(
        "2026-11-18",
        {
            "sessions": "2000",
            "sessions_with_cart_additions": "200",
            "sessions_that_reached_checkout": "100",
            "sessions_that_completed_checkout": "50",
        },
    )
    assert (r["conversion_rate"], r["cart_rate"], r["checkout_rate"]) == (2.5, 10.0, 5.0)
    assert r["checkout_completion_rate"] == 50.0 and r["cart_abandonment_rate"] == 75.0
    assert conversion.funnel_row("x", {})["conversion_rate"] is None


def test_daily_skips_today_and_cvr_comparison() -> None:
    conversion.clear_cache()
    rows = [
        {
            "day": d,
            "sessions": "1000",
            "sessions_with_cart_additions": "0",
            "sessions_that_reached_checkout": "0",
            "sessions_that_completed_checkout": str(c),
        }
        for d, c in (("2026-11-17", 30), ("2026-11-18", 21), ("2026-11-19", 5))
    ]

    def gql(_q: str, _v: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"shopifyqlQuery": {"parseErrors": None, "tableData": {"columns": [], "rows": rows}}}

    today = date(2026, 11, 19)
    daily = conversion.daily("TEST", today, 7, gql)
    assert [r["date"] for r in daily] == ["2026-11-17", "2026-11-18"]
    cmp = conversion.cvr_comparison(daily, today)
    assert (cmp["previous_cvr"], cmp["yesterday_cvr"], cmp["drop_percent"]) == (3.0, 2.1, 30.0)
    assert alarms.evaluate_cvr(cmp, 20) == "triggered"
    assert alarms.evaluate_cvr(cmp, 40) == "normal"
    assert alarms.evaluate_cvr({"drop_percent": None}, 20) == "insufficient_data"
    conversion.clear_cache()


def test_product_gap_rule() -> None:
    now = datetime(2026, 11, 19, 12, tzinfo=UTC)
    assert alarms.evaluate_gap(None, now, 12) == ("no_matching_orders", None)
    assert alarms.evaluate_gap(now - timedelta(hours=13), now, 12) == ("triggered", 13.0)
    assert alarms.evaluate_gap(now - timedelta(hours=2), now, 12) == ("normal", 2.0)


def test_inactive_rule_is_not_evaluated() -> None:
    assert alarms.check_rule(
        {"is_active": False, "kind": "cvr_drop"}, "RBP", date(2026, 11, 19)
    ) == {"status": "rule_inactive"}


def test_recommendations_need_evidence() -> None:
    assert (
        recommendations.build(
            product_alarms=[], cvr=None, funnel=None, today_revenue=None, declines=[], health=None
        )
        == []
    )
    recs = recommendations.build(
        product_alarms=[
            {
                "status": "alarm_active",
                "keyword": "quilt",
                "hours_elapsed": 14.0,
                "threshold_hours": 12.0,
                "last_order": "#RBP9",
            }
        ],
        cvr={
            "drop_percent": 16.0,
            "yesterday_cvr": 2.1,
            "previous_cvr": 2.5,
            "yesterday_date": "2026-11-18",
            "previous_date": "2026-11-17",
        },
        funnel=None,
        today_revenue={"too_early": True, "change_pct": None},
        declines=[],
        health={"total_orders": 5},
    )
    assert [r["priority"] for r in recs] == ["High", "Medium"]
    assert recs[0]["title"].startswith("Orders for 'quilt'")


def _fake(rows_for: Any) -> Any:
    seen: list[str] = []

    def gql(_q: str, v: dict[str, Any] | None = None) -> dict[str, Any]:
        q = str((v or {}).get("q"))
        seen.append(q)
        out = rows_for(q)
        if isinstance(out, Exception):
            return {"shopifyqlQuery": {"parseErrors": [str(out)], "tableData": None}}
        return {"shopifyqlQuery": {"parseErrors": None, "tableData": {"columns": [], "rows": out}}}

    gql.seen = seen  # type: ignore[attr-defined]
    return gql


def test_session_queries_leave_bots_out() -> None:
    conversion.clear_cache()
    gql = _fake(lambda _q: [])
    conversion.daily("TEST", date(2026, 11, 19), 7, gql)
    conversion.daily_between("TEST", date(2026, 11, 1), date(2026, 11, 7), date(2026, 11, 19), gql)
    conversion.segments("TEST", "device", 7, gql)
    assert gql.seen and all("human_or_bot_session = 'Human'" in q for q in gql.seen)
    conversion.clear_cache()


def test_cvr_against_the_4_week_weekday_average() -> None:
    today = date(2026, 11, 21)  # yesterday: Friday 20 Nov

    def row(day: date, sessions: int, cvr: float) -> dict[str, Any]:
        return {"date": day.isoformat(), "sessions": sessions, "conversion_rate": cvr}

    y = date(2026, 11, 20)
    rows = [row(y, 1000, 1.5), row(y - timedelta(days=1), 1000, 9.0)]  # the day before is ignored
    rows += [row(y - timedelta(days=7 * w), 1000, 2.0 + w * 0.5) for w in range(1, 5)]
    cmp = conversion.cvr_vs_weekday_average(rows, today)
    assert cmp["yesterday_weekday"] == "Friday" and cmp["baseline_cvr"] == 3.25
    assert cmp["drop_percent"] == round((3.25 - 1.5) / 3.25 * 100, 2)
    assert alarms.evaluate_cvr(cmp, 20) == "triggered"
    # Too few sessions yesterday, or too few usable past weeks: not judged.
    quiet = [row(y, 20, 0.0), *rows[2:]]
    assert conversion.cvr_vs_weekday_average(quiet, today)["reason"] == "too_few_sessions_yesterday"
    thin = [rows[0], row(y - timedelta(days=7), 1000, 3.0), row(y - timedelta(days=14), 10, 3.0)]
    cmp = conversion.cvr_vs_weekday_average(thin, today)
    assert cmp["drop_percent"] is None and cmp["reason"] == "not_enough_past_weeks"
    assert alarms.evaluate_cvr(cmp, 20) == "insufficient_data"


def test_sales_daily_keeps_returns_positive_and_fills_empty_days() -> None:
    conversion.clear_cache()
    gql = _fake(
        lambda _q: [
            {
                "day": "2026-11-18", "orders": "70", "gross_sales": "7631.09",
                "discounts": "-499.62", "returns": "-238.74", "net_sales": "6892.73",
                "shipping_charges": "0", "taxes": "108.79", "total_sales": "7001.52",
            }
        ]
    )  # fmt: skip
    out = conversion.sales_daily("TEST", date(2026, 11, 17), date(2026, 11, 18), gql)
    assert "FROM sales" in gql.seen[0]
    assert out["2026-11-17"]["total"] == 0 and out["2026-11-17"]["orders"] == 0
    day = out["2026-11-18"]
    assert (day["orders"], day["discounts"], day["returns"], day["total"]) == (
        70, 499.62, 238.74, 7001.52,
    )  # fmt: skip
    conversion.clear_cache()


def _device_rows(q: str) -> Any:
    if "session_viewed_product" not in q:
        return [{"session_device_type": "mobile", "sessions": "100",
                 "sessions_with_cart_additions": "10", "sessions_that_reached_checkout": "5",
                 "sessions_that_completed_checkout": "2"}]  # fmt: skip
    return [
        {"session_device_type": "mobile", "session_viewed_product": True, "sessions": "60",
         "sessions_with_cart_additions": "9", "sessions_that_reached_checkout": "5",
         "sessions_that_completed_checkout": "2"},
        {"session_device_type": "mobile", "session_viewed_product": False, "sessions": "40",
         "sessions_with_cart_additions": "1", "sessions_that_reached_checkout": "0",
         "sessions_that_completed_checkout": "0"},
        {"session_device_type": "desktop", "session_viewed_product": "true", "sessions": "30",
         "sessions_with_cart_additions": "6", "sessions_that_reached_checkout": "4",
         "sessions_that_completed_checkout": "3"},
    ]  # fmt: skip


def test_funnel_by_device_adds_the_product_view_step() -> None:
    conversion.clear_cache()
    week = (date(2026, 11, 14), date(2026, 11, 20))
    f = conversion.funnel_by_device("TEST", *week, _fake(_device_rows))
    assert f["product_views_available"] is True
    assert [d["label"] for d in f["devices"]] == ["Mobile", "Desktop"]
    steps = {s["key"]: s for s in f["all"]["steps"]}
    assert f["all"]["sessions"] == 130 and steps["viewed_product"]["count"] == 90
    assert steps["added_to_cart"]["count"] == 16
    assert steps["added_to_cart"]["pct_of_previous"] == 17.8
    assert steps["completed_checkout"]["pct_of_sessions"] == 3.8
    assert f["all"]["conversion_rate"] == 3.85
    conversion.clear_cache()


def test_funnel_by_device_without_product_views() -> None:
    conversion.clear_cache()

    def rows(q: str) -> Any:
        return ValueError("unknown dimension") if "session_viewed_product" in q else _device_rows(q)

    f = conversion.funnel_by_device("TEST", date(2026, 11, 14), date(2026, 11, 20), _fake(rows))
    assert f["product_views_available"] is False
    first = f["all"]["steps"][0]
    assert first["key"] == "viewed_product" and first["count"] is None
    assert f["all"]["steps"][1]["pct_of_previous"] == 10.0  # cart against sessions
    conversion.clear_cache()


def test_a_burst_of_report_queries_is_capped_and_shared() -> None:
    import threading
    import time as _time
    from concurrent.futures import ThreadPoolExecutor

    conversion.clear_cache()
    running = [0]
    peak = [0]
    calls: list[str] = []
    guard = threading.Lock()

    def gql(_q: str, v: dict[str, Any] | None = None) -> dict[str, Any]:
        with guard:
            running[0] += 1
            peak[0] = max(peak[0], running[0])
            calls.append(str((v or {}).get("q")))
        _time.sleep(0.05)
        with guard:
            running[0] -= 1
        return {"shopifyqlQuery": {"parseErrors": None, "tableData": {"columns": [], "rows": []}}}

    queries = [f"FROM sales SHOW orders SINCE -{i}d" for i in range(1, 16)]
    with ThreadPoolExecutor(max_workers=30) as pool:
        list(
            pool.map(lambda q: conversion.run("RBP", q, gql), queries + queries)
        )  # each asked twice
    assert peak[0] <= conversion.MAX_PARALLEL
    assert sorted(calls) == sorted(queries)  # a query being read is not asked again
    conversion.clear_cache()


def test_settled_days_are_kept_longer_than_today(monkeypatch: pytest.MonkeyPatch) -> None:
    from zoneinfo import ZoneInfo

    monkeypatch.setattr(shopify, "shop_info", lambda store: {"timezone": "America/New_York"})
    ny = ZoneInfo("America/New_York")
    short = float(conversion.cro_config().cache_seconds)
    q = "FROM sessions SHOW sessions SINCE 2026-11-14 UNTIL 2026-11-20"
    # 20 Nov ended at local midnight; at 01:00 it is still settling, at 04:00 it is final
    assert conversion.ttl_for("RBP", q, datetime(2026, 11, 21, 1, 0, tzinfo=ny)) == short
    assert (
        conversion.ttl_for("RBP", q, datetime(2026, 11, 21, 4, 0, tzinfo=ny))
        == conversion.FINAL_TTL
    )
    today_q = "FROM sessions SHOW sessions SINCE 2026-11-14 UNTIL 2026-11-21"
    assert conversion.ttl_for("RBP", today_q, datetime(2026, 11, 21, 15, 0, tzinfo=ny)) == short
    assert conversion.ttl_for("RBP", "FROM sessions SHOW sessions SINCE -8d UNTIL today") == short


def test_the_cache_never_grows_past_its_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    conversion.clear_cache()
    monkeypatch.setattr(conversion, "CACHE_MAX", 5)
    for i in range(12):
        conversion._store_answer(("RBP", f"q{i}"), [], 60.0)
    assert len(conversion._cache) <= 5 and ("RBP", "q11") in conversion._cache
    conversion.clear_cache()


def test_the_warm_up_reads_each_default_view_once_and_keeps_going(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from zoneinfo import ZoneInfo

    from flowmerce.modules.cro import service

    monkeypatch.setattr(
        service,
        "_ctx",
        lambda brand: ("RBP", ZoneInfo("America/New_York"), datetime(2026, 11, 21, 15, tzinfo=UTC)),
    )
    seen: list[tuple[str, Any]] = []

    def fake(name: str, fail: bool = False) -> Any:
        def call(*args: Any) -> dict[str, Any]:
            seen.append((name, args[-1] if args else None))
            if fail:
                raise RuntimeError("Shopify said no")
            return {}

        return call

    for name in (
        "overview",
        "conversion_trend",
        "sales_trend",
        "traffic_changes",
        "overview_trends",
        "buy_heatmap",
        "sales_breakdown",
        "site_health",
        "segments",
        "geo",
        "landing_pages",
        "landing_grids",
        "checkout_extras",
        "product_insights",
        "discount_codes",
        "customers",
    ):
        monkeypatch.setattr(service, name, fake(name))
    monkeypatch.setattr(service, "recommendation_list", fake("recommendation_list", fail=True))
    out = service.warm_views("ridhi", pause=0)
    assert out["failed"] == ["recommendations"] and out["reads"] == len(seen)
    day = next(rq for name, rq in seen if name == "overview")
    assert (day.frm, day.to, day.compare) == (
        "2026-11-20",
        "2026-11-20",
        "4week_avg",
    )  # the page's default
    assert sum(1 for name, _ in seen if name == "product_insights") == 1


def test_a_round_syncs_every_store_before_warming_any_views(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from flowmerce.modules.cro import scheduler, service, sync

    calls: list[str] = []
    monkeypatch.setattr(
        sync, "sync_store", lambda store: calls.append(f"sync {store}") or {"state": "ok"}
    )
    monkeypatch.setattr(scheduler.data, "snapshot", lambda store, force=False: None)
    monkeypatch.setattr(service, "today_for", lambda store: date(2026, 11, 21))
    monkeypatch.setattr(
        alarms, "check_store", lambda store, today: calls.append(f"alarms {store}") or {}
    )
    monkeypatch.setattr(scheduler, "_warm_catalog", lambda store: "cached")
    monkeypatch.setattr(
        service, "warm_views", lambda brand: calls.append(f"warm {brand}") or {"reads": 0}
    )
    out = scheduler.run_once()
    assert calls == ["sync RBP", "alarms RBP", "sync CPC", "alarms CPC", "warm ridhi", "warm cpc"]
    assert out["stores"]["RBP"]["warm"] == {"reads": 0}


def test_every_change_log_window_comes_from_one_read(monkeypatch: pytest.MonkeyPatch) -> None:
    from zoneinfo import ZoneInfo

    from flowmerce.modules.cro import data, service

    data.forget_reads()
    utc = ZoneInfo("UTC")
    monkeypatch.setattr(
        service, "_ctx", lambda brand: ("RBP", utc, datetime(2026, 11, 21, 12, tzinfo=UTC))
    )
    reads: list[str] = []
    rows = [{"id": 2, "entry_date": "2026-11-01"}, {"id": 1, "entry_date": "2026-06-01"}]
    monkeypatch.setattr(data, "change_log", lambda store, since: reads.append(since) or rows)
    assert [e["id"] for e in service.change_log("ridhi", 63)["entries"]] == [2]
    assert [e["id"] for e in service.change_log("ridhi", 365)["entries"]] == [2, 1]
    assert len(reads) == 1  # the 63-day and the 365-day windows share one Supabase read
    data.forget_reads()
