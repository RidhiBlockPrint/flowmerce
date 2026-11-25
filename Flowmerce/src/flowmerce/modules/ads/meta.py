"""Meta Marketing API client: reading only.

What this file may do: list the ad accounts the token can see, read campaigns, ad sets, ads and
their creatives, and read daily insights. What it must never do: create, pause or change anything.
The token Flowmerce asks for carries `ads_read` and `business_management` only, so a write would
fail at the platform anyway; the point of saying so here is that nobody adds one later by accident.

Shape of the API (developers.facebook.com/docs/marketing-api, read 2026-11-25):
  * Everything hangs off https://graph.facebook.com/<version>/, with the version pinned in config.
  * GET /act_<id>/insights returns a `data` array of rows plus `paging`; metric values are strings.
  * `level` picks the row grain (account, campaign, adset, ad) and `time_increment=1` gives one row
    per day. `fields` chooses the metrics; `actions` and `action_values` come back as lists of
    {action_type, value} pairs, from which purchases are read as `omni_purchase` (falling back to
    `purchase`, which is what the Pixel alone reports).
  * Long ranges should go through an async report run (POST, then poll `async_status`), which this
    MVP does not use: a 90-day read at ad level over two accounts stays inside the synchronous
    limits. If it starts timing out, the async path is the fix, not a longer timeout.
  * Every response carries throttle headers (`x-fb-ads-insights-throttle` with `app_id_util_pct` and
    `acc_id_util_pct`). The client reads them and reports the utilisation so a sync can slow down
    before Meta starts refusing calls.

Errors become `MetaError` with a plain `state` the UI can show. No error message, log line or return
value ever contains the token.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import httpx

from .config import MetaCredentials

log = logging.getLogger(__name__)

GRAPH_HOST = "https://graph.facebook.com"

# Insight fields the Ads page and Creative Strategist need. Kept deliberately short: every extra
# field costs time on a 90-day ad-level read.
INSIGHT_FIELDS = (
    "date_start",
    "date_stop",
    "account_currency",
    "campaign_id",
    "adset_id",
    "ad_id",
    "spend",
    "impressions",
    "reach",
    "frequency",
    "clicks",
    "inline_link_clicks",
    "actions",
    "action_values",
    "video_3_sec_watched_actions",
    "video_thruplay_watched_actions",
)

# action_type values, best first. omni_purchase counts web and app purchases together; `purchase`
# is what a Pixel-only setup reports.
PURCHASE_ACTIONS = ("omni_purchase", "purchase")
ADD_TO_CART_ACTIONS = ("omni_add_to_cart", "add_to_cart")
CHECKOUT_ACTIONS = ("omni_initiated_checkout", "initiate_checkout")
LANDING_PAGE_ACTIONS = ("landing_page_view",)


class MetaError(Exception):
    """A Meta request that failed in a way the page can explain."""

    def __init__(self, state: str, message: str, status: int = 0, code: int = 0) -> None:
        super().__init__(message)
        self.state = state
        self.message = message
        self.status = status
        self.code = code


def _classify(status: int, body: Any) -> MetaError:
    """Turn Meta's error body into a state the UI can act on. Never holds the token or the URL."""
    error = body.get("error") if isinstance(body, dict) else None
    code = 0
    subcode = 0
    message = ""
    etype = ""
    if isinstance(error, dict):
        try:
            code = int(error.get("code") or 0)
        except (TypeError, ValueError):
            code = 0
        try:
            subcode = int(error.get("error_subcode") or 0)
        except (TypeError, ValueError):
            subcode = 0
        message = str(error.get("message") or "")[:300]
        etype = str(error.get("type") or "")
    # 190 = the token is invalid or has expired; 102 = the session is no longer valid.
    if code in (102, 190) or status == 401:
        return MetaError(
            "token_invalid",
            "Meta refused the access token. It has expired or been revoked; a new system user "
            "token is needed in META_SYSTEM_USER_TOKEN.",
            status,
            code,
        )
    # 200 / 10 = the token lacks a permission; 272 = no access to this ad account.
    if code in (10, 200, 272) or status == 403:
        return MetaError(
            "permission_denied",
            "The Meta token may not read this ad account. Check that the system user is assigned "
            "to the account and has the ads_read permission.",
            status,
            code,
        )
    if code == 100 and subcode == 33:
        return MetaError(
            "not_found",
            "Meta does not know this ad account id. Check the <BRAND>_META_AD_ACCOUNT_ID value.",
            status,
            code,
        )
    # 4 / 17 / 80000 = rate limited; subcode 1504022 is the insights throttle.
    if code in (4, 17, 32, 613, 80000, 80004) or status == 429:
        return MetaError(
            "rate_limited",
            "Meta is rate limiting the app. The sync will try again on its next round.",
            status,
            code,
        )
    if status >= 500:
        return MetaError("platform_error", f"Meta had a server error ({status}).", status, code)
    detail = message or etype or f"HTTP {status}"
    return MetaError("error", f"Meta rejected the request: {detail}", status, code)


