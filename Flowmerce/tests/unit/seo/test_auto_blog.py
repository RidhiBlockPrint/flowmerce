"""The automatic blog pipeline (services/auto_blog.py) and the AEO/GEO/LLMO checks (services/answer_checks.py).
Owner decisions of 2026-11-20: two blogs a week per brand, written with no person involved, with a publish request a
reviewer must authorize; since 2026-11-24 the blog stays in Flowmerce (never a Shopify draft) until that request is
authorized. No network: Claude is replaced by stand-ins."""
from datetime import date, timedelta

import pytest

from flowmerce.modules.seo.db import all_rows, get, now, run
from flowmerce.modules.seo.integrations import claude
from flowmerce.modules.seo.services import ai_budget, ai_jobs, answer_checks, auto_blog, autopilot, workflow
from tests.fixtures.seo import DRAFT_RESULT, TOPIC_RESULT

IMG = "https://cdn.shopify.com/s/files/ait-tablecloth.jpg"
IMG2 = "https://cdn.shopify.com/s/files/ait-napkins.jpg"

GOOD_BODY = (
    "<p>Ait block print cotton care is simple: wash in cold water at 30 °C, dry in shade and iron on the reverse. "
    "Ridhi Block Print fabrics keep their colour for 5 years or more when cared for this way, and each piece is printed by hand.</p>"
    "<h2>How do you wash ait block print cotton care items?</h2><p>Use a mild detergent and 30 °C water. Wash dark colours apart for the first 2 washes.</p>"
    "<ul><li>Cold water</li><li>Mild soap</li></ul>"
    "<h2>What makes hand block printing different?</h2><p>Each block is carved by hand from teak, and a 90 cm tablecloth needs about 400 impressions. "
    '<a href="/products/ait-tablecloth">Peacock blue tablecloth</a> and <a href="/products/ait-napkins">napkins</a> show it well.</p>'
    "<h2>Which detergents should you avoid?</h2><p>Avoid bleach and optical brighteners.</p>"
    "<h2>Frequently asked questions</h2><h3>Can you tumble dry block print cotton?</h3><p>No, dry it flat in shade.</p>"
    f'<figure><img src="{IMG}" alt="Peacock blue tablecloth"></figure><figure><img src="{IMG2}" alt="Napkins"></figure>'
)
GOOD = {"title": "Ait block print cotton care: the simple guide", "handle": "ait-block-print-cotton-care", "primary_keyword": "ait block print cotton care",
        "meta_title": "Ait block print cotton care guide", "meta_description": "Ait block print cotton care made simple: how to wash, dry and iron hand printed cotton so its colours last for years, step by step.",
        "summary_html": "<p>How to wash and dry hand printed cotton.</p>", "body_html": GOOD_BODY, "tags": "care, cotton, guide",
        "image_url": IMG, "image_alt": "Peacock blue tablecloth", "ai_notes_json": '{"sources": ["02-brand-voice-bible.md"]}'}


def test_a_well_built_article_passes_the_answer_engine_checks():
    r = answer_checks.check(GOOD, "Ridhi Block Print", "ridhiblockprint.com")
    for g in ("aeo", "geo", "llmo"):
        assert r["groups"][g]["score"] == 100, (g, [c for c in r["groups"][g]["checks"] if not c["ok"]])
    assert {c["id"] for c in r["failures"]} == {"length"}            # the sample is short; everything else passes


def test_a_thin_draft_gets_a_revision_request_without_the_points_claude_cannot_fix():
    r = answer_checks.check({**GOOD, "body_html": "<p>Short.</p>", "image_url": "", "ai_notes_json": "{}"}, "Ridhi Block Print")
    ids = {c["id"] for c in r["failures"]}
    assert {"answer-first", "faq", "questions", "images", "image", "sources"} <= ids
    req = answer_checks.revision_request(r)
    assert "FAQ" in req and "Direct answer" in req
    assert "Featured image" not in req and "Sources recorded" not in req   # a person or a later step handles those


