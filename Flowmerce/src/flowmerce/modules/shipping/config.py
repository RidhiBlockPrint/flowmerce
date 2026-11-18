"""Shipping configuration. Secrets come from the environment, `.env`, or `.env.shipping` (both git-ignored)
and never leave the server."""
from __future__ import annotations

import os
from dataclasses import dataclass

from ..seo.config import ROOT, _load_env_file

# .env is already loaded by the SEO config; .env.shipping may hold the Supabase settings instead.
_load_env_file(ROOT / ".env.shipping")


def _env(key: str, default: str = "") -> str:
    return (os.environ.get(key) or default).strip()


@dataclass(frozen=True)
class ShippingConfig:
    url: str                 # https://<project>.supabase.co  (no trailing slash)
    key: str                 # service-role key: server only, never sent to the browser
    schema: str              # Flowmerce tables live in this Postgres schema
    timeout: float
    refresh_minutes: int     # how often the backend refreshes ops.* from public.orders (0 = off)

    @property
    def configured(self) -> bool:
        return bool(self.url and self.key)


def shipping_config() -> ShippingConfig:
    try:
        refresh = int(_env("SHIPPING_REFRESH_MINUTES", "15"))
    except ValueError:
        refresh = 15
    try:
        timeout = float(_env("SHIPPING_TIMEOUT_SECONDS", "20"))
    except ValueError:
        timeout = 20.0
    return ShippingConfig(
        url=_env("SUPABASE_URL").rstrip("/"),
        key=_env("SUPABASE_SERVICE_ROLE_KEY"),
        schema=_env("SHIPPING_SCHEMA", "ops"),
        timeout=timeout,
        refresh_minutes=max(0, refresh),
    )
