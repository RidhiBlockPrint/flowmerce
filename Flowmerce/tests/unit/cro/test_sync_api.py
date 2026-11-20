"""CRO order sync and HTTP routes. No network: Supabase is an httpx.MockTransport, Shopify a
fake function.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest
from tests.fixtures.seo import local_client

from flowmerce.modules.cro import service, sync
from flowmerce.modules.cro.config import set_cro_client
from flowmerce.modules.shipping.config import ShippingConfig
from flowmerce.modules.shipping.supabase import SupabaseClient

CFG = ShippingConfig("https://example.supabase.co", "service-key", "cro", 5, 0)
NOW = datetime(2026, 11, 19, 12, tzinfo=UTC)


class FakeSupabase:
    """Records every call; answers begin_sync / save_orders / end_sync and reads of sync_state."""

    def __init__(self, lock: bool = True, held_since: str | None = None) -> None:
        self.lock = lock
        self.held_since = held_since
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.patches: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["Accept-Profile"] == "cro"
        fn = request.url.path.rsplit("/", 1)[-1]
        if request.method == "GET" and fn == "sync_state":
            return httpx.Response(200, json=[{"running_since": self.held_since}])
        body = json.loads(request.content or b"{}")
        if request.method == "PATCH":
            self.patches.append((request.url.query.decode(), body))
            return httpx.Response(204)
        self.calls.append((fn, body))
        if fn == "begin_sync":
            return httpx.Response(
                200, json=[{"got_lock": True, "since_cursor": None}] if self.lock else []
            )
        if fn == "save_orders":
            return httpx.Response(200, json=len(body["p_orders"]))
        return httpx.Response(204)

    def client(self) -> SupabaseClient:
        return SupabaseClient(CFG, transport=httpx.MockTransport(self))


def order_node(oid: int, updated: str, test: bool = False) -> dict[str, Any]:
    return {
        "legacyResourceId": str(oid),
        "name": f"#{oid}",
        "createdAt": "2026-11-18T10:00:00Z",
        "updatedAt": updated,
        "test": test,
        "displayFinancialStatus": "PAID",
        "currentTotalPriceSet": {"shopMoney": {"amount": "10", "currencyCode": "USD"}},
        "lineItems": {"nodes": []},
    }


def pages(*batches: list[dict[str, Any]]) -> Any:
    seen: list[dict[str, Any] | None] = []

    def gql(_q: str, v: dict[str, Any] | None = None) -> dict[str, Any]:
        seen.append(v)
        i = len(seen) - 1
        return {
            "orders": {
                "nodes": batches[i],
                "pageInfo": {"hasNextPage": i + 1 < len(batches), "endCursor": f"c{i}"},
            }
        }

    gql.seen = seen  # type: ignore[attr-defined]
    return gql


def test_first_sync_reads_60_days_skips_test_orders_and_saves_cursor() -> None:
    fake = FakeSupabase()
    gql = pages(
        [order_node(1, "2026-11-18T11:00:00Z"), order_node(2, "2026-11-18T12:00:00Z", test=True)],
        [order_node(1, "2026-11-19T09:00:00Z"), order_node(3, "2026-11-18T13:00:00Z")],
    )
    res = sync.sync_store("RBP", c=fake.client(), gql=gql, now=NOW)
    assert res["state"] == "ok" and res["mode"] == "first load"
    assert res["orders_read"] == 4 and res["orders_written"] == 2
    assert "updated_at:>='2026-09-20T12:00:00Z'" == gql.seen[0]["q"]
    assert gql.seen[1]["after"] == "c0"
    saved = [b for fn, b in fake.calls if fn == "save_orders"]
    assert len(saved) == 1
    ids = [o["id"] for o in saved[0]["p_orders"]]
    assert sorted(ids) == [1, 3]  # test order 2 left out, order 1 once (latest copy)
    end = [b for fn, b in fake.calls if fn == "end_sync"][-1]
    assert end["p_ok"] is True and end["p_cursor"] == "2026-11-19T09:00:00Z"


def test_sync_refuses_while_another_runs() -> None:
    fake = FakeSupabase(lock=False)
    res = sync.sync_store("RBP", c=fake.client(), gql=pages([]), now=NOW)
    assert res["state"] == "already_running"
    assert [fn for fn, _ in fake.calls] == ["begin_sync"]


def test_shopify_failure_is_recorded_and_releases_the_lock() -> None:
    fake = FakeSupabase()

    def broken(_q: str, _v: dict[str, Any] | None = None) -> dict[str, Any]:
        raise RuntimeError("Shopify 503")

    res = sync.sync_store("RBP", c=fake.client(), gql=broken, now=NOW)
    assert res["state"] == "failed" and "503" in res["error"]
    end = [b for fn, b in fake.calls if fn == "end_sync"][-1]
    assert end["p_ok"] is False and end["p_cursor"] is None


def test_cursor_overlap() -> None:
    since, first = sync.since_from_cursor("2026-11-19T10:00:00+00:00", NOW)
    assert not first and since == datetime(2026, 11, 19, 9, 50, tzinfo=UTC)


# ------------------------------------------------------------------------------------------ routes
@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch) -> Any:
    from flowmerce.modules.seo.app import create_app

    monkeypatch.setattr(service, "store_timezone", lambda _s: ZoneInfo("UTC"))
    set_cro_client(SupabaseClient(ShippingConfig("", "", "cro", 5, 0)))  # Supabase "not configured"
    yield create_app()
    set_cro_client(None)


def test_routes_are_mounted_and_explain_missing_supabase(app: Any) -> None:
    c = local_client(app)
    r = c.get("/api/cro/overview?brand=ridhi")
    assert r.status_code == 503 and r.json()["code"] == "not_configured"
    assert c.get("/api/cro/benchmarks").status_code == 200


def test_unknown_brand_is_a_bad_request(app: Any) -> None:
    r = local_client(app).get("/api/cro/overview?brand=nope")
    assert r.status_code == 400 and r.json()["code"] == "bad_request"


def test_writes_need_the_csrf_header(app: Any) -> None:
    c = local_client(app)
    r = c.post("/api/cro/change-log?brand=ridhi", json={"change": "New theme"})
    assert r.status_code == 403 and r.json()["code"] == "csrf"


def test_change_log_input_is_checked(app: Any) -> None:
    c = local_client(app)
    r = c.post(
        "/api/cro/change-log?brand=ridhi",
        json={"change": "  ", "entry_date": "2026-11-19"},
        headers={"X-Requested-With": "blog-ops"},
    )
    assert r.status_code == 400 and "1 to 1000" in r.json()["error"]


def test_progress_is_saved_after_every_batch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sync, "SAVE_BATCH", 2)
    fake = FakeSupabase()
    gql = pages(
        [order_node(1, "2026-11-18T01:00:00Z"), order_node(2, "2026-11-18T02:00:00Z")],
        [order_node(3, "2026-11-18T03:00:00Z"), order_node(4, "2026-11-18T04:00:00Z")],
        [order_node(5, "2026-11-18T05:00:00Z")],
    )
    res = sync.sync_store("RBP", c=fake.client(), gql=gql, now=NOW)
    assert res["state"] == "ok"
    cursors = [b.get("cursor") for _, b in fake.patches]
    assert cursors == ["2026-11-18T02:00:00+00:00", "2026-11-18T04:00:00+00:00"]
    assert all("running_since" in b for _, b in fake.patches)  # the lock is refreshed too


def test_resumes_from_a_saved_cursor_without_moving_it_back() -> None:
    fake = FakeSupabase()
    fake.lock = True

    def begin(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("begin_sync"):
            return httpx.Response(
                200, json=[{"got_lock": True, "since_cursor": "2026-11-18T09:00:00Z"}]
            )
        return fake(request)

    c = SupabaseClient(CFG, transport=httpx.MockTransport(begin))
    gql = pages([order_node(1, "2026-11-18T08:55:00Z")] * 50)
    res = sync.sync_store("RBP", c=c, gql=gql, now=NOW)
    assert res["mode"] == "changes"
    assert gql.seen[0]["q"] == "updated_at:>='2026-11-18T08:50:00Z'"
    assert all("cursor" not in b for _, b in fake.patches)  # 08:55 is behind 09:00: not saved


def test_abandoned_lock_is_cleared_but_a_live_one_is_kept() -> None:
    old = FakeSupabase(held_since="2026-11-19T11:40:00+00:00")  # 20 minutes ago
    assert sync.clear_abandoned_lock(old.client(), "RBP", NOW) is True
    query, body = old.patches[0]
    assert body == {"running_since": None} and "running_since=eq." in query
    live = FakeSupabase(held_since="2026-11-19T11:55:00+00:00")  # 5 minutes ago
    assert sync.clear_abandoned_lock(live.client(), "RBP", NOW) is False
    assert live.patches == []


def test_background_job_obeys_scheduler_false() -> None:
    from flowmerce.modules.cro import scheduler
    from flowmerce.modules.seo.config import config

    assert config.scheduler is False  # set by tests/fixtures/seo.py
    assert scheduler.enabled() is False and scheduler.start() is False


def test_order_data_state() -> None:
    assert service.order_data_state(None)["first_load_complete"] is False
    running = service.order_data_state({"running_since": "x", "cursor": "2026-11-06T00:00:00Z"})
    assert running["first_load_complete"] is False and "still running" in running["note"]
    done = service.order_data_state({"cursor": "c", "last_run_at": "t", "last_status": "ok"})
    assert done["first_load_complete"] is True and done["note"] == ""
    failed = service.order_data_state(
        {"cursor": "c", "last_run_at": "t", "last_status": "failed", "last_error": "Shopify 503"}
    )
    assert failed["first_load_complete"] is True and "Shopify 503" in failed["note"]


def test_recommendations_wait_for_the_first_load(monkeypatch: pytest.MonkeyPatch) -> None:
    from flowmerce.modules.cro import conversion, data
    from flowmerce.modules.cro.data import Snapshot
    from flowmerce.modules.cro.shopify import AnalyticsError

    monkeypatch.setattr(service, "store_timezone", lambda _s: ZoneInfo("UTC"))
    monkeypatch.setattr(data, "snapshot", lambda _s: Snapshot("RBP", (), (), NOW, NOW))
    monkeypatch.setattr(data, "sync_state", lambda _s: {"running_since": "x", "cursor": None})
    monkeypatch.setattr(data, "alarm_rules", lambda _s: pytest.fail("order checks must not run"))
    monkeypatch.setattr(data, "first_order_day", lambda _s: None)   # no Supabase in tests

    def no_reports(*_a: Any, **_k: Any) -> Any:
        raise AnalyticsError("reports_access_missing", "no")

    monkeypatch.setattr(conversion, "daily", no_reports)
    out = service.recommendation_list("ridhi")
    assert out["recommendations"] == []
    assert any("first order load" in s for s in out["skipped"])
    assert out["order_data"]["first_load_complete"] is False
