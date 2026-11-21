"""Deeper product analysis (batch 4 of the new CRO prototype): refunds per product, discount codes,
products bought together, price bands, and product groups from product views.

Where each figure comes from (owner decision 2026-11-21: money and orders from Shopify; GA4 only
for what Shopify cannot see):

* Shopify's sales report (ShopifyQL `sales` by product_id): gross sales, discounts, returns
  (refunds), net sales, items sold and orders per product, the same numbers as Shopify's "Total
  sales by product" report. A refund counts on the day it is made, as in Shopify.
* Shopify's sales report by discount_code: orders, average order and discounts per code. An order
  that used two codes appears under both codes, so "orders with a code" is all orders minus the
  orders without one.
* The order copy (cro.orders / cro.order_lines): which products were bought in the same order,
  orders per price band, and orders per product on the days GA4 has views (for conversion).
  Cancelled orders are left out.
* Shopify's product list: each product's lowest variant price ("from $X") and product type.
* GA4 (the store's Google tag sends Shopify's ecommerce events): product views (`itemsViewed`) and
  add-to-carts (`itemsAddedToCart`) per product. Shopify itself has no per-product page views: it
  only knows the page a visit started on. GA4's item id is shopify_<country>_<product id>_<variant
  id>, so products are matched by id, never by title. GA4 counts views, not people (opening the
  same product twice is two views), and misses visitors who block tracking.

Product groups (from the prototype). Each product is judged against its own category, so a quilt is
not compared with napkins (a category with fewer than MIN_CATEGORY_PRODUCTS viewed products is
compared with all products instead):
    conversion        = orders with the product / its views, over the days GA4 has views
    adjusted rate     = (orders + 200 x category rate) / (views + 200)   (small-sample adjustment)
    many views        = at or above the category's median views
    Stars             many views, adjusted rate >= category rate  -> keep in stock, use in ads
    Hidden gems       few views,  adjusted rate >= category rate  -> send more traffic
    Leaky             many views, below the category              -> fix the product page first
    Dead weight       few views,  below the category              -> rework or drop
    left on the table = views x (category rate - product rate) x price   (Leaky only; the fix-first
                        list is ranked by it)
Groups are only given once GA4 has MIN_VIEW_DAYS days of views in the range; never estimated.
"""

from __future__ import annotations

import threading
import time
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from itertools import combinations
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

from . import shopify
from .config import STORE_BRAND, cro_config
from .conversion import run
from .data import Snapshot
from .metrics import live, product_sales
from .periods import Window, days_window
from .traffic import num, rate, required, run_many, since

Days = tuple[date, date]
Post = Callable[[dict[str, Any]], dict[str, Any]]

MIN_VIEW_DAYS = 7  # fewer days of GA4 views than this in the range -> no groups yet
RELIABLE_VIEW_DAYS = 14  # below this the page says the groups are still settling
PRIOR_VIEWS = 200  # the "200" in the small-sample adjustment
MIN_CATEGORY_PRODUCTS = 3  # smaller categories are compared with all products
MIN_REFUND_GROSS = 300.0  # products with less gross sales are left out of the refund lists
BANDS: tuple[tuple[int, int | None], ...] = (
    (0, 25),
    (25, 50),
    (50, 75),
    (75, 100),
    (100, 150),
    (150, 200),
    (200, 300),
    (300, None),
)
PAIR_LIMIT = 20
MIN_PAIR_ORDERS = 2  # a pair bought together only once is chance
CODE_LIMIT = 15
GA4_PAGE = 100_000
GROUPS = ("star", "hidden_gem", "leaky", "dead_weight")

