"""Ads settings: which ad accounts to read, and the credentials for each platform.

Secrets come from the environment (`.env`, git-ignored) and never leave the server: no token is
logged, returned by a route or written to the database. Supabase is the same project Shipping and
CRO use; the Ads tables live in schema `ads`.

Naming follows the existing per-brand convention (`RIDHI_*` / `CPC_*` for things that differ per
store, bare names for things shared by both):

    META_SYSTEM_USER_TOKEN        one Business Manager system user token for both stores
    META_API_VERSION              pinned Graph version (default v25.0, the Marketing API release)
    RIDHI_META_AD_ACCOUNT_ID      act_<digits>
    CPC_META_AD_ACCOUNT_ID        act_<digits>

    GOOGLE_ADS_CLIENT_ID          OAuth client of the Google Cloud project
    GOOGLE_ADS_CLIENT_SECRET
    GOOGLE_ADS_REFRESH_TOKEN      one consent, reused; exchanged for an access token per run
    GOOGLE_ADS_LOGIN_CUSTOMER_ID  the manager (MCC) account, digits only; optional
    GOOGLE_ADS_API_VERSION        pinned API version (default v26)
    RIDHI_GOOGLE_ADS_CUSTOMER_ID  10 digits, no dashes
    CPC_GOOGLE_ADS_CUSTOMER_ID

Google no longer uses a developer token: it was sunset on 2026-09-09 and API access levels are now
granted to the Google Cloud project that issued the OAuth credentials. The header is still accepted
but ignored, and Google says it will be rejected in a future major version, so Flowmerce does not
send it. What matters instead is the project's access level: a project at Test level cannot read a
production account at all (error CLOUD_PROJECT_NOT_APPROVED_FOR_PRODUCTION).
Source: developers.google.com/google-ads/api/docs/api-policy/access-levels and .../deprecations,
read 2026-11-25.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from ..cro.config import BRAND_STORE, STORE_BRAND

__all__ = [
    "BRAND_STORE",
    "STORE_BRAND",
    "AdsConfig",
    "GoogleCredentials",
    "MetaCredentials",
    "ads_client",
    "ads_config",
    "google_credentials",
    "meta_credentials",
    "set_ads_client",
    "store_for",
]

# Pinned API versions. Both platforms break old versions on a timetable, so the version is never
# left to the platform's default. Meta Marketing API v25.0 (released 2026-02-18) and Google Ads API
# v26 (v26.2 released 2026-11-11) were the current releases when this module was written.
DEFAULT_META_VERSION = "v25.0"
DEFAULT_GOOGLE_VERSION = "v26"

# Platforms restate the last few days as conversions arrive late, so every sync re-reads a window
# that ends today rather than trusting figures it already stored.
RESTATEMENT_DAYS = 7
FIRST_RUN_DAYS = 90


def _env(key: str, default: str = "") -> str:
    return (os.environ.get(key) or default).strip()


def _int_env(key: str, default: int, low: int, high: int) -> int:
    try:
        value = int(_env(key) or default)
    except ValueError:
        return default
    return max(low, min(high, value))


def store_for(brand: str) -> str:
    """The ops.stores id for a brand id ('ridhi' -> 'RBP'). Raises ValueError for an unknown one."""
    store = BRAND_STORE.get(brand)
    if store is None:
        raise ValueError(
            f"Unknown brand {brand!r}; expected one of {', '.join(sorted(BRAND_STORE))}."
        )
    return store


@dataclass(frozen=True)
class MetaCredentials:
    """Meta Marketing API access for one store. `token` is a system user token with ads_read."""

    token: str
    account_id: str  # act_<digits>
    api_version: str

    @property
    def configured(self) -> bool:
        return bool(self.token and self.account_id)

    @property
    def missing(self) -> list[str]:
        """Which environment variables still have to be filled in, for the status page."""
        gaps: list[str] = []
        if not self.token:
            gaps.append("META_SYSTEM_USER_TOKEN")
        if not self.account_id:
            gaps.append("<BRAND>_META_AD_ACCOUNT_ID")
        return gaps


@dataclass(frozen=True)
class GoogleCredentials:
    """Google Ads API access for one store. No developer token: see the module docstring."""

    client_id: str
    client_secret: str
    refresh_token: str
    customer_id: str  # 10 digits, no dashes
    login_customer_id: str  # the MCC, digits only; empty when the account is accessed directly
    api_version: str

    @property
    def configured(self) -> bool:
        return bool(
            self.client_id and self.client_secret and self.refresh_token and self.customer_id
        )

    @property
    def missing(self) -> list[str]:
        gaps: list[str] = []
        if not self.client_id:
            gaps.append("GOOGLE_ADS_CLIENT_ID")
        if not self.client_secret:
            gaps.append("GOOGLE_ADS_CLIENT_SECRET")
        if not self.refresh_token:
            gaps.append("GOOGLE_ADS_REFRESH_TOKEN")
        if not self.customer_id:
            gaps.append("<BRAND>_GOOGLE_ADS_CUSTOMER_ID")
        return gaps


def _digits(value: str) -> str:
    """Google customer ids are written 123-456-7890 in the UI but sent as digits only."""
    return "".join(ch for ch in value if ch.isdigit())


def meta_credentials(store: str) -> MetaCredentials:
    """Meta credentials for a store id ('RBP' / 'CPC'). The token is shared, the account is not."""
    brand = STORE_BRAND.get(store, "").upper()
    prefix = "RIDHI" if brand == "RIDHI" else brand
    account = _env(f"{prefix}_META_AD_ACCOUNT_ID") if prefix else ""
    # The ad account id is act_<digits> in the API; accept a bare number and add the prefix.
    if account and not account.startswith("act_"):
        account = f"act_{_digits(account)}" if _digits(account) else ""
    return MetaCredentials(
        token=_env("META_SYSTEM_USER_TOKEN"),
        account_id=account,
        api_version=_env("META_API_VERSION", DEFAULT_META_VERSION),
    )


def google_credentials(store: str) -> GoogleCredentials:
    """Google Ads credentials for a store id. The OAuth client is shared, the customer id is not."""
    brand = STORE_BRAND.get(store, "").upper()
    prefix = "RIDHI" if brand == "RIDHI" else brand
    return GoogleCredentials(
        client_id=_env("GOOGLE_ADS_CLIENT_ID"),
        client_secret=_env("GOOGLE_ADS_CLIENT_SECRET"),
        refresh_token=_env("GOOGLE_ADS_REFRESH_TOKEN"),
        customer_id=_digits(_env(f"{prefix}_GOOGLE_ADS_CUSTOMER_ID")) if prefix else "",
        login_customer_id=_digits(_env("GOOGLE_ADS_LOGIN_CUSTOMER_ID")),
        api_version=_env("GOOGLE_ADS_API_VERSION", DEFAULT_GOOGLE_VERSION),
    )


@dataclass(frozen=True)
class AdsConfig:
    """Tunable Ads settings (all optional in .env)."""

    sync_minutes: int  # background sync interval; 0 turns the background job off
    timeout: float  # HTTP timeout for a single platform request
    max_days: int  # how many days one sync reads at most on a first run
    demo: bool  # show demo figures instead of calling the platforms


def ads_config() -> AdsConfig:
    """Read the Ads settings from the environment.

    ADS_DEMO defaults to true while no credentials are set, so the pages have something to show
    before the manager hands over access; it is forced on by the project-wide DEMO_MODE.
    """
    try:
        timeout = float(_env("ADS_TIMEOUT_SECONDS", "30"))
    except ValueError:
        timeout = 30.0
    demo_flag = _env("ADS_DEMO").lower()
    demo_mode = _env("DEMO_MODE").lower() in ("true", "1", "yes")
    if demo_flag in ("false", "0", "no"):
        demo = demo_mode  # DEMO_MODE wins: it must never show real figures
    elif demo_flag in ("true", "1", "yes"):
        demo = True
    else:
        demo = demo_mode or not _any_credentials()
    return AdsConfig(
        sync_minutes=_int_env("ADS_SYNC_MINUTES", 180, 0, 1440),
        timeout=max(5.0, min(120.0, timeout)),
        max_days=_int_env("ADS_MAX_DAYS", FIRST_RUN_DAYS, 1, 400),
        demo=demo,
    )


def _any_credentials() -> bool:
    """Whether any platform is configured for any store."""
    return any(
        meta_credentials(store).configured or google_credentials(store).configured
        for store in STORE_BRAND
    )


# ------------------------------------------------------------------ Supabase client (schema `ads`)
# Shipping's client class and keys, Shipping's connection settings; only the schema differs. Built
# lazily so importing this module never needs Supabase to be configured.
_ads: object | None = None


def ads_client() -> object:
    """One shared Supabase client for schema `ads`.

    Returns Shipping's ``SupabaseClient``; typed as ``object`` here so the import stays local and a
    missing Supabase configuration cannot break an import of this module.
    """
    global _ads
    if _ads is None:
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
        _ads = SupabaseClient(dataclasses.replace(shipping_config(), schema="ads"), transport)
    return _ads


def set_ads_client(client: object | None) -> None:
    """Tests swap in a client with a fake transport."""
    global _ads
    close = getattr(_ads, "close", None)
    if _ads is not None and _ads is not client and callable(close):
        close()
    _ads = client
