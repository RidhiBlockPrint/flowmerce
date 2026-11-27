"""A read-only client for the Google Ads API (REST, googleAds:search), using httpx (already a
project dependency).

* Only reports are read (GAQL SELECT queries): nothing here can change a budget, a bid, a status or
  anything else in an ad account.
* The Google login (client id and secret, refresh token) is exchanged for a short-lived access token
  that is kept in memory only. No key or token appears in a log line, an error message or a return
  value.
* Errors become `GoogleAdsError` with a plain `state` the page can explain: token_expired,
  not_enabled, permission, rate_limited, bad_request, connection_failed, error.

Purchases (checked on Ridhi's account, 2026-11-27): Google files three actions under "purchase":
"Google Shopping App Purchase" (primary, Google's own), "Ridhi Shopify (web) purchase" (secondary:
the same orders counted again) and "Ridhi Shopify (web) click" (primary, but a click, worth $1). The
module counts Google's primary purchase conversions (`metrics.conversions`, which leaves secondary
actions out) and drops every action named like a click.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

import httpx

from .config import GOOGLE_ADS_API_VERSION, GOOGLE_ADS_BASE_URL, GOOGLE_TOKEN_URL, GoogleAccount

log = logging.getLogger(__name__)

RETRY_PAUSES = (5, 15, 45, 0)  # as the Meta client: rides out a short network outage
TOKEN_EARLY_SECONDS = 120  # get a new access token this long before the old one runs out

# Google's channel types as the page's campaign types.
CHANNEL_TYPE = {
    "SEARCH": "search",
    "PERFORMANCE_MAX": "pmax",
    "DISPLAY": "display",
    "SHOPPING": "shopping",
    "VIDEO": "video",
    "DEMAND_GEN": "demand_gen",
    "DISCOVERY": "demand_gen",
    "MULTI_CHANNEL": "app",
    "SMART": "smart",
    "LOCAL": "local",
}


def counts_as_purchase(action_name: str, category: str) -> bool:
    """Whether a conversion action's figures count as purchases (see the module text)."""
    return category == "PURCHASE" and "click" not in action_name.lower()


class GoogleAdsError(Exception):
    """A Google request that failed, with a `state` the page can explain and a message without
    secrets."""

    def __init__(self, state: str, message: str, status: int = 0) -> None:
        super().__init__(message)
        self.state = state
        self.message = message
        self.status = status


def _google_error(r: httpx.Response) -> GoogleAdsError:
    """Google's error answer as a GoogleAdsError (codes as documented for v26)."""
    try:
        body = r.json().get("error") or {}
    except ValueError:
        body = {}
    codes: list[str] = []
    for d in body.get("details") or []:
        for e in d.get("errors") or []:
            codes.extend(str(v) for v in (e.get("errorCode") or {}).values())
    first = codes[0] if codes else str(body.get("status") or "")
    if "CUSTOMER_NOT_ENABLED" in codes:
        return GoogleAdsError(
            "not_enabled",
            "The Google Ads account is not enabled or has been closed.",
            r.status_code,
        )
    if r.status_code == 401 or "UNAUTHENTICATED" in codes:
        return GoogleAdsError(
            "token_expired",
            "The Google sign-in for Google Ads no longer works: make a new refresh token.",
            r.status_code,
        )
    if r.status_code == 403 or "USER_PERMISSION_DENIED" in codes:
        return GoogleAdsError(
            "permission",
            "This Google login cannot read that Google Ads account. Give it access in Google Ads "
            "(Admin, Access and security), or set GOOGLE_ADS_LOGIN_CUSTOMER_ID to a manager "
            "account that holds it.",
            r.status_code,
        )
    if r.status_code == 429 or "RESOURCE_EXHAUSTED" in codes:
        return GoogleAdsError(
            "rate_limited", "Google Ads asked to slow down; the next round carries on.", 429
        )
    if r.status_code == 400:
        return GoogleAdsError(
            "bad_request", f"Google Ads did not accept the request ({first}).", 400
        )
    return GoogleAdsError(
        "error",
        f"Google Ads answered {r.status_code} ({first or 'no reason given'}).",
        r.status_code,
    )