# Product families by a word in the title, checked before Shopify's product type: many products
# have no type (half of Ridhi's sales), and some types are wrong (a table runner typed as a quilt).
# Bags first: "Quilted Cosmetic Bag" is not a quilt.
FAMILIES: tuple[tuple[str, str], ...] = (
    ("cosmetic bag", "Bags"),
    ("toiletry bag", "Bags"),
    (" bag", "Bags"),
    ("coaster", "Coasters"),
    ("picture frame", "Picture frames"),
    ("sticky note", "Sticky note holders"),
    ("quilt", "Quilts"),
    ("tablecloth", "Tablecloths"),
    ("napkin", "Napkins"),
    ("runner", "Table runners"),
    ("placemat", "Placemats"),
    ("pillow cover", "Pillow covers"),
    ("cushion", "Cushions"),
    ("pillow insert", "Pillow inserts"),
    ("tissue box", "Tissue box covers"),
    ("curtain", "Curtains"),
    ("towel", "Kitchen towels"),
    ("ornament", "Ornaments"),
    ("tree skirt", "Tree skirts"),
)

GROUP_LABELS = {
    "star": "Stars",
    "hidden_gem": "Hidden gems",
    "leaky": "Leaky",
    "dead_weight": "Dead weight",
}


class ViewsError(Exception):
    """GA4 product views could not be read. `state`: not_configured or ga4_error."""

    def __init__(self, state: str, message: str) -> None:
        super().__init__(message)
        self.state = state
        self.message = message


def category(title: str, product_type: str) -> str:
    """The product's family: a word in the title first, then Shopify's product type, else Other."""
    t = f" {title.lower()} "
    for word, label in FAMILIES:
        if word in t:
            return label
    pt = product_type.strip()
    return pt[:1].upper() + pt[1:] if pt else "Other"


def product_id_of(item_id: Any) -> int | None:
    """GA4 item id 'shopify_US_8287119605921_45114036715681' -> 8287119605921."""
    parts = str(item_id or "").split("_")
    if len(parts) >= 3 and parts[0] == "shopify" and parts[2].isdigit():
        return int(parts[2])
    return None


def _ga4_date(raw: str) -> str:
    return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"


# ------------------------------------------------------------------------------------------ GA4
_ga4_cache: dict[tuple[str, str, str], tuple[float, dict[str, Any]]] = {}
_ga4_lock = threading.Lock()


def _ga4_post(store: str) -> Post:
    """A GA4 runReport caller for the store's property (the SEO module's Google service account)."""
    from ..seo.config import config
    from ..seo.integrations import google

    brand = config.brands.get(STORE_BRAND.get(store, ""))
    if brand is None or not google.ga4_configured(brand):
        raise ViewsError(
            "not_configured",
            "GA4 is not set up for this store (no GA4 property id or Google service account).",
        )
    url = (
        "https://analyticsdata.googleapis.com/v1beta/properties/"
        f"{quote(brand.ga4_property_id, safe='')}:runReport"
    )
    return lambda body: dict(google._post(url, google.SCOPE_GA4, body))


