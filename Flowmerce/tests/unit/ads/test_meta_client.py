"""Meta client: paging, error states, throttle reading and the row mapping.

No network: httpx.MockTransport answers every request. No real token is used anywhere.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import httpx
import pytest

from flowmerce.modules.ads.config import MetaCredentials
from flowmerce.modules.ads.meta import MetaClient, MetaError, action_value, metric_row

CREDS = MetaCredentials(token="test-token", account_id="act_123", api_version="v25.0")


def client_for(handler: Any) -> MetaClient:
    return MetaClient(CREDS, timeout=5, transport=httpx.MockTransport(handler))


def test_not_configured_before_any_credentials() -> None:
    blank = MetaClient(MetaCredentials("", "", "v25.0"))
    with pytest.raises(MetaError) as exc:
        blank.accounts()
    assert exc.value.state == "not_configured"


def test_insights_sends_the_pinned_version_level_and_daily_increment() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"data": []})

    client_for(handler).insights(date(2026, 11, 1), date(2026, 11, 7))
    assert len(seen) == 1
    url = seen[0].url
    assert "/v25.0/act_123/insights" in str(url.path)
    assert url.params["level"] == "ad"
    assert url.params["time_increment"] == "1"
    assert json.loads(url.params["time_range"]) == {"since": "2026-11-01", "until": "2026-11-07"}


def test_the_token_travels_in_the_query_and_is_never_in_an_error_message() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["access_token"] == "test-token"
        return httpx.Response(
            400, json={"error": {"code": 100, "error_subcode": 33, "message": "Unknown path"}}
        )

    with pytest.raises(MetaError) as exc:
        client_for(handler).insights(date(2026, 11, 1), date(2026, 11, 7))
    assert exc.value.state == "not_found"
    assert "test-token" not in exc.value.message


def test_paging_follows_the_after_cursor_until_next_is_gone() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.params.get("after", ""))
        if len(calls) == 1:
            return httpx.Response(
                200,
                json={
                    "data": [{"ad_id": "1"}],
                    "paging": {"cursors": {"after": "CUR2"}, "next": "https://example/next"},
                },
            )
        return httpx.Response(200, json={"data": [{"ad_id": "2"}], "paging": {"cursors": {}}})

    rows = client_for(handler).insights(date(2026, 11, 1), date(2026, 11, 2))
    assert [r["ad_id"] for r in rows] == ["1", "2"]
    assert calls == ["", "CUR2"]


@pytest.mark.parametrize(
    ("status", "body", "state"),
    [
        (401, {"error": {"code": 190, "message": "expired"}}, "token_invalid"),
        (403, {"error": {"code": 272, "message": "no access"}}, "permission_denied"),
        (400, {"error": {"code": 100, "error_subcode": 33}}, "not_found"),
        (500, {"error": {"code": 2}}, "platform_error"),
    ],
)
def test_error_states(status: int, body: dict[str, Any], state: str) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=body)

    with pytest.raises(MetaError) as exc:
        # attempts=1 so a retryable state fails immediately instead of sleeping through retries
        client_for(handler)._get("/act_123/insights", {}, attempts=1)
    assert exc.value.state == state


def test_rate_limit_is_retried_then_reported() -> None:
    tries: list[int] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        tries.append(1)
        return httpx.Response(429, json={"error": {"code": 4, "message": "too many"}})

    with pytest.raises(MetaError) as exc:
        client_for(handler)._get("/act_123/insights", {}, attempts=2)
    assert exc.value.state == "rate_limited"
    assert len(tries) == 2


def test_throttle_header_is_read_and_flags_a_near_limit() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"data": []},
            headers={
                "x-fb-ads-insights-throttle": json.dumps(
                    {
                        "app_id_util_pct": 81.5,
                        "acc_id_util_pct": 12.0,
                        "ads_api_access_tier": "standard_access",
                    }
                )
            },
        )

    client = client_for(handler)
    client.insights(date(2026, 11, 1), date(2026, 11, 2))
    assert client.throttle.app_pct == 81.5
    assert client.throttle.tier == "standard_access"
    assert client.throttle.near_limit is True


def test_bad_range_and_bad_level_are_refused_before_any_request() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:  # pragma: no cover - must not run
        raise AssertionError("no request should be made")

    client = client_for(handler)
    with pytest.raises(MetaError) as exc:
        client.insights(date(2026, 11, 7), date(2026, 11, 1))
    assert exc.value.state == "bad_request"
    with pytest.raises(MetaError):
        client.insights(date(2026, 11, 1), date(2026, 11, 2), level="nonsense")


def test_action_value_prefers_omni_then_falls_back() -> None:
    both = [
        {"action_type": "omni_purchase", "value": "5"},
        {"action_type": "purchase", "value": "3"},
    ]
    assert action_value(both, ("omni_purchase", "purchase")) == 5.0
    pixel_only = [{"action_type": "purchase", "value": "3"}]
    assert action_value(pixel_only, ("omni_purchase", "purchase")) == 3.0
    assert action_value(None, ("omni_purchase",)) == 0.0


def test_metric_row_reads_strings_and_leaves_absent_metrics_null() -> None:
    row = {
        "date_start": "2026-11-18",
        "account_currency": "INR",
        "spend": "1234.56",
        "impressions": "10000",
        "clicks": "250",
        "inline_link_clicks": "200",
        "actions": [{"action_type": "omni_purchase", "value": "4"}],
        "action_values": [{"action_type": "omni_purchase", "value": "6400.5"}],
    }
    out = metric_row(row)
    assert out["metric_date"] == "2026-11-18"
    assert out["spend"] == 1234.56
    assert out["impressions"] == 10000
    assert out["purchases"] == 4.0
    assert out["purchase_value"] == 6400.5
    assert out["currency"] == "INR"
    # Meta leaves a metric out rather than sending zero; an absent metric stays null, not 0.
    assert out["reach"] is None
    assert out["video_3s_views"] is None
