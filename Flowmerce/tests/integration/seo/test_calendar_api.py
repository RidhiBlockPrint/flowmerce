"""GET /api/calendar for any month and year (owner request 2026-11-24: a full calendar you can move through, seeing
each month's events and blogs, and scheduling there). Local operator mode: a loopback client acts as the admin."""
from datetime import date, timedelta

import pytest

from flowmerce.modules.seo.app import create_app
from flowmerce.modules.seo.db import run
from flowmerce.modules.seo.services import ai_budget, auto_blog
from tests.fixtures.seo import local_client


@pytest.fixture(scope="module")
def app():
    return create_app()


@pytest.fixture
def clean():
    yield
    run("DELETE FROM auto_blogs WHERE topic_id IN (SELECT id FROM topics WHERE title LIKE 'CALAPI %')")
    run("DELETE FROM topics WHERE title LIKE 'CALAPI %'")


def test_a_month_next_year_shows_its_events_and_the_blog_scheduled_in_it(app, users, clean):
    today = date.fromisoformat(ai_budget.today())
    day = date(today.year + 1, 3, 10).isoformat()
    slot = auto_blog.schedule_topic(users["admin"], {"brand": "cpc", "publish_on": day, "title": "CALAPI Spring table linens"})
    c = local_client(app)
    r = c.get(f"/api/calendar?brand=cpc&from={today.year + 1}-02-23&to={today.year + 1}-04-05")
    assert r.status_code == 200
    d = r.json()
    assert any(s["id"] == slot["id"] and s["topic_title"] == "CALAPI Spring table linens" for s in d["slots"])
    assert any(e["name"] == "Spring begins" for e in d["events"])           # built-in events exist for any year
    assert d["today"] == today.isoformat()


def test_a_range_too_long_is_refused(app):
    c = local_client(app)
    start = date.fromisoformat(ai_budget.today())
    assert c.get(f"/api/calendar?from={start}&to={start + timedelta(days=500)}").status_code == 400
