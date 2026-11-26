"""Brand knowledge, SEO-complete drafts with Claude's notes, revisions, the daily Claude limit and the content calendar."""
import json
from datetime import date

import pytest

from flowmerce.modules.seo.db import all_rows, get, now, run
from flowmerce.modules.seo.integrations import claude
from flowmerce.modules.seo.services import ai_budget, ai_jobs, ai_results, calendar_plan
from flowmerce.modules.seo.services.brands import brand, brand_settings, update_brand_settings
from flowmerce.modules.seo.services.knowledge import brand_knowledge, knowledge_files
from tests.fixtures.seo import DRAFT_RESULT, make_topic

IMG = "https://cdn.shopify.com/s/files/ait-tablecloth.jpg"
PRODUCT_URL = "https://ridhiblockprint.com/products/ait-tablecloth"


@pytest.fixture
def blog_env(ai_env):
    """The AI test environment plus one synced product and empty usage, calendar and schedule tables."""
    run("DELETE FROM claude_usage")
    run("DELETE FROM content_schedule")
    run("DELETE FROM calendar_events")
    run("DELETE FROM app_settings")
    run("INSERT OR REPLACE INTO products (brand_id, handle, title, url, image_url, product_type, synced_at, source) VALUES (?,?,?,?,?,?,?,?)",
        "ridhi", "ait-tablecloth", "AIT Peacock Blue Tablecloth", PRODUCT_URL, IMG, "Tablecloth", now(), "test")
    yield ai_env
    run("DELETE FROM claude_usage")
    run("DELETE FROM content_schedule")
    run("DELETE FROM calendar_events")
    run("DELETE FROM app_settings")
    run("DELETE FROM products WHERE handle = 'ait-tablecloth'")


def _draft(**extra):
    return {**DRAFT_RESULT, "image_url": "", "notes": {"secondary_keywords": ["block print"], "needs_confirmation": [], "recommendations": ["Add a photo"],
                                                       "technical_checks": [], "sources": ["02-brand-voice-bible.md"], "next_article": "Napkin care", "image_brief": ""},
            **extra}


# ---------------- knowledge and the prompt ----------------

def test_brand_documents_are_sent_and_the_readme_is_not(tmp_path, monkeypatch):
    # The real guides are internal and git-ignored (the repository is public), so stand-in files are used here.
    from flowmerce.modules.seo.services import knowledge
    (tmp_path / "README.md").write_text("# Brand knowledge for Claude", encoding="utf-8")
    for bid, phrase in (("cpc", "Cotton Print Club: Brand Voice Guide"), ("ridhi", "Brand Voice Bible")):
        (tmp_path / bid).mkdir()
        (tmp_path / bid / "01-voice.md").write_text(f"# {phrase}\nWrite warmly.", encoding="utf-8")
        (tmp_path / bid / "README.md").write_text("# Brand knowledge for Claude", encoding="utf-8")
        (tmp_path / bid / "notes.docx").write_text("not sent", encoding="utf-8")
    monkeypatch.setattr(knowledge, "KNOWLEDGE_DIR", tmp_path)
    brand_knowledge.cache_clear()
    try:
        for bid, phrase in (("cpc", "Cotton Print Club: Brand Voice Guide"), ("ridhi", "Brand Voice Bible")):
            text = brand_knowledge(bid)
            assert phrase in text and '<document name="01-voice.md">' in text
            assert "Brand knowledge for Claude" not in text and "not sent" not in text
            assert [f["name"] for f in knowledge_files(bid)] == ["01-voice.md"]
        assert brand_knowledge("nobody") == ""
    finally:
        brand_knowledge.cache_clear()


def test_documents_are_cached_and_standing_instructions_come_after_the_cache_point(blog_env, tmp_path, monkeypatch):
    from flowmerce.modules.seo.services import knowledge
    (tmp_path / "ridhi").mkdir()                 # stand-in guide: the real ones are internal and git-ignored
    (tmp_path / "ridhi" / "02-brand-voice-bible.md").write_text("# Brand Voice Bible\nWarm and exact.", encoding="utf-8")
    monkeypatch.setattr(knowledge, "KNOWLEDGE_DIR", tmp_path)
    brand_knowledge.cache_clear()
    update_brand_settings("ridhi", {"claudeInstructions": "Always link the care guide."}, 1)
    try:
        blocks = claude._brand_system(brand("ridhi"), brand_settings("ridhi"))
        assert blocks[0]["cache_control"] == {"type": "ephemeral"} and "Brand Voice Bible" in blocks[0]["text"]
        assert "Always link the care guide." in blocks[1]["text"] and "cache_control" not in blocks[1]
        assert "Always link the care guide." not in blocks[0]["text"]          # editing it never invalidates the cached documents
    finally:
        update_brand_settings("ridhi", {"claudeInstructions": ""}, 1)
        brand_knowledge.cache_clear()


