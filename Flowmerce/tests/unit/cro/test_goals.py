"""The monthly revenue goal on the CRO Overview (modules/cro/goals.py, GET/PUT /api/cro/goal)."""

from __future__ import annotations

from typing import Any

import pytest
from tests.fixtures.seo import local_client

from flowmerce.modules.cro import goals
from flowmerce.modules.seo.db import get, run
from flowmerce.modules.seo.util import HttpError

HEADERS = {"X-Requested-With": "blog-ops"}


@pytest.fixture(autouse=True)
def _clean() -> Any:
    run("DELETE FROM app_settings WHERE key LIKE 'cro_goal:%'")
    yield
    run("DELETE FROM app_settings WHERE key LIKE 'cro_goal:%'")


def test_no_goal_is_zero_and_a_goal_is_kept_per_store(users: dict[str, Any]) -> None:
    assert goals.goal("ridhi")["monthly_revenue"] == 0
    goals.set_goal("ridhi", {"monthly_revenue": "190000"}, users["admin"])
    assert goals.goal("ridhi")["monthly_revenue"] == 190000
    assert goals.goal("cpc")["monthly_revenue"] == 0
    assert get("SELECT 1 FROM audit_log WHERE action = 'cro.goal' AND brand_id = 'ridhi'")


def test_a_bad_goal_is_refused(users: dict[str, Any]) -> None:
    for bad in ("lots", -1, 10**12, None):
        with pytest.raises(HttpError):
            goals.set_goal("ridhi", {"monthly_revenue": bad}, users["admin"])


def test_the_routes_read_and_write_it() -> None:
    from flowmerce.modules.seo.app import create_app

    c = local_client(create_app())
    r = c.put("/api/cro/goal?brand=cpc", json={"monthly_revenue": 80000}, headers=HEADERS)
    assert r.status_code == 200, r.text
    assert c.get("/api/cro/goal?brand=cpc").json()["monthly_revenue"] == 80000
    assert c.get("/api/cro/goal?brand=nope").status_code == 400
