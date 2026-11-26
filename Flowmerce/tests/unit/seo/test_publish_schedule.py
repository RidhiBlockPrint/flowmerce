"""Scheduled publishing: the article goes to Shopify HIDDEN with a future publish date, and Shopify shows it then.

Shopify refuses isPublished: true together with a future publishDate ("Can't set isPublished to true and also set a
future publish date"), so a schedule must never send both."""
from datetime import datetime, timedelta, timezone

import pytest

from flowmerce.modules.seo.config import config
from flowmerce.modules.seo.db import all_rows, get, run
from flowmerce.modules.seo.integrations import shopify
from flowmerce.modules.seo.services import articles, publishing, sync
from flowmerce.modules.seo.services.articles import decorate, get_article
from flowmerce.modules.seo.util import HttpError


def _iso(t: datetime) -> str:
    return t.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class FakeShopify:
    """Records every Admin API write and answers like Shopify does: a hidden article keeps the publishDate it was given."""

    def __init__(self):
        self.calls: list[dict] = []
        self.listed: list[dict] = []
        self.answer_published_at = "same"   # "same" = echo publishDate back; anything else is returned as publishedAt

    def gql(self, b, query, variables=None):
        self.calls.append(variables or {})
        art = (variables or {}).get("article", {})
        if art.get("isPublished") and art.get("publishDate"):
            return {"articleCreate" if "articleCreate" in query else "articleUpdate": {"article": None, "userErrors": [
                {"field": ["article"], "message": "Can't set isPublished to true and also set a future publish date."}]}}
        at = art.get("publishDate") if self.answer_published_at == "same" else self.answer_published_at
        out = {"id": "gid://shopify/Article/sched-1", "handle": art.get("handle"), "isPublished": bool(art.get("isPublished")),
               "publishedAt": at if not art.get("isPublished") else _iso(datetime.now(timezone.utc))}
        return {"articleCreate" if "articleCreate" in query else "articleUpdate": {"article": out, "userErrors": []}}


@pytest.fixture
def fake(monkeypatch):
    f = FakeShopify()
    monkeypatch.setattr(config, "allow_live_publish", True)
    monkeypatch.setattr(shopify, "configured", lambda b: True)
    monkeypatch.setattr(shopify, "_gql", f.gql)
    monkeypatch.setattr(shopify, "find_blog", lambda b: {"id": "gid://shopify/Blog/1", "handle": "news"})
    monkeypatch.setattr(shopify, "list_articles", lambda b, blog_id: shopify.Listing(f.listed))
    monkeypatch.setattr(shopify, "list_products", lambda b: shopify.Listing())
    yield f
    for r in all_rows("SELECT id FROM articles WHERE title LIKE 'SCHEDT %'"):
        for t in ("publish_requests", "article_revisions"):
            run(f"DELETE FROM {t} WHERE article_id = ?", r["id"])
        run("DELETE FROM articles WHERE id = ?", r["id"])


def _approved(users, handle):
    m, r = users["seo_manager"], users["reviewer"]
    a = articles.create_article(m, "ridhi", {"title": f"SCHEDT {handle}", "handle": handle, "primary_keyword": handle,
                                             "body_html": "<p>Body</p>", "meta_description": "Meta"}, "app", "draft")
    articles.submit_for_review(m, a["id"])
    articles.review_article(r, a["id"], "approve", a["version"], "")
    return a


def test_schedule_is_sent_hidden_with_the_publish_date(fake, users):
    m, r = users["seo_manager"], users["reviewer"]
    a = _approved(users, "schedt-hidden")
    when = _iso(datetime.now(timezone.utc) + timedelta(days=2))
    req = publishing.request_publish(m, a["id"], "schedule", when, "")
    publishing.authorize_request(r, req["id"], "PUBLISH", "")

    sent = fake.calls[-1]["article"]
    assert sent["isPublished"] is False and sent["publishDate"] == when   # hidden now, visible at the chosen time

    after = decorate(get_article(a["id"]))
    assert after["status"] == "scheduled" and after["publish_at"] == when
    assert after["shopify_published"] is False                            # not live until Shopify shows it
    assert after["has_shopify_draft"] is False                            # a schedule, not a draft
    assert get("SELECT status FROM publish_requests WHERE id = ?", req["id"])["status"] == "executed"

    q = publishing.publishing_queue("ridhi")
    assert a["id"] in [x["id"] for x in q["scheduled"]] and a["id"] not in [x["id"] for x in q["drafts"]]
    assert len(fake.calls) == 1                                           # one write to Shopify: the authorized schedule


def test_publish_now_is_sent_visible_without_a_date(fake, users):
    m, r = users["seo_manager"], users["reviewer"]
    a = _approved(users, "schedt-now")
    req = publishing.request_publish(m, a["id"], "publish_now", None, "")
    publishing.authorize_request(r, req["id"], "PUBLISH", "")
    sent = fake.calls[-1]["article"]
    assert sent["isPublished"] is True and "publishDate" not in sent
    after = get_article(a["id"])
    assert after["status"] == "published" and after["shopify_published"] == 1


def test_a_schedule_shopify_did_not_keep_fails_loudly(fake, users):
    m, r = users["seo_manager"], users["reviewer"]
    a = _approved(users, "schedt-lost")
    when = _iso(datetime.now(timezone.utc) + timedelta(days=2))
    req = publishing.request_publish(m, a["id"], "schedule", when, "")
    fake.answer_published_at = None                                      # Shopify saved it hidden but dropped the date
    with pytest.raises(HttpError, match="did not keep the schedule"):
        publishing.authorize_request(r, req["id"], "PUBLISH", "")
    assert get_article(a["id"])["status"] == "failed"


def test_sync_marks_a_scheduled_article_live_once_shopify_shows_it(fake, users):
    m, r = users["seo_manager"], users["reviewer"]
    a = _approved(users, "schedt-golive")
    when = _iso(datetime.now(timezone.utc) + timedelta(days=2))
    req = publishing.request_publish(m, a["id"], "schedule", when, "")
    publishing.authorize_request(r, req["id"], "PUBLISH", "")

    row = {"id": "gid://shopify/Article/sched-1", "handle": "schedt-golive", "title": "SCHEDT schedt-golive", "body": "<p>Body</p>",
           "summary": "", "tags": [], "author": {"name": "Ed"}, "image": None, "seoTitle": None, "seoDescription": {"value": "Meta"},
           "isPublished": False, "publishedAt": when, "createdAt": None, "updatedAt": None}
    fake.listed = [row]
    sync.sync_shopify("ridhi")                                            # still before the date: stays scheduled and hidden
    mid = get_article(a["id"])
    assert mid["status"] == "scheduled" and mid["shopify_published"] == 0

    fake.listed = [{**row, "isPublished": True, "publishedAt": _iso(datetime.now(timezone.utc) - timedelta(minutes=5))}]
    sync.sync_shopify("ridhi")                                            # Shopify has shown it: now live
    done = get_article(a["id"])
    assert done["status"] == "published" and done["shopify_published"] == 1
