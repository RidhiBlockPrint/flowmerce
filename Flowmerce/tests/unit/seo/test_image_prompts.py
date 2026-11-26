"""AI image prompts for featured images (services/image_prompts.py). Owner request 2026-11-23: one prompt that works in any
AI image tool, sized for each store's Shopify theme, different for every article, made for every new draft, and available
for past drafts and live blogs. No network: Claude is replaced by stand-ins."""
import pytest

from flowmerce.modules.seo.db import get, now, run
from flowmerce.modules.seo.integrations import claude
from flowmerce.modules.seo.services import ai_budget, articles, auto_blog, image_prompts
from flowmerce.modules.seo.util import HttpError
from tests.fixtures.seo import local_client

IMG = "https://cdn.shopify.com/s/files/1/ait-tablecloth.jpg?v=1"
LONG = "<h2>Why indigo lasts</h2><p>" + "Indigo is dyed in many dips and each dip deepens the blue on the cotton. " * 14 + "</p><h2>How to wash it</h2><p>Cold water.</p>"
SCENE = ("A sunlit breakfast table on a wooden veranda in late morning, a deep indigo block printed tablecloth falling in soft folds, "
         "a brass tea pot, two cups and a bowl of mangoes, shot from a low three-quarter angle with gentle depth of field, warm and calm, "
         "light shadows of leaves moving across the cloth and the grain of the old teak boards visible at the edge of the frame.")
PIN_SCENE = ("A tall top-down view of hands smoothing a deep indigo block printed tablecloth across a teak table, a brass tea pot and two cups "
             "at the lower edge, mango slices on a plate, soft morning light from the left, calm empty space on the warm wood at the top "
             "of the frame for a title, the weave and slightly irregular hand-stamped motifs crisp in the foreground.")


@pytest.fixture
def env(ai_env, monkeypatch):
    run("DELETE FROM image_prompts")
    run("DELETE FROM claude_usage")
    run("DELETE FROM app_settings WHERE key LIKE 'image_style:%' OR key = 'auto_blog'")
    run("INSERT OR REPLACE INTO products (brand_id, handle, title, url, image_url, product_type, synced_at, source) VALUES (?,?,?,?,?,?,?,?)",
        "ridhi", "ait-indigo-tablecloth", "AIT Indigo Tablecloth", "https://ridhiblockprint.com/products/ait-indigo-tablecloth", IMG, "Tablecloth", now(), "test")
    calls = {"style": 0, "prompt": []}

    def style(b, v, photos):
        calls["style"] += 1
        calls["photos"] = photos
        return {"style": "Light: soft daylight. Colour palette: indigo and cream. Avoid: harsh flash."}, "m"

    def prompt(b, v, style_text, article, products, used, fmt, pin_fmt):
        calls["prompt"].append({"style": style_text, "article": article, "products": products, "used": used, "fmt": fmt, "pin_fmt": pin_fmt})
        return {"concept": f"veranda breakfast {len(calls['prompt'])}", "scene": SCENE, "pin_scene": PIN_SCENE, "payoff": "Indigo keeps its blue for years.",
                "references": [1, 1, 9], "alt_text": "Indigo tablecloth on a veranda table", "file_name": "Indigo Veranda Breakfast.JPG"}, "m"

    monkeypatch.setattr(claude, "image_style", style)
    monkeypatch.setattr(claude, "image_prompt", prompt)
    yield calls
    run("DELETE FROM image_prompts")
    run("DELETE FROM products WHERE handle LIKE 'ait-%'")


def article(title="AIT Indigo tablecloth care", body=LONG, status="draft", origin="app", brand="ridhi", created=None):
    a = articles.create_article(None, brand, {"title": title, "primary_keyword": "indigo tablecloth", "body_html": body}, origin, status)
    if created:
        run("UPDATE articles SET created_at = ? WHERE id = ?", created, a["id"])
    return a


