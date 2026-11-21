"""Shopify access for CRO: orders with money fields and line items, ShopifyQL, the shop's timezone,
the product list (price and type per product).

Uses the brand's existing Admin API client (`seo.integrations.shopify`), so the keys stay in
Flowmerce's .env and every module talks to Shopify through one app per store. Nothing about the
customer is requested.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from datetime import datetime
from typing import Any

from .config import STORE_BRAND

Gql = Callable[[str, dict[str, Any] | None], dict[str, Any]]


class AnalyticsError(Exception):
    """ShopifyQL could not be read. `state` is what the page shows: not_configured,
    reports_access_missing,
    query_error or shopify_error."""

    def __init__(self, state: str, message: str) -> None:
        super().__init__(message)
        self.state = state
        self.message = message


ORDERS_QUERY = """
query CroOrders($q: String!, $after: String) {
  orders(first: 25, after: $after, query: $q, sortKey: UPDATED_AT) {
    pageInfo { hasNextPage endCursor }
    nodes {
      legacyResourceId name createdAt updatedAt cancelledAt test displayFinancialStatus
      currentTotalPriceSet { shopMoney { amount currencyCode } }
      currentSubtotalPriceSet { shopMoney { amount } }
      currentTotalDiscountsSet { shopMoney { amount } }
      currentShippingPriceSet { shopMoney { amount } }
      currentTotalTaxSet { shopMoney { amount } }
      totalRefundedSet { shopMoney { amount } }
      lineItems(first: 30) {
        nodes {
          title quantity
          originalUnitPriceSet { shopMoney { amount } }
          product { legacyResourceId productType tags }
        }
      }
    }
  }
}
"""

SHOPIFYQL_QUERY = """
query CroShopifyQL($q: String!) {
  shopifyqlQuery(query: $q) { tableData { columns { name } rows } parseErrors }
}
"""

SHOP_QUERY = "{ shop { ianaTimezone currencyCode } }"


def _brand(store: str) -> Any:
    from ..seo.config import config

    return config.brands.get(STORE_BRAND.get(store, ""))


def configured(store: str) -> bool:
    """True when this store has Shopify keys in .env."""
    from ..seo.integrations.shopify import configured as brand_configured

    b = _brand(store)
    return bool(b and brand_configured(b))


def gql_for(store: str) -> Gql:
    """A GraphQL caller bound to this store's app."""
    from ..seo.integrations.shopify import _gql

    b = _brand(store)

    def call(query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        result: dict[str, Any] = _gql(b, query, variables)
        return result

    return call


# ------------------------------------------------------------------------------------------ orders
def _money(node: dict[str, Any], key: str) -> float:
    try:
        return round(float(((node.get(key) or {}).get("shopMoney") or {}).get("amount") or 0), 2)
    except TypeError, ValueError:
        return 0.0


def _int_id(value: Any) -> int | None:
    try:
        return int(value)
    except TypeError, ValueError:
        return None


def order_row(store: str, node: dict[str, Any]) -> dict[str, Any] | None:
    """One Shopify order node -> the shape cro.save_orders() expects. None for a test order or a bad
    node.
    """
    oid = _int_id(node.get("legacyResourceId"))
    if node.get("test") or oid is None or not node.get("createdAt"):
        return None
    total_set = (node.get("currentTotalPriceSet") or {}).get("shopMoney") or {}
    lines = []
    for i, item in enumerate(((node.get("lineItems") or {}).get("nodes")) or [], start=1):
        product = item.get("product") or {}
        lines.append(
            {
                "line_no": i,
                "product_id": _int_id(product.get("legacyResourceId")),
                "title": str(item.get("title") or "")[:500],
                "product_type": str(product.get("productType") or "")[:255],
                "tags": ", ".join(str(t) for t in (product.get("tags") or []))[:2000],
                "quantity": max(0, int(item.get("quantity") or 0)),
                "unit_price": _money(item, "originalUnitPriceSet"),
            }
        )
    return {
        "id": oid,
        "store": store,
        "name": str(node.get("name") or "")[:100],
        "placed_at": node["createdAt"],
        "shop_updated_at": node.get("updatedAt") or node["createdAt"],
        "cancelled_at": node.get("cancelledAt"),
        "financial_status": node.get("displayFinancialStatus"),
        "currency": total_set.get("currencyCode") or "USD",
        "total": _money(node, "currentTotalPriceSet"),
        "subtotal": _money(node, "currentSubtotalPriceSet"),
        "discounts": _money(node, "currentTotalDiscountsSet"),
        "shipping": _money(node, "currentShippingPriceSet"),
        "tax": _money(node, "currentTotalTaxSet"),
        "refunded": _money(node, "totalRefundedSet"),
        "lines": lines,
    }


def iter_orders(gql: Gql, since: datetime) -> Iterator[dict[str, Any]]:
    """Every order updated since `since`, oldest change first, one page (25 orders) at a time."""
    search = f"updated_at:>='{since.strftime('%Y-%m-%dT%H:%M:%SZ')}'"
    after: str | None = None
    while True:
        data = gql(ORDERS_QUERY, {"q": search, "after": after})["orders"]
        yield from data.get("nodes") or []
        page = data.get("pageInfo") or {}
        if not page.get("hasNextPage"):
            return
        after = page.get("endCursor")


# ------------------------------------------------------------------------------------------
# ShopifyQL
def _rows(table: dict[str, Any]) -> list[dict[str, Any]]:
    """ShopifyQL rows as dicts. Rows arrive as objects keyed by column name, or as lists in column
    order.
    """
    names = [str(c.get("name")) for c in table.get("columns") or []]
    out: list[dict[str, Any]] = []
    for row in table.get("rows") or []:
        if isinstance(row, dict):
            out.append(row)
        elif isinstance(row, list):
            out.append(dict(zip(names, row, strict=False)))
    return out


def shopifyql(gql: Gql, query: str) -> list[dict[str, Any]]:
    """Run one ShopifyQL query. Raises AnalyticsError with a plain state when it cannot be
    answered.
    """
    try:
        data = gql(SHOPIFYQL_QUERY, {"q": query})["shopifyqlQuery"]
    except Exception as e:  # noqa: BLE001 - every Shopify failure becomes one explained state
        message = getattr(e, "message", None) or str(e)
        if "read_reports" in message or "shopifyqlQuery" in message:
            raise AnalyticsError(
                "reports_access_missing",
                "Shopify refused the analytics query. The store's app needs the read_reports "
                "scope and "
                "Level 2 protected customer data access (name, email, phone, address).",
            ) from None
        if getattr(e, "code", "") == "pending_setup":
            raise AnalyticsError("not_configured", message) from None
        raise AnalyticsError(
            "shopify_error", f"Shopify analytics could not be read: {message[:300]}"
        ) from None
    if data.get("parseErrors"):
        raise AnalyticsError(
            "query_error", f"Shopify rejected the analytics query: {data['parseErrors']}"
        )
    return _rows(data.get("tableData") or {})


# ------------------------------------------------------------------------------------------ shop
_shop_cache: dict[str, tuple[float, dict[str, str]]] = {}
SHOP_CACHE_SECONDS = 6 * 3600


def shop_info(store: str, gql: Gql | None = None) -> dict[str, str]:
    """The shop's timezone and currency as Shopify reports them (cached for 6 hours)."""
    cached = _shop_cache.get(store)
    if cached and cached[0] > time.monotonic():
        return cached[1]
    shop = (gql or gql_for(store))(SHOP_QUERY, None)["shop"]
    info = {
        "timezone": str(shop.get("ianaTimezone") or "UTC"),
        "currency": str(shop.get("currencyCode") or "USD"),
    }
    _shop_cache[store] = (time.monotonic() + SHOP_CACHE_SECONDS, info)
    return info


# --------------------------------------------------------------------------------------- products
PRODUCTS_QUERY = """
query CroProducts($after: String) {
  products(first: 250, after: $after) {
    pageInfo { hasNextPage endCursor }
    nodes {
      legacyResourceId title handle productType
      priceRangeV2 { minVariantPrice { amount } }
    }
  }
}
"""
_catalog_cache: dict[str, tuple[float, dict[int, dict[str, Any]]]] = {}
CATALOG_PAGES = 80  # 20,000 products at most


def product_catalog(store: str, gql: Gql | None = None) -> dict[int, dict[str, Any]]:
    """Every product's title, handle, type and lowest variant price ("from $X"), by product id
    (cached for 6 hours)."""
    cached = _catalog_cache.get(store)
    if cached and cached[0] > time.monotonic():
        return cached[1]
    call = gql or gql_for(store)
    out: dict[int, dict[str, Any]] = {}
    after = None
    for _ in range(CATALOG_PAGES):
        page = call(PRODUCTS_QUERY, {"after": after})["products"]
        for n in page.get("nodes") or []:
            pid = _int_id(n.get("legacyResourceId"))
            if pid is None:
                continue
            price = ((n.get("priceRangeV2") or {}).get("minVariantPrice") or {}).get("amount")
            try:
                value: float | None = round(float(price), 2) if price is not None else None
            except TypeError, ValueError:
                value = None
            out[pid] = {
                "title": str(n.get("title") or ""),
                "handle": n.get("handle"),
                "product_type": str(n.get("productType") or ""),
                "price": value,
            }
        info = page.get("pageInfo") or {}
        if not info.get("hasNextPage"):
            break
        after = info.get("endCursor")
    _catalog_cache[store] = (time.monotonic() + SHOP_CACHE_SECONDS, out)
    return out


CATALOG_REFRESH_LEFT = 3600  # the background job reads the list again when less than this is left


def warm_catalog(store: str, gql: Gql | None = None) -> bool:
    """Keep the product list cached (called by the background job), so no page waits the ~2 s
    it takes to read: read again when the cached copy has less than an hour left. True when it
    was read now."""
    cached = _catalog_cache.get(store)
    if cached and cached[0] - time.monotonic() > CATALOG_REFRESH_LEFT:
        return False
    _catalog_cache.pop(store, None)
    product_catalog(store, gql)
    return True
