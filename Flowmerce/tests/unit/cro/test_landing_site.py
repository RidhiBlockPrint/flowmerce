"""CRO landing pages, page speed, site search and payments. No network: Shopify is faked."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from flowmerce.modules.cro import conversion, landing, payments, shopify, site_health

WEEK = (date(2026, 11, 14), date(2026, 11, 20))
BEFORE = (date(2026, 11, 7), date(2026, 11, 13))


def fake(answer: Any) -> Any:
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


def test_paths_are_merged_and_rates_weighted_by_visits() -> None:
    assert landing.norm_path("https://shop.com/Products/X/?variant=1") == "/products/x"
    assert landing.norm_path("") == "/" and landing.norm_path("/#top") == "/"
    rows = [
        {
            "landing_page_path": "/a",
            "sessions": "300",
            "bounce_rate": "0.5",
            "added_to_cart_rate": "0.1",
            "conversion_rate": "0.02",
        },
        {
            "landing_page_path": "/a/",
            "sessions": "100",
            "bounce_rate": "0.9",
            "added_to_cart_rate": "0.0",
            "conversion_rate": "0.0",
        },
        {"landing_page_path": None, "sessions": "400"},  # a totals row
    ]
    a = landing.rate_rows(rows, "landing_page_path")["/a"]
    assert a == {
        "sessions": 400,
        "bounce_rate": 60.0,
        "added_to_cart_rate": 7.5,
        "conversion_rate": 1.5,
    }


def test_compare_needs_enough_visits_in_both_periods() -> None:
    cur = {
        "/a": {
            "sessions": 200,
            "bounce_rate": 60.0,
            "added_to_cart_rate": 5.0,
            "conversion_rate": 2.0,
        },
        "/b": {
            "sessions": 50,
            "bounce_rate": 40.0,
            "added_to_cart_rate": 5.0,
            "conversion_rate": 1.0,
        },
    }
    prev = {
        "/a": {
            "sessions": 150,
            "bounce_rate": 50.0,
            "added_to_cart_rate": 5.0,
            "conversion_rate": 2.5,
        },
        "/b": {
            "sessions": 500,
            "bounce_rate": 20.0,
            "added_to_cart_rate": 5.0,
            "conversion_rate": 1.0,
        },
    }
    a, b = landing.compare(cur, prev, 100)
    assert (a["bounce_change_pts"], a["conversion_change_pts"]) == (10.0, -0.5)
    assert b["bounce_change_pts"] is None and b["too_few_sessions"] is True


def _landing_answer(q: str) -> Any:
    now = "2026-11-14" in q
    if "order_landing_page_path" in q:
        return [
            {"order_landing_page_path": "/collections/quilts/", "total_sales": "500", "orders": "5"}
        ]
    if "landing_page_path, referrer_source" in q:
        return [
            {
                "landing_page_path": "/collections/quilts",
                "referrer_source": "social",
                "sessions": "700",
            },
            {
                "landing_page_path": "/collections/quilts",
                "referrer_source": "search",
                "sessions": "300",
            },
        ]
    if "landing_page_path" in q:
        return [
            {
                "landing_page_path": "/collections/quilts",
                "landing_page_type": "Collection",
                "sessions": "1000",
                "bounce_rate": "0.60" if now else "0.50",
                "added_to_cart_rate": "0.05",
                "conversion_rate": "0.01",
            },
            {
                "landing_page_path": "/pages/about",
                "landing_page_type": "Page",
                "sessions": "40",
                "bounce_rate": "0.9",
                "added_to_cart_rate": "0",
                "conversion_rate": "0",
            },
        ]
    field = next(
        f for f in ("landing_page_type", "referrer_source", "session_device_type") if f in q
    )
    return [
        {
            field: "Collection" if field == "landing_page_type" else "mobile",
            "sessions": "1040",
            "bounce_rate": "0.6",
            "added_to_cart_rate": "0.05",
            "conversion_rate": "0.01",
        }
    ]


def test_landing_pages_report() -> None:
    out = landing.landing_pages("TEST", WEEK, BEFORE, fake(_landing_answer))
    quilts, about = out["pages"]
    assert quilts["path"] == "/collections/quilts" and quilts["page_type"] == "Collection"
    assert quilts["bounce_change_pts"] == 10.0 and quilts["bounce_flag"] is True
    assert (quilts["revenue"], quilts["orders"], quilts["revenue_per_session"]) == (500.0, 5, 0.5)
    assert (quilts["top_source"], quilts["top_source_share"]) == ("social", 70.0)
    assert about["revenue"] == 0.0 and about["too_few_sessions"] is True
    assert out["page_types"][0]["share_of_sessions"] == 100.0
    assert out["revenue_available"] is True and out["errors"] == {}


def test_landing_pages_without_revenue_or_comparison() -> None:
    def answer(q: str) -> Any:
        return ValueError("no") if "FROM sales" in q else _landing_answer(q)

    out = landing.landing_pages("TEST", WEEK, None, fake(answer))
    assert out["revenue_available"] is False and out["pages"][0]["revenue"] is None
    assert out["pages"][0]["bounce_change_pts"] is None and "page_sales" in out["errors"]
    conversion.clear_cache()  # answers are reused for 10 minutes
    with pytest.raises(shopify.AnalyticsError):
        landing.landing_pages("TEST", WEEK, None, fake(lambda q: ValueError("down")))


def test_grids() -> None:
    def answer(q: str) -> Any:
        if "landing_page_path" in q:
            return [
                {
                    "landing_page_path": "/a",
                    "referrer_source": "social",
                    "sessions": "100",
                    "conversion_rate": "0.02",
                },
                {
                    "landing_page_path": "/a",
                    "referrer_source": "direct",
                    "sessions": "10",
                    "conversion_rate": "0.1",
                },
                {
                    "landing_page_path": "/b",
                    "referrer_source": "social",
                    "sessions": "50",
                    "conversion_rate": "0.04",
                },
            ]
        return []

    out = landing.grids("TEST", WEEK, fake(answer))["page_by_source"]
    assert out["rows"] == ["/a", "/b"] and out["columns"] == ["social", "direct"]
    assert out["cells"][0][0]["sessions"] == 100 and out["cells"][0][0]["conversion_rate"] == 2.0
    assert out["cells"][0][1]["conversion_rate"] is None  # 10 visits
    assert out["cells"][1][1] == {
        "sessions": 0,
        "conversion_rate": None,
        "added_to_cart_rate": None,
        "bounce_rate": None,
    }
    # "All" for /a counts both sources: (100 x 2% + 10 x 10%) / 110 visits
    first = out["row_totals"][0]
    assert (first["sessions"], first["conversion_rate"]) == (110, 2.73)
    assert out["column_totals"][0]["sessions"] == 150 and out["total"]["sessions"] == 160


def test_vitals_ratings_and_shares() -> None:
    assert [site_health.rating("lcp", v) for v in (2500, 3000, 4001)] == [
        "good",
        "needs_improvement",
        "poor",
    ]
    assert site_health.rating("cls", None) is None
    v = site_health.vitals(
        {
            "page_loads": "10",
            "lcp_p75_ms": "1416.4",
            "p75_cls": "0.123",
            "lcp_good_view_count": "8",
            "lcp_okay_view_count": "1",
            "lcp_poor_view_count": "1",
        }
    )
    assert v["lcp"] == {"p75": 1416.0, "rating": "good", "good_share": 80.0, "poor_share": 10.0}
    assert v["cls"]["rating"] == "needs_improvement" and v["inp"]["p75"] is None
    site_health.with_change(v, {"lcp": {"p75": 1500.0}})
    assert v["lcp"]["change"] == -84 and v["inp"]["change"] is None


def test_search_summary() -> None:
    out = site_health.search_summary(
        {
            "sessions_with_searches": "100",
            "search_sessions_that_completed_checkout": "7",
            "search_added_to_cart_rate": "0.15",
            "search_click_rate": "0.6",
        },
        {"sessions": "2100", "sessions_that_completed_checkout": "47"},
        [
            {"search_results_were_returned": True, "searches": "190"},
            {"search_results_were_returned": False, "searches": "10"},
        ],
        [{"search_query": "Round tablecloth", "searches": "40"}],
        [{"search_query": "diary", "searches": "6"}],
        [
            {
                "search_query": "round tablecloth",
                "search_queries": "50",
                "search_queries_with_clicks": "20",
            }
        ],
    )
    assert out is not None
    assert (out["searcher_conversion_rate"], out["non_searcher_conversion_rate"]) == (7.0, 2.0)
    assert (out["share_of_sessions"], out["zero_result_share"]) == (4.76, 5.0)
    assert out["top_terms"][0]["click_rate"] == 40.0
    assert out["zero_result_terms"] == [{"term": "diary", "searches": 6}]
    assert site_health.search_summary(None, None, None, None, None, None) is None


def test_site_health_says_when_shopify_has_not_published_yet() -> None:
    out = site_health.site_health("TEST", WEEK, BEFORE, fake(lambda q: []))
    assert out["speed_available"] is False and out["search"] is None
    assert "1-2 days late" in out["late_note"]
    conversion.clear_cache()
    with pytest.raises(shopify.AnalyticsError):
        site_health.site_health("TEST", WEEK, None, fake(lambda q: ValueError("down")))


def test_payments_sum_the_wanted_days() -> None:
    def answer(q: str) -> Any:
        key = "payment_method" if "payment_method" in q else "payment_card_wallet"
        rows = []
        for day, n in (
            ("2026-11-12", 50),
            ("2026-11-14", 100),
            ("2026-11-20", 100),
            ("2026-11-21", 9),
        ):
            rows.append(
                {
                    "day": day,
                    key: "credit_card" if key == "payment_method" else "shopify_pay",
                    "unique_payment_attempts": str(n),
                    "successful_payments": str(n - 2),
                    "failed_payment_attempts": "3",
                }
            )
        return rows

    out = payments.payments("TEST", WEEK, BEFORE, fake(answer))
    card = out["methods"][0]
    assert (card["attempts"], card["successful"], card["failed_attempts"]) == (200, 196, 6)
    assert out["success_rate"] == 98.0 and out["previous_success_rate"] == 96.0
    assert card["share_of_payments"] == 100.0 and out["wallets"][0]["label"] == "shopify_pay"
    assert out["latest_day_with_data"] == "2026-11-21"
