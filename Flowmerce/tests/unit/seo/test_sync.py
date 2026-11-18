"""Batch A: data accuracy and sync reliability.

Every outside service is replaced in these tests (the shared fixtures also block the network). Rows for analytics
use the made-up brand id "synct" where possible, so they cannot mix with other tests' data."""
import pytest

from flowmerce.modules.seo import db as dbmod
from flowmerce.modules.seo.config import normalize_ga4_property_id
from flowmerce.modules.seo.db import all_rows, get, now, run
from flowmerce.modules.seo.integrations import shopify
from flowmerce.modules.seo.integrations.status import INTERRUPTED, mark_attempt, mark_success, record_check, status_of, sweep_stuck_syncs
from flowmerce.modules.seo.services import analytics, resync, scheduler, sync
from flowmerce.modules.seo.services.articles import create_article, decorate, get_article, save_article
from flowmerce.modules.seo.util import HttpError, add_days, today

FAKE = "synct"


# ---------------- helpers ----------------

def _admin_article(handle, published, body="<p>Body</p>", desc=None, gid=None):
    return {"id": gid or f"gid://shopify/Article/{handle}", "handle": handle, "title": f"SYNCT {handle}", "body": body, "summary": "",
            "tags": [], "isPublished": published, "publishedAt": "2026-01-01T00:00:00Z" if published else None, "updatedAt": None,
            "author": {"name": "Ed"}, "image": None, "seoTitle": None, "seoDescription": {"value": desc} if desc is not None else None}


@pytest.fixture
def admin_shopify(monkeypatch):
    """Ridhi's Admin API, replaced: tests set `state["articles"]` before each sync."""
    state = {"articles": []}
    monkeypatch.setattr(shopify, "configured", lambda b: True)
    monkeypatch.setattr(shopify, "find_blog", lambda b: {"id": "gid://shopify/Blog/1", "handle": "news"})
    monkeypatch.setattr(shopify, "list_articles", lambda b, blog_id: shopify.Listing(state["articles"]))
    monkeypatch.setattr(shopify, "list_products", lambda b: shopify.Listing())
    yield state
    ids = [r["id"] for r in all_rows("SELECT id FROM articles WHERE title LIKE 'SYNCT %'")]
    for i in ids:
        run("DELETE FROM article_revisions WHERE article_id = ?", i)
        run("DELETE FROM articles WHERE id = ?", i)


@pytest.fixture
def clean_fake():
    yield
    for t in ("gsc_page_daily", "ga4_page_daily", "gsc_query_period", "articles", "workflow_runs", "integration_status"):
        run(f"DELETE FROM {t} WHERE brand_id = ?", FAKE)


def _gsc(brand, day, page, clicks, imps, src):
    run("INSERT INTO gsc_page_daily (brand_id, date, page, clicks, impressions, ctr, position, source, imported_at) VALUES (?,?,?,?,?,?,?,?,?)",
        brand, day, page, clicks, imps, 0.1, 5.0, src, now())


# ---------------- Shopify ----------------

def test_admin_sync_keeps_origin_and_shows_current_sync_source(admin_shopify):
    a = create_article(None, "ridhi", {"title": "SYNCT kept", "handle": "synct-kept", "body_html": "<p>Body</p>"}, "shopify_public", "published")
    run("UPDATE articles SET shopify_published = 1, live_hash = content_hash WHERE id = ?", a["id"])
    assert decorate(get_article(a["id"]))["shopify_sync"] == "public_feed"

    admin_shopify["articles"] = [_admin_article("synct-kept", True, desc="From Shopify")]
    res = sync.sync_shopify("ridhi")

    after = get_article(a["id"])
    assert after["origin"] == "shopify_public"                       # provenance is never rewritten
    assert after["shopify_article_id"] == "gid://shopify/Article/synct-kept"
    assert decorate(after)["shopify_sync"] == "admin_api"           # the current sync path is shown separately
    assert after["meta_description"] == "From Shopify"              # an unedited live article picks up Shopify's SEO field
    assert res["mode"] == "admin_api" and res["articles"] == 1 and res["published"] == 1