@pytest.fixture
def pipe(ai_env, monkeypatch):
    for table in ("claude_usage", "content_schedule", "calendar_events", "app_settings", "auto_blogs"):
        run(f"DELETE FROM {table}")
    run("INSERT OR REPLACE INTO products (brand_id, handle, title, url, image_url, product_type, synced_at, source) VALUES (?,?,?,?,?,?,?,?)",
        "ridhi", "ait-tablecloth", "AIT Peacock Blue Tablecloth", "https://ridhiblockprint.com/products/ait-tablecloth", IMG, "Tablecloth", now(), "test")
    run("DELETE FROM autopilot_runs")
    run("INSERT OR REPLACE INTO products (brand_id, handle, title, url, image_url, product_type, synced_at, source) VALUES (?,?,?,?,?,?,?,?)",
        "ridhi", "ait-napkins", "AIT Sage Napkins", "https://ridhiblockprint.com/products/ait-napkins", IMG2, "Napkins", now(), "test")
    monkeypatch.setattr(claude, "research_topics", lambda *a, **k: (TOPIC_RESULT, "m"))
    monkeypatch.setattr(claude, "generate_draft", lambda *a: ({**DRAFT_RESULT, "image_url": IMG, "notes": {"secondary_keywords": [], "needs_confirmation": [],
                        "recommendations": [], "technical_checks": [], "sources": [], "next_article": "", "image_brief": ""}}, "m"))
    run("""INSERT INTO app_settings (key, value_json, updated_at) VALUES ('auto_blog', '{"enabled": true}', ?)""", now())
    yield ai_env
    for table in ("claude_usage", "content_schedule", "calendar_events", "app_settings", "auto_blogs", "autopilot_runs"):
        run(f"DELETE FROM {table}")
    run("DELETE FROM products WHERE handle IN ('ait-napkins', 'ait-tablecloth')")


def _today():
    return date.fromisoformat(ai_budget.today())


def test_two_slots_a_week_are_kept_planned_for_four_weeks(pipe):
    t = _today()
    added = auto_blog.plan(t)
    days = [r["publish_on"] for r in all_rows("SELECT publish_on FROM auto_blogs WHERE brand_id = 'ridhi' ORDER BY publish_on")]
    assert added == 16 and len(days) == 8                                       # 2 a week x 4 weeks x 2 brands
    assert {date.fromisoformat(d).weekday() for d in days} == {1, 4}           # Tuesday and Friday
    assert auto_blog.plan(t) == 0                                               # nothing moves or doubles


def test_a_slot_starts_five_days_ahead_and_a_late_one_is_marked_missed(pipe, users):
    t = _today()
    run("INSERT INTO auto_blogs (brand_id, publish_on, created_at, updated_at) VALUES ('ridhi', ?, ?, ?)", (t + timedelta(days=9)).isoformat(), now(), now())
    late = run("INSERT INTO auto_blogs (brand_id, publish_on, created_at, updated_at) VALUES ('cpc', ?, ?, ?)", t.isoformat(), now(), now()).last_id
    assert auto_blog.start_due(t) == 0                                          # 9 days away: not yet
    assert get("SELECT status FROM auto_blogs WHERE id = ?", late)["status"] == "missed"
    assert auto_blog.start_due(t + timedelta(days=4)) == 1


def test_a_paused_brand_starts_nothing(pipe, users):
    t = _today()
    run("INSERT INTO auto_blogs (brand_id, publish_on, created_at, updated_at) VALUES ('ridhi', ?, ?, ?)", (t + timedelta(days=3)).isoformat(), now(), now())
    workflow.set_paused(users["admin"], "ridhi", True, "test")
    try:
        assert auto_blog.start_due(t) == 0
    finally:
        workflow.set_paused(users["admin"], "ridhi", False, "")