def ga4_views(store: str, w: Days, post: Post | None = None) -> dict[str, Any]:
    """Product views and add-to-carts per Shopify product id over the local days w (inclusive):
    {by_product: {id: {views, add_to_carts}}, days: [days with any views], unmatched_views}.
    Cached like the ShopifyQL answers. Raises ViewsError."""
    key = (store, w[0].isoformat(), w[1].isoformat())
    with _ga4_lock:
        hit = _ga4_cache.get(key)
        if hit and hit[0] > time.monotonic():
            return hit[1]
    call = post or _ga4_post(store)
    ranges = [{"startDate": w[0].isoformat(), "endDate": w[1].isoformat()}]
    try:
        daily = call(
            {
                "dateRanges": ranges,
                "dimensions": [{"name": "date"}],
                "metrics": [{"name": "itemsViewed"}],
                "limit": 1000,
            }
        )
        by: dict[int, dict[str, int]] = {}
        unmatched = offset = 0
        while True:
            page = call(
                {
                    "dateRanges": ranges,
                    "dimensions": [{"name": "itemId"}],
                    "metrics": [{"name": "itemsViewed"}, {"name": "itemsAddedToCart"}],
                    "limit": GA4_PAGE,
                    "offset": offset,
                }
            )
            rows = page.get("rows") or []
            for r in rows:
                values = [int(num(m.get("value"))) for m in r.get("metricValues") or []]
                views, carts = (values + [0, 0])[:2]
                pid = product_id_of((r.get("dimensionValues") or [{}])[0].get("value"))
                if pid is None:
                    unmatched += views
                    continue
                acc = by.setdefault(pid, {"views": 0, "add_to_carts": 0})
                acc["views"] += views
                acc["add_to_carts"] += carts
            offset += len(rows)
            if len(rows) < GA4_PAGE or offset >= int(num(page.get("rowCount"))):
                break
    except Exception as e:  # noqa: BLE001 - every GA4 failure becomes one explained state
        raise ViewsError(
            "ga4_error", f"GA4 could not be read: {str(getattr(e, 'message', e))[:300]}"
        ) from None
    days = sorted(
        _ga4_date(str(r["dimensionValues"][0]["value"]))
        for r in daily.get("rows") or []
        if num(r["metricValues"][0].get("value")) > 0
    )
    out = {"by_product": by, "days": days, "unmatched_views": unmatched}
    with _ga4_lock:
        _ga4_cache[key] = (time.monotonic() + cro_config().cache_seconds, out)
    return out


def clear_cache() -> None:
    """Forget remembered GA4 answers (tests)."""
    with _ga4_lock:
        _ga4_cache.clear()


# ------------------------------------------------------------------------------ Shopify reads
SALES_SHOW = "gross_sales, discounts, returns, net_sales, net_items_sold, orders"


def sales_by_product(
    store: str, w: Days, gql: shopify.Gql | None = None
) -> tuple[dict[int, dict[str, float]], float]:
    """Shopify's sales per product id over w, and the refunds not tied to a product (custom items,
    shipping). Discounts and returns are given as positive amounts."""
    rows = run(
        store,
        f"FROM sales SHOW {SALES_SHOW} GROUP BY product_id {since(w)} "
        "ORDER BY net_sales DESC LIMIT 1000",
        gql,
    )
    out: dict[int, dict[str, float]] = {}
    loose = 0.0
    for r in rows:
        raw = str(r.get("product_id") or "").strip()
        if not raw.isdigit():
            loose += abs(num(r.get("returns")))
            continue
        acc = out.setdefault(
            int(raw),
            dict.fromkeys(("gross", "discounts", "refunded", "net", "items", "orders"), 0.0),
        )
        acc["gross"] += num(r.get("gross_sales"))
        acc["discounts"] += abs(num(r.get("discounts")))
        acc["refunded"] += abs(num(r.get("returns")))
        acc["net"] += num(r.get("net_sales"))
        acc["items"] += num(r.get("net_items_sold"))
        acc["orders"] += num(r.get("orders"))
    return out, round(loose, 2)


CODE_SHOW = "orders, gross_sales, discounts, net_sales, average_order_value"


def _code_block(v: list[float], all_orders: float) -> dict[str, Any]:
    orders, gross, disc, net, value = v
    return {
        "orders": int(orders),
        "share_of_orders": rate(orders, all_orders, 1),
        "net_sales": round(net, 2),
        "aov": round(value / orders, 2) if orders else None,
        "discount_given": round(disc, 2),
        "discount_pct": rate(disc, gross, 1),
    }