def test_unpublished_in_shopify_is_flagged_not_demoted(admin_shopify):
    admin_shopify["articles"] = [_admin_article("synct-gone", True)]
    sync.sync_shopify("ridhi")
    aid = get("SELECT id FROM articles WHERE handle = 'synct-gone'")["id"]
    assert get_article(aid)["status"] == "published"

    admin_shopify["articles"] = [_admin_article("synct-gone", False)]
    res = sync.sync_shopify("ridhi")
    a = decorate(get_article(aid))
    assert a["status"] == "published"                                # no automatic demotion
    assert a["unpublished_in_shopify"] is True and a["shopify_published"] is False
    assert res["unpublishedInShopify"] == 1
    assert get("SELECT 1 FROM audit_log WHERE action = 'article.unpublished_in_shopify' AND entity_id = ?", str(aid))


def test_imported_draft_refreshes_until_someone_edits_it_here(admin_shopify, users):
    admin_shopify["articles"] = [_admin_article("synct-draft", False, body="<p>v1</p>")]
    sync.sync_shopify("ridhi")
    aid = get("SELECT id FROM articles WHERE handle = 'synct-draft'")["id"]
    assert get_article(aid)["status"] == "draft"

    admin_shopify["articles"] = [_admin_article("synct-draft", False, body="<p>v2</p>")]
    res = sync.sync_shopify("ridhi")
    assert res["draftsRefreshed"] == 1 and "v2" in get_article(aid)["body_html"]

    save_article(users["admin"], aid, {"body_html": "<p>edited in Flowmerce</p>"})
    admin_shopify["articles"] = [_admin_article("synct-draft", False, body="<p>v3</p>")]
    res = sync.sync_shopify("ridhi")
    assert res["draftsProtected"] == 1 and res["draftsRefreshed"] == 0
    assert "edited in Flowmerce" in get_article(aid)["body_html"]   # a person's edit is never overwritten


def test_imported_articles_take_their_creation_date_from_shopify(admin_shopify, users):
    new = {**_admin_article("synct-made", False), "createdAt": "2025-03-04T05:06:07Z"}
    admin_shopify["articles"] = [new]
    sync.sync_shopify("ridhi")
    aid = get("SELECT id FROM articles WHERE handle = 'synct-made'")["id"]
    assert get_article(aid)["created_at"] == "2025-03-04T05:06:07.000Z"      # new import: Shopify's date, not today

    old = create_article(None, "ridhi", {"title": "SYNCT old", "handle": "synct-old", "body_html": "<p>Body</p>"}, "shopify_public", "published")
    mine = create_article(users["admin"], "ridhi", {"title": "SYNCT mine", "handle": "synct-mine", "body_html": "<p>Body</p>"}, "app", "draft")
    admin_shopify["articles"] = [new, {**_admin_article("synct-old", True), "createdAt": "2024-01-02T03:04:05+05:30"},
                                 {**_admin_article("synct-mine", False), "createdAt": "2026-11-01T00:00:00Z"}]
    sync.sync_shopify("ridhi")
    assert get_article(old["id"])["created_at"] == "2024-01-01T21:34:05.000Z"  # earlier import corrected, converted to UTC
    assert get_article(mine["id"])["created_at"] == mine["created_at"]         # written in Flowmerce: keeps its own date


def test_products_are_not_pruned_when_the_listing_hit_its_page_limit(admin_shopify, monkeypatch):
    run("INSERT OR REPLACE INTO products (brand_id, handle, title, url, synced_at, source) VALUES ('ridhi','synct-old-product','Old','https://x/p', '2000-01-01T00:00:00Z', 'shopify_admin')")
    capped = shopify.Listing([{"handle": "synct-new-product", "title": "New", "url": "https://x/n", "image": "", "type": ""}])
    capped.truncated = True
    monkeypatch.setattr(shopify, "list_products", lambda b: capped)
    res = sync.sync_shopify("ridhi")
    assert res["productsTruncated"] is True
    assert get("SELECT 1 FROM products WHERE brand_id = 'ridhi' AND handle = 'synct-old-product'")
    run("DELETE FROM products WHERE handle LIKE 'synct-%'")


