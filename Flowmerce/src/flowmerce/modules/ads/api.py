"""Ads routes, mounted under /api/ads. Every route checks the `view` permission like the rest of
Flowmerce; every change (rules, a suggestion marked, a manual sync) is written to the shared
audit log.

Errors the page can explain come back with a `code`:
  400 bad_request, 404 not_found, 503 not_configured (no Meta keys) / not_synced (first read not
  finished) / google_not_connected (phase 3), 503 schema_missing / permission_denied /
  connection_failed (Supabase). `brand` is 'ridhi' or 'cpc' on every route.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Body, Request

from ..seo.audit import audit
from ..seo.auth import require_perm
from ..seo.util import HttpError
from ..shipping.supabase import SupabaseError
from . import scheduler, service

ads = APIRouter(prefix="/api/ads")

_BODY: Any = Body(default={})
_SUPABASE_STATUS = {
    "not_configured": 503,
    "schema_missing": 503,
    "permission_denied": 503,
    "connection_failed": 503,
    "bad_request": 400,
    "not_found": 404,
    "conflict": 409,
}


def _call[T](fn: Callable[[], T]) -> T:
    """Run a service call and turn its known failures into explained HTTP errors."""
    try:
        return fn()
    except service.InputError as e:
        raise HttpError(400, str(e), "bad_request") from None
    except LookupError as e:
        raise HttpError(404, str(e), "not_found") from None
    except service.NotReadyError as e:
        raise HttpError(503, e.message, e.code) from None
    except service.GoogleNotConnectedError as e:
        raise HttpError(503, e.message, "google_not_connected") from None
    except SupabaseError as e:
        message = e.message
        if e.state == "schema_missing":
            message = (
                "The Ads tables are missing, or the `ads` schema is not exposed in Supabase "
                "(Project Settings "
                "-> Data API -> Exposed schemas). Run db/central/115_ads.sql (and "
                "117_ads_google.sql for Google) first."
            )
        raise HttpError(_SUPABASE_STATUS.get(e.state, 502), message, e.state) from None


def _who(user: dict[str, Any]) -> str:
    return str(user.get("email") or user.get("name") or "team")


def _range(request: Request) -> tuple[str | None, str | None, str | None, str | None]:
    """from, to, compare and cfrom (a custom comparison's first day) from the address."""
    return tuple(_q(request, k) for k in ("from", "to", "compare", "cfrom"))  # type: ignore[return-value]


def _q(request: Request, key: str) -> str | None:
    v = request.query_params.get(key)
    return v[:20] if v else None


@ads.get("/settings")
def settings(request: Request, brand: str = "ridhi") -> dict[str, Any]:
    """The accounts the page reads, when each was last read, and the account's today."""
    require_perm(request, "view")
    return _call(lambda: service.settings(brand))


@ads.get("/overview")
def overview(request: Request, brand: str = "ridhi", platform: str = "all") -> dict[str, Any]:
    """Store sales against ad spend, the scaling gate, the goal and the day strip."""
    require_perm(request, "view")
    return _call(
        lambda: service.overview(
            brand,
            platform,
            _q(request, "from"),
            _q(request, "to"),
            _q(request, "compare"),
            _q(request, "cfrom"),
        )
    )


@ads.get("/campaigns")
def campaigns(request: Request, brand: str = "ridhi", platform: str = "all") -> dict[str, Any]:
    """Every campaign with CBO health and its ad sets."""
    require_perm(request, "view")
    return _call(lambda: service.campaigns(brand, platform, *_range(request)))


@ads.get("/creatives")
def creatives(request: Request, brand: str = "ridhi") -> dict[str, Any]:
    """Every Meta ad with its verdict, figures and video drop-off."""
    require_perm(request, "view")
    return _call(lambda: service.creatives(brand, *_range(request)))


@ads.get("/funnel")
def funnel(request: Request, brand: str = "ridhi", platform: str = "all") -> dict[str, Any]:
    """From impression to purchase, against the comparison."""
    require_perm(request, "view")
    return _call(
        lambda: service.funnel(
            brand,
            platform,
            _q(request, "from"),
            _q(request, "to"),
            _q(request, "compare"),
            _q(request, "cfrom"),
        )
    )


@ads.get("/search-terms")
def search_terms(request: Request, brand: str = "ridhi") -> dict[str, Any]:
    """Google keywords, search terms and products for the chosen days."""
    require_perm(request, "view")
    return _call(lambda: service.search_terms(brand, *_range(request)))


@ads.get("/gap")
def gap(request: Request, brand: str = "ridhi") -> dict[str, Any]:
    """Proven test ads missing from the scaling campaign."""
    require_perm(request, "view")
    return _call(lambda: service.gap(brand))


@ads.get("/actions")
def actions(request: Request, brand: str = "ridhi", platform: str = "all") -> dict[str, Any]:
    """The rules' suggestions, what the team marked, and the history."""
    require_perm(request, "view")
    return _call(lambda: service.actions(brand, platform))


@ads.patch("/actions/{action_id}")
def mark_action(
    request: Request, action_id: str, brand: str = "ridhi", body: dict[str, Any] = _BODY
) -> dict[str, Any]:
    """Mark a suggestion done, skipped or open again (in Flowmerce only: nothing changes in the ad
    account)."""
    user = require_perm(request, "view")
    status = str((body or {}).get("status") or "")
    out = _call(lambda: service.mark_action(brand, action_id[:200], status, _who(user)))
    audit(
        user,
        "ads.action_marked",
        "ads_action",
        action_id[:200],
        brand,
        f"Marked {status}: {out.get('title', '')}",
    )
    return out


@ads.get("/rules")
def rules(request: Request, brand: str = "ridhi") -> dict[str, Any]:
    """Every threshold for the brand, the rupee rate, the defaults and the glossary."""
    require_perm(request, "view")
    return _call(lambda: service.rules(brand))


@ads.patch("/rules")
def save_rules(
    request: Request, brand: str = "ridhi", body: dict[str, Any] = _BODY
) -> dict[str, Any]:
    """Change thresholds (and the rupee rate, from today on)."""
    user = require_perm(request, "view")
    out = _call(lambda: service.save_rules(brand, body, _who(user)))
    audit(user, "ads.rules_changed", "ads_rules", brand, brand, "Changed Ads rules", details=body)
    return out


@ads.post("/sync")
def sync_now(request: Request, brand: str = "ridhi") -> dict[str, Any]:
    """Read the brand's Meta account now (it also runs in the background every ADS_SYNC_MINUTES)."""
    user = require_perm(request, "view")
    out = _call(lambda: scheduler.sync_one(brand))
    audit(
        user,
        "ads.sync",
        "ads_account",
        brand,
        brand,
        f"Read the Meta account now: {out.get('state')}",
    )
    return out
