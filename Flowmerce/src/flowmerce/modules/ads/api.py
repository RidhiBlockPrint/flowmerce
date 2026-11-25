"""Ads routes, mounted under /api/ads. Read-only: there is no route here that changes anything on
Meta or Google, by design.

Every route checks the `view` permission like the rest of Flowmerce. Errors the page can explain
come back with a `code`:
  400 bad_request, 503 not_configured / token_invalid / permission_denied / access_level_too_low /
  rate_limited / connection_failed / platform_error.
`brand` is 'ridhi' or 'cpc' on every route.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Request

from ..seo.auth import require_perm
from ..seo.util import HttpError
from . import service
from .google import GoogleAdsError
from .meta import MetaError

ads = APIRouter(prefix="/api/ads")

# A platform problem is never the browser's fault: everything the platform refuses is reported as
# 503 (the service is unavailable to us right now) except a request we built wrongly.
_PLATFORM_STATUS = {"bad_request": 400, "not_found": 404}


def _call[T](fn: Callable[[], T]) -> T:
    """Run a service call and turn its known failures into explained HTTP errors."""
    try:
        return fn()
    except service.InputError as exc:
        raise HttpError(400, str(exc), "bad_request") from None
    except ValueError as exc:  # unknown brand from store_for()
        raise HttpError(400, str(exc), "bad_request") from None
    except (MetaError, GoogleAdsError) as exc:
        raise HttpError(_PLATFORM_STATUS.get(exc.state, 503), exc.message, exc.state) from None


def _int(value: str | None, default: int, low: int, high: int) -> int:
    try:
        return max(low, min(high, int(value or default)))
    except (TypeError, ValueError):
        return default


@ads.get("/status")
def status(request: Request) -> dict[str, Any]:
    """Which platforms are connected per store, and which .env values are still missing.

    Reads the environment only: it never calls Meta or Google, so it answers immediately and works
    before anything is connected. No token or secret is included, only account ids.
    """
    require_perm(request, "view")
    return _call(service.status)


@ads.get("/summary")
def summary(request: Request, brand: str = "ridhi") -> dict[str, Any]:
    """Spend and performance per platform for the last `days` complete days (default 28).

    Answers from demo figures while no platform is connected; `source` says which it was.
    """
    require_perm(request, "view")
    days = _int(request.query_params.get("days"), 28, 1, 400)
    return _call(lambda: service.summary(brand, days))