@dataclass(frozen=True)
class Report:
    """One kind of daily figures: the query for spend, impressions and clicks; the query for
    purchases (by conversion action); and how a row becomes (item, campaign id, label, extra)."""

    figures: str
    purchases: str
    key: Callable[[dict[str, Any]], tuple[str, str, str, str]]


def _g(row: dict[str, Any], path: str) -> Any:
    v: Any = row
    for part in path.split("."):
        v = (v or {}).get(part) if isinstance(v, dict) else None
    return v


def _span(since: date, until: date) -> str:
    return f"segments.date BETWEEN '{since.isoformat()}' AND '{until.isoformat()}'"


FIG = "metrics.cost_micros, metrics.impressions, metrics.clicks"
BUY = (
    "segments.conversion_action_name, segments.conversion_action_category, metrics.conversions, "
    "metrics.conversions_value"
)
BUY_WHERE = "AND segments.conversion_action_category = 'PURCHASE'"


def _reports() -> dict[str, list[Report]]:
    """The reports per kind of item (a group is either an ad group or an asset group)."""

    def camp(r: dict[str, Any]) -> tuple[str, str, str, str]:
        cid = str(_g(r, "campaign.id") or "")
        return cid, cid, str(_g(r, "campaign.name") or ""), ""

    def ad_group(r: dict[str, Any]) -> tuple[str, str, str, str]:
        return (
            str(_g(r, "adGroup.id") or ""),
            str(_g(r, "campaign.id") or ""),
            str(_g(r, "adGroup.name") or ""),
            "ad_group",
        )

    def asset_group(r: dict[str, Any]) -> tuple[str, str, str, str]:
        return (
            str(_g(r, "assetGroup.id") or ""),
            str(_g(r, "campaign.id") or ""),
            str(_g(r, "assetGroup.name") or ""),
            "asset_group",
        )

    def term(r: dict[str, Any]) -> tuple[str, str, str, str]:
        t = str(_g(r, "searchTermView.searchTerm") or "")
        return t, str(_g(r, "campaign.id") or ""), t, ""

    def keyword(r: dict[str, Any]) -> tuple[str, str, str, str]:
        return (
            f"{_g(r, 'adGroup.id')}~{_g(r, 'adGroupCriterion.criterionId')}",
            str(_g(r, "campaign.id") or ""),
            str(_g(r, "adGroupCriterion.keyword.text") or ""),
            str(_g(r, "adGroupCriterion.keyword.matchType") or ""),
        )

    def product(r: dict[str, Any]) -> tuple[str, str, str, str]:
        return (
            str(_g(r, "segments.productItemId") or ""),
            str(_g(r, "campaign.id") or ""),
            str(_g(r, "segments.productTitle") or ""),
            "",
        )

    def pair(view: str, fields: str, key: Callable[..., Any], only_spend: bool = False) -> Report:
        extra = " AND metrics.cost_micros > 0" if only_spend else ""
        # GAQL built from this module's own constants and dates only; nothing a person typed.
        return Report(
            f"SELECT {fields}, segments.date, {FIG} FROM {view} WHERE {{span}}{extra}",  # noqa: S608
            f"SELECT {fields}, segments.date, {BUY} FROM {view} WHERE {{span}} {BUY_WHERE}",  # noqa: S608
            key,
        )

    return {
        "campaign": [pair("campaign", "campaign.id, campaign.name", camp)],
        "group": [
            pair("ad_group", "ad_group.id, ad_group.name, campaign.id", ad_group),
            pair("asset_group", "asset_group.id, asset_group.name, campaign.id", asset_group),
        ],
        "term": [pair("search_term_view", "search_term_view.search_term, campaign.id", term)],
        "keyword": [
            pair(
                "keyword_view",
                "ad_group.id, ad_group_criterion.criterion_id, ad_group_criterion.keyword.text, "
                "ad_group_criterion.keyword.match_type, campaign.id",
                keyword,
            )
        ],
        # Thousands of products show without spend; only those with spend (or a purchase) are kept.
        "product": [
            pair(
                "shopping_performance_view",
                "segments.product_item_id, segments.product_title, campaign.id",
                product,
                only_spend=True,
            )
        ],
    }