def test_the_draft_prompt_carries_the_seo_rules_and_product_images(blog_env, monkeypatch):
    seen = {}
    monkeypatch.setattr(claude, "_structured", lambda system, prompt, schema, effort, **k: seen.update(prompt=prompt, schema=schema) or ({}, "m"))
    claude.generate_draft(brand("ridhi"), brand_settings("ridhi"), {"title": "T", "primary_keyword": "k", "intent": "informational"},
                          [{"title": "AIT Peacock Blue Tablecloth", "url": PRODUCT_URL, "image_url": IMG, "kind": "product"}])
    assert "120-160 characters" in seen["prompt"] and "at least 2 internal links" in seen["prompt"] and IMG in seen["prompt"]
    assert set(seen["schema"]["required"]) >= {"image_url", "notes"}


# ---------------- drafts with notes ----------------

def test_a_draft_saves_claudes_notes_and_keeps_a_real_product_image(blog_env, monkeypatch):
    tid = make_topic()
    monkeypatch.setattr(claude, "generate_draft", lambda *a: (_draft(image_url=IMG, image_alt="Peacock blue tablecloth"), "m"))
    job, _ = ai_jobs.create_job(None, "ridhi", "content_generation", {"topic_id": tid})
    ai_jobs.run_pending()
    a = get("SELECT * FROM articles WHERE topic_id = ?", tid)
    notes = json.loads(a["ai_notes_json"])
    assert a["image_url"] == IMG and notes["recommendations"] == ["Add a photo"] and notes["jobId"] == job["id"]


def test_an_invented_image_is_removed_and_an_unknown_link_is_flagged(blog_env):
    body = DRAFT_RESULT["body_html"] + f'<p><a href="/collections/made-up">x</a> <a href="{PRODUCT_URL}">y</a></p><img src="https://evil.example/x.jpg" alt="x">'
    out = ai_results.check_against_store("ridhi", ai_results.validate("content_generation", _draft(image_url="https://example.com/x.jpg", body_html=body)))
    assert out["image_url"] == "" and "evil.example" not in out["body_html"]
    flagged = " ".join(out["notes"]["needs_confirmation"])
    assert "/collections/made-up" in flagged and PRODUCT_URL not in flagged and "featured image" in flagged


def test_a_result_without_notes_is_still_accepted():   # an external worker that predates notes keeps working
    assert ai_results.validate("content_generation", DRAFT_RESULT)["notes"] == {}


# ---------------- revisions ----------------

def test_a_revision_becomes_the_next_version_and_records_what_was_asked(blog_env, monkeypatch):
    tid = make_topic()
    monkeypatch.setattr(claude, "generate_draft", lambda *a: (_draft(), "m"))
    ai_jobs.create_job(None, "ridhi", "content_generation", {"topic_id": tid})
    ai_jobs.run_pending()
    a = get("SELECT * FROM articles WHERE topic_id = ?", tid)
    seen = {}

    def revise(b, st, article, instructions, links):
        seen.update(article=article, instructions=instructions)
        return _draft(title="AIT A shorter guide to hand block printing"), "m"
    monkeypatch.setattr(claude, "revise_draft", revise)
    ai_jobs.create_job(None, "ridhi", "content_revision", {"article_id": a["id"], "base_version": a["version"], "instructions": "Make the title shorter"})
    ai_jobs.run_pending()
    b = get("SELECT * FROM articles WHERE id = ?", a["id"])
    assert b["version"] == a["version"] + 1 and b["title"] == "AIT A shorter guide to hand block printing"
    assert seen["instructions"] == "Make the title shorter" and seen["article"]["title"] == a["title"]
    assert json.loads(b["ai_notes_json"])["revision"] == "Make the title shorter"
    assert get("SELECT note FROM article_revisions WHERE article_id = ? AND version = ?", a["id"], b["version"])["note"].startswith("Revised by Claude")


