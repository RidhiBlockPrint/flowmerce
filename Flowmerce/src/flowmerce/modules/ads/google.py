"""Google Ads API client: reading only, over REST.

Why REST and not the official library: `google-ads` would be a new dependency, and the project rule
is that a package arrives only with a stated reason and the owner's approval. The REST surface is
the same API and needs nothing beyond httpx, which the project already has.

Shape of the API (developers.google.com/google-ads/api, read 2026-11-25):
  * Base https://googleads.googleapis.com/<version>/, version pinned in config (v26 here).
  * A read is POST /customers/<customer_id>/googleAds:searchStream with a JSON body {"query": GAQL}.
    searchStream answers with a JSON *array* of batches, each batch holding a `results` array;
    googleAds:search is the paged alternative (10,000 rows a page, `nextPageToken`).
  * GET /customers:listAccessibleCustomers lists what the credentials can reach. Used by the
    credential check script, since it needs no customer id and so proves the OAuth part alone.
  * Headers: `Authorization: Bearer <access token>` always, and `login-customer-id` (digits only)
    when the account is reached through a manager (MCC) account.
  * There is no developer token any more. It was sunset on 2026-09-09; the header is accepted but
    ignored today and Google says it will be rejected in a future major version, so this client does
    not send one. Access is granted to the Google Cloud project that issued the OAuth client: a
    project still at Test level cannot read a production account and the API answers
    CLOUD_PROJECT_NOT_APPROVED_FOR_PRODUCTION.
  * An access token is obtained from the refresh token at
    https://www.googleapis.com/oauth2/v3/token (the v3 there is unrelated to the Ads API version)
    and is cached in memory until shortly before it expires.

Errors become `GoogleAdsError` with a plain `state` the UI can show. No error message, log line or
return value ever contains the refresh token, the client secret or an access token.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import httpx

from .config import GoogleCredentials

log = logging.getLogger(__name__)

ADS_HOST = "https://googleads.googleapis.com"
TOKEN_URL = "https://www.googleapis.com/oauth2/v3/token"  # noqa: S105 - a public endpoint, not a secret

# Refresh the access token a minute before Google's own expiry, so a long sync never sends a token
# that expires mid-flight.
TOKEN_EARLY_SECONDS = 60


class GoogleAdsError(Exception):
    """A Google Ads request that failed in a way the page can explain."""

    def __init__(self, state: str, message: str, status: int = 0, code: str = "") -> None:
        super().__init__(message)
        self.state = state
        self.message = message
        self.status = status
        self.code = code


def _error_text(body: Any) -> tuple[str, str]:
    """Pull (status text, first error code) out of a Google Ads error body."""
    if not isinstance(body, dict):
        return "", ""
    error = body.get("error")
    if not isinstance(error, dict):
        return "", ""
    message = str(error.get("message") or "")[:300]
    details = error.get("details")
    code = ""
    if isinstance(details, list):
        for detail in details:
            if not isinstance(detail, dict):
                continue
            errors = detail.get("errors")
            if not isinstance(errors, list):
                continue
            for item in errors:
                if not isinstance(item, dict):
                    continue
                error_code = item.get("errorCode")
                if isinstance(error_code, dict):
                    for value in error_code.values():
                        if value:
                            code = str(value)
                            break
                if not message:
                    message = str(item.get("message") or "")[:300]
                if code:
                    break
            if code:
                break
    return message, code


def _classify(status: int, body: Any) -> GoogleAdsError:
    """Turn a Google Ads error into a state the UI can act on."""
    message, code = _error_text(body)
    if code == "CLOUD_PROJECT_NOT_APPROVED_FOR_PRODUCTION" or "not approved" in message.lower():
        return GoogleAdsError(
            "access_level_too_low",
            "The Google Cloud project behind these credentials is still at Test access level, so "
            "it may only read test accounts. Apply for Explorer or Basic access on the Google Ads "
            "API Overview page in the Cloud console.",
            status,
            code,
        )
    if code in ("CUSTOMER_NOT_FOUND", "CUSTOMER_NOT_ENABLED"):
        return GoogleAdsError(
            "not_found",
            "Google Ads does not know this customer id, or the account is not active. Check the "
            "<BRAND>_GOOGLE_ADS_CUSTOMER_ID value (10 digits, no dashes).",
            status,
            code,
        )
    if code == "NOT_ADS_USER" or status == 403:
        return GoogleAdsError(
            "permission_denied",
            "These credentials may not read this Google Ads account. If the account sits under a "
            "manager account, GOOGLE_ADS_LOGIN_CUSTOMER_ID must hold the manager's id.",
            status,
            code,
        )
    if status == 401 or code in ("AUTHENTICATION_ERROR", "AUTHORIZATION_ERROR"):
        return GoogleAdsError(
            "token_invalid",
            "Google refused the credentials. The refresh token may have been revoked, or the "
            "project's access level may not cover this account.",
            status,
            code,
        )
    if status == 429 or code == "RESOURCE_EXHAUSTED":
        return GoogleAdsError(
            "rate_limited",
            "Google Ads is rate limiting the project. The sync will try again on its next round.",
            status,
            code,
        )
    if status >= 500:
        return GoogleAdsError(
            "platform_error", f"Google Ads had a server error ({status}).", status, code
        )
    detail = message or code or f"HTTP {status}"
    return GoogleAdsError("error", f"Google Ads rejected the request: {detail}", status, code)


def _as_int(value: Any) -> int:
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return 0


def _as_float(value: Any) -> float:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return 0.0


def micros(value: Any) -> float:
    """Google reports money in micros: 1,230,000 micros = 1.23 in the account's currency."""
    return _as_float(value) / 1_000_000.0


