"""Automatic featured images (services/ai_images.py, integrations/image_gen.py). Owner request 2026-11-23: Claude's prompt ->
an image API -> Shopify Files -> the article's featured image, with no person needed. No network: the image API, the photo
download, Shopify and Claude's print check are all stand-ins."""
import base64
import json

import pytest

from flowmerce.modules.seo.config import config
from flowmerce.modules.seo.db import get, now, run
from flowmerce.modules.seo.integrations import claude, image_gen, shopify
from flowmerce.modules.seo.services import ai_images, articles, autopilot, image_prompts

IMG = "https://cdn.shopify.com/s/files/1/ait-quilt.jpg?v=1"
UPLOADED = "https://cdn.shopify.com/s/files/1/ai-banner.jpg"
LONG = "<h2>Layering a quilt</h2><p>" + "A cotton quilt is warm enough in winter when it is layered over a blanket or a comforter. " * 12 + "</p>"
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 300


# ---------------------------------------------------------------- the image API client

def test_the_picture_is_found_in_every_known_answer_shape():
    b64 = base64.b64encode(JPEG).decode()
    gemini_new = {"steps": [{"type": "model_output", "content": [{"type": "text", "text": "Here"}, {"type": "image", "mime_type": "image/jpeg", "data": b64}]}]}
    gemini_old = {"candidates": [{"content": {"parts": [{"inlineData": {"mimeType": "image/png", "data": b64}}]}}]}
    openai = {"data": [{"b64_json": b64}], "output_format": "jpeg"}
    assert image_gen._first_image(gemini_new) == (b64, "image/jpeg")
    assert image_gen._first_image(gemini_old) == (b64, "image/png")
    assert image_gen._first_image(openai)[0] == b64
    assert image_gen.sniff(JPEG) == "image/jpeg" and image_gen.sniff(b"<html>") is None   # the real type comes from the bytes
    assert image_gen._first_image({"candidates": [{"finishReason": "SAFETY"}]}) is None


def test_provider_follows_the_keys(monkeypatch):
    for k in ("gemini_api_key", "openai_api_key", "image_provider", "image_model"):
        monkeypatch.setattr(config, k, "")
    assert not image_gen.configured() and "GEMINI_API_KEY" in image_gen.status()["setup"]
    monkeypatch.setattr(config, "openai_api_key", "sk-test")
    assert image_gen.provider() == "openai" and image_gen.model() == "gpt-image-2"
    monkeypatch.setattr(config, "gemini_api_key", "g-test")
    assert image_gen.provider() == "gemini" and image_gen.model() == "gemini-3-pro-image" and image_gen.cost_estimate() == 0.134
    monkeypatch.setattr(config, "image_provider", "openai")
    assert image_gen.provider() == "openai"


def test_requests_carry_the_photo_and_the_exact_shape(monkeypatch):
    seen = []
    monkeypatch.setattr(image_gen, "_post", lambda url, headers, body: seen.append((url, headers, body)) or {"data": [{"b64_json": base64.b64encode(JPEG).decode()}]})
    monkeypatch.setattr(config, "image_model", "")
    monkeypatch.setattr(config, "image_provider", "gemini")
    monkeypatch.setattr(config, "gemini_api_key", "g-test")
    data, _ = image_gen.generate("A quilt", [(JPEG, "image/jpeg")], "4:3", 2400, 1800)
    url, headers, body = seen[-1]
    assert data == JPEG and url.endswith("/interactions") and headers["x-goog-api-key"] == "g-test"
    assert body["response_format"]["aspect_ratio"] == "4:3" and body["input"][1]["type"] == "image" and body["input"][1]["mime_type"] == "image/jpeg"
    monkeypatch.setattr(config, "image_provider", "openai")
    monkeypatch.setattr(config, "openai_api_key", "sk-test")
    image_gen.generate("A quilt", [(JPEG, "image/jpeg")], "4:3", 2400, 1800)
    url, headers, body = seen[-1]
    assert url.endswith("/images/edits") and body["size"] == "2400x1792" and body["images"][0]["image_url"].startswith("data:image/jpeg;base64,")
    image_gen.generate("A table", [], "1:1", 2048, 2048)
    assert seen[-1][0].endswith("/images/generations") and "images" not in seen[-1][2]


