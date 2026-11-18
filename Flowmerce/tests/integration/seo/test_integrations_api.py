"""POST /api/integrations/test and GET /api/integrations: a connection test reports authentication and API access as
separate steps, is stored without changing the sync status, and the list shows what is actually known."""
import pytest

from flowmerce.modules.seo import api as api_module
from flowmerce.modules.seo.app import create_app
from flowmerce.modules.seo.db import run
from flowmerce.modules.seo.integrations.status import mark_success, status_of
from tests.fixtures.seo import local_client

HDR = {"X-Requested-With": "blog-ops"}


@pytest.fixture(scope="module")
def app():
    return create_app()


@pytest.fixture
def clean_status():
    run("DELETE FROM integration_status WHERE key IN ('gsc', 'ga4', 'shopify') AND brand_id = 'cpc'")
    yield
    run("DELETE FROM integration_status WHERE key IN ('gsc', 'ga4', 'shopify') AND brand_id = 'cpc'")


def _item(body, key, brand):
    return next(i for i in body["items"] if i["key"] == key and i["brand"] == brand)


def test_test_button_records_auth_and_api_separately(app, clean_status, monkeypatch):
    monkeypatch.setattr(api_module, "check_access", lambda b, kind, s, e: {"auth": True, "api": False, "rows": None, "error": "Google refused access (403)"})
    c = local_client(app)
    r = c.post("/api/integrations/test", json={"key": "gsc", "brand": "cpc"}, headers=HDR).json()
    assert r["ok"] is False and r["result"]["auth"] is True and r["result"]["api"] is False and "403" in r["error"]
    st = status_of("gsc", "cpc")
    assert st["details"]["lastCheck"]["api"] is False
    assert st["last_success_at"] is None                 # a test never pretends a sync happened
    h = _item(c.get("/api/integrations").json(), "gsc", "cpc")["health"]
    assert h["auth"] is True and h["api"] is False and h["lastCheckError"]


def test_connected_with_zero_rows_is_not_reported_as_data(app, clean_status):
    mark_success("ga4", "cpc", "api", {"rows": 0, "dataThrough": None})
    h = _item(local_client(app).get("/api/integrations").json(), "ga4", "cpc")["health"]
    assert h["rows"] == 0 and h["receivedData"] is False and h["dataThrough"] is None
    mark_success("ga4", "cpc", "api", {"rows": 5, "dataThrough": "2026-11-10"})
    h = _item(local_client(app).get("/api/integrations").json(), "ga4", "cpc")["health"]
    assert h["receivedData"] is True and h["dataThrough"] == "2026-11-10" and h["auth"] is True


def test_manual_sync_while_one_is_running_is_refused(app, monkeypatch):
    from flowmerce.modules.seo.services import sync
    monkeypatch.setattr(sync, "gsc_configured", lambda b: True)
    with sync.exclusive("gsc", "cpc"):
        r = local_client(app).post("/api/analytics/sync", json={"brand": "cpc", "source": "gsc"}, headers=HDR)
    assert r.status_code == 409 and r.json()["code"] == "sync_running"