def test_a_revision_of_an_outdated_version_is_refused(blog_env, monkeypatch):
    tid = make_topic()
    monkeypatch.setattr(claude, "generate_draft", lambda *a: (_draft(), "m"))
    ai_jobs.create_job(None, "ridhi", "content_generation", {"topic_id": tid})
    ai_jobs.run_pending()
    a = get("SELECT * FROM articles WHERE topic_id = ?", tid)
    with pytest.raises(Exception) as e:
        ai_jobs.create_job(None, "ridhi", "content_revision", {"article_id": a["id"], "base_version": a["version"] - 1 or 99, "instructions": "x"})
    assert getattr(e.value, "code", "") == "version_conflict"


# ---------------- the daily limit ----------------

def test_cost_follows_list_prices():
    usage = {"model": "claude-opus-5-5", "inputTokens": 1_000_000, "outputTokens": 100_000, "cacheWriteTokens": 0, "cacheReadTokens": 1_000_000}
    assert ai_budget.cost_usd(usage) == pytest.approx(4.0 + 2.0 + 0.20)
    assert ai_budget.cost_usd({**usage, "model": "unknown-model"}) == pytest.approx(6.2)   # priced like the default, never lower


def test_the_daily_limit_is_the_monthly_budget_spread_over_the_month(blog_env):
    ai_budget.update_settings({"monthlyBudgetUsd": 31}, 1)
    st = ai_budget.status()
    assert st["dailyLimitUsd"] == pytest.approx(31 / st["daysInMonth"], abs=1e-3) and st["todayUsd"] == 0


def test_a_job_is_refused_when_it_would_pass_todays_limit(blog_env):
    ai_budget.update_settings({"monthlyBudgetUsd": 30}, 1)
    ai_budget.record({"model": "claude-opus-5-5", "inputTokens": 0, "outputTokens": 45_000}, "ridhi", "content_generation")   # $0.90 spent
    with pytest.raises(Exception) as e:
        ai_jobs.create_job(None, "ridhi", "topic_research")
    assert getattr(e.value, "code", "") == "daily_limit"


def test_a_queued_job_waits_for_tomorrow_without_using_a_retry(blog_env, monkeypatch):
    calls = []
    monkeypatch.setattr(claude, "research_topics", lambda *a, **k: calls.append(1))
    job, _ = ai_jobs.create_job(None, "ridhi", "topic_research")
    ai_budget.record({"model": "claude-opus-5-5", "outputTokens": 200_000}, "ridhi", "assist")   # the limit is used up after it was queued
    ai_jobs.run_pending()
    j = get("SELECT * FROM ai_jobs WHERE id = ?", job["id"])
    assert calls == [] and j["status"] == "pending" and j["retry_count"] == 0 and j["next_attempt_at"]


# ---------------- the calendar ----------------

def test_builtin_event_dates():
    ev = {e["name"]: e for e in calendar_plan.builtin_events(2026)}
    assert ev["Thanksgiving"]["date"] == "2026-11-26" and ev["Black Friday"]["date"] == "2026-11-27"
    assert ev["Easter"]["date"] == "2026-04-05" and ev["Mother's Day"]["date"] == "2026-05-10" and ev["Memorial Day"]["date"] == "2026-05-25"
    assert ev["Labor Day"]["date"] == "2026-09-07" and ev["Christmas"]["publish_by"] == "2026-11-05"
    assert "Diwali" not in {e["name"] for e in calendar_plan.builtin_events(2031)}   # unknown moon dates are left out, not guessed


def test_a_suggested_plan_puts_at_most_one_claude_task_on_a_day(blog_env, users):
    made = calendar_plan.suggest_plan(users["admin"], "ridhi", days=120)
    days = [m["run_on"] for m in made]
    assert made and len(days) == len(set(days)) and all(d >= ai_budget.today() for d in days)
    assert calendar_plan.suggest_plan(users["admin"], "ridhi", days=120) == []          # events that are planned are not planned twice


def test_a_due_research_entry_starts_a_job_and_waits_when_the_limit_is_used(blog_env, users):
    e = calendar_plan.add_entry(users["admin"], {"brand": "ridhi", "action": "research", "run_on": ai_budget.today(), "focus": "AIT winter quilts"})
    ai_budget.record({"model": "claude-opus-5-5", "outputTokens": 200_000}, "ridhi", "assist")
    calendar_plan.run_due()
    assert get("SELECT * FROM content_schedule WHERE id = ?", e["id"])["status"] == "planned"   # waits for tomorrow's limit
    run("DELETE FROM claude_usage")
    assert calendar_plan.run_due() == 1
    row = get("SELECT * FROM content_schedule WHERE id = ?", e["id"])
    job = get("SELECT * FROM ai_jobs WHERE id = ?", row["job_id"])
    assert row["status"] == "done" and job["task_type"] == "topic_research" and "AIT winter quilts" in job["input_json"]