def test_an_answer_without_a_picture_is_a_clear_failure(monkeypatch):
    monkeypatch.setattr(config, "gemini_api_key", "g-test")
    monkeypatch.setattr(config, "image_provider", "")
    monkeypatch.setattr(image_gen, "_post", lambda *a: {"steps": [{"content": [{"type": "text", "text": "I can't make that."}]}]})
    with pytest.raises(image_gen.ImageGenError) as e:
        image_gen.generate("x", [], "1:1", 1024, 1024)
    assert e.value.kind == "no_image" and "can't make that" in str(e.value)


# ---------------------------------------------------------------- the automatic chain

@pytest.fixture
def chain(ai_env, monkeypatch):
    for table in ("image_prompts", "image_generations", "claude_usage"):
        run(f"DELETE FROM {table}")
    run("DELETE FROM app_settings WHERE key IN ('image_generation', 'auto_blog') OR key LIKE 'image_style:%'")
    run("INSERT OR REPLACE INTO products (brand_id, handle, title, url, image_url, product_type, synced_at, source) VALUES (?,?,?,?,?,?,?,?)",
        "ridhi", "ait-basil-quilt", "AIT Basil Green Quilt", "https://ridhiblockprint.com/products/ait-basil-quilt", IMG, "Quilt", now(), "test")
    monkeypatch.setattr(config, "gemini_api_key", "g-test")
    monkeypatch.setattr(config, "image_provider", "")
    monkeypatch.setattr(config, "image_model", "")
    calls = {"generate": [], "upload": [], "check": []}
    monkeypatch.setattr(claude, "image_style", lambda *a: ({"style": "Warm light."}, "m"))
    monkeypatch.setattr(claude, "image_prompt", lambda *a: ({
        "payoff": "Layer it for warmth.", "concept": "hand folding back a quilt", "pin_scene": "",
        "scene": "A hand folds back the AIT Basil Green Quilt from the attached photo at the foot of a bed at dusk, showing the oatmeal blanket "
                 "and white comforter beneath it, warm lamplight, a mug with steam, off-centre on a diagonal, shallow depth of field, cosy and calm.",
        "references": [1], "alt_text": "A hand folding back a green quilt over a blanket", "file_name": "quilt-layers.jpg"}, "m"))
    monkeypatch.setattr(ai_images, "_download", lambda url: (JPEG, "image/jpeg"))
    monkeypatch.setattr(image_gen, "generate", lambda prompt, refs, ratio, w, h: calls["generate"].append((prompt, len(refs), ratio)) or (JPEG, "image/jpeg"))
    monkeypatch.setattr(shopify, "upload_image", lambda b, data, name, mime, alt="": calls["upload"].append((name, mime)) or UPLOADED)
    calls["verdict"] = {"faithful": True, "looks_real": True, "problems": ""}
    monkeypatch.setattr(claude, "image_check", lambda b, v, refs, url: calls["check"].append((refs, url)) or (calls["verdict"], "m"))
    yield calls
    run("DELETE FROM image_prompts")
    run("DELETE FROM products WHERE handle LIKE 'ait-%'")


def draft(title="AIT Are quilts warm enough", status="draft", origin="app"):
    return articles.create_article(None, "ridhi", {"title": title, "primary_keyword": "quilt warm winter", "body_html": LONG}, origin, status)


def run_all():
    out = []
    while (r := image_prompts.process_next()) not in ("empty", "wait"):
        out.append(r)
    while (r := ai_images.process_next()) not in ("empty", "wait"):
        out.append(r)
    return out


def test_a_new_draft_gets_its_picture_attached_with_no_person(chain):
    a = draft()
    run_all()
    p = get("SELECT * FROM image_prompts WHERE article_id = ?", a["id"])
    assert p["image_status"] == "ready" and p["image_url"] == UPLOADED and p["image_attached"] == 1 and not p["image_error"]
    art = articles.get_article(a["id"])
    assert art["image_url"] == UPLOADED and art["image_alt"] == "A hand folding back a green quilt over a blanket"
    assert chain["generate"][0][1] == 1 and chain["generate"][0][2] == "1:1"            # the real product photo went with the prompt, square for Ridhi
    assert chain["upload"][0] == ("quilt-layers.jpg", "image/jpeg")
    assert chain["check"] and chain["check"][0][1].endswith("width=800")
    assert get("SELECT COUNT(*) n, SUM(cost_usd) usd FROM image_generations WHERE ok = 1")["n"] == 1
    st = image_prompts.state(a["id"])
    assert st["image"]["attached"] and st["image"]["check"]["faithful"]


