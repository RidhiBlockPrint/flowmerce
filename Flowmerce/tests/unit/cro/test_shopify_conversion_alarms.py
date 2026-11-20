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