def code_summary(rows: list[dict[str, Any]], total_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Orders with vs without a discount code, and per code (pure). Average order is Shopify's
    (`average_order_value`); for "with a code" it is worked out from all orders minus the orders
    without a code, because an order with two codes is in two code rows."""
    total = total_rows[0] if total_rows else {}
    all_orders = num(total.get("orders"))
    no_code: dict[str, Any] = {}
    by_code: dict[str, list[float]] = {}
    for r in rows:
        code = str(r.get("discount_code") or "").strip().upper()
        if not code:
            no_code = r
            continue
        acc = by_code.setdefault(code, [0.0, 0.0, 0.0, 0.0, 0.0])
        o = num(r.get("orders"))
        acc[0] += o
        acc[1] += num(r.get("gross_sales"))
        acc[2] += abs(num(r.get("discounts")))
        acc[3] += num(r.get("net_sales"))
        acc[4] += num(r.get("average_order_value")) * o

    def part(src: dict[str, Any]) -> list[float]:
        o = num(src.get("orders"))
        return [
            o,
            num(src.get("gross_sales")),
            abs(num(src.get("discounts"))),
            num(src.get("net_sales")),
            num(src.get("average_order_value")) * o,
        ]

    everything, without = part(total), part(no_code)
    with_code = [max(a - b, 0.0) for a, b in zip(everything, without, strict=True)]
    codes = [
        {"code": c, **_code_block(v, all_orders)}
        for c, v in sorted(by_code.items(), key=lambda kv: (-kv[1][0], kv[0]))
    ]
    return {
        "total_orders": int(all_orders),
        "with_code": _code_block(with_code, all_orders),
        "without_code": _code_block(without, all_orders),
        "codes": codes[:CODE_LIMIT],
        "code_count": len(codes),
    }


def discount_codes(
    store: str, cur: Days, base: Days | None, gql: shopify.Gql | None = None
) -> dict[str, Any]:
    """Discount codes for `cur`, with the comparison's with-code share and average order."""
    queries = {
        "codes": f"FROM sales SHOW {CODE_SHOW} GROUP BY discount_code {since(cur)} "
        "ORDER BY orders DESC LIMIT 1000",
        "total": f"FROM sales SHOW {CODE_SHOW} {since(cur)}",
    }
    if base:
        queries["base_codes"] = (
            f"FROM sales SHOW {CODE_SHOW} GROUP BY discount_code {since(base)} "
            "ORDER BY orders DESC LIMIT 1000"
        )
        queries["base_total"] = f"FROM sales SHOW {CODE_SHOW} {since(base)}"
    rows, errors = run_many(store, queries, gql)
    out = code_summary(required(rows, errors, "codes"), required(rows, errors, "total"))
    prev = None
    if base and rows.get("base_codes") is not None and rows.get("base_total") is not None:
        p = code_summary(rows["base_codes"] or [], rows["base_total"] or [])
        prev = {k: p[k] for k in ("total_orders", "with_code", "without_code")}
    return {**out, "previous": prev, "skipped": sorted(errors)}


# ------------------------------------------------------------------------------- pure analysis
def bought_together(snap: Snapshot, w: Window, limit: int = PAIR_LIMIT) -> dict[str, Any]:
    """The product pairs most often in the same order (pure). pct_of_a = share of the first
    product's orders that also had the second; lift = how many times more often than chance."""
    keep = {o.id for o in live(snap.orders, w)}
    baskets: dict[int, dict[str, str]] = {}
    for ln in snap.lines:
        if ln.order_id in keep:
            key = (
                f"id:{ln.product_id}" if ln.product_id is not None else f"title:{ln.title.lower()}"
            )
            baskets.setdefault(ln.order_id, {})[key] = ln.title
    single: Counter[str] = Counter()
    pairs: Counter[tuple[str, str]] = Counter()
    titles: dict[str, str] = {}
    multi = 0
    for products in baskets.values():
        titles.update(products)
        keys = sorted(products)
        single.update(keys)
        if len(keys) > 1:
            multi += 1
            pairs.update(combinations(keys, 2))
    n = len(keep)
    rows: list[dict[str, Any]] = []
    for (x, y), c in pairs.most_common():
        if c < MIN_PAIR_ORDERS or len(rows) >= limit:
            break
        a, b = (x, y) if (single[x], x) >= (single[y], y) else (y, x)
        lift = (c / n) / ((single[a] / n) * (single[b] / n)) if n else None
        rows.append(
            {
                "a": titles[a],
                "b": titles[b],
                "orders_together": c,
                "a_orders": single[a],
                "b_orders": single[b],
                "pct_of_a": rate(c, single[a], 1),
                "pct_of_b": rate(c, single[b], 1),
                "lift": round(lift, 1) if lift else None,
            }
        )
    return {
        "rows": rows,
        "orders": n,
        "multi_product_orders": multi,
        "multi_share": rate(multi, n, 1),
        "min_orders_together": MIN_PAIR_ORDERS,
    }


def band_of(price: float) -> tuple[int, int | None]:
    """The price band a price falls in."""
    for lo, hi in BANDS:
        if price >= lo and (hi is None or price < hi):
            return lo, hi
    return BANDS[-1]


def band_label(lo: int, hi: int | None) -> str:
    """(0, 25) -> 'Under $25'; (25, 50) -> '$25-49'; (300, None) -> '$300+'."""
    if hi is None:
        return f"${lo}+"
    return f"${lo}-{hi - 1}" if lo else f"Under ${hi}"


def price_bands(
    rows: list[dict[str, Any]],
    order_ids: dict[int, set[int]],
    view_order_ids: dict[int, set[int]] | None,
) -> list[dict[str, Any]]:
    """Products grouped by their "from" price (pure): products, orders (an order counts once per
    band), items, net sales and share, and, when views are known, views and conversion."""
    acc: dict[tuple[int, int | None], dict[str, Any]] = {}
    for p in rows:
        if p.get("price") is None or p.get("product_id") is None:
            continue
        b = acc.setdefault(
            band_of(float(p["price"])),
            {"products": 0, "items": 0, "net_sales": 0.0, "views": 0, "orders": set(), "vo": set()},
        )
        b["products"] += 1
        b["items"] += int(p.get("items") or 0)
        b["net_sales"] += float(p.get("net_sales") or 0)
        b["views"] += int(p.get("views") or 0)
        b["orders"] |= order_ids.get(p["product_id"], set())
        if view_order_ids is not None:
            b["vo"] |= view_order_ids.get(p["product_id"], set())
    total = sum(b["net_sales"] for b in acc.values())
    out = []
    for lo, hi in BANDS:
        band = acc.get((lo, hi))
        if not band:
            continue
        views = band["views"] if view_order_ids is not None else None
        out.append(
            {
                "band": band_label(lo, hi),
                "from": lo,
                "products": band["products"],
                "orders": len(band["orders"]),
                "items": band["items"],
                "net_sales": round(band["net_sales"], 2),
                "share_of_sales": rate(band["net_sales"], total, 1),
                "views": views,
                "conversion_rate": rate(len(band["vo"]), views, 2) if views else None,
            }
        )
    return out


def _median(values: list[float]) -> float:
    s = sorted(values)
    if not s:
        return 0.0
    mid = len(s) // 2
    return s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2


def _peer_stats(members: list[dict[str, Any]]) -> tuple[float, float, list[float]]:
    views = sum(p["views"] for p in members)
    orders = sum(p["view_orders"] for p in members)
    prices = [float(p["price"]) for p in members if p.get("price")]
    return (orders / views if views else 0.0), _median([p["views"] for p in members]), prices


def classify(rows: list[dict[str, Any]]) -> None:
    """Adds the comparison rate, adjusted rate, group and money left on the table to every product
    with views (mutates; pure otherwise). Products GA4 saw no views for get no group. A category
    with fewer than MIN_CATEGORY_PRODUCTS viewed products is compared with all products instead (a
    product alone in its category would only be compared with itself), and a comparison rate of 0
    (nothing in it sold) makes no Star or Hidden gem."""
    seen = [p for p in rows if p.get("views")]
    if not seen:
        return
    members: dict[str, list[dict[str, Any]]] = {}
    for p in seen:
        members.setdefault(p["category"], []).append(p)
    by_cat = {k: _peer_stats(m) for k, m in members.items() if len(m) >= MIN_CATEGORY_PRODUCTS}
    store = _peer_stats(seen)
    for p in seen:
        own = p["category"] in by_cat
        cr, median_views, prices = by_cat[p["category"]] if own else store
        views, orders = p["views"], p["view_orders"]
        raw = orders / views
        adjusted = (orders + PRIOR_VIEWS * cr) / (views + PRIOR_VIEWS)
        many = views >= median_views
        good = cr > 0 and adjusted >= cr
        group = ("star" if many else "hidden_gem") if good else ("leaky" if many else "dead_weight")
        price = float(p.get("price") or _median(prices))
        left = views * (cr - raw) * price if group == "leaky" and cr > raw else 0.0
        p.update(
            {
                "compared_with": p["category"] if own else "All products",
                "category_rate": round(cr * 100, 2),
                "adjusted_rate": round(adjusted * 100, 2),
                "vs_category_pts": round((adjusted - cr) * 100, 2),
                "group": group,
                "left_on_table": round(left, 2),
            }
        )


def refunds(rows: list[dict[str, Any]], loose: float) -> dict[str, Any]:
    """Store refund rate and the products refunding most, by rate and by amount (pure). Products
    with less than MIN_REFUND_GROSS of gross sales are left out of the lists."""
    gross = sum(float(p.get("gross_sales") or 0) for p in rows)
    refunded = sum(float(p.get("refunded") or 0) for p in rows)
    listed = [
        {
            k: p[k]
            for k in ("product_id", "name", "category", "gross_sales", "refunded", "refund_rate")
        }
        for p in rows
        if (p.get("gross_sales") or 0) >= MIN_REFUND_GROSS and p.get("refunded")
    ]
    return {
        "store_refund_rate": rate(refunded, gross, 1),
        "total_refunded": round(refunded, 2),
        "refunded_without_product": loose,
        "min_gross_sales": MIN_REFUND_GROSS,
        "products_with_refunds": sum(1 for p in rows if p.get("refunded")),
        "by_rate": sorted(listed, key=lambda r: (-r["refund_rate"], -r["refunded"]))[:10],
        "by_amount": sorted(listed, key=lambda r: -r["refunded"])[:10],
    }


def product_rows(
    copy: list[dict[str, Any]],
    sales: dict[int, dict[str, float]] | None,
    catalog: dict[int, dict[str, Any]],
    views: dict[int, dict[str, int]] | None,
    view_orders: dict[int, int] | None,
) -> list[dict[str, Any]]:
    """One row per product (pure): the order copy's products, Shopify's sales, and products GA4
    saw views for that are in the product list. Net sales, items and orders are Shopify's when its
    report answered, else the order copy's (units x price before discounts)."""
    by_id = {r["product_id"]: r for r in copy if r["product_id"] is not None}
    ids = set(by_id) | set(sales or {}) | ({i for i in (views or {}) if i in catalog})
    out: list[dict[str, Any]] = []
    for pid in ids:
        c = by_id.get(pid) or {}
        cat = catalog.get(pid) or {}
        s = (sales or {}).get(pid)
        name = str(cat.get("title") or c.get("name") or f"Product {pid}")
        v = (views or {}).get(pid, {"views": 0, "add_to_carts": 0})
        items = int(s["items"]) if s else int(c.get("quantity") or 0)
        net = round(s["net"], 2) if s else float(c.get("revenue") or 0)
        row: dict[str, Any] = {
            "product_id": pid,
            "name": name,
            "category": category(name, str(cat.get("product_type") or c.get("product_type") or "")),
            "orders": int(s["orders"]) if s else int(c.get("orders") or 0),
            "items": items,
            "net_sales": net,
            "gross_sales": round(s["gross"], 2) if s else None,
            "discounts": round(s["discounts"], 2) if s else None,
            "refunded": round(s["refunded"], 2) if s else None,
            "refund_rate": rate(s["refunded"], s["gross"], 1) if s else None,
            "price": cat.get("price")
            if cat.get("price") is not None
            else (round(net / items, 2) if items > 0 and net > 0 else None),
            "handle": cat.get("handle"),
            "views": v["views"] if views is not None else None,
            "add_to_carts": v["add_to_carts"] if views is not None else None,
            "add_to_cart_rate": rate(v["add_to_carts"], v["views"], 1) if views else None,
            "view_orders": (view_orders or {}).get(pid, 0) if view_orders is not None else None,
            "conversion_rate": (
                rate((view_orders or {}).get(pid, 0), v["views"], 2)
                if view_orders is not None
                else None
            ),
            "group": None,
        }
        out.append(row)
    for c in copy:  # custom items without a product: order copy figures only
        if c["product_id"] is None:
            out.append(
                {
                    **dict.fromkeys(
                        (
                            "gross_sales",
                            "discounts",
                            "refunded",
                            "refund_rate",
                            "price",
                            "handle",
                            "views",
                            "add_to_carts",
                            "add_to_cart_rate",
                            "view_orders",
                            "conversion_rate",
                            "group",
                        )
                    ),
                    "product_id": None,
                    "name": c["name"],
                    "category": category(c["name"], c.get("product_type") or ""),
                    "orders": c["orders"],
                    "items": c["quantity"],
                    "net_sales": c["revenue"],
                }
            )
    out.sort(key=lambda r: (-(r["net_sales"] or 0), r["name"]))
    return out


def group_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Products, views and net sales per group, and the fix-first list (pure)."""
    groups = []
    for g in GROUPS:
        members = [p for p in rows if p.get("group") == g]
        groups.append(
            {
                "group": g,
                "label": GROUP_LABELS[g],
                "products": len(members),
                "views": sum(p["views"] for p in members),
                "net_sales": round(sum(p["net_sales"] or 0 for p in members), 2),
                "top": [p["name"] for p in sorted(members, key=lambda p: -p["views"])[:3]],
            }
        )
    fix_first = sorted(
        (p for p in rows if p.get("group") == "leaky" and p.get("left_on_table")),
        key=lambda p: -p["left_on_table"],
    )[:10]
    return {
        "groups": groups,
        "fix_first": [
            {
                k: p.get(k)
                for k in (
                    "product_id",
                    "name",
                    "category",
                    "handle",
                    "views",
                    "add_to_cart_rate",
                    "view_orders",
                    "conversion_rate",
                    "compared_with",
                    "category_rate",
                    "price",
                    "left_on_table",
                )
            }
            for p in fix_first
        ],
        "left_on_table": round(sum(p["left_on_table"] for p in fix_first), 2),
    }


# ------------------------------------------------------------------------------------ assembly
def _orders_by_product(snap: Snapshot, w: Window) -> dict[int, set[int]]:
    return {
        p.product_id: set(p.order_ids) for p in product_sales(snap, w) if p.product_id is not None
    }


def _days(n: int) -> str:
    return f"{n} day" if n == 1 else f"{n} days"


def _views_state(days: list[str], window_days: int, unmatched: int) -> dict[str, Any]:
    n = len(days)
    if n >= MIN_VIEW_DAYS:
        note = (
            f"Views and add-to-carts from GA4 for {_days(n)}; conversion uses the orders of "
            "the same days."
            + (
                f" The groups settle as more days come in (best after {RELIABLE_VIEW_DAYS})."
                if n < RELIABLE_VIEW_DAYS
                else ""
            )
        )
        state = "ready"
    elif n:
        note = (
            f"GA4 has product views for {n} of the {_days(window_days)} so far; the groups and the "
            f"fix-first list show once it has {MIN_VIEW_DAYS}."
        )
        state = "collecting"
    else:
        note = "GA4 has no product views for these days."
        state = "collecting"
    return {
        "state": state,
        "days": n,
        "window_days": window_days,
        "from": days[0] if days else None,
        "to": days[-1] if days else None,
        "unmatched_views": unmatched,
        "message": note,
    }


def insights(
    store: str,
    tz: ZoneInfo,
    cur: Days,
    snap: Snapshot,
    gql: shopify.Gql | None = None,
    post: Post | None = None,
) -> dict[str, Any]:
    """Everything the Products tab shows for the local days `cur` (complete days). A source that
    cannot be read leaves its part empty with the reason; the rest still shows."""

    def sales_read() -> tuple[dict[int, dict[str, float]] | None, float, str | None]:
        try:
            s, loose = sales_by_product(store, cur, gql)
            return s, loose, None
        except shopify.AnalyticsError as e:
            return None, 0.0, e.message

    def catalog_read() -> tuple[dict[int, dict[str, Any]], str | None]:
        try:
            return shopify.product_catalog(store, gql), None
        except Exception as e:  # noqa: BLE001 - prices then come from sales / items
            return {}, str(getattr(e, "message", e))[:300]

    def views_read() -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        try:
            return ga4_views(store, cur, post), None
        except ViewsError as e:
            return None, {"state": e.state, "message": e.message}

    with ThreadPoolExecutor(max_workers=3, thread_name_prefix="cro-products") as pool:
        f_sales, f_cat, f_views = (
            pool.submit(sales_read),
            pool.submit(catalog_read),
            pool.submit(views_read),
        )
        sales, loose, sales_error = f_sales.result()
        catalog, catalog_error = f_cat.result()
        ga4, views_error = f_views.result()

    window = days_window(cur[0], cur[1], tz)
    copy = [p.as_dict() for p in product_sales(snap, window)]
    window_days = (cur[1] - cur[0]).days + 1
    views_state = views_error or _views_state(
        ga4["days"] if ga4 else [], window_days, ga4["unmatched_views"] if ga4 else 0
    )
    ready = ga4 is not None and views_state["state"] == "ready"
    view_ids: dict[int, set[int]] | None = None
    if ga4 is not None and ga4["days"]:
        first, last = date.fromisoformat(ga4["days"][0]), date.fromisoformat(ga4["days"][-1])
        view_ids = _orders_by_product(snap, days_window(first, last, tz))
    rows = product_rows(
        copy,
        sales,
        catalog,
        ga4["by_product"] if ga4 else None,
        {k: len(v) for k, v in view_ids.items()} if view_ids is not None else None,
    )
    if ready:
        classify(rows)
    return {
        "products": rows,
        "sales_source": "shopify" if sales is not None else "orders",
        "sales_error": sales_error,
        "catalog_error": catalog_error,
        "views": views_state,
        "views_source": "ga4" if ga4 is not None else None,
        "refunds": refunds(rows, loose) if sales is not None else None,
        "groups": group_summary(rows) if ready else None,
        "price_bands": price_bands(
            rows, _orders_by_product(snap, window), view_ids if ready else None
        ),
        "bought_together": bought_together(snap, window),
    }


def leaky_for(
    store: str, tz: ZoneInfo, cur: Days, snap: Snapshot, post: Post | None = None
) -> dict[str, Any]:
    """The fix-first list for the recommendations, with the GA4 views state (an empty list when
    GA4 has too few days of views or cannot be read)."""
    got = insights(store, tz, cur, snap, post=post)
    groups = got["groups"]
    return {
        "fix_first": groups["fix_first"] if groups else [],
        "days": got["views"].get("days") or 0,
        "state": got["views"]["state"],
        "message": got["views"]["message"],
    }
