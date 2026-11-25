"""The /api/ads and /api/creative routes, through the real application.

Proves that both routers are actually mounted on the app (a module that fails to import is skipped
silently by design, so only a request shows it is really there), and that each route answers in
demo mode without any credential or network call.
"""

from __future__ import annotations

from typing import Any

import pytest
from tests.fixtures.seo import local_client

ENV_KEYS = (
    "META_SYSTEM_USER_TOKEN",
    "RIDHI_META_AD_ACCOUNT_ID",
    "CPC_META_AD_ACCOUNT_ID",
    "GOOGLE_ADS_CLIENT_ID",
    "GOOGLE_ADS_CLIENT_SECRET",
    "GOOGLE_ADS_REFRESH_TOKEN",
    "RIDHI_GOOGLE_ADS_CUSTOMER_ID",
    "CPC_GOOGLE_ADS_CUSTOMER_ID",
    "ADS_DEMO",
    "CREATIVE_DEMO",
    "DEMO_MODE",
)


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch) -> Any:
    """The real application with no ad credentials set, so both modules answer in demo mode."""
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    from flowmerce.modules.seo.app import create_app

    return create_app()


def test_ads_status_route_is_mounted_and_reports_both_stores(app: Any) -> None:
    response = local_client(app).get("/api/ads/status")
    assert response.status_code == 200
    body = response.json()
    assert body["demo"] is True
    assert {row["store"] for row in body["stores"]} == {"RBP", "CPC"}
    assert body["stores"][0]["meta"]["connected"] is False


def test_ads_summary_route_answers_with_demo_figures(app: Any) -> None:
    response = local_client(app).get("/api/ads/summary?brand=ridhi&days=28")
    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "demo"
    assert body["platforms"]["meta"]["spend"] == 4235.0
    assert body["platforms"]["meta"]["currency"] == "USD"
    assert body["problems"] == []


def test_ads_summary_rejects_an_unknown_brand(app: Any) -> None:
    response = local_client(app).get("/api/ads/summary?brand=nope")
    assert response.status_code == 400
    assert response.json()["code"] == "bad_request"


def test_ads_summary_clamps_a_silly_day_count(app: Any) -> None:
    """A query string is not trusted: 9999 days is clamped, not passed through."""
    response = local_client(app).get("/api/ads/summary?brand=ridhi&days=9999")
    assert response.status_code == 200
    body = response.json()
    assert body["platforms"]["meta"]["days"] == 400


def test_creative_insights_route_is_mounted(app: Any) -> None:
    response = local_client(app).get("/api/creative/insights?brand=ridhi")
    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "demo"
    assert body["adsSeen"] == 6
    assert body["comparisons"]["formatRoas"]["best"]["key"] == "video"


def test_creative_concepts_and_brief_routes(app: Any) -> None:
    client = local_client(app)
    concepts = client.get("/api/creative/concepts?brand=ridhi")
    assert concepts.status_code == 200
    assert len(concepts.json()["concepts"]) == 3

    brief = client.get("/api/creative/concepts/1/brief?brand=ridhi")
    assert brief.status_code == 200
    assert "From the carved block to your table" in brief.json()["markdown"]


def test_brief_for_an_unknown_concept_is_a_400(app: Any) -> None:
    response = local_client(app).get("/api/creative/concepts/999/brief?brand=ridhi")
    assert response.status_code == 400
    assert response.json()["code"] == "bad_request"


def test_no_route_here_can_change_anything(app: Any) -> None:
    """Both modules are read-only: a write to either prefix must not find a handler."""
    client = local_client(app)
    for method, url in (
        ("post", "/api/ads/summary"),
        ("post", "/api/creative/concepts"),
        ("delete", "/api/creative/concepts/1"),
    ):
        response = getattr(client, method)(url, headers={"X-Requested-With": "blog-ops"})
        assert response.status_code in (404, 405), f"{method.upper()} {url} should not be handled"