def test_shopify_retry_after_header_is_honoured():
    class R:
        headers = {"Retry-After": "2.5"}
    assert shopify._retry_after(R(), 9) == 2.5
    R.headers = {"Retry-After": "600"}
    assert shopify._retry_after(R(), 9) == 10.0
    R.headers = {}
    assert shopify._retry_after(R(), 1.5) == 1.5


# ---------------- Search Console / GA4 ----------------

def test_gsc_url_variants_are_added_together():
    d = "2026-10-01"
    rows = [{"keys": [d, "https://www.ex.com/blogs/news/a?utm=1"], "clicks": 2, "impressions": 10, "position": 3.0},
            {"keys": [d, "http://ex.com/blogs/news/a/"], "clicks": 3, "impressions": 30, "position": 5.0}]
    out = sync.aggregate_gsc(rows, "date_page")
    assert list(out) == [(d, "/blogs/news/a")]
    m = out[(d, "/blogs/news/a")]
    assert (m["clicks"], m["impressions"]) == (5, 40)
    assert m["position"] == pytest.approx((3 * 10 + 5 * 30) / 40)  # weighted by impressions, not overwritten


def test_gsc_sync_replaces_only_live_rows_and_reports_a_gap(monkeypatch):
    end = add_days(today(), -sync.GSC_LAG_DAYS)
    old = add_days(end, -40)
    _gsc("cpc", old, "/blogs/synct/old", 1, 10, "api")
    _gsc("cpc", end, "/blogs/synct/a", 99, 999, "excel")
    _gsc("cpc", end, "/blogs/synct/a", 77, 777, "demo")

    def fake_query(b, start, stop, dims, row_limit=25000):
        if dims == ["date", "page"]:
            return [{"keys": [end, "https://cottonprintclub.com/blogs/synct/a"], "clicks": 1, "impressions": 10, "position": 2.0},
                    {"keys": [end, "https://www.cottonprintclub.com/blogs/synct/a/"], "clicks": 2, "impressions": 20, "position": 4.0}]
        return [{"keys": ["https://cottonprintclub.com/blogs/synct/a", "synct query"], "clicks": 3, "impressions": 30, "position": 3.0}]

    monkeypatch.setattr(sync, "gsc_configured", lambda b: True)
    monkeypatch.setattr(sync, "gsc_query", fake_query)
    try:
        res = sync.sync_gsc("cpc")
        assert res["gap"] and res["gap"]["from"] == add_days(old, 1)
        assert res["dataThrough"] == end and res["rows"] >= 1
        api = get("SELECT clicks, impressions FROM gsc_page_daily WHERE brand_id='cpc' AND source='api' AND date=? AND page='/blogs/synct/a'", end)
        assert (api["clicks"], api["impressions"]) == (3, 30)
        for src, clicks in (("excel", 99), ("demo", 77)):
            assert get("SELECT clicks FROM gsc_page_daily WHERE brand_id='cpc' AND source=? AND page='/blogs/synct/a'", src)["clicks"] == clicks
        assert get("SELECT 1 FROM gsc_page_daily WHERE brand_id='cpc' AND source='api' AND date=?", old)  # outside the window: kept
        st = status_of("gsc", "cpc")
        assert st["status"] == "connected" and st["details"]["gap"]["days"] > 0
    finally:
        run("DELETE FROM gsc_page_daily WHERE brand_id='cpc' AND page LIKE '/blogs/synct/%'")
        run("DELETE FROM gsc_query_period WHERE brand_id='cpc' AND page LIKE '/blogs/synct/%'")