def test_a_new_draft_is_queued_once_it_has_enough_text(env):
    short = article("AIT Short one", "<p>Only a few words so far.</p>")
    assert not get("SELECT 1 FROM image_prompts WHERE article_id = ?", short["id"])
    articles.save_article(None, short["id"], {"body_html": LONG})
    assert get("SELECT status, reason FROM image_prompts WHERE article_id = ?", short["id"]) == {"status": "queued", "reason": "new_article"} or \
        dict(get("SELECT status, reason FROM image_prompts WHERE article_id = ?", short["id"])) == {"status": "queued", "reason": "new_article"}


def test_imported_and_older_articles_wait_for_the_backfill(env):
    live = article("AIT Live from Shopify", origin="shopify", status="published")
    old = article("AIT Old draft", "<p>Started last month.</p>", created="2026-10-01T10:00:00.000Z")
    articles.save_article(None, old["id"], {"body_html": LONG})
    assert not get("SELECT 1 FROM image_prompts WHERE article_id IN (?, ?)", live["id"], old["id"])


def test_the_prompt_is_built_with_the_store_size_references_and_exclusions(env):
    a = article()
    assert image_prompts.process_next() == "done"
    p = get("SELECT * FROM image_prompts WHERE article_id = ?", a["id"])
    assert p["status"] == "ready" and env["style"] == 1
    assert "square image, aspect ratio 1:1, 2048 × 2048 pixels" in p["prompt"]          # Ridhi's theme
    assert "“AIT Indigo Tablecloth”" in p["prompt"] and "exactly as in the reference" in p["prompt"]
    assert "Use the photo only for the product itself" in p["prompt"]                    # the scene, not the product shot, sets the layout
    assert "middle half of the height" in p["prompt"]                                     # survives the wide social-media crop
    assert PIN_SCENE in p["pin_prompt"] and "portrait image, aspect ratio 2:3, 1000 × 1500 pixels" in p["pin_prompt"]
    assert "top quarter" in p["pin_prompt"] and "“AIT Indigo Tablecloth”" in p["pin_prompt"]
    assert p["payoff"] == "Indigo keeps its blue for years." and "2:3" in env["prompt"][0]["pin_fmt"]
    assert "Do not include any words, letters" in p["prompt"] and SCENE in p["prompt"]
    assert p["file_name"] == "indigo-veranda-breakfast.jpg"
    refs = image_prompts.state(a["id"])["references"]
    assert len(refs) == 1 and refs[0]["url"] == IMG                                       # duplicates and unknown numbers dropped
    shown = env["prompt"][0]
    assert shown["products"][0]["url"].endswith("width=800") and shown["article"]["headings"] == ["Why indigo lasts", "How to wash it"]
    assert "Light: soft daylight" in shown["style"]


def test_cpc_gets_its_own_landscape_size(env):
    run("INSERT OR REPLACE INTO products (brand_id, handle, title, url, image_url, product_type, synced_at, source) VALUES (?,?,?,?,?,?,?,?)",
        "cpc", "ait-cpc-napkins", "AIT Napkins", "https://cottonprintclub.com/products/ait-cpc-napkins", IMG, "Napkins", now(), "test")
    a = article("AIT CPC napkin guide", brand="cpc")
    image_prompts.process_next()
    p = get("SELECT prompt FROM image_prompts WHERE article_id = ?", a["id"])["prompt"]
    assert "landscape image, aspect ratio 4:3, 2400 × 1800 pixels" in p and "middle 60% of the height" in p


def test_each_article_is_told_the_concepts_already_used(env):
    first, second = article("AIT First"), article("AIT Second")
    image_prompts.process_next()
    image_prompts.process_next()
    assert env["prompt"][0]["used"] == [] and env["prompt"][1]["used"] == ["veranda breakfast 1"]
    assert env["style"] == 1                                                              # the style is read once and kept
    assert get("SELECT COUNT(*) n FROM image_prompts WHERE status = 'ready' AND article_id IN (?, ?)", first["id"], second["id"])["n"] == 2


