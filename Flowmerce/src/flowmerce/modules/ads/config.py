"""Ads settings: which ad account belongs to which brand, the API version, the sync timing and the
Supabase client.

The account IDs and tokens come from the server's environment (.env): RIDHI_META_AD_ACCOUNT_ID,
RIDHI_META_ACCESS_TOKEN, CPC_META_AD_ACCOUNT_ID, CPC_META_ACCESS_TOKEN. They are never stored in
Supabase, never sent to the browser and never logged.
"""

from __future__ import annotations

import dataclasses
import os
from dataclasses import dataclass

import httpx

from ..shipping.config import shipping_config
from ..shipping.supabase import SupabaseClient

BRANDS: tuple[str, ...] = ("ridhi", "cpc")
# The Shopify store behind each brand (ops.stores id) and the time zone Shopify reports for it.
# ops.stores.timezone is not kept up to date (both stores say America/Los_Angeles there), so the
# zone Shopify reports is used here.
BRAND_STORE: dict[str, str] = {"ridhi": "RBP", "cpc": "CPC"}
STORE_TIMEZONE: dict[str, str] = {"ridhi": "America/New_York", "cpc": "America/Phoenix"}

# Meta refuses calls without a version ("deprecated version of the Ads API"), so it is pinned.
# Checked 2026-11-24.
META_API_VERSION = "v27.0"
META_BASE_URL = "https://graph.facebook.com"

# Days loaded on the first sync, and re-read by the nightly full sync (Meta keeps revising recent
# days as late purchases are attributed). Every other run re-reads the last few days only.
FIRST_LOAD_DAYS = 90
FULL_RELOAD_DAYS = 28
QUICK_RELOAD_DAYS = 3
FULL_EVERY_HOURS = 20


@dataclass(frozen=True)
class MetaAccount:
    """One brand's Meta ad account as set in .env."""

    brand: str
    account_id: str  # always with the act_ prefix
    token: str

    @property
    def key(self) -> str:
        """The account's key in schema `ads` ('meta:ridhi')."""
        return f"meta:{self.brand}"


def meta_account(brand: str) -> MetaAccount | None:
    """The brand's Meta account, or None when its ID or token is not set."""
    prefix = brand.upper()
    raw = (os.environ.get(f"{prefix}_META_AD_ACCOUNT_ID") or "").strip()
    token = (os.environ.get(f"{prefix}_META_ACCESS_TOKEN") or "").strip()
    if not raw or not token:
        return None
    return MetaAccount(brand, raw if raw.startswith("act_") else f"act_{raw}", token)


def google_configured(brand: str) -> bool:
    """Whether the brand's Google Ads keys are set. Google Ads is read from phase 3 on; until then
    the page says it is not connected even when this is true."""
    names = (
        "GOOGLE_ADS_DEVELOPER_TOKEN",
        "GOOGLE_ADS_REFRESH_TOKEN",
        f"{brand.upper()}_GOOGLE_ADS_CUSTOMER_ID",
    )
    return all((os.environ.get(n) or "").strip() for n in names)


def check_brand(brand: str) -> str:
    """The brand id, or ValueError: Ads shows one brand at a time and never adds two brands
    together."""
    if brand not in BRANDS:
        raise ValueError("brand must be 'ridhi' or 'cpc'. Ads shows one brand at a time.")
    return brand


def _int_env(key: str, default: int, low: int, high: int) -> int:
    try:
        value = int((os.environ.get(key) or "").strip() or default)
    except ValueError:
        return default
    return max(low, min(high, value))


@dataclass(frozen=True)
class AdsConfig:
    """Tunable settings (all optional in .env)."""

    sync_minutes: int  # how often the ad accounts are read; 0 turns the background job off
    timeout: float  # seconds for one Meta request


def ads_config() -> AdsConfig:
    """Read the Ads settings from the environment."""
    return AdsConfig(sync_minutes=_int_env("ADS_SYNC_MINUTES", 60, 0, 1440), timeout=90.0)


_client: SupabaseClient | None = None


def ads_client() -> SupabaseClient:
    """One shared Supabase client for schema `ads` (Shipping's client class and keys, like CRO)."""
    global _client
    if _client is None:
        transport = httpx.HTTPTransport(
            limits=httpx.Limits(max_connections=10, keepalive_expiry=55.0)
        )
        _client = SupabaseClient(dataclasses.replace(shipping_config(), schema="ads"), transport)
    return _client


def set_ads_client(client: SupabaseClient | None) -> None:
    """Tests swap in a client with a fake transport."""
    global _client
    if _client is not None and _client is not client:
        _client.close()
    _client = client
