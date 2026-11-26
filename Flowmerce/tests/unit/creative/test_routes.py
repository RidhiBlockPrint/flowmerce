"""The /api/creative routes, through the real application.

Proves the router is actually mounted on the app (a module that fails to import is skipped
silently by design, so only a request shows it is really there), and that each route answers in
demo mode without any credential or network call.
"""

from __future__ import annotations

from typing import Any

import pytest
from tests.fixtures.seo import local_client

ENV_KEYS = (
    "RIDHI_META_AD_ACCOUNT_ID",
    "RIDHI_META_ACCESS_TOKEN",
    "CPC_META_AD_ACCOUNT_ID",
    "CPC_META_ACCESS_TOKEN",
    "GOOGLE_ADS_DEVELOPER_TOKEN",
    "GOOGLE_ADS_REFRESH_TOKEN",
    "RIDHI_GOOGLE_ADS_CUSTOMER_ID",
    "CPC_GOOGLE_ADS_CUSTOMER_ID",
    "CREATIVE_DEMO",
    "DEMO_MODE",
)


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch) -> Any:
    """The real application with no ad credentials set, so Creative answers in demo mode."""
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    from flowmerce.modules.seo.app import create_app

    return create_app()


def test_creative_insights_route_is_mounted(app: Any) -> None:
    response = local_client(app).get("/api/creative/insights?brand=ridhi")
    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "demo"
    assert body["adsSeen"] == 6
    assert body["comparisons"]["formatRoas"]["best"]["key"] == "video"


def test_creative_insights_and_trend_honour_an_explicit_date_range(app: Any) -> None:
    client = local_client(app)
    insights = client.get("/api/creative/insights?brand=ridhi&from=2026-01-01&to=2026-01-07")
    assert insights.status_code == 200
    assert insights.json()["from"] == "2026-01-01"
    assert insights.json()["to"] == "2026-01-07"

    trend = client.get("/api/creative/trend?brand=ridhi&from=2026-01-01&to=2026-01-07")
    assert trend.status_code == 200
    assert trend.json()["from"] == "2026-01-01"
    assert len(trend.json()["days"]) == 7


def test_creative_insights_rejects_a_badly_formed_date(app: Any) -> None:
    response = local_client(app).get(
        "/api/creative/insights?brand=ridhi&from=not-a-date&to=2026-01-07"
    )
    assert response.status_code == 400
    assert response.json()["code"] == "bad_request"


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


def test_saving_a_concept_in_demo_mode_is_refused(app: Any) -> None:
    """Demo concepts already behave as if saved; there is nothing real yet to attach a save to."""
    response = local_client(app).post(
        "/api/creative/concepts?brand=ridhi",
        json={"title": "A new idea"},
        headers={"X-Requested-With": "blog-ops"},
    )
    assert response.status_code == 400
    assert response.json()["code"] == "bad_request"


def test_no_route_here_can_delete_a_concept(app: Any) -> None:
    """The Concepts page can save, but nothing here can delete through the API yet."""
    response = local_client(app).delete(
        "/api/creative/concepts/1", headers={"X-Requested-With": "blog-ops"}
    )
    assert response.status_code in (404, 405)