@dataclass
class GoogleAdsClient:
    """Read-only Google Ads client. One instance per store; safe to reuse between requests."""

    creds: GoogleCredentials
    timeout: float = 30.0
    transport: httpx.BaseTransport | None = None
    _client: httpx.Client | None = field(default=None, repr=False)
    _token: str = field(default="", repr=False)
    _token_expires: float = field(default=0.0, repr=False)

    def _http(self) -> httpx.Client:
        if not self.creds.configured:
            raise GoogleAdsError(
                "not_configured",
                "Google Ads is not connected. Set GOOGLE_ADS_CLIENT_ID, GOOGLE_ADS_CLIENT_SECRET, "
                "GOOGLE_ADS_REFRESH_TOKEN and the store's <BRAND>_GOOGLE_ADS_CUSTOMER_ID in .env.",
            )
        if self._client is None:
            self._client = httpx.Client(timeout=self.timeout, transport=self.transport)
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
        self._token = ""
        self._token_expires = 0.0

    # -------------------------------------------------------------- auth
    def access_token(self) -> str:
        """A valid access token, refreshed from the refresh token when the cached one expires."""
        if self._token and time.monotonic() < self._token_expires:
            return self._token
        try:
            response = self._http().post(
                TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "client_id": self.creds.client_id,
                    "client_secret": self.creds.client_secret,
                    "refresh_token": self.creds.refresh_token,
                },
            )
        except httpx.HTTPError as exc:
            raise GoogleAdsError(
                "connection_failed", f"Could not reach Google to sign in ({type(exc).__name__})."
            ) from None
        if response.status_code >= 400:
            # Google answers invalid_grant when the refresh token has been revoked or the consent
            # was removed. Nothing but a fresh consent fixes that, so say so plainly.
            try:
                body = response.json()
            except ValueError:
                body = {}
            kind = str(body.get("error") or "") if isinstance(body, dict) else ""
            if kind in ("invalid_grant", "invalid_client", "unauthorized_client"):
                raise GoogleAdsError(
                    "token_invalid",
                    "Google refused the refresh token (it was revoked, or the OAuth client does "
                    "not match). A new refresh token has to be generated once, with consent from "
                    "someone who can read the Ads account.",
                    response.status_code,
                    kind,
                )
            raise GoogleAdsError(
                "token_invalid",
                f"Google would not issue an access token (HTTP {response.status_code}).",
                response.status_code,
                kind,
            )
        try:
            body = response.json()
        except ValueError:
            raise GoogleAdsError("error", "Google's sign-in reply was not JSON.") from None
        token = str(body.get("access_token") or "") if isinstance(body, dict) else ""
        if not token:
            raise GoogleAdsError("token_invalid", "Google's sign-in reply carried no access token.")
        expires = _as_int(body.get("expires_in")) if isinstance(body, dict) else 0
        self._token = token
        self._token_expires = time.monotonic() + max(expires - TOKEN_EARLY_SECONDS, 30)
        return token

    def _headers(self) -> dict[str, str]:
        """Authorization, and login-customer-id when a manager account is in the path.

        No developer-token header: it is ignored today and will be rejected in a future version.
        """
        headers = {
            "Authorization": f"Bearer {self.access_token()}",
            "Content-Type": "application/json",
        }
        if self.creds.login_customer_id:
            headers["login-customer-id"] = self.creds.login_customer_id
        return headers

    # -------------------------------------------------------------- low level
    def _request(
        self, method: str, path: str, *, json_body: Any = None, attempts: int = 3
    ) -> Any:
        url = f"{ADS_HOST}/{self.creds.api_version}{path}"
        last: Exception | None = None
        for i in range(max(attempts, 1)):
            try:
                response = self._http().request(
                    method, url, json=json_body, headers=self._headers()
                )
            except httpx.HTTPError as exc:
                last = exc
                if i + 1 < attempts:
                    time.sleep(0.5 * (i + 1))
                    continue
                raise GoogleAdsError(
                    "connection_failed", f"Could not reach Google Ads ({type(exc).__name__})."
                ) from None
            if response.status_code >= 400:
                try:
                    body = response.json()
                except ValueError:
                    body = None
                error = _classify(response.status_code, body)
                if error.state in ("rate_limited", "platform_error") and i + 1 < attempts:
                    time.sleep(1.5 * (i + 1))
                    continue
                raise error
            try:
                return response.json()
            except ValueError:
                raise GoogleAdsError(
                    "error", "Google Ads returned a response that is not JSON."
                ) from None
        raise GoogleAdsError(
            "connection_failed", f"Could not reach Google Ads ({type(last).__name__})."
        )

    # -------------------------------------------------------------- reads
    def accessible_customers(self) -> list[str]:
        """Customer ids these credentials can reach, as returned by listAccessibleCustomers.

        Needs no customer id, so it proves the OAuth half on its own: the credential check script
        calls this first.
        """
        body = self._request("GET", "/customers:listAccessibleCustomers")
        names = body.get("resourceNames") if isinstance(body, dict) else None
        if not isinstance(names, list):
            return []
        # Google returns "customers/1234567890"; the page only ever shows the id.
        return [str(name).rsplit("/", 1)[-1] for name in names]

    def search(self, query: str) -> list[dict[str, Any]]:
        """Run one GAQL query through searchStream and return the rows from every batch."""
        if not query.strip():
            raise GoogleAdsError("bad_request", "An empty GAQL query cannot be sent.")
        body = self._request(
            "POST",
            f"/customers/{self.creds.customer_id}/googleAds:searchStream",
            json_body={"query": query},
        )
        # searchStream answers with an array of batches, each holding its own results array.
        batches = body if isinstance(body, list) else [body]
        rows: list[dict[str, Any]] = []
        for batch in batches:
            if not isinstance(batch, dict):
                continue
            results = batch.get("results")
            if isinstance(results, list):
                rows.extend(row for row in results if isinstance(row, dict))
        return rows

    def account(self) -> dict[str, Any]:
        """Name, currency and time zone of the configured customer."""
        rows = self.search(
            "SELECT customer.id, customer.descriptive_name, customer.currency_code, "
            "customer.time_zone, customer.status FROM customer LIMIT 1"
        )
        return rows[0] if rows else {}

    def campaigns(self) -> list[dict[str, Any]]:
        """Campaigns, excluding removed ones."""
        return self.search(
            "SELECT campaign.id, campaign.name, campaign.status, "
            "campaign.advertising_channel_type, campaign.start_date, campaign.end_date, "
            "campaign_budget.amount_micros, campaign.bidding_strategy_type "
            "FROM campaign WHERE campaign.status != 'REMOVED'"
        )

    def ad_groups(self) -> list[dict[str, Any]]:
        """Ad groups, excluding removed ones."""
        return self.search(
            "SELECT ad_group.id, ad_group.name, ad_group.status, ad_group.campaign, "
            "ad_group.cpc_bid_micros, campaign.id "
            "FROM ad_group WHERE ad_group.status != 'REMOVED'"
        )

    def ads(self) -> list[dict[str, Any]]:
        """Ads with their headlines and descriptions, which Creative Strategist reads."""
        return self.search(
            "SELECT ad_group_ad.ad.id, ad_group_ad.ad.name, ad_group_ad.status, "
            "ad_group_ad.ad.type, ad_group_ad.ad.final_urls, "
            "ad_group_ad.ad.responsive_search_ad.headlines, "
            "ad_group_ad.ad.responsive_search_ad.descriptions, "
            "ad_group_ad.ad.tracking_url_template, ad_group.id "
            "FROM ad_group_ad WHERE ad_group_ad.status != 'REMOVED'"
        )

    def daily_metrics(self, since: date, until: date, *, level: str = "ad") -> list[dict[str, Any]]:
        """Daily figures between two dates (inclusive), one row per entity per day.

        `level` is one of campaign, ad_group, ad. Google restates recent days too, so callers
        re-read a window instead of trusting stored figures.
        """
        resources = {
            "campaign": ("campaign", "campaign.id"),
            "ad_group": ("ad_group", "ad_group.id, campaign.id"),
            "ad": ("ad_group_ad", "ad_group_ad.ad.id, ad_group.id, campaign.id"),
        }
        if level not in resources:
            raise GoogleAdsError("bad_request", f"Unknown metrics level {level!r}.")
        if until < since:
            raise GoogleAdsError("bad_request", "The metrics range ends before it starts.")
        resource, ids = resources[level]
        # GAQL, not SQL, and nothing here comes from the caller as text: `ids` and `resource` are
        # looked up in the table above, and the dates are date objects formatted by isoformat().
        return self.search(
            f"SELECT {ids}, segments.date, metrics.cost_micros, metrics.impressions, "  # noqa: S608
            "metrics.clicks, metrics.conversions, metrics.conversions_value, "
            "customer.currency_code "
            f"FROM {resource} "
            f"WHERE segments.date BETWEEN '{since.isoformat()}' AND '{until.isoformat()}' "
            "AND metrics.impressions > 0"
        )