def _as_int(value: Any) -> int:
    """Meta returns every figure as a string, and leaves a metric out when it is zero."""
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return 0


def _as_float(value: Any) -> float:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return 0.0


def action_value(rows: Any, wanted: tuple[str, ...]) -> float:
    """Read one figure out of an `actions` / `action_values` list, trying each name in turn.

    Meta returns ``[{"action_type": "omni_purchase", "value": "3"}, ...]``. The first name that is
    present wins, so a store with the Conversions API (omni_*) and one with only the Pixel
    (purchase) both report a number instead of a gap.
    """
    if not isinstance(rows, list):
        return 0.0
    by_type = {
        str(row.get("action_type")): row.get("value")
        for row in rows
        if isinstance(row, dict) and row.get("action_type")
    }
    for name in wanted:
        if name in by_type:
            return _as_float(by_type[name])
    return 0.0


@dataclass
class Throttle:
    """What Meta's throttle headers said on the last response (percent of the limit used)."""

    app_pct: float = 0.0
    account_pct: float = 0.0
    tier: str = ""

    @property
    def near_limit(self) -> bool:
        """Meta's guidance is to back off as utilisation approaches 100%."""
        return max(self.app_pct, self.account_pct) >= 75.0


@dataclass
class MetaClient:
    """Read-only Meta client. One instance per store; safe to reuse between requests."""

    creds: MetaCredentials
    timeout: float = 30.0
    transport: httpx.BaseTransport | None = None
    throttle: Throttle = field(default_factory=Throttle)
    _client: httpx.Client | None = field(default=None, repr=False)

    def _http(self) -> httpx.Client:
        if not self.creds.configured:
            raise MetaError(
                "not_configured",
                "Meta Ads is not connected. Set META_SYSTEM_USER_TOKEN and the store's "
                "<BRAND>_META_AD_ACCOUNT_ID in .env.",
            )
        if self._client is None:
            self._client = httpx.Client(
                base_url=f"{GRAPH_HOST}/{self.creds.api_version}",
                timeout=self.timeout,
                transport=self.transport,
            )
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    # -------------------------------------------------------------- low level
    def _get(self, path: str, params: dict[str, str], *, attempts: int = 3) -> dict[str, Any]:
        """One GET, with the token added here and nowhere else. Retries network errors and 5xx."""
        query = dict(params)
        query["access_token"] = self.creds.token
        last: Exception | None = None
        for i in range(max(attempts, 1)):
            try:
                response = self._http().get(path, params=query)
            except httpx.HTTPError as exc:
                last = exc
                if i + 1 < attempts:
                    time.sleep(0.5 * (i + 1))
                    continue
                raise MetaError(
                    "connection_failed", f"Could not reach Meta ({type(exc).__name__})."
                ) from None
            self._read_throttle(response)
            if response.status_code >= 400:
                try:
                    body = response.json()
                except ValueError:
                    body = None
                error = _classify(response.status_code, body)
                # A rate limit or a server error is worth one more try; a bad token is not.
                if error.state in ("rate_limited", "platform_error") and i + 1 < attempts:
                    time.sleep(1.5 * (i + 1))
                    continue
                raise error
            try:
                payload = response.json()
            except ValueError:
                raise MetaError("error", "Meta returned a response that is not JSON.") from None
            if not isinstance(payload, dict):
                raise MetaError("error", "Meta returned an unexpected response shape.")
            return payload
        raise MetaError("connection_failed", f"Could not reach Meta ({type(last).__name__}).")

    def _read_throttle(self, response: httpx.Response) -> None:
        """Record the insights throttle header so a sync can slow down before Meta refuses."""
        raw = response.headers.get("x-fb-ads-insights-throttle")
        if not raw:
            return
        try:
            data = json.loads(raw)
        except ValueError:
            return
        if isinstance(data, dict):
            self.throttle = Throttle(
                app_pct=_as_float(data.get("app_id_util_pct")),
                account_pct=_as_float(data.get("acc_id_util_pct")),
                tier=str(data.get("ads_api_access_tier") or ""),
            )

    def _paged(
        self, path: str, params: dict[str, str], *, max_pages: int = 50
    ) -> list[dict[str, Any]]:
        """Follow `paging.cursors.after` until the data runs out or max_pages is reached."""
        rows: list[dict[str, Any]] = []
        query = dict(params)
        for _ in range(max_pages):
            payload = self._get(path, query)
            data = payload.get("data")
            if isinstance(data, list):
                rows.extend(row for row in data if isinstance(row, dict))
            paging = payload.get("paging")
            after = ""
            if isinstance(paging, dict):
                cursors = paging.get("cursors")
                if isinstance(cursors, dict):
                    after = str(cursors.get("after") or "")
                if not paging.get("next"):
                    break
            if not after:
                break
            query["after"] = after
        return rows

    # -------------------------------------------------------------- reads
    def accounts(self) -> list[dict[str, Any]]:
        """The ad accounts this token can see. Used by the credential check script."""
        rows = self._paged(
            "/me/adaccounts",
            {"fields": "id,account_id,name,currency,timezone_name,account_status", "limit": "50"},
        )
        return rows

    def account(self) -> dict[str, Any]:
        """Name, currency and timezone of the configured ad account."""
        return self._get(
            f"/{self.creds.account_id}",
            {"fields": "id,name,currency,timezone_name,account_status"},
        )

    def campaigns(self) -> list[dict[str, Any]]:
        """Campaigns of the configured account, newest effective status included."""
        return self._paged(
            f"/{self.creds.account_id}/campaigns",
            {
                "fields": (
                    "id,name,objective,effective_status,daily_budget,lifetime_budget,"
                    "start_time,stop_time,updated_time"
                ),
                "limit": "200",
            },
        )

    def ad_sets(self) -> list[dict[str, Any]]:
        """Ad sets (Meta's name for an ad group)."""
        return self._paged(
            f"/{self.creds.account_id}/adsets",
            {
                "fields": "id,name,campaign_id,effective_status,daily_budget,optimization_goal",
                "limit": "200",
            },
        )

    def ads(self) -> list[dict[str, Any]]:
        """Ads with the creative text Creative Strategist reads (headline, body, call to action)."""
        return self._paged(
            f"/{self.creds.account_id}/ads",
            {
                "fields": (
                    "id,name,adset_id,effective_status,created_time,"
                    "creative{title,body,call_to_action_type,thumbnail_url,object_type,"
                    "url_tags,effective_object_story_id},"
                    "tracking_specs"
                ),
                "limit": "200",
            },
        )

    def insights(
        self,
        since: date,
        until: date,
        *,
        level: str = "ad",
    ) -> list[dict[str, Any]]:
        """Daily figures between two dates (inclusive), one row per entity per day.

        `level` is one of account, campaign, adset, ad. Meta restates recent days as late
        conversions arrive, so callers re-read a window rather than trusting stored figures.
        """
        if level not in ("account", "campaign", "adset", "ad"):
            raise MetaError("bad_request", f"Unknown insights level {level!r}.")
        if until < since:
            raise MetaError("bad_request", "The insights range ends before it starts.")
        return self._paged(
            f"/{self.creds.account_id}/insights",
            {
                "level": level,
                "time_increment": "1",
                "time_range": json.dumps(
                    {"since": since.isoformat(), "until": until.isoformat()}
                ),
                "fields": ",".join(INSIGHT_FIELDS),
                "limit": "500",
            },
        )


