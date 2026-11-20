"""How the CRO pages read Supabase quickly: paged reads at the same time, the order snapshot served
while it reloads in the background, and the short cache of small reads. No network: Supabase is an
httpx.MockTransport.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from flowmerce.modules.cro import data, service
from flowmerce.modules.shipping.config import ShippingConfig
from flowmerce.modules.shipping.supabase import SupabaseClient

CFG = ShippingConfig("https://example.supabase.co", "service-key", "cro", 5, 0)


@pytest.fixture(autouse=True)
def _clean() -> Iterator[None]:
    data.forget_snapshots()
    yield
    data.forget_snapshots()


class Paged:
    """`total` rows of one table, served in PostgREST pages (Range header, Content-Range total)."""

    def __init__(self, total: int, report_total: bool = True) -> None:
        self.total = total
        self.report_total = report_total
        self.ranges: list[str] = []
        self.lock = threading.Lock()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        start, end = (int(x) for x in request.headers["Range"].split("-"))
        with self.lock:
            self.ranges.append(request.headers["Range"])
        rows = [{"n": i} for i in range(start, min(end + 1, self.total))]
        tail = str(self.total) if self.report_total else "*"
        return httpx.Response(
            200, json=rows, headers={"content-range": f"{start}-{start + len(rows) - 1}/{tail}"}
        )

    def client(self) -> SupabaseClient:
        return SupabaseClient(CFG, transport=httpx.MockTransport(self))


@pytest.mark.parametrize("total", [0, 5, 1000, 1001, 3456])
def test_all_reads_every_row_in_order(total: int) -> None:
    fake = Paged(total)
    rows = data._all(fake.client(), "orders", [("select", "n")])
    assert [r["n"] for r in rows] == list(range(total))
    assert len(fake.ranges) == max(1, -(-total // data.PAGE))  # one request per page, no extra


def test_all_without_a_total_reads_page_by_page() -> None:
    fake = Paged(2500, report_total=False)
    rows = data._all(fake.client(), "orders", [("select", "n")])
    assert [r["n"] for r in rows] == list(range(2500))


def _snap(store: str, age_seconds: float) -> data.Snapshot:
    now = datetime.now(UTC) - timedelta(seconds=age_seconds)
    return data.Snapshot(store=store, orders=(), lines=(), loaded_at=now, since=now)


def test_stale_snapshot_is_served_at_once_and_reloaded_in_background(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = threading.Event()
    release = threading.Event()
    loads: list[str] = []

    def slow_load(store: str, *_: Any, **__: Any) -> data.Snapshot:
        loads.append(store)
        started.set()
        release.wait(5)
        return _snap(store, 0)

    monkeypatch.setattr(data, "load_snapshot", slow_load)
    old = _snap("RBP", 300)
    data._snapshots["RBP"] = (time.monotonic() - 1, old)  # expired, but younger than 30 min

    assert data.snapshot("RBP") is old  # no waiting for the reload
    assert started.wait(2)
    assert data.snapshot("RBP") is old  # one background reload at a time
    release.set()
    for _ in range(100):
        if data._snapshots["RBP"][1] is not old and "RBP" not in data._refreshing:
            break
        time.sleep(0.02)
    assert data._snapshots["RBP"][1] is not old
    assert loads == ["RBP"]


def test_very_old_or_missing_snapshot_is_loaded_before_answering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(data, "load_snapshot", lambda store, *a, **k: _snap(store, 0))
    fresh = data.snapshot("CPC")  # none yet
    assert (datetime.now(UTC) - fresh.loaded_at).total_seconds() < 5
    data._snapshots["CPC"] = (time.monotonic() - 1, _snap("CPC", data.MAX_STALE_SECONDS + 60))
    again = data.snapshot("CPC")
    assert (datetime.now(UTC) - again.loaded_at).total_seconds() < 5


def test_recent_reuses_a_read_until_a_write_forgets_it() -> None:
    calls: list[int] = []

    def load() -> int:
        calls.append(1)
        return len(calls)

    assert data.recent(("alarm_rules", "RBP"), load) == 1
    assert data.recent(("alarm_rules", "RBP"), load) == 1
    data.forget_reads("CPC")  # another store's write leaves RBP's read alone
    assert data.recent(("alarm_rules", "RBP"), load) == 1
    data.forget_reads("RBP")
    assert data.recent(("alarm_rules", "RBP"), load) == 2


def test_home_rejects_an_unknown_brand_before_reading() -> None:
    with pytest.raises(service.InputError):
        service.home("nope")
