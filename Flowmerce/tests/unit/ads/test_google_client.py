"""Google Ads client: token exchange, headers, searchStream batches, error states, row mapping.

No network: httpx.MockTransport answers every request, including the OAuth token endpoint. No real
credentials are used anywhere.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import httpx
import pytest

from flowmerce.modules.ads.config import GoogleCredentials
from flowmerce.modules.ads.google import GoogleAdsClient, GoogleAdsError, metric_row, micros

CREDS = GoogleCredentials(
    client_id="client-id",
    client_secret="client-secret",
    refresh_token="refresh-token",
    customer_id="1234567890",
    login_customer_id="",
    api_version="v26",
)
MANAGED = GoogleCredentials(
    client_id="client-id",
    client_secret="client-secret",
    refresh_token="refresh-token",
    customer_id="1234567890",
    login_customer_id="9998887777",
    api_version="v26",
)


def token_ok(request: httpx.Request) -> httpx.Response | None:
    """Answer the OAuth token endpoint; returns None for any other request."""
    if "oauth2" in str(request.url):
        return httpx.Response(200, json={"access_token": "access-abc", "expires_in": 3600})
    return None


def client_for(handler: Any, creds: GoogleCredentials = CREDS) -> GoogleAdsClient:
    return GoogleAdsClient(creds, timeout=5, transport=httpx.MockTransport(handler))


def test_not_configured_before_any_credentials() -> None:
    blank = GoogleAdsClient(GoogleCredentials("", "", "", "", "", "v26"))
    with pytest.raises(GoogleAdsError) as exc:
        blank.accessible_customers()
    assert exc.value.state == "not_configured"


def test_search_sends_bearer_token_and_no_developer_token() -> None:
    """The developer token was sunset in September 2026 and is rejected later: never send it."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        answered = token_ok(request)
        if answered is not None:
            return answered
        seen.append(request)
        return httpx.Response(200, json=[{"results": []}])

    client_for(handler).search("SELECT customer.id FROM customer")
    assert len(seen) == 1
    assert seen[0].headers["Authorization"] == "Bearer access-abc"
    assert "developer-token" not in {k.lower() for k in seen[0].headers}
    assert "login-customer-id" not in {k.lower() for k in seen[0].headers}
    assert "/v26/customers/1234567890/googleAds:searchStream" in str(seen[0].url)


def test_manager_account_adds_the_login_customer_id_header() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        answered = token_ok(request)
        if answered is not None:
            return answered
        seen.append(request)
        return httpx.Response(200, json=[{"results": []}])

    client_for(handler, MANAGED).search("SELECT customer.id FROM customer")
    assert seen[0].headers["login-customer-id"] == "9998887777"


def test_access_token_is_reused_between_calls() -> None:
    token_calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if "oauth2" in str(request.url):
            token_calls.append(1)
            return httpx.Response(200, json={"access_token": "access-abc", "expires_in": 3600})
        return httpx.Response(200, json=[{"results": []}])

    client = client_for(handler)
    client.search("SELECT customer.id FROM customer")
    client.search("SELECT customer.id FROM customer")
    assert len(token_calls) == 1


def test_revoked_refresh_token_is_explained() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "oauth2" in str(request.url):
            return httpx.Response(400, json={"error": "invalid_grant"})
        return httpx.Response(200, json=[{"results": []}])

    with pytest.raises(GoogleAdsError) as exc:
        client_for(handler).search("SELECT customer.id FROM customer")
    assert exc.value.state == "token_invalid"
    assert "refresh token" in exc.value.message
    assert "refresh-token" not in exc.value.message  # the value itself never appears


def test_searchstream_collects_results_from_every_batch() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        answered = token_ok(request)
        if answered is not None:
            return answered
        return httpx.Response(
            200,
            json=[
                {"results": [{"campaign": {"id": "1"}}, {"campaign": {"id": "2"}}]},
                {"results": [{"campaign": {"id": "3"}}]},
            ],
        )

    rows = client_for(handler).campaigns()
    assert [r["campaign"]["id"] for r in rows] == ["1", "2", "3"]


def test_accessible_customers_strips_the_resource_prefix() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        answered = token_ok(request)
        if answered is not None:
            return answered
        return httpx.Response(
            200, json={"resourceNames": ["customers/1234567890", "customers/2223334444"]}
        )

    assert client_for(handler).accessible_customers() == ["1234567890", "2223334444"]


def test_test_level_project_is_named_as_the_problem() -> None:
    """A Cloud project still at Test access cannot read a real account; say exactly that."""

    def handler(request: httpx.Request) -> httpx.Response:
        answered = token_ok(request)
        if answered is not None:
            return answered
        return httpx.Response(
            403,
            json={
                "error": {
                    "message": "The project is not approved for production access.",
                    "details": [
                        {
                            "errors": [
                                {
                                    "errorCode": {
                                        "authorizationError":
                                            "CLOUD_PROJECT_NOT_APPROVED_FOR_PRODUCTION"
                                    }
                                }
                            ]
                        }
                    ],
                }
            },
        )

    with pytest.raises(GoogleAdsError) as exc:
        client_for(handler).account()
    assert exc.value.state == "access_level_too_low"
    assert "Test access level" in exc.value.message


def test_unknown_customer_id_is_explained() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        answered = token_ok(request)
        if answered is not None:
            return answered
        return httpx.Response(
            404,
            json={
                "error": {
                    "message": "not found",
                    "details": [
                        {"errors": [{"errorCode": {"requestError": "CUSTOMER_NOT_FOUND"}}]}
                    ],
                }
            },
        )

    with pytest.raises(GoogleAdsError) as exc:
        client_for(handler).account()
    assert exc.value.state == "not_found"


def test_bad_range_and_level_are_refused_before_any_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        answered = token_ok(request)
        if answered is not None:
            return answered
        raise AssertionError("no Ads request should be made")  # pragma: no cover

    client = client_for(handler)
    with pytest.raises(GoogleAdsError) as exc:
        client.daily_metrics(date(2026, 11, 7), date(2026, 11, 1))
    assert exc.value.state == "bad_request"
    with pytest.raises(GoogleAdsError):
        client.daily_metrics(date(2026, 11, 1), date(2026, 11, 2), level="nonsense")


def test_micros_and_metric_row() -> None:
    assert micros("1230000") == 1.23
    row = {
        "segments": {"date": "2026-11-18"},
        "metrics": {
            "costMicros": "18900000000",
            "impressions": "141300",
            "clicks": "4521",
            "conversions": "61.0",
            "conversionsValue": "97600.0",
        },
        "customer": {"currencyCode": "INR"},
    }
    out = metric_row(row)
    assert out["metric_date"] == "2026-11-18"
    assert out["spend"] == 18900.0
    assert out["impressions"] == 141300
    assert out["purchases"] == 61.0
    assert out["currency"] == "INR"
    # Google does not report these in this query: null means "not reported", not zero.
    assert out["reach"] is None
    assert out["video_3s_views"] is None
    assert out["add_to_cart"] is None