def test_the_whole_chain_ends_as_a_checked_blog_in_flowmerce_with_a_publish_request_on_the_calendar(pipe, users, monkeypatch):
    t = _today()
    day = (t + timedelta(days=3)).isoformat()
    sid = run("INSERT INTO auto_blogs (brand_id, publish_on, created_at, updated_at) VALUES ('ridhi', ?, ?, ?)", day, now(), now()).last_id
    asked = {}

    def revise(b, v, article, instructions, links):
        asked["instructions"] = instructions
        return ({**{k: article[k] for k in ("title", "handle", "meta_title", "meta_description", "summary_html", "image_url", "image_alt")},
                 "body_html": article["body_html"] + "<h2>Frequently asked questions</h2><h3>Can you machine wash it?</h3><p>Yes, cold.</p>",
                 "tags": ["care", "cotton", "guide"], "notes": {"secondary_keywords": [], "needs_confirmation": [], "recommendations": ["Added an FAQ"],
                 "technical_checks": [], "sources": ["02-brand-voice-bible.md"], "next_article": "", "image_brief": ""}}, "m")

    monkeypatch.setattr(claude, "revise_draft", revise)
    assert auto_blog.start_due(t) == 1
    assert get("SELECT status FROM auto_blogs WHERE id = ?", sid)["status"] == "writing"
    ai_jobs.run_pending(); autopilot.advance_all()                              # topics in, one picked, draft job queued
    ai_jobs.run_pending(); autopilot.advance_all()                              # draft written: images added, checked, sent back once
    r = get("SELECT * FROM autopilot_runs WHERE slot_id = ?", sid)
    assert r["step"] == "revise" and "FAQ" in asked.get("instructions", "FAQ")
    a = get("SELECT * FROM articles WHERE id = ?", r["article_id"])
    assert IMG2 in a["body_html"] and 'alt="AIT Sage Napkins"' in a["body_html"]   # a second product photo inside the body
    ai_jobs.run_pending(); autopilot.advance_all()                              # revision in: approved, kept here, calendar
    slot = get("SELECT * FROM auto_blogs WHERE id = ?", sid)
    a = get("SELECT * FROM articles WHERE id = ?", slot["article_id"])
    assert slot["status"] == "ready" and a["status"] in ("approved", "publish_requested") and not a["shopify_published"]
    assert a["shopify_article_id"] is None                                     # never sent to Shopify as a draft
    assert "FAQ" in asked["instructions"]
    entry = get("SELECT * FROM content_schedule WHERE article_id = ? AND action = 'publish'", a["id"])
    assert entry and entry["run_on"] == day                                     # on the calendar for the slot's day
    assert get("SELECT reviewer_name FROM review_notes WHERE article_id = ? AND kind = 'approved'", a["id"])["reviewer_name"] == "Flowmerce (auto)"
    ov = auto_blog.overview("ridhi")
    mine = next(x for x in ov["slots"] if x["id"] == sid)
    assert mine["checks"]["score"] is not None and ov["counts"]["ready"] >= 1
    assert ov["projection"]["claudeUsdNext4Weeks"] >= 0


def test_a_planned_slot_can_be_cancelled_once(pipe, users):
    t = _today()
    sid = run("INSERT INTO auto_blogs (brand_id, publish_on, created_at, updated_at) VALUES ('cpc', ?, ?, ?)", (t + timedelta(days=12)).isoformat(), now(), now()).last_id
    done = auto_blog.cancel(users["admin"], sid)
    assert done["status"] == "skipped" and done["message"].startswith("Cancelled by")
    with pytest.raises(Exception) as e:
        auto_blog.cancel(users["admin"], sid)
    assert getattr(e.value, "status", 409) == 409