def test_backfill_queues_past_drafts_and_live_blogs_behind_new_work(env, users):
    old = article("AIT Old live blog", origin="shopify", status="published")
    draft = article("AIT Old draft two", "<p>Started last month.</p>", created="2026-10-01T10:00:00.000Z")
    r = image_prompts.backfill(users["admin"], "ridhi", "published")
    assert r["queued"] >= 1 and get("SELECT priority, reason FROM image_prompts WHERE article_id = ?", old["id"])["reason"] == "backfill"
    assert not get("SELECT 1 FROM image_prompts WHERE article_id = ?", draft["id"])
    image_prompts.backfill(users["admin"], "ridhi", "drafts")
    new = article("AIT Brand new")
    image_prompts.process_next()
    assert get("SELECT status FROM image_prompts WHERE article_id = ?", new["id"])["status"] == "ready"   # new work goes first
    again = image_prompts.backfill(users["admin"], "ridhi", "all")
    assert get("SELECT reason FROM image_prompts WHERE article_id = ?", new["id"])["reason"] == "new_article"
    assert again["queued"] == 0                                                            # nothing queued twice
    image_prompts.cancel_backfill(users["admin"], "ridhi")
    assert not get("SELECT 1 FROM image_prompts WHERE article_id = ?", old["id"])


def test_backfill_leaves_room_for_an_automatic_blog(env, users, monkeypatch):
    run("INSERT INTO app_settings (key, value_json, updated_at) VALUES ('auto_blog', '{\"enabled\": true}', ?)", now())
    monkeypatch.setattr(ai_budget, "status", lambda: {"todayUsd": 1.0, "dailyLimitUsd": 3.0})
    old = article("AIT Waiting blog", origin="shopify", status="published")
    image_prompts.backfill(users["admin"], "ridhi", "published")
    assert 1.0 + auto_blog.BLOG_ESTIMATE_USD + 0.10 > 3.0
    assert image_prompts.process_next() == "wait"
    assert get("SELECT status FROM image_prompts WHERE article_id = ?", old["id"])["status"] == "queued"


def test_a_failed_call_is_retried_then_reported(env, monkeypatch):
    a = article("AIT Flaky")
    monkeypatch.setattr(claude, "image_prompt", lambda *x: (_ for _ in ()).throw(claude.ClaudeError("Claude rate limit reached (429).", "rate_limit", retryable=True, retry_after=1)))
    assert image_prompts.process_next() == "retry"
    run("UPDATE image_prompts SET next_attempt_at = NULL WHERE article_id = ?", a["id"])
    monkeypatch.setattr(claude, "image_prompt", lambda *x: (_ for _ in ()).throw(claude.ClaudeError("Claude declined this request (refusal).", "refusal")))
    assert image_prompts.process_next() == "failed"
    st = image_prompts.state(a["id"])
    assert st["status"] == "failed" and "refusal" in st["error"]


def test_a_thin_answer_is_rejected():
    with pytest.raises(claude.ClaudeError):
        image_prompts.clean_result({"scene": "A table.", "references": []}, [])


def test_the_editor_can_ask_for_a_new_prompt(env, users):
    a = article("AIT Editor asks")
    image_prompts.process_next()
    st = image_prompts.request(users["admin"], a["id"])
    assert st["status"] == "queued" and st["prompt"]                                       # the old prompt stays visible until replaced
    assert st["format"]["ratio"] == "1:1" and "Gemini" in st["tool"]["name"]
    with pytest.raises(HttpError):
        image_prompts.request(users["admin"], 999999)


def test_api_routes(env, users):
    from flowmerce.modules.seo.app import create_app
    c = local_client(create_app())
    a = article("AIT Api route")
    assert c.get(f"/api/articles/{a['id']}/image-prompt").json()["status"] == "queued"
    assert c.post(f"/api/articles/{a['id']}/image-prompt", headers={"X-Requested-With": "blog-ops"}).status_code == 200
    s = c.get("/api/image-prompts?brand=ridhi").json()
    assert s["formats"]["ridhi"]["ratio"] == "1:1" and "drafts" in s["withoutPrompt"]
    r = c.post("/api/image-prompts/backfill", json={"brand": "ridhi", "scope": "nonsense"}, headers={"X-Requested-With": "blog-ops"})
    assert r.status_code == 400
