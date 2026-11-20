"""The automatic blog pipeline (services/auto_blog.py) and the AEO/GEO/LLMO checks (services/answer_checks.py).
Owner decisions of 2026-11-20: two blogs a week per brand, written with no person involved, kept as HIDDEN Shopify drafts
with a publish request a reviewer must authorize. No network: Claude is replaced by stand-ins."""
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
    monkeypatch.setattr(autopilot.shopify, "configured", lambda b: False)
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


def test_the_whole_chain_ends_as_a_checked_hidden_draft_with_a_publish_request_on_the_calendar(pipe, users, monkeypatch):
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
    ai_jobs.run_pending(); autopilot.advance_all()                              # revision in: approved, hidden draft, calendar
    slot = get("SELECT * FROM auto_blogs WHERE id = ?", sid)
    a = get("SELECT * FROM articles WHERE id = ?", slot["article_id"])
    assert slot["status"] == "ready" and a["status"] in ("approved", "publish_requested") and not a["shopify_published"]
    assert "FAQ" in asked["instructions"]
    entry = get("SELECT * FROM content_schedule WHERE article_id = ? AND action = 'publish'", a["id"])
    assert entry and entry["run_on"] == day                                     # on the calendar for the slot's day
    assert get("SELECT reviewer_name FROM review_notes WHERE article_id = ? AND kind = 'approved'", a["id"])["reviewer_name"] == "Flowmerce (auto)"
    ov = auto_blog.overview("ridhi")
    mine = next(x for x in ov["slots"] if x["id"] == sid)
    assert mine["checks"]["score"] is not None and ov["counts"]["ready"] >= 1
    assert ov["projection"]["claudeUsdNext4Weeks"] >= 0


def test_a_slot_can_be_skipped_only_before_it_starts(pipe, users):
    t = _today()
    sid = run("INSERT INTO auto_blogs (brand_id, publish_on, created_at, updated_at) VALUES ('cpc', ?, ?, ?)", (t + timedelta(days=12)).isoformat(), now(), now()).last_id
    assert auto_blog.skip(users["admin"], sid)["status"] == "skipped"
    with pytest.raises(Exception) as e:
        auto_blog.skip(users["admin"], sid)
    assert getattr(e.value, "status", 409) == 409


def test_the_pipeline_is_off_until_switched_on_and_then_only_plans(pipe, users):
    run("DELETE FROM app_settings WHERE key = 'auto_blog'")
    assert auto_blog.settings()["enabled"] is False                            # off by default: one copy is switched on on purpose
    t = _today()
    assert auto_blog.plan(t) > 0                                                # the calendar still shows the slots
    assert auto_blog.start_due(t + timedelta(days=1)) == 0                      # but nothing is written
    assert auto_blog.update_settings(users["admin"], {"enabled": True})["enabled"] is True
    with pytest.raises(Exception):
        auto_blog.update_settings(users["admin"], {"weekdays": [9]})