KINDS = ("campaign", "group", "term", "keyword", "product")


class GoogleAdsClient:
    """Read-only access to one brand's Google Ads account."""

    def __init__(
        self,
        account: GoogleAccount,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 90.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.account = account
        self._http = httpx.Client(
            timeout=httpx.Timeout(timeout, connect=15.0),
            transport=transport,
            headers={"User-Agent": "flowmerce-ads/1.0"},
        )
        self._sleep = sleep
        self._access: str | None = None
        self._access_until = 0.0

    def close(self) -> None:
        """Close the connection pool."""
        self._http.close()

    # ------------------------------------------------------------------ sign-in
    def _token(self, fresh: bool = False) -> str:
        if self._access and not fresh and time.monotonic() < self._access_until:
            return self._access
        a = self.account
        try:
            r = self._http.post(
                GOOGLE_TOKEN_URL,
                data={
                    "client_id": a.client_id,
                    "client_secret": a.client_secret,
                    "refresh_token": a.refresh_token,
                    "grant_type": "refresh_token",
                },
            )
        except httpx.HTTPError as e:
            raise GoogleAdsError(
                "connection_failed", f"Could not reach Google ({type(e).__name__})."
            ) from None
        if r.status_code != 200:
            try:
                why = str(r.json().get("error") or "")
            except ValueError:
                why = ""
            if why in ("invalid_grant", "invalid_client", "unauthorized_client"):
                raise GoogleAdsError(
                    "token_expired",
                    "The Google sign-in for Google Ads no longer works (refresh token refused): "
                    "make a new GOOGLE_ADS_REFRESH_TOKEN.",
                    r.status_code,
                )
            raise GoogleAdsError(
                "error", f"Google's sign-in answered {r.status_code}.", r.status_code
            )
        body = r.json()
        self._access = str(body["access_token"])
        self._access_until = (
            time.monotonic() + int(body.get("expires_in") or 3600) - TOKEN_EARLY_SECONDS
        )
        return self._access

    def _headers(self, fresh: bool = False) -> dict[str, str]:
        h = {"Authorization": f"Bearer {self._token(fresh)}"}
        if self.account.developer_token:
            h["developer-token"] = self.account.developer_token
        if self.account.login_customer_id:
            h["login-customer-id"] = self.account.login_customer_id
        return h

    # ------------------------------------------------------------------ queries
    def search(self, query: str) -> list[dict[str, Any]]:
        """Every row of a GAQL query, page by page."""
        url = (
            f"{GOOGLE_ADS_BASE_URL}/{GOOGLE_ADS_API_VERSION}/customers/"
            f"{self.account.customer_id}/googleAds:search"
        )
        rows: list[dict[str, Any]] = []
        page: str | None = None
        while True:
            body: dict[str, Any] = {"query": query}
            if page:
                body["pageToken"] = page
            data = self._post(url, body)
            rows.extend(data.get("results") or [])
            page = data.get("nextPageToken")
            if not page:
                return rows

    def _post(self, url: str, body: dict[str, Any]) -> dict[str, Any]:
        fresh = False
        for i, pause in enumerate(RETRY_PAUSES):
            last = i == len(RETRY_PAUSES) - 1
            try:
                r = self._http.post(url, json=body, headers=self._headers(fresh))
            except httpx.HTTPError as e:
                if last:
                    raise GoogleAdsError(
                        "connection_failed", f"Could not reach Google Ads ({type(e).__name__})."
                    ) from None
                self._sleep(pause)
                continue
            if r.status_code == 200:
                return dict(r.json())
            if r.status_code == 401 and not fresh:
                fresh = True  # the access token ran out early: get a new one once
                continue
            if r.status_code in (429, 500, 502, 503, 504) and not last:
                self._sleep(pause)
                continue
            raise _google_error(r)
        raise GoogleAdsError("error", "Google Ads did not answer.")

    # ------------------------------------------------------------------ what the sync reads
    def account_info(self) -> dict[str, Any]:
        """The account's name, currency and time zone."""
        rows = self.search(
            "SELECT customer.descriptive_name, customer.currency_code, customer.time_zone "
            "FROM customer"
        )
        c = (rows[0] if rows else {}).get("customer") or {}
        return {
            "name": str(c.get("descriptiveName") or ""),
            "currency": str(c.get("currencyCode") or "USD"),
            "timezone": str(c.get("timeZone") or "UTC"),
        }

    def campaigns(self) -> list[dict[str, Any]]:
        """Every campaign with its type, status, daily budget (account currency) and bid
        strategy."""
        out = []
        for r in self.search(
            "SELECT campaign.id, campaign.name, campaign.advertising_channel_type, "
            "campaign.status, campaign.bidding_strategy_type, campaign_budget.amount_micros "
            "FROM campaign"
        ):
            micros = _g(r, "campaignBudget.amountMicros")
            out.append(
                {
                    "id": str(_g(r, "campaign.id")),
                    "name": str(_g(r, "campaign.name") or ""),
                    "channel": str(_g(r, "campaign.advertisingChannelType") or ""),
                    "status": str(_g(r, "campaign.status") or ""),
                    "daily_budget": round(int(micros) / 1e6, 2) if micros is not None else None,
                    "bid_strategy": _g(r, "campaign.biddingStrategyType"),
                }
            )
        return out

    def daily(self, kind: str, since: date, until: date) -> list[dict[str, Any]]:
        """One kind's figures per item per day, purchases merged in: rows ready for ads.g_replace
        (amounts in the account currency)."""
        merged: dict[tuple[str, str, str], dict[str, Any]] = {}

        def row(r: dict[str, Any], key: Callable[..., tuple[str, str, str, str]]) -> dict[str, Any]:
            item, campaign_id, label, extra = key(r)
            day = str(_g(r, "segments.date") or "")
            k = (item, campaign_id, day)
            if k not in merged:
                merged[k] = {
                    "item": item[:400],
                    "campaign_id": campaign_id,
                    "day": day,
                    "label": label,
                    "extra": extra,
                    "spend": 0.0,
                    "impressions": 0,
                    "clicks": 0,
                    "purchases": 0.0,
                    "value": 0.0,
                }
            return merged[k]

        span = _span(since, until)
        for rep in _reports()[kind]:
            for r in self.search(rep.figures.format(span=span)):
                m = row(r, rep.key)
                m["spend"] += int(_g(r, "metrics.costMicros") or 0) / 1e6
                m["impressions"] += int(_g(r, "metrics.impressions") or 0)
                m["clicks"] += int(_g(r, "metrics.clicks") or 0)
            for r in self.search(rep.purchases.format(span=span)):
                name = str(_g(r, "segments.conversionActionName") or "")
                cat = str(_g(r, "segments.conversionActionCategory") or "")
                n = float(_g(r, "metrics.conversions") or 0)
                if not counts_as_purchase(name, cat) or not n:
                    continue
                m = row(r, rep.key)
                m["purchases"] += n
                m["value"] += float(_g(r, "metrics.conversionsValue") or 0)
        out = []
        for m in merged.values():
            if not m["item"] or not m["day"]:
                continue
            m["spend"] = round(m["spend"], 4)
            m["purchases"] = round(m["purchases"], 2)
            m["value"] = round(m["value"], 2)
            out.append(m)
        return out