def metric_row(row: dict[str, Any]) -> dict[str, Any]:
    """Turn one insights row into the columns of ads.daily_metric.

    Keeps Meta's own figures as they are: the platform's purchase count is what Meta claims, which
    the Ads page shows next to (not instead of) the Shopify order count.
    """
    return {
        "metric_date": str(row.get("date_start") or "")[:10],
        "spend": round(_as_float(row.get("spend")), 2),
        "impressions": _as_int(row.get("impressions")),
        "reach": _as_int(row.get("reach")) or None,
        "frequency": round(_as_float(row.get("frequency")), 3) or None,
        "clicks": _as_int(row.get("clicks")),
        "link_clicks": _as_int(row.get("inline_link_clicks")) or None,
        "landing_page_views": int(action_value(row.get("actions"), LANDING_PAGE_ACTIONS)) or None,
        "add_to_cart": round(action_value(row.get("actions"), ADD_TO_CART_ACTIONS), 2) or None,
        "initiate_checkout": round(action_value(row.get("actions"), CHECKOUT_ACTIONS), 2) or None,
        "purchases": round(action_value(row.get("actions"), PURCHASE_ACTIONS), 2) or None,
        "purchase_value": round(action_value(row.get("action_values"), PURCHASE_ACTIONS), 2)
        or None,
        "video_3s_views": int(action_value(row.get("video_3_sec_watched_actions"), ("video_view",)))
        or None,
        "video_thruplays": int(
            action_value(row.get("video_thruplay_watched_actions"), ("video_view",))
        )
        or None,
        "currency": str(row.get("account_currency") or ""),
    }