def test_a_slot_being_written_can_be_cancelled_and_claude_stops(pipe, users):
    t = _today()
    sid = run("INSERT INTO auto_blogs (brand_id, publish_on, created_at, updated_at) VALUES ('ridhi', ?, ?, ?)", (t + timedelta(days=3)).isoformat(), now(), now()).last_id
    assert auto_blog.start_due(t) == 1
    slot = get("SELECT * FROM auto_blogs WHERE id = ?", sid)
    r = get("SELECT * FROM autopilot_runs WHERE id = ?", slot["run_id"])
    assert slot["status"] == "writing" and r["status"] == "running"
    done = auto_blog.cancel(users["admin"], sid)
    assert done["status"] == "skipped" and "Stopped by" in done["message"]
    assert get("SELECT status FROM autopilot_runs WHERE id = ?", r["id"])["status"] == "failed"
    assert get("SELECT status FROM ai_jobs WHERE id = ?", r["research_job_id"])["status"] == "cancelled"
    ai_jobs.run_pending(); autopilot.advance_all()
    assert get("SELECT status FROM auto_blogs WHERE id = ?", sid)["status"] == "skipped"   # nothing writes it after all


def test_the_pipeline_is_off_until_switched_on_and_then_only_plans(pipe, users):
    run("DELETE FROM app_settings WHERE key = 'auto_blog'")
    assert auto_blog.settings()["enabled"] is False                            # off by default: one copy is switched on on purpose
    t = _today()
    assert auto_blog.plan(t) > 0                                                # the calendar still shows the slots
    assert auto_blog.start_due(t + timedelta(days=1)) == 0                      # but nothing is written
    assert auto_blog.update_settings(users["admin"], {"enabled": True})["enabled"] is True
    with pytest.raises(Exception):
        auto_blog.update_settings(users["admin"], {"weekdays": [9]})


# ---------------------------------------------------------------- a topic a person puts on the calendar (2026-11-24)

def test_a_topic_put_on_the_calendar_is_written_and_put_forward_for_its_day(pipe, users, monkeypatch):
    """Owner request 2026-11-24: add a topic to a day; Flowmerce drafts, checks and approves it, and makes a publish request
    for that day that waits for one click from a reviewer. It runs even while the automatic weekday blogs are off."""
    monkeypatch.setattr(claude, "revise_draft", lambda *a: (_ for _ in ()).throw(AssertionError("not needed")))
    auto_blog.update_settings(users["admin"], {"enabled": False})
    t = _today()
    day = (t + timedelta(days=12)).isoformat()
    slot = auto_blog.schedule_topic(users["admin"], {"brand": "ridhi", "publish_on": day, "title": "AIT How to wash a block print quilt",
                                                     "keyword": "ait wash block print quilt"})
    assert slot["status"] == "planned" and slot["scheduled_topic"] and slot["topic_title"] == "AIT How to wash a block print quilt"
    topic = get("SELECT * FROM topics WHERE id = ?", slot["topic_id"])
    assert topic["status"] == "approved"                                         # putting it on the calendar approves it
    assert auto_blog.start_due(t) == 0                                           # 12 days away: written 5 days before
    assert auto_blog.start_due(t + timedelta(days=8)) == 1                       # inside the lead time: Claude writes it
    s = get("SELECT * FROM auto_blogs WHERE id = ?", slot["id"])
    r = get("SELECT * FROM autopilot_runs WHERE id = ?", s["run_id"])
    assert s["status"] == "writing" and r["topic_id"] == topic["id"] and r["slot_id"] == s["id"] and r["step"] == "draft"
    for _ in range(3):
        ai_jobs.run_pending(); autopilot.advance_all()
    s = get("SELECT * FROM auto_blogs WHERE id = ?", slot["id"])
    a = get("SELECT * FROM articles WHERE id = ?", s["article_id"])
    assert s["status"] == "ready" and a["topic_id"] == topic["id"] and a["status"] == "approved" and a["shopify_article_id"] is None
    entry = get("SELECT * FROM content_schedule WHERE article_id = ? AND action = 'publish'", a["id"])
    assert entry and entry["run_on"] == day                                      # the publish request is made for that day
    assert not get("SELECT 1 FROM publish_requests WHERE article_id = ? AND status = 'executed'", a["id"])   # nothing went live