def _ga4(brand, day, path, sessions, src):
    run("""INSERT INTO ga4_page_daily (brand_id, date, page_path, sessions, engaged_sessions, engagement_rate, avg_engagement_seconds, key_events, source, imported_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)""", brand, day, path, sessions, sessions // 2, 0.5, 30.0, 1, src, now())


def _demo_only_brand():
    """FAKE has demo rows only (Search Console page rows, a query row and GA4 rows) and one hidden-draft-free live article."""
    day = "2026-09-10"
    _gsc(FAKE, day, "/blogs/x/a", 31337, 313370, "demo")
    _ga4(FAKE, day, "/blogs/x/a", 31337, "demo")
    run("""INSERT INTO gsc_query_period (brand_id, start_date, end_date, page, query, clicks, impressions, ctr, position, source, imported_at)
           VALUES (?, '2026-09-01', ?, '/blogs/x/a', 'synthetic query', 31337, 313370, 0.1, 3, 'demo', ?)""", FAKE, day, now())
    t = now()
    run("""INSERT INTO articles (brand_id, title, handle, status, shopify_published, live_url, published_at, created_at, updated_at)
           VALUES (?, 'SYNCT demo article', 'synct-demo-article', 'published', 1, 'https://x/blogs/x/a', '2026-01-01', ?, ?)""", FAKE, t, t)
    return day


def test_normal_mode_never_reads_demo_rows_even_without_real_data(clean_fake, monkeypatch):
    from flowmerce.modules.seo.config import config
    monkeypatch.setattr(config, "demo_mode", False)
    day = _demo_only_brand()
    g, a = analytics.gsc_report(FAKE, day, day), analytics.ga4_report(FAKE, day, day)
    assert g["source"]["kind"] is None and g["totals"] is None and g["source"]["state"] == "not_synced"   # missing, and says why
    assert a["source"]["kind"] is None and a["totals"] is None
    perf = analytics.article_performance(FAKE, day, day)["rows"][0]
    assert perf["clicks"] is None and perf["sessions"] is None
    assert analytics.article_queries(FAKE, "https://x/blogs/x/a") is None


def test_demo_mode_reads_demo_rows_only_and_never_mixes_real_rows(clean_fake, monkeypatch):
    from flowmerce.modules.seo.config import config
    day = _demo_only_brand()
    _gsc(FAKE, day, "/blogs/x/b", 7, 70, "api")             # real rows in the same range
    _ga4(FAKE, day, "/blogs/x/b", 7, "excel")
    monkeypatch.setattr(config, "demo_mode", True)
    g, a = analytics.gsc_report(FAKE, day, day), analytics.ga4_report(FAKE, day, day)
    assert g["source"]["kind"] == "demo" and g["totals"]["clicks"] == 31337        # not 31337 + 7
    assert a["source"]["kind"] == "demo" and a["totals"]["sessions"] == 31337
    assert analytics.article_queries(FAKE, "https://x/blogs/x/a")["source"] == "demo"
    monkeypatch.setattr(config, "demo_mode", False)
    g = analytics.gsc_report(FAKE, day, day)
    assert g["source"]["kind"] == "api" and g["totals"]["clicks"] == 7              # and the real report has no demo in it


def test_demo_mode_without_demo_rows_says_so(clean_fake, monkeypatch):
    from flowmerce.modules.seo.config import config
    _gsc(FAKE, "2026-09-10", "/blogs/x/b", 7, 70, "api")
    monkeypatch.setattr(config, "demo_mode", True)
    s = analytics.gsc_report(FAKE, "2026-09-10", "2026-09-10")["source"]
    assert s["kind"] is None and s["state"] == "demo_not_loaded"


@pytest.mark.parametrize("demo_mode", [False, True])
def test_exports_never_contain_demo_rows(clean_fake, monkeypatch, demo_mode):
    from flowmerce.modules.seo.config import config
    from flowmerce.modules.seo.services.excel import export_rows
    monkeypatch.setattr(config, "demo_mode", demo_mode)
    _demo_only_brand()
    for kind in ("gsc_pages", "gsc_queries", "ga4_pages"):
        rows = export_rows(kind, FAKE, "", "", "", "")
        assert not any(31337 in r.values() for r in rows), kind


def test_an_empty_range_says_why(clean_fake):
    day = "2026-09-10"
    assert analytics.gsc_report(FAKE, day, day)["source"]["state"] == "not_synced"
    mark_attempt("gsc", FAKE, "api")
    assert analytics.gsc_report(FAKE, day, day)["source"]["state"] == "syncing"
    run("UPDATE integration_status SET status='error', last_error='Google refused access (403)' WHERE key='gsc' AND brand_id=?", FAKE)
    s = analytics.gsc_report(FAKE, day, day)["source"]
    assert s["state"] == "sync_failed" and "403" in s["lastError"]
    mark_success("gsc", FAKE, "api", {"rows": 0})
    assert analytics.gsc_report(FAKE, day, day)["source"]["state"] == "no_rows"


def test_partial_coverage_is_reported(clean_fake):
    _gsc(FAKE, "2026-09-10", "/blogs/x/a", 1, 10, "api")
    s = analytics.gsc_report(FAKE, "2026-09-01", "2026-09-20")["source"]
    assert s["kind"] == "api" and s["state"] == "partial" and s["coverage"]["to"] == "2026-09-10"


def test_article_metrics_are_none_for_hidden_drafts_and_zero_only_when_live(clean_fake):
    t = now()
    live = run("""INSERT INTO articles (brand_id, title, handle, status, shopify_published, live_url, published_at, created_at, updated_at)
                  VALUES (?, 'SYNCT live', 'synct-live', 'published', 1, 'https://x/blogs/n/live', '2026-01-01', ?, ?)""", FAKE, t, t).last_id
    draft = run("""INSERT INTO articles (brand_id, title, handle, status, shopify_published, live_url, created_at, updated_at)
                   VALUES (?, 'SYNCT draft', 'synct-draft2', 'draft', 0, 'https://x/blogs/n/draft', ?, ?)""", FAKE, t, t).last_id
    _gsc(FAKE, "2026-09-10", "/blogs/n/other", 5, 50, "api")
    rows = {r["id"]: r for r in analytics.article_performance(FAKE, "2026-09-01", "2026-09-20")["rows"]}
    assert rows[live]["clicks"] == 0                    # live, source has data, no clicks: a real zero
    assert rows[draft]["clicks"] is None                # hidden draft: nothing to measure


# ---------------- status, scheduler, locking, backups ----------------

def test_connection_test_survives_a_sync_and_stuck_syncs_are_swept(clean_fake):
    record_check("ga4", FAKE, {"auth": True, "api": True, "rows": 0})
    mark_success("ga4", FAKE, "api", {"rows": 12, "dataThrough": "2026-11-10"})
    st = status_of("ga4", FAKE)
    assert st["details"]["lastCheck"]["rows"] == 0 and st["details"]["rows"] == 12
    good = st["last_success_at"]
    mark_attempt("ga4", FAKE, "api")
    assert sweep_stuck_syncs() >= 1
    st = status_of("ga4", FAKE)
    assert st["status"] == "error" and st["last_error"] == INTERRUPTED and st["last_success_at"] == good


def test_ga4_property_id_is_normalised():
    assert normalize_ga4_property_id("properties/123456") == "123456"
    assert normalize_ga4_property_id(" 123456 ") == "123456"
    assert normalize_ga4_property_id("") == ""


def test_scheduler_retries_failures_with_backoff(clean_fake):
    assert scheduler.retry_delay_ms(1) == 30 * 60_000
    assert scheduler.retry_delay_ms(3) == 120 * 60_000
    assert scheduler.retry_delay_ms(10) == scheduler.REFRESH_HOURS * 3600_000
    from datetime import datetime, timedelta, timezone

    def ago(minutes):
        return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat(timespec="milliseconds").replace("+00:00", "Z")

    assert scheduler.is_due(FAKE)                       # never ran
    run("INSERT INTO workflow_runs (brand_id, stage, status, trigger_kind, started_at) VALUES (?, 'performance_tracking', 'succeeded', 'scheduler', ?)", FAKE, ago(60))
    assert not scheduler.is_due(FAKE)                   # succeeded an hour ago
    run("INSERT INTO workflow_runs (brand_id, stage, status, trigger_kind, started_at) VALUES (?, 'performance_tracking', 'failed', 'scheduler', ?)", FAKE, ago(10))
    assert not scheduler.is_due(FAKE)                   # failed 10 min ago: first retry after 30 min
    run("UPDATE workflow_runs SET started_at = ? WHERE brand_id = ? AND status = 'failed'", ago(40), FAKE)
    assert scheduler.is_due(FAKE)                       # not 6 hours: retried after 30 min


def test_a_second_sync_of_the_same_source_is_refused():
    with sync.exclusive("gsc", FAKE):
        with pytest.raises(HttpError) as e:
            with sync.exclusive("gsc", FAKE):
                pass
        assert e.value.status == 409
        with sync.exclusive("ga4", FAKE):               # another source is independent
            pass


def test_backup_is_verified(tmp_path):
    b = dbmod.backup_database(tmp_path, "unit test")
    assert b["integrity"] == "ok" and b["rows"] > 0
    assert (tmp_path / b["path"].split("\\")[-1].split("/")[-1]).exists()
    # The read-only report opens a database file without changing it.
    from flowmerce.modules.seo.maintenance import db_report
    rep = db_report(b["path"])
    assert rep["schemaVersion"] == len(dbmod.MIGRATIONS) and isinstance(rep["integrations"], list)


def test_resync_preview_writes_nothing_and_apply_backs_up_first(monkeypatch, tmp_path):
    latest = add_days(today(), -3)
    frm, to = add_days(latest, -400), add_days(latest, -399)
    _gsc("cpc", frm, "/blogs/synct/r", 1, 10, "api")
    _gsc("cpc", frm, "/blogs/synct/r", 50, 500, "excel")

    def fake_query(b, start, stop, dims, row_limit=25000):
        return [{"keys": [frm, "https://cottonprintclub.com/blogs/synct/r"], "clicks": 4, "impressions": 40, "position": 2.0},
                {"keys": [to, "https://cottonprintclub.com/blogs/synct/r"], "clicks": 6, "impressions": 60, "position": 2.0}]

    backups = []
    monkeypatch.setattr(resync, "gsc_configured", lambda b: True)
    monkeypatch.setattr(sync, "gsc_query", fake_query)
    monkeypatch.setattr(resync, "backup_database", lambda label: backups.append(label) or dbmod.backup_database(tmp_path, label))
    try:
        p = resync.preview("gsc", "cpc", frm, to)
        assert p["writes"] is False and p["daysAdded"] == 1 and p["daysChanged"] == 1 and p["untouchedRows"] == {"excel": 1}
        assert get("SELECT clicks FROM gsc_page_daily WHERE brand_id='cpc' AND source='api' AND date=? AND page='/blogs/synct/r'", frm)["clicks"] == 1
        assert not backups

        r = resync.apply("gsc", "cpc", frm, to)
        assert backups and r["backup"]["integrity"] == "ok"
        assert get("SELECT clicks FROM gsc_page_daily WHERE brand_id='cpc' AND source='api' AND date=? AND page='/blogs/synct/r'", frm)["clicks"] == 4
        assert get("SELECT clicks FROM gsc_page_daily WHERE brand_id='cpc' AND source='excel' AND page='/blogs/synct/r'")["clicks"] == 50
        assert get("SELECT 1 FROM audit_log WHERE action = 'gsc.resync' AND brand_id = 'cpc'")
        with pytest.raises(HttpError):
            resync.preview("gsc", "cpc", to, frm)       # reversed range is refused
    finally:
        run("DELETE FROM gsc_page_daily WHERE brand_id='cpc' AND page LIKE '/blogs/synct/%'")