def test_a_publish_entry_waits_for_approval(blog_env, users, monkeypatch):
    tid = make_topic()
    monkeypatch.setattr(claude, "generate_draft", lambda *a: (_draft(), "m"))
    ai_jobs.create_job(None, "ridhi", "content_generation", {"topic_id": tid})
    ai_jobs.run_pending()
    a = get("SELECT * FROM articles WHERE topic_id = ?", tid)
    later = date.fromordinal(date.fromisoformat(ai_budget.today()).toordinal() + 10).isoformat()
    e = calendar_plan.add_entry(users["admin"], {"brand": "ridhi", "action": "publish", "run_on": later, "article_id": a["id"]})
    calendar_plan.run_due()
    row = get("SELECT * FROM content_schedule WHERE id = ?", e["id"])
    assert row["status"] == "planned" and "approval" in row["message"]
    assert not all_rows("SELECT id FROM publish_requests WHERE article_id = ?", a["id"])


def test_topic_research_is_told_about_upcoming_events(blog_env, monkeypatch):
    seen = {}
    monkeypatch.setattr(claude, "research_topics", lambda *a, **k: seen.update(k) or ({"topics": []}, "m"))
    ai_jobs.create_job(None, "ridhi", "topic_research")
    ai_jobs.run_pending()
    assert seen["events"] and all({"date", "name", "publish_by"} <= set(e) for e in seen["events"])


def test_an_event_that_is_too_close_to_plan_does_not_take_a_day(blog_env, users, monkeypatch):
    monkeypatch.setattr(ai_budget, "today", lambda: "2026-11-19")
    calendar_plan.add_event(users["admin"], {"brand": "ridhi", "name": "AIT flash sale", "date": "2026-11-24", "lead_days": 3})   # publish by the 21st: too close
    calendar_plan.add_event(users["admin"], {"brand": "ridhi", "name": "AIT launch", "date": "2026-12-09", "lead_days": 20})     # publish by Nov 19
    made = calendar_plan.suggest_plan(users["admin"], "ridhi", days=25)
    names = {m["event_name"] for m in made}
    assert "AIT flash sale" not in names and "AIT launch" not in names   # too late: no three-day research-to-draft gap fits
    # Those skipped events (and Winter begins, also too late) come before New Year's Eve, whose article is due Dec 1.
    # They must not have reserved a day, so New Year's Eve research gets today.
    nye = sorted(m["run_on"] for m in made if m["event_name"] == "New Year's Eve")
    assert nye == ["2026-11-19", "2026-11-22"]


def test_the_budget_is_90_dollars_and_cannot_be_set_higher(blog_env):
    assert ai_budget.settings()["monthlyBudgetUsd"] == 90
    with pytest.raises(Exception) as e:
        ai_budget.update_settings({"monthlyBudgetUsd": 91}, 1)
    assert "$90" in str(getattr(e.value, "message", e.value))
    assert ai_budget.update_settings({"monthlyBudgetUsd": 45}, 1)["monthlyBudgetUsd"] == 45


def test_a_warning_appears_when_the_limit_is_nearly_used(blog_env):
    ai_budget.update_settings({"monthlyBudgetUsd": 90}, 1)
    daily = ai_budget.status()["dailyLimitUsd"]
    assert ai_budget.status()["warning"] is None
    ai_budget.record({"model": "claude-opus-5-5", "outputTokens": int(daily * 0.85 / 20 * 1_000_000)}, "ridhi", "content_generation")
    w = ai_budget.status()["warning"]
    assert w["level"] == "warn" and w["scope"] == "day" and "almost used" in w["message"]
    ai_budget.record({"model": "claude-opus-5-5", "outputTokens": int(daily * 0.15 / 20 * 1_000_000)}, "ridhi", "content_generation")
    assert ai_budget.status()["warning"]["level"] == "crit"


def test_a_month_warning_appears_near_the_end_of_the_budget(blog_env):
    ai_budget.update_settings({"monthlyBudgetUsd": 90}, 1)
    first = ai_budget.today()[:8] + "01"
    if first == ai_budget.today():
        pytest.skip("on the 1st of the month every spend is today's")
    run("INSERT INTO claude_usage (ts, day, brand_id, kind, model, cost_usd) VALUES (?,?,?,?,?,?)", now(), first, "ridhi", "assist", "claude-opus-5-5", 75.0)
    w = ai_budget.status()["warning"]
    assert w["scope"] == "month" and "$75.00 of $90.00" in w["message"]