def _section(row: dict[str, Any], name: str) -> dict[str, Any]:
    """One nested object of a GAQL result row, or an empty one when the field is absent.

    Google nests a row as {"metrics": {...}, "segments": {...}}, and leaves a section out entirely
    when nothing in it was selected.
    """
    value = row.get(name)
    return value if isinstance(value, dict) else {}


def metric_row(row: dict[str, Any]) -> dict[str, Any]:
    """Turn one Google metrics row into the columns of ads.daily_metric.

    Google has no reach, frequency, add-to-cart or video hook figures in this query, so those stay
    null: an empty cell means "this platform does not report it", not zero.
    """
    metrics = _section(row, "metrics")
    segments = _section(row, "segments")
    customer = _section(row, "customer")
    return {
        "metric_date": str(segments.get("date") or "")[:10],
        "spend": round(micros(metrics.get("costMicros")), 2),
        "impressions": _as_int(metrics.get("impressions")),
        "reach": None,
        "frequency": None,
        "clicks": _as_int(metrics.get("clicks")),
        # A Google click is already a click through to the site, so it is also the link-click count.
        "link_clicks": _as_int(metrics.get("clicks")) or None,
        "landing_page_views": None,
        "add_to_cart": None,
        "initiate_checkout": None,
        "purchases": round(_as_float(metrics.get("conversions")), 2) or None,
        "purchase_value": round(_as_float(metrics.get("conversionsValue")), 2) or None,
        "video_3s_views": None,
        "video_thruplays": None,
        "currency": str(customer.get("currencyCode") or ""),
    }
