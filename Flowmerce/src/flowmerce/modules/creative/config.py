"""Creative Strategist settings and the Supabase client for schema `creative`.

Supabase is the same project Shipping, CRO and Ads use; only the schema differs. Claude is the one
the SEO and CRO modules already use (ANTHROPIC_API_KEY), so no new credential and no new package.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from ..ads.config import BRAND_STORE, STORE_BRAND, store_for

__all__ = [
    "BRAND_STORE",
    "STORE_BRAND",
    "CreativeConfig",
    "creative_client",
    "creative_config",
    "set_creative_client",
    "store_for",
]

# A finding needs this much behind it before it is worth acting on. Below it the page still shows
# the row, marked as too early, rather than hiding it: hidden data makes people distrust the page.
MIN_IMPRESSIONS = 1000
MIN_SPEND = 1000.0

# How many days of ad figures one round of insights reads. Four weeks covers a full weekly cycle
# without reaching back into a different season of the catalogue.
INSIGHT_DAYS = 28


def _int_env(key: str, default: int, low: int, high: int) -> int:
    try:
        value = int((os.environ.get(key) or "").strip() or default)
    except ValueError:
        return default
    return max(low, min(high, value))


@dataclass(frozen=True)
class CreativeConfig:
    """Tunable Creative settings (all optional in .env)."""

    insight_days: int  # how many complete days one round of insights reads
    min_impressions: int  # below this a finding is marked "too early", not acted on
    max_concepts: int  # how many concepts one AI round may propose
    demo: bool  # show sample insights and concepts instead of reading ads.*


def creative_config() -> CreativeConfig:
    """Read the Creative settings from the environment.

    Demo follows the Ads module: while no ad platform is connected there is nothing real to read,
    so the page shows samples and says so.
    """
    from ..ads.config import ads_config

    flag = (os.environ.get("CREATIVE_DEMO") or "").strip().lower()
    demo_mode = (os.environ.get("DEMO_MODE") or "").strip().lower() in ("true", "1", "yes")
    if flag in ("false", "0", "no"):
        demo = demo_mode  # DEMO_MODE wins: it must never show real figures
    elif flag in ("true", "1", "yes"):
        demo = True
    else:
        demo = ads_config().demo
    return CreativeConfig(
        insight_days=_int_env("CREATIVE_INSIGHT_DAYS", INSIGHT_DAYS, 7, 180),
        min_impressions=_int_env("CREATIVE_MIN_IMPRESSIONS", MIN_IMPRESSIONS, 100, 1_000_000),
        max_concepts=_int_env("CREATIVE_MAX_CONCEPTS", 5, 1, 20),
        demo=demo,
    )


# ------------------------------------------------------------ Supabase client (schema `creative`)
_creative: object | None = None


def creative_client() -> object:
    """One shared Supabase client for schema `creative` (Shipping's client class and keys)."""
    global _creative
    if _creative is None:
        import dataclasses

        import httpx

        from ..cro.config import SUPABASE_KEEPALIVE
        from ..shipping.config import shipping_config
        from ..shipping.supabase import SupabaseClient

        transport = httpx.HTTPTransport(
            limits=httpx.Limits(
                max_connections=20,
                max_keepalive_connections=10,
                keepalive_expiry=SUPABASE_KEEPALIVE,
            )
        )
        _creative = SupabaseClient(
            dataclasses.replace(shipping_config(), schema="creative"), transport
        )
    return _creative


def set_creative_client(client: object | None) -> None:
    """Tests swap in a client with a fake transport."""
    global _creative
    close = getattr(_creative, "close", None)
    if _creative is not None and _creative is not client and callable(close):
        close()
    _creative = client
