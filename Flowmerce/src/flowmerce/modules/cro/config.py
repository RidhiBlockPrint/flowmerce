"""CRO settings and the store/brand mapping.

Supabase uses the same URL and service-role key as Shipping (server only); CRO's tables are in
schema `cro`. Shopify uses each brand's existing app keys (RIDHI_SHOPIFY_* / CPC_SHOPIFY_*): one app
per store for every module.
"""

from __future__ import annotations

import dataclasses
import os
from dataclasses import dataclass

from ..shipping.config import shipping_config
from ..shipping.supabase import SupabaseClient

# ops.stores id -> SEO brand id (whose Shopify keys are used). Same mapping as Shipping.
STORE_BRAND: dict[str, str] = {"RBP": "ridhi", "CPC": "cpc"}
BRAND_STORE: dict[str, str] = {b: s for s, b in STORE_BRAND.items()}

# "Too early to compare" limits from the manager's checklist (about 70 orders and 2,800 sessions a
# day,
# 19 Nov 2026): below these a % change is mostly noise, so the page says so instead of printing it.
MIN_ORDERS_FOR_COMPARISON = 20
MIN_SESSIONS_FOR_COMPARISON = 500

# How many days of orders the page keeps in memory. Covers the 4-week same-weekday average, 14 + 14
# day
# trends and 60-day product reports. Shopify lets the app read 60 days without the read_all_orders
# scope.
SNAPSHOT_DAYS = 63
FIRST_RUN_DAYS = 60


def _int_env(key: str, default: int, low: int, high: int) -> int:
    try:
        value = int((os.environ.get(key) or "").strip() or default)
    except ValueError:
        return default
    return max(low, min(high, value))


@dataclass(frozen=True)
class CroConfig:
    """Tunable CRO settings (all optional in .env)."""

    sync_minutes: int  # order sync + alarm check interval; 0 turns the background job off
    cache_seconds: int  # how long ShopifyQL answers are reused
    snapshot_seconds: int  # how long the in-memory order snapshot is reused between syncs


def cro_config() -> CroConfig:
    """Read the CRO settings from the environment."""
    return CroConfig(
        sync_minutes=_int_env("CRO_SYNC_MINUTES", 15, 0, 1440),
        cache_seconds=_int_env("CRO_CACHE_SECONDS", 600, 0, 86_400),
        snapshot_seconds=_int_env("CRO_SNAPSHOT_SECONDS", 120, 0, 3600),
    )


def store_for(brand: str) -> str:
    """The ops.stores id for a brand id ('ridhi' -> 'RBP'). Raises ValueError for an unknown
    brand.
    """
    store = BRAND_STORE.get(brand)
    if store is None:
        raise ValueError(
            f"Unknown brand {brand!r}; expected one of {', '.join(sorted(BRAND_STORE))}."
        )
    return store


_cro: SupabaseClient | None = None


def cro_client() -> SupabaseClient:
    """One shared Supabase client for schema `cro` (Shipping's client class, Shipping's keys)."""
    global _cro
    if _cro is None:
        _cro = SupabaseClient(dataclasses.replace(shipping_config(), schema="cro"))
    return _cro


def set_cro_client(client: SupabaseClient | None) -> None:
    """Tests swap in a client with a fake transport."""
    global _cro
    if _cro is not None and _cro is not client:
        _cro.close()
    _cro = client
