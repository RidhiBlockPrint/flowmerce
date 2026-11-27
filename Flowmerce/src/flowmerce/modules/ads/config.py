"""Ads settings: which ad account belongs to which brand, the API version, the sync timing and the
Supabase client.

The account IDs and tokens come from the server's environment (.env): RIDHI_META_AD_ACCOUNT_ID,
RIDHI_META_ACCESS_TOKEN, CPC_META_AD_ACCOUNT_ID, CPC_META_ACCESS_TOKEN for Meta;
GOOGLE_ADS_CLIENT_ID, GOOGLE_ADS_CLIENT_SECRET, GOOGLE_ADS_REFRESH_TOKEN (one Google login for
both brands), optional GOOGLE_ADS_DEVELOPER_TOKEN and GOOGLE_ADS_LOGIN_CUSTOMER_ID (a manager
account), and RIDHI_GOOGLE_ADS_CUSTOMER_ID / CPC_GOOGLE_ADS_CUSTOMER_ID for Google. They are
never stored in Supabase, never sent to the browser and never logged.
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
# Google Ads API, read with plain REST (googleAds:search). Each version is withdrawn about a year
# after release, so it is pinned and checked. v26 answered on 2026-11-27.
GOOGLE_ADS_API_VERSION = "v26"
GOOGLE_ADS_BASE_URL = "https://googleads.googleapis.com"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105 - an address, not a secret

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


@dataclass(frozen=True)
class GoogleAccount:
    """One brand's Google Ads account as set in .env, with the shared Google login."""

    brand: str
    customer_id: str  # ten digits, no dashes
    client_id: str
    client_secret: str
    refresh_token: str
    developer_token: str  # may be empty: Google answered this login without one (2026-11-27)
    login_customer_id: str  # a manager account to read through, or empty

    @property
    def key(self) -> str:
        """The account's key in schema `ads` ('google:ridhi')."""
        return f"google:{self.brand}"


def _digits(v: str | None) -> str:
    return "".join(ch for ch in (v or "") if ch.isdigit())


def google_account(brand: str) -> GoogleAccount | None:
    """The brand's Google Ads account, or None when its customer ID or the Google login is not
    set."""
    env = {
        n: (os.environ.get(n) or "").strip()
        for n in (
            "GOOGLE_ADS_CLIENT_ID",
            "GOOGLE_ADS_CLIENT_SECRET",
            "GOOGLE_ADS_REFRESH_TOKEN",
            "GOOGLE_ADS_DEVELOPER_TOKEN",
            "GOOGLE_ADS_LOGIN_CUSTOMER_ID",
        )
    }
    customer = _digits(os.environ.get(f"{brand.upper()}_GOOGLE_ADS_CUSTOMER_ID"))
    if len(customer) != 10 or not all(
        env[n]
        for n in ("GOOGLE_ADS_CLIENT_ID", "GOOGLE_ADS_CLIENT_SECRET", "GOOGLE_ADS_REFRESH_TOKEN")
    ):
        return None
    return GoogleAccount(
        brand,
        customer,
        env["GOOGLE_ADS_CLIENT_ID"],
        env["GOOGLE_ADS_CLIENT_SECRET"],
        env["GOOGLE_ADS_REFRESH_TOKEN"],
        env["GOOGLE_ADS_DEVELOPER_TOKEN"],
        _digits(env["GOOGLE_ADS_LOGIN_CUSTOMER_ID"]),
    )


def google_configured(brand: str) -> bool:
    """Whether the brand's Google Ads account and the Google login are set."""
    return google_account(brand) is not None


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