# ---------------- Write a blog (autopilot) and the 6-hour rule ----------------

@pytest.fixture
def auto_env(blog_env, monkeypatch):
    from tests.fixtures.seo import TOPIC_RESULT
    run("DELETE FROM autopilot_runs")
    monkeypatch.setattr(claude, "research_topics", lambda *a, **k: (TOPIC_RESULT, "m"))
    monkeypatch.setattr(claude, "generate_draft", lambda *a: (_draft(image_url=IMG, image_alt="Peacock blue tablecloth"), "m"))
    yield blog_env
    run("DELETE FROM autopilot_runs")


def test_write_a_blog_runs_to_an_approved_draft_without_stopping(auto_env, users, monkeypatch):
    from flowmerce.modules.seo.services import autopilot
    r = autopilot.start(users["admin"], "ridhi")
    assert r["step"] == "research" and r["status"] == "running"
    ai_jobs.run_pending(); autopilot.advance_all()          # topics in, one picked and approved, draft job queued
    r = autopilot.get_run(r["id"])
    assert r["step"] == "draft" and get("SELECT status FROM topics WHERE id = ?", r["topic_id"])["status"] == "approved"
    ai_jobs.run_pending(); autopilot.advance_all()          # draft written and approved; it stays in Flowmerce
    r = autopilot.get_run(r["id"])
    a = get("SELECT * FROM articles WHERE id = ?", r["article_id"])
    assert r["status"] == "done" and a["status"] == "approved" and a["approved_hash"] == a["content_hash"] and not a["shopify_published"]
    assert a["shopify_article_id"] is None and r["message"] == autopilot.KEPT
    note = get("SELECT * FROM review_notes WHERE article_id = ? AND kind = 'approved'", a["id"])
    assert note["reviewer_name"] == "Flowmerce (auto)" and note["note"].startswith("Auto-approved by Flowmerce")
    assert get("SELECT 1 FROM audit_log WHERE action = 'article.auto_approve' AND entity_id = ?", str(a["id"]))


def test_only_one_blog_at_a_time_per_brand_and_within_the_limit(auto_env, users):
    from flowmerce.modules.seo.services import autopilot
    autopilot.start(users["admin"], "ridhi")
    with pytest.raises(Exception) as e:
        autopilot.start(users["admin"], "ridhi")
    assert getattr(e.value, "code", "") == "already_running"
    ai_budget.record({"model": "claude-opus-5-5", "outputTokens": 100_000}, "cpc", "assist")   # $2 of $3 spent: a blog needs ~$1.20
    with pytest.raises(Exception) as e:
        autopilot.start(users["admin"], "cpc")
    assert getattr(e.value, "code", "") == "daily_limit"


def test_a_failed_claude_job_fails_the_run(auto_env, users, monkeypatch):
    from flowmerce.modules.seo.services import autopilot
    monkeypatch.setattr(claude, "research_topics", lambda *a, **k: (_ for _ in ()).throw(claude.ClaudeError("auth", "auth")))
    r = autopilot.start(users["admin"], "ridhi")
    ai_jobs.run_pending(); autopilot.advance_all()
    r = autopilot.get_run(r["id"])
    assert r["status"] == "failed" and "failed" in r["message"]


def _scheduled_draft(users, monkeypatch, run_on):
    tid = make_topic()
    monkeypatch.setattr(claude, "generate_draft", lambda *a: (_draft(), "m"))
    ai_jobs.create_job(None, "ridhi", "content_generation", {"topic_id": tid})
    ai_jobs.run_pending()
    a = get("SELECT * FROM articles WHERE topic_id = ?", tid)
    e = calendar_plan.add_entry(users["admin"], {"brand": "ridhi", "action": "publish", "run_on": run_on, "article_id": a["id"]})
    return a, e


def test_the_six_hour_rule_approves_and_keeps_it_hidden(blog_env, users, monkeypatch):
    from datetime import datetime, timedelta
    from flowmerce.modules.seo.services import autopilot
    day = date.fromordinal(date.fromisoformat(ai_budget.today()).toordinal() + 3).isoformat()
    a, e = _scheduled_draft(users, monkeypatch, day)
    at = datetime.fromisoformat(calendar_plan._publish_at(day).replace("Z", "+00:00"))
    assert autopilot.enforce_deadlines(at - timedelta(hours=7)) == 0                       # still time for a person
    assert get("SELECT status FROM articles WHERE id = ?", a["id"])["status"] == "draft"
    assert autopilot.enforce_deadlines(at - timedelta(hours=5)) == 1                       # inside the last 6 hours
    b = get("SELECT * FROM articles WHERE id = ?", a["id"])
    assert b["status"] == "approved" and not b["shopify_published"]
    assert "Publishing still needs a reviewer" in get("SELECT message FROM content_schedule WHERE id = ?", e["id"])["message"]
    assert not all_rows("SELECT id FROM publish_requests WHERE article_id = ? AND status = 'published'", a["id"])


