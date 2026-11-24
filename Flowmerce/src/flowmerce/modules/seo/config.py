"""Server configuration. Every secret is read from the environment (or a local, git-ignored .env file)
and stays on the server: nothing here is sent to the browser except what brand_public() picks out."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(os.environ.get("FLOWMERCE_ROOT") or Path(__file__).resolve().parents[4])


def _load_env_file(path: Path) -> None:
    """Minimal .env reader: KEY=VALUE lines, # comments, optional quotes. Real environment wins."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key.strip(), value)


_load_env_file(ROOT / ".env")


def env(key: str, default: str = "") -> str:
    return (os.environ.get(key) or default).strip()


def flag(key: str, default: bool = False) -> bool:
    v = env(key)
    return default if not v else v.lower() in ("1", "true", "yes", "on")


BRAND_IDS = ("ridhi", "cpc")


def normalize_ga4_property_id(value: str) -> str:
    """GA4 property ids are numeric. Accept the 'properties/123' form people copy from the GA4 admin and keep only the number,
    so the Data API URL is never built as properties/properties%2F123."""
    v = value.strip()
    return v[len("properties/"):].strip() if v.lower().startswith("properties/") else v


@dataclass(frozen=True)
class BrandConfig:
    id: str
    name: str
    short: str
    storefront_domain: str
    shop_domain: str
    admin_token: str
    client_id: str
    client_secret: str
    blog_handle: str
    gsc_property: str
    ga4_property_id: str


def _brand(bid: str, prefix: str, name: str, short: str, storefront: str, shop: str, blog: str, gsc: str) -> BrandConfig:
    return BrandConfig(
        id=bid,
        name=env(f"{prefix}_NAME", name),
        short=short,
        storefront_domain=env(f"{prefix}_STOREFRONT_DOMAIN", storefront),
        shop_domain=env(f"{prefix}_SHOPIFY_SHOP", shop),
        admin_token=env(f"{prefix}_SHOPIFY_ADMIN_TOKEN"),
        client_id=env(f"{prefix}_SHOPIFY_CLIENT_ID"),
        client_secret=env(f"{prefix}_SHOPIFY_CLIENT_SECRET"),
        blog_handle=env(f"{prefix}_SHOPIFY_BLOG_HANDLE", blog),
        gsc_property=env(f"{prefix}_GSC_PROPERTY", gsc),
        ga4_property_id=normalize_ga4_property_id(env(f"{prefix}_GA4_PROPERTY_ID")),
    )


class Config:
    root = ROOT
    port = int(env("PORT", "8787"))
    host = env("HOST", "127.0.0.1")
    data_dir = (ROOT / env("DATA_DIR", "data")).resolve()
    production = env("APP_ENV", env("NODE_ENV")) == "production"
    cookie_secure = flag("COOKIE_SECURE", env("APP_ENV", env("NODE_ENV")) == "production")
    session_hours = int(env("SESSION_HOURS", "12"))

    # Hosted mode (the cloud copy, started by scripts/run_hosted.py): each person signs in with their own
    # account and every /api call needs their session (docs/decisions/0011-hosted-team-sign-in.md).
    # Off on your own computer, where the app stays in local operator mode with no sign-in.
    hosted = flag("FLOWMERCE_HOSTED", False)
    # Shared only between the hosted frontend and this API, generated at every start by run_hosted.py.
    internal_secret = env("FLOWMERCE_INTERNAL_SECRET")
    # The owner key: this username and password sign in as the first administrator (hosted mode only).
    login_user = env("FLOWMERCE_LOGIN_USER", "admin")
    login_password = env("FLOWMERCE_LOGIN_PASSWORD")

    # Safety switch. Until an admin sets this, the server refuses every request that would make an
    # article visible on a storefront, whoever asks. Hidden Shopify drafts are still allowed.
    allow_live_publish = flag("ALLOW_LIVE_PUBLISH", False)

    # Demo mode. Off (the default): every report uses only live-API and explicitly imported rows; demo fixtures are
    # never read. On: analytics screens use ONLY demo fixtures and a banner marks every page. The two never mix.
    demo_mode = flag("DEMO_MODE", False)

    shopify_api_version = env("SHOPIFY_API_VERSION", "2025-10")
    public_feed_sync = flag("PUBLIC_FEED_SYNC", True)
    # Relative paths (e.g. secrets/key.json) are taken from the project folder.
    google_service_account_file = str(ROOT / env("GOOGLE_SERVICE_ACCOUNT_FILE")) if env("GOOGLE_SERVICE_ACCOUNT_FILE") else ""
    anthropic_api_key = env("ANTHROPIC_API_KEY")
    claude_model = env("CLAUDE_MODEL", "claude-opus-5-5")
    claude_fallbacks = flag("CLAUDE_FALLBACKS", True)
    workflow_webhook_secret = env("WORKFLOW_WEBHOOK_SECRET")
    claude_timeout = int(env("CLAUDE_TIMEOUT_SECONDS", "600"))      # one Claude request, end to end
    claude_max_retries = int(env("CLAUDE_MAX_RETRIES", "2"))        # rate limits, 5xx and connection errors only

    # AI job bridge. Mode: anthropic_api (this server calls Claude), external_worker (an independent worker does), disabled.
    ai_execution_mode = env("AI_EXECUTION_MODE", "anthropic_api").lower()
    ai_worker_url = env("AI_WORKER_URL")
    ai_worker_token = env("AI_WORKER_TOKEN")
    ai_callback_url = env("AI_CALLBACK_URL")                        # public HTTPS URL of POST /api/hooks/workflow, sent to the worker
    ai_worker_timeout = int(env("AI_WORKER_TIMEOUT_SECONDS", "15"))
    ai_max_concurrency = max(1, int(env("AI_MAX_CONCURRENCY", "2")))
    ai_max_retries = int(env("AI_JOB_MAX_RETRIES", "3"))
    ai_lease_seconds = int(env("AI_LEASE_SECONDS", "900"))          # must be longer than CLAUDE_TIMEOUT_SECONDS
    ai_job_timeout_seconds = int(env("AI_JOB_TIMEOUT_SECONDS", "1800"))   # worker silent for this long -> job fails
    ai_retry_base_seconds = int(env("AI_RETRY_BASE_SECONDS", "5"))
    ai_retry_max_seconds = int(env("AI_RETRY_MAX_SECONDS", "300"))
    scheduler = flag("SCHEDULER", True)
    admin_email = env("ADMIN_EMAIL")
    admin_password = env("ADMIN_PASSWORD")

    brands: dict[str, BrandConfig] = {
        "ridhi": _brand("ridhi", "RIDHI", "Ridhi Block Print", "Ridhi", "ridhiblockprint.com",
                        "guz0he-21.myshopify.com", "news", "sc-domain:ridhiblockprint.com"),
        "cpc": _brand("cpc", "CPC", "Cotton Print Club", "CPC", "cottonprintclub.com",
                      "liquidationfashion.myshopify.com", "blogs", "sc-domain:cottonprintclub.com"),
    }


config = Config()


def is_brand(v: object) -> bool:
    return v in BRAND_IDS


def has_google_credentials() -> bool:
    f = config.google_service_account_file
    return bool(f) and Path(f).exists()