def test_a_changed_print_is_made_again_then_left_to_a_person(chain):
    chain["verdict"] = {"faithful": False, "looks_real": True, "problems": "The motifs are simplified."}
    a = draft()
    run_all()
    p = get("SELECT * FROM image_prompts WHERE article_id = ?", a["id"])
    assert len(chain["generate"]) == 2 and p["image_attached"] == 0 and "did not pass the print check twice" in p["image_error"]
    assert articles.get_article(a["id"])["image_url"] != UPLOADED


def test_a_live_blog_keeps_its_image_until_a_person_chooses(chain, users):
    a = draft("AIT Live quilt guide", status="published", origin="shopify")
    image_prompts.backfill(users["admin"], "ridhi", "published")
    run_all()
    p = get("SELECT * FROM image_prompts WHERE article_id = ?", a["id"])
    assert p["image_url"] == UPLOADED and p["image_attached"] == 0
    assert articles.get_article(a["id"])["image_url"] != UPLOADED
    ai_images.use_image(users["admin"], a["id"])
    assert articles.get_article(a["id"])["image_url"] == UPLOADED


def test_without_the_shopify_permission_the_step_says_what_to_do(chain, monkeypatch):
    monkeypatch.setattr(shopify, "upload_image", lambda *a, **k: (_ for _ in ()).throw(shopify.MissingScope("access denied")))
    a = draft()
    run_all()
    p = get("SELECT image_status, image_error FROM image_prompts WHERE article_id = ?", a["id"])
    assert p["image_status"] == "failed" and "write_files" in p["image_error"]


def test_the_daily_limit_stops_pictures(chain, users):
    ai_images.update_settings(users["admin"], {"dailyLimit": 0})
    a = draft()
    image_prompts.process_next()
    assert ai_images.process_next() == "wait"
    assert get("SELECT image_status FROM image_prompts WHERE article_id = ?", a["id"])["image_status"] == "queued"


def test_switched_off_or_without_a_key_nothing_is_made(chain, users, monkeypatch):
    ai_images.update_settings(users["admin"], {"enabled": False})
    a = draft()
    run_all()
    assert get("SELECT image_status FROM image_prompts WHERE article_id = ?", a["id"])["image_status"] == ""
    ai_images.update_settings(users["admin"], {"enabled": True})
    monkeypatch.setattr(config, "gemini_api_key", "")
    assert not ai_images.active() and ai_images.process_next() == "empty"


def test_an_automatic_blog_waits_for_its_picture(chain):
    a = draft()
    rid = run("""INSERT INTO autopilot_runs (brand_id, status, step, message, source, created_at, updated_at) VALUES ('ridhi','running','draft','', 'auto', ?, ?)""",
              now(), now()).last_id
    r = get("SELECT * FROM autopilot_runs WHERE id = ?", rid)
    finished = []
    import flowmerce.modules.seo.services.autopilot as ap
    orig = ap._finish_auto
    ap._finish_auto = lambda r, aid, note: finished.append((aid, note))
    try:
        autopilot._image_then_finish(r, a["id"], "The draft passed the quality check.")
        r = get("SELECT * FROM autopilot_runs WHERE id = ?", rid)
        assert r["step"] == "image" and not finished
        autopilot._advance(r)
        assert not finished                                                                # the prompt is still queued
        run_all()
        autopilot._advance(get("SELECT * FROM autopilot_runs WHERE id = ?", rid))
        assert finished and finished[0][1] == "The draft passed the quality check."
        assert articles.get_article(a["id"])["image_url"] == UPLOADED                        # the picture is in place before approval
    finally:
        ap._finish_auto = orig
    run("DELETE FROM autopilot_runs WHERE id = ?", rid)


def test_settings_are_bounded(chain, users):
    s = ai_images.update_settings(users["admin"], {"dailyLimit": 5000, "monthlyUsd": -3, "pins": 1})
    assert s["dailyLimit"] == ai_images.MAX_DAILY and s["monthlyUsd"] == 0 and s["pins"] is True
    assert json.loads(get("SELECT value_json FROM app_settings WHERE key = 'image_generation'")["value_json"])["pins"] is True