def test_a_scheduled_topic_needs_a_free_future_day_and_is_scheduled_once(pipe, users):
    t = _today()
    with pytest.raises(Exception) as e:
        auto_blog.schedule_topic(users["admin"], {"brand": "cpc", "publish_on": t.isoformat(), "title": "AIT Too soon a topic"})
    assert getattr(e.value, "status", 0) == 400
    day = (t + timedelta(days=20)).isoformat()
    first = auto_blog.schedule_topic(users["admin"], {"brand": "cpc", "publish_on": day, "title": "AIT Napkin rings for a long table"})
    with pytest.raises(Exception) as e:                                          # the same topic again, on another day
        auto_blog.schedule_topic(users["admin"], {"brand": "cpc", "publish_on": (t + timedelta(days=21)).isoformat(), "topic_id": first["topic_id"]})
    assert getattr(e.value, "code", "") == "already_scheduled"
    with pytest.raises(Exception) as e:                                          # another topic on a day that has one
        auto_blog.schedule_topic(users["admin"], {"brand": "cpc", "publish_on": day, "title": "AIT A different topic for that day"})
    assert getattr(e.value, "code", "") == "day_taken"
    auto_blog.cancel(users["admin"], first["id"])                                # cancelled: the day is free again
    again = auto_blog.schedule_topic(users["admin"], {"brand": "cpc", "publish_on": day, "title": "AIT A different topic for that day"})
    assert again["id"] == first["id"] and again["status"] == "planned" and again["topic_title"] == "AIT A different topic for that day"


def test_an_automatic_slot_becomes_the_scheduled_topics_day_and_a_paused_brand_waits(pipe, users):
    t = _today()
    auto_blog.plan(t)
    auto_day = get("SELECT publish_on FROM auto_blogs WHERE brand_id = 'ridhi' AND topic_id IS NULL ORDER BY publish_on DESC LIMIT 1")["publish_on"]
    slot = auto_blog.schedule_topic(users["admin"], {"brand": "ridhi", "publish_on": auto_day, "title": "AIT Kantha throws explained"})
    assert get("SELECT COUNT(*) n FROM auto_blogs WHERE brand_id = 'ridhi' AND publish_on = ?", auto_day)["n"] == 1
    assert slot["scheduled_topic"]
    workflow.set_paused(users["admin"], "ridhi", True, "test")
    try:
        auto_blog.start_due(date.fromisoformat(auto_day) - timedelta(days=2))
        assert get("SELECT status FROM auto_blogs WHERE id = ?", slot["id"])["status"] == "planned"   # waits while paused
    finally:
        workflow.set_paused(users["admin"], "ridhi", False, "")


def test_a_topic_written_by_hand_meanwhile_is_put_forward_instead_of_written_again(pipe, users):
    t = _today()
    slot = auto_blog.schedule_topic(users["admin"], {"brand": "ridhi", "publish_on": (t + timedelta(days=15)).isoformat(), "title": "AIT Table runner lengths"})
    from flowmerce.modules.seo.services import articles
    a = articles.create_article(users["admin"], "ridhi", {"title": "AIT Table runner lengths", "primary_keyword": "ait table runner lengths",
                                                         "topic_id": slot["topic_id"], "body_html": "<p>Body</p>"}, "app", "draft")
    assert auto_blog.start_due(t + timedelta(days=11)) == 0                      # nothing for Claude to write
    s = get("SELECT * FROM auto_blogs WHERE id = ?", slot["id"])
    assert s["status"] == "ready" and s["article_id"] == a["id"] and s["run_id"] is None
    assert get("SELECT run_on FROM content_schedule WHERE article_id = ? AND action = 'publish'", a["id"])["run_on"] == slot["publish_on"]
