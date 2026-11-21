"""CRO batch 4: refunds per product, discount codes, bought together, price bands and product groups
from GA4 product views. No network: Shopify and GA4 are fake functions."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from flowmerce.modules.cro import conversion, products, recommendations, shopify
from flowmerce.modules.cro.data import Line, Order, Snapshot
from flowmerce.modules.cro.periods import days_window

NY = ZoneInfo("America/New_York")
NOW = datetime(2026, 11, 21, 15, 0, tzinfo=UTC)
CUR = (date(2026, 11, 1), date(2026, 11, 20))


@pytest.fixture(autouse=True)
def _clean_cache() -> Any:
    conversion.clear_cache()
    products.clear_cache()
    shopify._catalog_cache.clear()
    yield
    conversion.clear_cache()
    products.clear_cache()
    shopify._catalog_cache.clear()


def at(day: int, hour: int = 12) -> datetime:
    return datetime(2026, 11, day, hour, tzinfo=NY).astimezone(UTC)


def order(oid: int, day: int, *, cancelled: bool = False) -> Order:
    when = at(day)
    return Order(oid, f"#{oid}", when, when if cancelled else None, "paid", "USD",
                 100.0, 100.0, 0.0, 0.0, 0.0, 0.0)  # fmt: skip


def line(
    oid: int, day: int, pid: int | None, title: str, qty: int = 1, price: float = 50.0
) -> Line:
    return Line(oid, at(day), pid, title, "", "", qty, price)


def snap(orders: list[Order], lines: list[Line]) -> Snapshot:
    return Snapshot("RBP", tuple(orders), tuple(lines), NOW, NOW - timedelta(days=63))


def test_category_title_first_then_type() -> None:
    assert products.category("Quilted Cosmetic Bag", "Quilt") == "Bags"
    assert products.category("Blue Table Runner", "Quilt") == "Table runners"
    assert products.category("Mughal Buta Blue Quilt", "") == "Quilts"
    assert products.category("Gift card", "gift card") == "Gift card"
    assert products.category("Mystery", "") == "Other"


def test_ga4_item_ids_match_shopify_product_ids() -> None:
    assert products.product_id_of("shopify_ZZ_8287119605921_45114036715681") == 8287119605921
    assert products.product_id_of("shopify_GB_10872810602655_62854942883999") == 10872810602655
    assert products.product_id_of("SKU-123") is None and products.product_id_of(None) is None


def test_discount_codes_count_an_order_with_two_codes_once() -> None:
    rows = [
        {"discount_code": None, "orders": "60", "gross_sales": "6000", "discounts": "-100",
         "net_sales": "5900", "average_order_value": "98"},
        {"discount_code": "save10", "orders": "30", "gross_sales": "3000", "discounts": "-300",
         "net_sales": "2700", "average_order_value": "90"},
        {"discount_code": "SAVE10", "orders": "5", "gross_sales": "500", "discounts": "-50",
         "net_sales": "450", "average_order_value": "90"},
        {"discount_code": "VIP", "orders": "15", "gross_sales": "1500", "discounts": "-150",
         "net_sales": "1350", "average_order_value": "90"},
    ]  # fmt: skip
    total = [{"orders": "100", "gross_sales": "10500", "discounts": "-550", "net_sales": "9950",
              "average_order_value": "95"}]  # fmt: skip
    s = products.code_summary(rows, total)
    assert s["total_orders"] == 100
    assert s["without_code"]["orders"] == 60 and s["without_code"]["aov"] == 98.0
    # 35 + 15 = 50 code rows, but only 40 orders used a code: 10 orders used two codes
    assert s["with_code"]["orders"] == 40 and s["with_code"]["share_of_orders"] == 40.0
    assert s["with_code"]["aov"] == round((9500 - 5880) / 40, 2)
    assert [c["code"] for c in s["codes"]] == ["SAVE10", "VIP"] and s["codes"][0]["orders"] == 35
    assert s["codes"][0]["discount_pct"] == 10.0


def test_bought_together_pairs_lift_and_cancelled_orders() -> None:
    orders = [order(i, 5) for i in range(1, 11)] + [order(11, 5, cancelled=True)]
    lines = []
    for i in range(1, 11):
        lines.append(line(i, 5, 1, "Quilt"))
    for i in (1, 2, 3):
        lines.append(line(i, 5, 2, "Pillow cover"))
    lines += [line(4, 5, 3, "Napkins"), line(11, 5, 2, "Pillow cover")]
    out = products.bought_together(snap(orders, lines), days_window(*CUR, NY))
    assert out["orders"] == 10 and out["multi_product_orders"] == 4 and out["multi_share"] == 40.0
    assert len(out["rows"]) == 1  # Quilt + Napkins only once: chance
    top = out["rows"][0]
    assert (top["a"], top["b"], top["orders_together"]) == ("Quilt", "Pillow cover", 3)
    assert top["pct_of_a"] == 30.0 and top["pct_of_b"] == 100.0 and top["lift"] == 1.0


def test_price_bands_count_an_order_once_per_band() -> None:
    rows = [
        {"product_id": 1, "price": 20.0, "items": 3, "net_sales": 60.0, "views": 100},
        {"product_id": 2, "price": 24.0, "items": 1, "net_sales": 24.0, "views": 50},
        {"product_id": 3, "price": 98.0, "items": 1, "net_sales": 98.0, "views": 300},
        {"product_id": 4, "price": None, "items": 1, "net_sales": 5.0, "views": 0},
    ]
    ids = {1: {10, 11}, 2: {11}, 3: {12}}
    bands = products.price_bands(rows, ids, ids)
    assert [b["band"] for b in bands] == ["Under $25", "$75-99"]
    low = bands[0]
    assert low["products"] == 2 and low["orders"] == 2 and low["items"] == 4
    assert low["conversion_rate"] == round(2 / 150 * 100, 2)
    assert products.price_bands(rows, ids, None)[0]["conversion_rate"] is None
    assert products.band_label(300, None) == "$300+" and products.band_label(25, 50) == "$25-49"


def _p(pid: int, cat: str, views: int, orders: int, price: float = 50.0) -> dict[str, Any]:
    return {"product_id": pid, "name": f"P{pid}", "category": cat, "views": views,
            "view_orders": orders, "price": price, "net_sales": orders * price}  # fmt: skip


def test_groups_judge_each_product_against_its_own_category() -> None:
    rows = [
        _p(1, "Quilts", 2000, 40),  # many views, converts well: star
        _p(2, "Quilts", 2000, 10),  # many views, converts badly: leaky
        _p(3, "Quilts", 100, 6),  # few views, converts well: hidden gem
        _p(4, "Quilts", 100, 0),  # few views, no orders: dead weight
        _p(5, "Napkins", 500, 0),  # alone in its category: judged against all products
        _p(6, "Napkins", 0, 3),  # GA4 saw no views: no group
    ]
    products.classify(rows)
    assert [r.get("group") for r in rows] == [
        "star", "leaky", "hidden_gem", "dead_weight", "leaky", None,
    ]  # fmt: skip
    cat = 56 / 4200
    assert rows[1]["category_rate"] == round(cat * 100, 2) and rows[1]["compared_with"] == "Quilts"
    assert rows[4]["compared_with"] == "All products" and rows[4]["category_rate"] == round(
        56 / 4700 * 100, 2
    )
    assert rows[1]["left_on_table"] == round(2000 * (cat - 10 / 2000) * 50, 2)
    assert rows[0]["left_on_table"] == 0.0
    s = products.group_summary(rows)
    assert [g["products"] for g in s["groups"]] == [1, 1, 2, 1]
    assert [p["product_id"] for p in s["fix_first"]] == [2, 5]
    assert s["fix_first"][1]["compared_with"] == "All products"


def test_a_category_where_nothing_sold_makes_no_star() -> None:
    rows = [_p(i, "Curtains", v, 0) for i, v in ((1, 900), (2, 400), (3, 100))]
    products.classify(rows)
    assert [r["group"] for r in rows] == ["leaky", "leaky", "dead_weight"]
    assert all(r["left_on_table"] == 0.0 for r in rows)  # nothing to compare a loss with


def test_refunds_store_rate_and_small_products_left_out() -> None:
    rows = [
        {"product_id": 1, "name": "Quilt", "category": "Quilts", "gross_sales": 1000.0,
         "refunded": 100.0, "refund_rate": 10.0},
        {"product_id": 2, "name": "Napkins", "category": "Napkins", "gross_sales": 200.0,
         "refunded": 100.0, "refund_rate": 50.0},
        {"product_id": 3, "name": "Runner", "category": "Table runners", "gross_sales": 800.0,
         "refunded": 0.0, "refund_rate": 0.0},
    ]  # fmt: skip
    r = products.refunds(rows, 25.0)
    assert r["store_refund_rate"] == 10.0 and r["total_refunded"] == 200.0
    assert r["refunded_without_product"] == 25.0 and r["products_with_refunds"] == 2
    assert [x["name"] for x in r["by_rate"]] == ["Quilt"]  # Napkins sold under $300


def ga4_fake(days: list[str], items: list[tuple[str, int, int]], page: int = 2) -> Any:
    calls: list[dict[str, Any]] = []

    def post(body: dict[str, Any]) -> dict[str, Any]:
        calls.append(body)
        if body["dimensions"][0]["name"] == "date":
            return {"rows": [{"dimensionValues": [{"value": d.replace("-", "")}],
                              "metricValues": [{"value": "5"}]} for d in days]}  # fmt: skip
        start = body["offset"]
        chunk = items[start : start + page]
        return {
            "rowCount": len(items),
            "rows": [{"dimensionValues": [{"value": i}],
                      "metricValues": [{"value": str(v)}, {"value": str(c)}]} for i, v, c in chunk],
        }  # fmt: skip

    post.calls = calls  # type: ignore[attr-defined]
    return post


def test_ga4_views_add_variants_up_and_page_through(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(products, "GA4_PAGE", 2)
    post = ga4_fake(
        ["2026-11-19", "2026-11-20"],
        [("shopify_ZZ_1_11", 100, 10), ("shopify_ZZ_1_12", 50, 5), ("shopify_ZZ_2_21", 30, 1),
         ("gift-card", 7, 0)],
    )  # fmt: skip
    v = products.ga4_views("RBP", CUR, post)
    assert v["by_product"] == {
        1: {"views": 150, "add_to_carts": 15},
        2: {"views": 30, "add_to_carts": 1},
    }
    assert v["days"] == ["2026-11-19", "2026-11-20"] and v["unmatched_views"] == 7
    assert len(post.calls) == 3  # one daily read, two pages of items
    products.ga4_views("RBP", CUR, post)
    assert len(post.calls) == 3  # remembered


def test_ga4_failure_and_missing_setup_are_explained(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(_body: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("Google refused access (403)")

    with pytest.raises(products.ViewsError) as e:
        products.ga4_views("RBP", CUR, broken)
    assert e.value.state == "ga4_error" and "403" in e.value.message
    with pytest.raises(products.ViewsError) as e2:
        products.ga4_views("NOPE", CUR)
    assert e2.value.state == "not_configured"


CATALOG = {
    1: ("Dark Salmon Pink Quilt", "", "97.99"),
    2: ("Dark Salmon Pink Pillow Cover", "Pillow Cover", "29.99"),
    3: ("Viewed Only Tablecloth", "Tablecloth", "36.99"),
}


def shop_fake() -> Any:
    def gql(query: str, v: dict[str, Any] | None = None) -> dict[str, Any]:
        if "CroProducts" in query:
            nodes = [{"legacyResourceId": str(k), "title": t, "handle": f"h{k}", "productType": pt,
                      "priceRangeV2": {"minVariantPrice": {"amount": pr}}}
                     for k, (t, pt, pr) in CATALOG.items()]  # fmt: skip
            return {"products": {"nodes": nodes, "pageInfo": {"hasNextPage": False}}}
        rows = [
            {"product_id": "1", "gross_sales": "1000", "discounts": "-50", "returns": "-100",
             "net_sales": "850", "net_items_sold": "10", "orders": "9"},
            {"product_id": "2", "gross_sales": "300", "discounts": "0", "returns": "0",
             "net_sales": "300", "net_items_sold": "10", "orders": "8"},
            {"product_id": None, "gross_sales": "0", "discounts": "0", "returns": "-20",
             "net_sales": "-20", "net_items_sold": "0", "orders": "0"},
        ]  # fmt: skip
        return {"shopifyqlQuery": {"parseErrors": None, "tableData": {"columns": [], "rows": rows}}}

    return gql


def test_insights_join_shopify_and_ga4_by_product_id() -> None:
    days = [(CUR[0] + timedelta(days=i)).isoformat() for i in range(20)]
    post = ga4_fake(days, [("shopify_US_1_9", 900, 60), ("shopify_US_2_9", 100, 12),
                           ("shopify_US_3_9", 400, 8)], page=10)  # fmt: skip
    orders = [order(i, 10) for i in range(1, 10)]
    lines = [line(i, 10, 1, "Dark Salmon Pink Quilt", price=97.99) for i in range(1, 10)]
    lines += [line(i, 10, 2, "Dark Salmon Pink Pillow Cover") for i in range(1, 9)]
    got = products.insights("RBP", NY, CUR, snap(orders, lines), shop_fake(), post)
    by = {p["product_id"]: p for p in got["products"]}
    assert got["sales_source"] == "shopify" and got["views"]["state"] == "ready"
    q = by[1]
    assert (q["category"], q["net_sales"], q["orders"], q["refund_rate"], q["price"]) == (
        "Quilts", 850.0, 9, 10.0, 97.99,
    )  # fmt: skip
    assert q["views"] == 900 and q["add_to_cart_rate"] == round(60 / 900 * 100, 1)
    assert q["conversion_rate"] == 1.0 and q["group"] is not None
    assert by[3]["orders"] == 0 and by[3]["views"] == 400  # viewed, never bought
    assert got["refunds"]["refunded_without_product"] == 20.0
    assert got["bought_together"]["rows"][0]["orders_together"] == 8
    assert {b["band"] for b in got["price_bands"]} == {"$25-49", "$75-99"}


def test_insights_wait_for_enough_ga4_days_and_survive_failures() -> None:
    post = ga4_fake(["2026-11-19", "2026-11-20"], [("shopify_US_1_9", 90, 6)])

    def no_reports(query: str, v: dict[str, Any] | None = None) -> dict[str, Any]:
        if "CroProducts" in query:
            raise RuntimeError("no products scope")
        return {"shopifyqlQuery": {"parseErrors": ["no"], "tableData": None}}

    orders = [order(1, 19)]
    lines = [line(1, 19, 1, "Dark Salmon Pink Quilt", price=97.99)]
    got = products.insights("CPC", NY, CUR, snap(orders, lines), no_reports, post)
    assert got["views"]["state"] == "collecting" and got["views"]["days"] == 2
    assert got["groups"] is None and got["refunds"] is None
    assert got["sales_source"] == "orders" and got["sales_error"] and got["catalog_error"]
    p = got["products"][0]
    assert p["net_sales"] == 97.99 and p["views"] == 90 and p["group"] is None
    assert p["price"] == 97.99  # from sales / items when the product list cannot be read


def test_leaky_products_become_ranked_recommendations() -> None:
    fix = [
        {"product_id": 7, "name": "Taupe Quilt", "category": "Quilts", "views": 1055,
         "add_to_cart_rate": 4.1, "conversion_rate": 0.57, "category_rate": 1.17,
         "price": 97.99, "left_on_table": 621.5},
        {"product_id": 8, "name": "Tiny", "category": "Quilts", "views": 90,
         "add_to_cart_rate": None, "conversion_rate": 1.0, "category_rate": 1.17,
         "price": 97.99, "left_on_table": 10.0},
    ]  # fmt: skip
    items = recommendations.leaky_items({"fix_first": fix, "days": 28})
    assert len(items) == 1  # under $50 left on the table is not worth a recommendation
    r = items[0]
    assert r["key"] == "product_leaky:7" and r["impact"] == 621.5 and r["area"] == "Products"
    assert "1,055 product views in 28 days" in r["evidence_list"][0]
    assert recommendations.leaky_items(None) == []


def test_the_product_list_is_refreshed_before_it_runs_out(monkeypatch: pytest.MonkeyPatch) -> None:
    reads: list[int] = []

    def gql(query: str, v: dict[str, Any] | None = None) -> dict[str, Any]:
        reads.append(1)
        return {"products": {"nodes": [], "pageInfo": {"hasNextPage": False}}}

    clock = [1000.0]
    monkeypatch.setattr(shopify.time, "monotonic", lambda: clock[0])
    assert shopify.warm_catalog("RBP", gql) is True and len(reads) == 1
    assert shopify.warm_catalog("RBP", gql) is False and len(reads) == 1  # fresh: kept
    clock[0] += shopify.SHOP_CACHE_SECONDS - shopify.CATALOG_REFRESH_LEFT + 1
    assert shopify.warm_catalog("RBP", gql) is True and len(reads) == 2  # under an hour left
