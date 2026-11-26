"""The read-only Meta client (modules/ads/meta.py). No network: Meta is an httpx.MockTransport."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from flowmerce.modules.ads import meta as meta_module
from flowmerce.modules.ads.config import MetaAccount
from flowmerce.modules.ads.meta import MetaClient, MetaError, ad_row, daily_row, minor_to_major

TOKEN = "EAAtestTOKENvalue123"  # noqa: S105 - a made-up token for the tests
ACC = MetaAccount("ridhi", "act_123", TOKEN)

# One insights row as Meta returns it (level=ad, one day), trimmed.
ROW = {
    "ad_id": "52547966364187",
    "date_start": "2026-10-23",
    "spend": "11843.12",
    "impressions": "20500",
    "inline_link_clicks": "800",
    "outbound_clicks": [{"action_type": "outbound_click", "value": "741"}],
    "actions": [
        {"action_type": "landing_page_view", "value": "700"},
        {"action_type": "add_to_cart", "value": "70"},
        {"action_type": "omni_add_to_cart", "value": "75"},
        {"action_type": "omni_initiated_checkout", "value": "24"},
        {"action_type": "purchase", "value": "9"},
        {"action_type": "omni_purchase", "value": "10"},
        {"action_type": "video_view", "value": "6900"},
    ],
    "action_values": [{"action_type": "purchase", "value": "15012.5"}],
    "video_play_actions": [{"action_type": "video_view", "value": "12000"}],
    "video_p25_watched_actions": [{"action_type": "video_view", "value": "4000"}],
    "video_p50_watched_actions": [{"action_type": "video_view", "value": "2000"}],
    "video_p75_watched_actions": [{"action_type": "video_view", "value": "1100"}],
    "video_p95_watched_actions": [{"action_type": "video_view", "value": "700"}],
    "video_avg_time_watched_actions": [{"action_type": "video_view", "value": "6"}],
}


def client(handler: Any) -> tuple[MetaClient, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    return MetaClient(ACC, transport=httpx.MockTransport(wrapped)), seen


def test_daily_row_uses_the_counts_that_match_the_sheet() -> None:
    r = daily_row(ROW)
    assert r["purchases"] == 9 and r["value"] == 15012.5  # `purchase`, not `omni_purchase`
    assert r["atc"] == 75 and r["ic"] == 24  # the combined website + app counts
    assert r["clicks"] == 741 and r["link_clicks"] == 800 and r["lpv"] == 700
    assert r["v3"] == 6900 and r["p25"] == 4000 and r["p95"] == 700
    assert r["plays"] == 12000 and r["watch_s"] == 72000  # average x plays, so days add up
    assert r["spend"] == 11843.12 and r["day"] == "2026-10-23"


def test_budgets_are_in_minor_units_and_ads_know_their_post_and_format() -> None:
    assert (
        minor_to_major("2000000") == 20000.0
        and minor_to_major(None) is None
        and minor_to_major("0") is None
    )
    a = ad_row(
        "meta:ridhi",
        {
            "id": 1,
            "name": "CR1 | x",
            "campaign_id": 2,
            "adset_id": 3,
            "effective_status": "ACTIVE",
            "creative": {"video_id": "99", "effective_object_story_id": "p_1"},
        },
    )
    assert (
        a["format"] == "video"
        and a["post_id"] == "p_1"
        and a["id"] == "1"
        and a["ad_set_id"] == "3"
    )
    assert ad_row("k", {"id": 5, "creative": {"object_type": "SHARE"}})["format"] == "image"


def test_only_reads_follow_paging_and_keep_the_token_out_of_urls() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "after" in str(request.url):
            return httpx.Response(200, json={"data": [ROW]})
        return httpx.Response(
            200,
            json={
                "data": [ROW],
                "paging": {"next": "https://graph.facebook.com/v27.0/act_123/insights?after=X"},
            },
        )

    meta, seen = client(handler)
    rows = meta.daily(datetime(2026, 10, 17).date(), datetime(2026, 10, 23).date())
    assert len(rows) == 2
    assert all(r.method == "GET" for r in seen)
    assert all(TOKEN not in str(r.url) for r in seen)
    assert all(r.headers["Authorization"] == f"Bearer {TOKEN}" for r in seen)
    first = seen[0].url
    assert first.path == "/v27.0/act_123/insights" and first.params["level"] == "ad"
    assert json.loads(first.params["time_range"]) == {"since": "2026-10-17", "until": "2026-10-23"}


def test_an_expired_token_is_explained_without_showing_it() -> None:
    meta, _ = client(
        lambda r: httpx.Response(
            400, json={"error": {"code": 190, "message": f"bad token {TOKEN}"}}
        )
    )
    with pytest.raises(MetaError) as e:
        meta.account_info()
    assert e.value.state == "token_expired" and TOKEN not in e.value.message


def test_meta_error_text_never_carries_the_token() -> None:
    meta, _ = client(
        lambda r: httpx.Response(400, json={"error": {"code": 1, "message": f"oops {TOKEN}"}})
    )
    with pytest.raises(MetaError) as e:
        meta.campaigns()
    assert TOKEN not in e.value.message and "<hidden>" in e.value.message


def test_stops_before_meta_blocks_the_account() -> None:
    usage = json.dumps({"123": [{"call_count": 95, "total_cputime": 10, "total_time": 10}]})
    meta, _ = client(
        lambda r: httpx.Response(
            200, json={"data": []}, headers={"x-business-use-case-usage": usage}
        )
    )
    with pytest.raises(MetaError) as e:
        meta.campaigns()
    assert e.value.state == "rate_limited"
    meta, _ = client(
        lambda r: httpx.Response(400, json={"error": {"code": 17, "message": "limit"}})
    )
    with pytest.raises(MetaError) as e:
        meta.campaigns()
    assert e.value.state == "rate_limited"


def test_budget_changes_come_from_budget_events_only() -> None:
    events = [
        {
            "event_type": "update_campaign_budget",
            "event_time": "2026-11-23T10:00:00+0000",
            "object_id": "c1",
        },
        {
            "event_type": "update_ad_run_status",
            "event_time": "2026-11-23T11:00:00+0000",
            "object_id": "c2",
        },
        {
            "event_type": "update_campaign_budget",
            "event_time": "2026-11-22T10:00:00+0000",
            "object_id": "c1",
        },
    ]
    meta, seen = client(lambda r: httpx.Response(200, json={"data": events}))
    out = meta.budget_changes(datetime(2026, 11, 20, tzinfo=UTC))
    assert out == {"c1": datetime(2026, 11, 23, 10, tzinfo=UTC)}
    assert seen[0].url.path.endswith("/activities")


def test_token_info_reads_the_expiry() -> None:
    meta, _ = client(
        lambda r: httpx.Response(200, json={"data": {"is_valid": True, "expires_at": 1800000000}})
    )
    info = meta.token_info()
    assert info.valid and info.expires_at == datetime.fromtimestamp(1800000000, UTC)


def test_too_much_data_is_read_in_smaller_pieces() -> None:
    asked: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        span = json.loads(request.url.params.get("time_range", "{}"))
        asked.append((span.get("since", ""), span.get("until", "")))
        if span.get("since") != span.get("until"):
            return httpx.Response(
                500,
                json={
                    "error": {
                        "code": 1,
                        "message": "Please reduce the amount of data you're asking for",
                    }
                },
            )
        return httpx.Response(200, json={"data": [{**ROW, "date_start": span["since"]}]})

    meta, _ = client(handler)
    rows = meta.daily(datetime(2026, 10, 17).date(), datetime(2026, 10, 20).date())
    assert [r["day"] for r in rows] == ["2026-10-17", "2026-10-18", "2026-10-19", "2026-10-20"]
    assert asked[0] == ("2026-10-17", "2026-10-20")


def test_too_much_data_halves_the_page_size() -> None:
    limits: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        limits.append(int(request.url.params["limit"]))
        if limits[-1] > 25:
            return httpx.Response(
                500,
                json={
                    "error": {
                        "code": 1,
                        "message": "Please reduce the amount of data you're asking for",
                    }
                },
            )
        return httpx.Response(200, json={"data": [{"id": "1"}]})

    meta, _ = client(handler)
    assert meta.ads() == [{"id": "1"}] and limits == [100, 50, 25]


def test_network_blips_are_retried_with_pauses(monkeypatch: pytest.MonkeyPatch) -> None:
    pauses: list[float] = []
    monkeypatch.setattr(meta_module.time, "sleep", pauses.append)
    calls = {"n": 0}

    def flaky(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            raise httpx.ConnectTimeout("no route", request=request)
        return httpx.Response(200, json={"name": "ok"})

    meta, _ = client(flaky)
    assert meta.account_info() == {"name": "ok"} and pauses == [5, 15]

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("no route", request=request)

    pauses.clear()
    meta, _ = client(down)
    with pytest.raises(MetaError) as e:
        meta.account_info()
    assert e.value.state == "connection_failed" and pauses == [5, 15, 45]