def test_the_six_hour_rule_never_overrides_a_reviewers_request_for_changes(blog_env, users, monkeypatch):
    from datetime import datetime, timedelta
    from flowmerce.modules.seo.services import autopilot
    day = date.fromordinal(date.fromisoformat(ai_budget.today()).toordinal() + 3).isoformat()
    a, _ = _scheduled_draft(users, monkeypatch, day)
    run("UPDATE articles SET status = 'changes_requested' WHERE id = ?", a["id"])
    at = datetime.fromisoformat(calendar_plan._publish_at(day).replace("Z", "+00:00"))
    assert autopilot.enforce_deadlines(at - timedelta(hours=1)) == 0
    assert get("SELECT status FROM articles WHERE id = ?", a["id"])["status"] == "changes_requested"


def test_a_calendar_drafting_task_approves_the_events_topic_and_runs_the_chain(auto_env, users):
    from flowmerce.modules.seo.services import autopilot
    tid = make_topic(status="proposed", title="AIT Christmas napkin folds", keyword="ait christmas napkin folds")
    christmas = next(e for e in calendar_plan.upcoming("ridhi", 400) if e["name"] == "Christmas")
    run("""INSERT INTO content_schedule (brand_id, action, run_on, event_key, event_name, status, created_by, created_at, updated_at)
           VALUES ('ridhi','draft',?,?,?,'planned',?,?,?)""", ai_budget.today(), christmas["key"], "Christmas", users["admin"]["id"], now(), now())
    assert calendar_plan.run_due() == 1
    assert get("SELECT status FROM topics WHERE id = ?", tid)["status"] == "approved"
    ai_jobs.run_pending(); autopilot.advance_all()
    r = get("SELECT * FROM autopilot_runs WHERE topic_id = ?", tid)
    assert r["status"] == "done" and get("SELECT status FROM articles WHERE id = ?", r["article_id"])["status"] == "approved"


def test_write_a_blog_never_sends_the_draft_to_shopify_even_when_shopify_is_connected(auto_env, users, monkeypatch):
    """Owner decision 2026-11-24: drafts stay in Flowmerce; only an authorized publish request writes to Shopify."""
    from flowmerce.modules.seo.integrations import shopify
    from flowmerce.modules.seo.services import autopilot
    monkeypatch.setattr(shopify, "configured", lambda b: True)
    monkeypatch.setattr(shopify, "_gql", lambda *a, **k: (_ for _ in ()).throw(AssertionError("a draft reached Shopify")))
    r = autopilot.start(users["admin"], "ridhi")
    for _ in range(2):
        ai_jobs.run_pending(); autopilot.advance_all()
    r = autopilot.get_run(r["id"])
    a = get("SELECT * FROM articles WHERE id = ?", r["article_id"])
    assert r["status"] == "done" and a["status"] == "approved" and a["shopify_article_id"] is None


def test_write_a_blog_can_be_stopped_while_claude_is_working(auto_env, users):
    from flowmerce.modules.seo.services import autopilot
    r = autopilot.start(users["admin"], "ridhi")
    stopped = autopilot.stop(users["admin"], r["id"])
    assert stopped["status"] == "failed" and stopped["message"].startswith("Stopped by")
    assert get("SELECT status FROM ai_jobs WHERE id = ?", r["research_job_id"])["status"] == "cancelled"   # no more Claude spend
    ai_jobs.run_pending(); autopilot.advance_all()                       # nothing moves on after a stop
    assert autopilot.get_run(r["id"])["status"] == "failed"
    assert not get("SELECT 1 FROM articles WHERE topic_id IN (SELECT id FROM topics WHERE status = 'approved') AND origin = 'claude'")
    with pytest.raises(Exception) as e:
        autopilot.stop(users["admin"], r["id"])
    assert getattr(e.value, "code", "") == "not_running"
    autopilot.start(users["admin"], "ridhi")                              # the brand is free for a new blog
