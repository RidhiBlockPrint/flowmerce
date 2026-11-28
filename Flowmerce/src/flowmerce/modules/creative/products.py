"""Product context: each store's Shopify products and what they look like.

Products are read from Shopify with SEO & Blog's Shopify connection (the same store credentials,
read-only) and kept in creative.product. Print, color, category and season fit are suggested by
Claude (see tagging.py) and confirmed or corrected by a person here. A sync refreshes only the
Shopify fields, so tags survive it; products Shopify no longer lists are marked inactive, not
deleted.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from . import taxonomy
from .config import creative_client, creative_config, store_for


class NotFoundError(LookupError):
    """The product or ad does not exist for this store (becomes HTTP 404)."""


class NotConfiguredError(RuntimeError):
    """A connection this action needs is not set up (becomes HTTP 412)."""


def require_live(what: str) -> None:
    """Refuse a write while the page shows sample data (no ad account connected)."""
    if creative_config().demo:
        raise NotConfiguredError(
            f"{what} needs a connected ad account; the Creative page is showing sample data."
        )


def client() -> Any:
    """The Supabase client for schema `creative` (tests swap in a fake with the same methods)."""
    return creative_client()


def sync(brand: str) -> dict[str, Any]:
    """Read the store's active Shopify products into creative.product."""
    from ..seo.config import config as seo_config
    from ..seo.integrations import shopify

    store = store_for(brand)
    require_live("Reading products")
    b = seo_config.brands.get(brand)
    if b is None or not shopify.configured(b):
        raise NotConfiguredError(
            f"Shopify is not set up for {brand}. Add its shop and Admin API token to .env "
            "(the same ones SEO & Blog uses)."
        )
    listing = shopify.list_products(b)
    stamp = datetime.now(UTC).isoformat()
    rows = [
        {
            "store": store,
            "handle": str(p["handle"]).lower(),
            "title": str(p.get("title") or ""),
            "product_type": str(p.get("type") or ""),
            "image_url": p.get("image") or None,
            "url": p.get("url") or None,
            "active": True,
            "synced_at": stamp,
        }
        for p in listing
        if p.get("handle")
    ]
    c = client()
    for i in range(0, len(rows), 500):
        c.upsert("product", rows[i : i + 500], on_conflict="store,handle")
    c.update("product", [("store", f"eq.{store}"), ("synced_at", f"lt.{stamp}")], {"active": False})
    return {
        "brand": brand,
        "products": len(rows),
        "truncated": bool(getattr(listing, "truncated", False)),
    }


def by_handle(brand: str) -> dict[str, dict[str, Any]]:
    """Every product of the store, by handle (active or not, since old ads link to old products)."""
    rows = (
        client()
        .select("product", [("select", "*"), ("store", f"eq.{store_for(brand)}")], limit=20_000)
        .rows
    )
    return {str(r["handle"]): r for r in rows}


def listing(brand: str, include_inactive: bool = False) -> list[dict[str, Any]]:
    """Products for the Product context tab, by title (none in demo mode)."""
    if creative_config().demo:
        store_for(brand)
        return []
    params: list[tuple[str, str]] = [
        ("select", "*"),
        ("store", f"eq.{store_for(brand)}"),
        ("order", "title.asc"),
    ]
    if not include_inactive:
        params.append(("active", "eq.true"))
    return list(client().select("product", params, limit=20_000).rows)


def update(brand: str, handle: str, fields: dict[str, Any]) -> dict[str, Any]:
    """Set attributes by hand, or confirm Claude's (`{"confirmed": true}`). Returns the product."""
    store = store_for(brand)
    require_live("Editing products")
    c = client()
    found = c.select(
        "product",
        [("select", "handle"), ("store", f"eq.{store}"), ("handle", f"eq.{handle}")],
        limit=1,
    ).rows
    if not found:
        raise NotFoundError(f"No product {handle!r} for {brand}.")
    changes = {
        k: taxonomy.check_value(k, str(v or ""), taxonomy.PRODUCT_FIELDS)
        for k, v in fields.items()
        if k != "confirmed"
    }
    if not changes and not fields.get("confirmed"):
        raise taxonomy.InvalidTagError(
            "Nothing to change: send attribute values or confirmed=true."
        )
    values: dict[str, Any] = {
        **changes,
        "confirmed": True,
        "tagged_at": datetime.now(UTC).isoformat(),
    }
    if changes:
        values["source"] = "manual"
    c.update("product", [("store", f"eq.{store}"), ("handle", f"eq.{handle}")], values)
    return dict(
        c.select(
            "product",
            [("select", "*"), ("store", f"eq.{store}"), ("handle", f"eq.{handle}")],
            limit=1,
        ).rows[0]
    )
