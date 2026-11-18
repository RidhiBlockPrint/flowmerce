"""Pull data from connected services into the local database.

Shopify: with Admin API access every article (drafts included) and products are read; without it the
storefront's public feed is used, which only shows live articles.

Rules that protect Flowmerce data:
 - An article's `origin` records where it was FIRST imported from and is never rewritten. Whether it is now
   kept in step through the Admin API is shown separately (it has a shopify_article_id; see articles.decorate).
 - Remote content never overwrites unpublished Flowmerce edits. A live article is refreshed only when the local
   copy was identical to what was live before (someone edited it in Shopify admin). An imported Shopify draft is
   refreshed only while nobody has edited it in Flowmerce (no revision saved by a person).
 - An article that is unpublished in Shopify is never demoted automatically: it is flagged for a person to
   reconcile (articles.decorate -> unpublished_in_shopify) and the change is written to the audit log.

Search Console and GA4: each sync re-reads a recent window (data for the last few days is still settling) and
replaces only live-API rows in that window; demo and manually imported rows are never touched. URL variants of
one page (www/non-www, http/https, ?query, trailing slash) are added together before saving. Days that fall
outside the window because the computer was off are reported as a gap, not filled automatically: filling them
goes through services/resync.py (preview first, then a verified backup, then the write)."""
from __future__ import annotations

import json
import logging
import threading
from contextlib import contextmanager
from datetime import timezone
from typing import Iterator

from ..audit import audit
from ..config import BrandConfig, config
from ..db import Row, all_rows, get, now, run, tx
from ..integrations import shopify
from ..integrations.google import ga4_configured, ga4_report, gsc_configured, gsc_query
from ..integrations.shopify_public import fetch_public_articles, fetch_public_products
from ..integrations.status import mark_attempt, mark_error, mark_pending, mark_success
from ..util import HttpError, add_days, days_between, page_path, parse_iso, sanitize_html, today
from .articles import CONTENT_FIELDS, content_of, create_article, hash_content
from .brands import brand

log = logging.getLogger(__name__)

FIRST_SYNC_DAYS = 480       # the first sync reads about 16 months
GSC_LAG_DAYS = 3            # Search Console data is final about 3 days after the day it describes
GSC_WINDOW_DAYS = 10        # later syncs re-read this many days
GSC_QUERY_DAYS = 28         # page x query table: one rolling 28-day period
GA4_LAG_DAYS = 1
GA4_WINDOW_DAYS = 7
IMPORTED_ORIGINS = ("shopify_admin", "shopify_public")
SOURCE_LABEL = {"shopify": "Shopify", "gsc": "Search Console", "ga4": "GA4"}

_locks: dict[tuple[str, str], threading.Lock] = {}
_locks_guard = threading.Lock()


@contextmanager
def exclusive(source: str, brand_id: str) -> Iterator[None]:
    """One sync per source and brand at a time, whoever starts it (scheduler, Automation or a Sync now button).
    A second request while one is running is refused with 409 instead of interleaving writes."""
    with _locks_guard:
        lock = _locks.setdefault((source, brand_id), threading.Lock())
    if not lock.acquire(blocking=False):
        raise HttpError(409, f"A {SOURCE_LABEL.get(source, source)} sync for this brand is already running.", "sync_running")
    try:
        yield
    finally:
        lock.release()


# ---------------- Shopify ----------------

def _incoming_content(i: dict, base: dict | None) -> dict:
    return {
        "title": i["title"], "handle": i["handle"],
        "primary_keyword": (base or {}).get("primary_keyword", ""),
        "meta_title": i["meta_title"] if i.get("meta_title") is not None else (base or {}).get("meta_title", ""),
        "meta_description": i["meta_description"] if i.get("meta_description") is not None else (base or {}).get("meta_description", ""),
        "summary_html": sanitize_html(i["summary"]), "body_html": sanitize_html(i["body"]),
        "tags": i["tags"], "author": i["author"], "image_url": i["image_url"], "image_alt": i["image_alt"],
    }


def edited_in_flowmerce(article_id: int) -> bool:
    """True when a person has saved a revision of this article in Flowmerce. Imports and syncs save revisions
    without a user, so their presence alone does not count as an edit."""
    return bool(get("SELECT 1 FROM article_revisions WHERE article_id = ? AND user_id IS NOT NULL LIMIT 1", article_id))


def _replace_content(local: Row, remote: dict, rh: str, t: str, live: bool, note: str, action: str, brand_id: str) -> None:
    v = local["version"] + 1
    hashes = "content_hash=?, live_hash=?, approved_hash=?" if live else "content_hash=?"
    hash_args = [rh, rh, rh] if live else [rh]
    run(f"UPDATE articles SET {', '.join(f + '=?' for f in CONTENT_FIELDS)}, {hashes}, version=?, updated_at=? WHERE id=?",
        *[remote[f] for f in CONTENT_FIELDS], *hash_args, v, t, local["id"])
    run("INSERT INTO article_revisions (article_id, version, data_json, content_hash, user_id, note, created_at) VALUES (?,?,?,?,?,?,?)",
        local["id"], v, json.dumps(remote, ensure_ascii=False), rh, None, note, t)
    audit(None, action, "article", local["id"], brand_id, remote["title"])


def _shopify_time(v: str | None) -> str | None:
    """A Shopify timestamp in Flowmerce's stored format (UTC, milliseconds, Z), or None when absent or unreadable."""
    if not v:
        return None
    try:
        t = parse_iso(v)
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return t.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _upsert_articles(brand_id: str, items: list[dict], origin: str) -> dict:
    """Insert new articles and refresh known ones. `origin` is the source of THIS sync; it is stored only on new rows."""
    counts = {"inserted": 0, "updated": 0, "refreshed": 0, "draftsRefreshed": 0, "draftsProtected": 0, "unpublishedInShopify": 0}
    t = now()
    with tx():
        for i in items:
            local = (i["shopify_id"] and get("SELECT * FROM articles WHERE brand_id = ? AND shopify_article_id = ?", brand_id, i["shopify_id"])) \
                or get("SELECT * FROM articles WHERE brand_id = ? AND handle = ?", brand_id, i["handle"])
            created = _shopify_time(i.get("created_at"))
            if not local:
                a = create_article(None, brand_id, _incoming_content(i, None), origin, "published" if i["is_published"] else "draft")
                run("UPDATE articles SET shopify_article_id=?, shopify_published=?, live_hash=?, live_url=?, published_at=?, shopify_synced_at=?, "
                    "created_at=COALESCE(?, created_at) WHERE id=?",
                    i["shopify_id"], 1 if i["is_published"] else 0, a["content_hash"] if i["is_published"] else None, i["url"], i["published_at"], t,
                    created, a["id"])
                counts["inserted"] += 1
                continue
            if created and local["origin"] in IMPORTED_ORIGINS and local["created_at"] != created:
                # Articles that came from Shopify keep Shopify's creation date, not the date Flowmerce first saw them.
                run("UPDATE articles SET created_at = ? WHERE id = ?", created, local["id"])
            now_live = (local["status"] == "scheduled" and i["is_published"] and i["published_at"]
                        and parse_iso(i["published_at"]).timestamp() <= parse_iso(t).timestamp())
            run("""UPDATE articles SET shopify_article_id=COALESCE(?, shopify_article_id), shopify_published=?, live_url=?,
                     published_at=COALESCE(?, published_at), shopify_synced_at=?, status=? WHERE id=?""",
                i["shopify_id"], 1 if i["is_published"] else 0, i["url"], i["published_at"], t,
                "published" if now_live else local["status"], local["id"])
            counts["refreshed"] += 1
            if origin != "shopify_admin":
                continue  # the public feed has no SEO fields or drafts; never use it to replace content
            if local["shopify_published"] and not i["is_published"]:
                # Live before, hidden now. Not demoted automatically: flagged for a person (see articles.decorate).
                counts["unpublishedInShopify"] += 1
                audit(None, "article.unpublished_in_shopify", "article", local["id"], brand_id,
                      f"{i['title']} (Flowmerce status kept: {local['status']})")
            remote = _incoming_content(i, content_of(local))
            rh = hash_content(remote)
            if rh == local["content_hash"]:
                if i["is_published"] and local["live_hash"] != rh:
                    run("UPDATE articles SET live_hash=? WHERE id=?", rh, local["id"])
                continue
            if i["is_published"]:
                clean = local["content_hash"] == local["live_hash"] or (local["status"] == "published" and not local["live_hash"])
                if clean and local["status"] == "published":
                    _replace_content(local, remote, rh, t, True, "Synced: edited directly in Shopify admin", "article.synced_from_shopify", brand_id)
                    counts["updated"] += 1
                elif local["live_hash"] != rh:
                    run("UPDATE articles SET live_hash=? WHERE id=?", rh, local["id"])
                continue
            # Hidden in Shopify and different from the local copy: refresh only an imported draft nobody edited here.
            if (local["status"] in ("draft", "idea") and not local["shopify_published"] and local["origin"] in IMPORTED_ORIGINS):
                if edited_in_flowmerce(local["id"]):
                    counts["draftsProtected"] += 1
                else:
                    _replace_content(local, remote, rh, t, False, "Synced: Shopify draft changed", "article.synced_from_shopify_draft", brand_id)
                    counts["draftsRefreshed"] += 1
    return counts


def _upsert_products(brand_id: str, items: list[dict], source: str, prune: bool = True) -> None:
    """Upsert products; with prune, products no longer returned by Shopify are removed. Pruning is skipped when the
    listing stopped at its page limit, because then 'not returned' does not mean 'gone'."""
    t = now()
    with tx():
        for p in items:
            run("""INSERT INTO products (brand_id, handle, title, url, image_url, product_type, synced_at, source) VALUES (?,?,?,?,?,?,?,?)
                   ON CONFLICT(brand_id, handle) DO UPDATE SET title=excluded.title, url=excluded.url, image_url=excluded.image_url,
                     product_type=excluded.product_type, synced_at=excluded.synced_at, source=excluded.source""",
                brand_id, p["handle"], p["title"], p["url"], p["image"], p["type"], t, source)
        if items and prune:
            run("DELETE FROM products WHERE brand_id = ? AND synced_at < ?", brand_id, t)


def _admin_items(b: BrandConfig, blog: dict, lst: list[dict]) -> list[dict]:
    return [{
        "shopify_id": a["id"], "handle": a["handle"], "title": a["title"], "body": a.get("body") or "",
        "summary": a.get("summary") or "", "tags": ", ".join(a.get("tags") or []), "author": (a.get("author") or {}).get("name", ""),
        "image_url": (a.get("image") or {}).get("url", ""), "image_alt": (a.get("image") or {}).get("altText") or "",
        "meta_title": (a.get("seoTitle") or {}).get("value"), "meta_description": (a.get("seoDescription") or {}).get("value"),
        "is_published": a["isPublished"], "published_at": a.get("publishedAt"), "created_at": a.get("createdAt"),
        "url": f"https://{b.storefront_domain}/blogs/{blog['handle']}/{a['handle']}",
    } for a in lst]


def sync_shopify(brand_id: str) -> dict:
    b = brand(brand_id)
    with exclusive("shopify", brand_id):
        if shopify.configured(b):
            mark_attempt("shopify", brand_id, "admin_api")
            try:
                blog = shopify.find_blog(b)
                lst = shopify.list_articles(b, blog["id"])
                items = _admin_items(b, blog, lst)
                res = _upsert_articles(brand_id, items, "shopify_admin")
                run("UPDATE articles SET shopify_blog_id = ? WHERE brand_id = ? AND shopify_blog_id IS NULL", blog["id"], brand_id)
                products = shopify.list_products(b)
                p_trunc, a_trunc = bool(getattr(products, "truncated", False)), bool(getattr(lst, "truncated", False))
                if p_trunc or a_trunc:
                    log.warning("Shopify listing for %s stopped at its page limit (articles: %s, products: %s)", brand_id, a_trunc, p_trunc)
                _upsert_products(brand_id, products, "shopify_admin", prune=not p_trunc)
                published = sum(1 for i in items if i["is_published"])
                details = {"blog": blog["handle"], "articles": len(lst), "published": published, "drafts": len(lst) - published,
                           "products": len(products), "rows": len(lst) + len(products), "articlesTruncated": a_trunc, "productsTruncated": p_trunc, **res}
                mark_success("shopify", brand_id, "admin_api", details)
                return {"mode": "admin_api", **details}
            except Exception as e:
                mark_error("shopify", brand_id, "admin_api", getattr(e, "message", e))
                raise
        mark_pending("shopify", brand_id, f"Set {brand_id.upper()}_SHOPIFY_CLIENT_ID and _CLIENT_SECRET (or {brand_id.upper()}_SHOPIFY_ADMIN_TOKEN) "
                                          "to read drafts and SEO fields and to save hidden drafts.")
        if not config.public_feed_sync:
            raise RuntimeError("Shopify Admin API is not set up and the public feed sync is turned off.")
        mark_attempt("shopify_public", brand_id, "public_feed")
        try:
            lst = fetch_public_articles(b)
            items = [{
                "shopify_id": None, "handle": a["handle"], "title": a["title"], "body": a["body_html"], "summary": a["summary_html"],
                "tags": ", ".join(a["tags"]), "author": a["author"], "image_url": "", "image_alt": "", "meta_title": None,
                "meta_description": None, "is_published": True, "published_at": a["published_at"] or None, "url": a["url"],
            } for a in lst]
            res = _upsert_articles(brand_id, items, "shopify_public")
            products = fetch_public_products(b)
            _upsert_products(brand_id, products, "shopify_public")
            details = {"articles": len(lst), "products": len(products), "rows": len(lst) + len(products), **res}
            mark_success("shopify_public", brand_id, "public_feed", details)
            return {"mode": "public_feed", **details}
        except Exception as e:
            mark_error("shopify_public", brand_id, "public_feed", e)
            raise


# ---------------- Search Console ----------------

def aggregate_gsc(rows: list[dict], by: str) -> dict[tuple[str, str], dict]:
    """Add Search Console rows together per (date, page path) when by='date_page', or per (page path, query) when
    by='page_query'. Several URL variants map to one path; their clicks and impressions are summed and the position
    is averaged weighted by impressions (a plain average when there are no impressions)."""
    acc: dict[tuple[str, str], dict] = {}
    for r in rows:
        k0, k1 = r["keys"][0], r["keys"][1]
        key = (k0, page_path(k1)) if by == "date_page" else (page_path(k0), k1)
        m = acc.setdefault(key, {"clicks": 0.0, "impressions": 0.0, "pw": 0.0, "ps": 0.0, "n": 0})
        imp = float(r.get("impressions") or 0)
        pos = float(r.get("position") or 0)
        m["clicks"] += float(r.get("clicks") or 0)
        m["impressions"] += imp
        m["pw"] += pos * imp
        m["ps"] += pos
        m["n"] += 1
    out: dict[tuple[str, str], dict] = {}
    for key, m in acc.items():
        c, i = int(round(m["clicks"])), int(round(m["impressions"]))
        out[key] = {"clicks": c, "impressions": i, "ctr": c / i if i else 0.0,
                    "position": m["pw"] / m["impressions"] if m["impressions"] else (m["ps"] / m["n"] if m["n"] else 0.0)}
    return out


def fetch_gsc_pages(b: BrandConfig, start: str, end: str) -> tuple[dict[tuple[str, str], dict], int]:
    """Daily rows per page for the range, variants added together. Returns (rows by (date, path), raw row count)."""
    raw = gsc_query(b, start, end, ["date", "page"])
    return aggregate_gsc(raw, "date_page"), len(raw)


def write_gsc_pages(brand_id: str, start: str, end: str, rows: dict[tuple[str, str], dict], t: str) -> None:
    """Replace the live-API rows of the range. Demo and imported rows are never touched."""
    run("DELETE FROM gsc_page_daily WHERE brand_id = ? AND source = 'api' AND date BETWEEN ? AND ?", brand_id, start, end)
    for (day, path), m in rows.items():
        run("""INSERT INTO gsc_page_daily (brand_id, date, page, clicks, impressions, ctr, position, source, source_timestamp, imported_at)
               VALUES (?,?,?,?,?,?,?,'api',?,?)""", brand_id, day, path, m["clicks"], m["impressions"], m["ctr"], m["position"], t, t)


def _window(table: str, brand_id: str, end: str, window_days: int) -> tuple[str, dict | None]:
    """Start of this sync's range, and the gap (days after the last stored live-API day that this range will not
    cover), if any. A gap appears when the computer was off for longer than the window."""
    mx = (get(f"SELECT MAX(date) mx FROM {table} WHERE brand_id = ? AND source = 'api'", brand_id) or {}).get("mx")
    if not mx:
        return add_days(end, -FIRST_SYNC_DAYS), None
    start = add_days(end, -window_days)
    gap_to = add_days(start, -1)
    if mx < gap_to:
        frm = add_days(mx, 1)
        return start, {"from": frm, "to": gap_to, "days": days_between(frm, gap_to) + 1}
    return start, None


def sync_gsc(brand_id: str) -> dict:
    """Search Console data is final ~3 days after the day it describes, so the window ends 3 days ago.
    The first sync takes 16 months; later syncs re-read the last 10 days."""
    b = brand(brand_id)
    if not gsc_configured(b):
        mark_pending("gsc", brand_id, "Set GOOGLE_SERVICE_ACCOUNT_FILE and add the service account to the Search Console property.")
        raise RuntimeError("Search Console is not set up for this brand.")
    with exclusive("gsc", brand_id):
        mark_attempt("gsc", brand_id, "api")
        try:
            end = add_days(today(), -GSC_LAG_DAYS)
            start, gap = _window("gsc_page_daily", brand_id, end, GSC_WINDOW_DAYS)
            pages, raw_pages = fetch_gsc_pages(b, start, end)
            q_start = add_days(end, -(GSC_QUERY_DAYS - 1))
            q_raw = gsc_query(b, q_start, end, ["page", "query"])
            queries = aggregate_gsc(q_raw, "page_query")
            t = now()
            with tx():
                write_gsc_pages(brand_id, start, end, pages, t)
                run("DELETE FROM gsc_query_period WHERE brand_id = ? AND source = 'api'", brand_id)
                for (path, query), m in queries.items():
                    run("""INSERT INTO gsc_query_period (brand_id, start_date, end_date, page, query, clicks, impressions, ctr, position, source, source_timestamp, imported_at)
                           VALUES (?,?,?,?,?,?,?,?,?,'api',?,?)""", brand_id, q_start, end, path, query, m["clicks"], m["impressions"], m["ctr"], m["position"], t, t)
            if gap:
                log.warning("Search Console for %s has no stored data from %s to %s; run a reviewed recovery to fill it", brand_id, gap["from"], gap["to"])
            details = {"start": start, "end": end, "pageRows": raw_pages, "storedRows": len(pages), "queryRows": len(q_raw),
                       "rows": len(pages), "dataThrough": max((d for d, _ in pages), default=None), "gap": gap}
            mark_success("gsc", brand_id, "api", details)
            return details
        except Exception as e:
            mark_error("gsc", brand_id, "api", getattr(e, "message", e))
            raise


# ---------------- GA4 ----------------

def aggregate_ga4(rows: list[dict]) -> dict[tuple[str, str], dict]:
    """Several landing-page variants of one path are summed per (date, path)."""
    merged: dict[tuple[str, str], dict] = {}
    for r in rows:
        m = merged.setdefault((r["date"], r["path"]), {"s": 0.0, "e": 0.0, "d": 0.0, "k": 0.0})
        m["s"] += r["sessions"]; m["e"] += r["engaged"]; m["d"] += r["duration"]; m["k"] += r["key_events"]
    return merged


def fetch_ga4_pages(b: BrandConfig, start: str, end: str) -> tuple[dict[tuple[str, str], dict], int]:
    raw = ga4_report(b, start, end)
    return aggregate_ga4(raw), len(raw)


def write_ga4_pages(brand_id: str, start: str, end: str, merged: dict[tuple[str, str], dict], t: str) -> None:
    """Replace the live-API rows of the range. Demo and imported rows are never touched."""
    run("DELETE FROM ga4_page_daily WHERE brand_id = ? AND source = 'api' AND date BETWEEN ? AND ?", brand_id, start, end)
    for (d, p), m in merged.items():
        run("""INSERT INTO ga4_page_daily (brand_id, date, page_path, sessions, engaged_sessions, engagement_rate, avg_engagement_seconds, key_events, source, source_timestamp, imported_at)
               VALUES (?,?,?,?,?,?,?,?,'api',?,?)""",
            brand_id, d, p, int(m["s"]), int(m["e"]), m["e"] / m["s"] if m["s"] else 0, m["d"] / m["s"] if m["s"] else 0, m["k"], t, t)


def sync_ga4(brand_id: str) -> dict:
    b = brand(brand_id)
    if not ga4_configured(b):
        mark_pending("ga4", brand_id, f"Set {brand_id.upper()}_GA4_PROPERTY_ID and give the service account Viewer access.")
        raise RuntimeError("GA4 is not set up for this brand.")
    with exclusive("ga4", brand_id):
        mark_attempt("ga4", brand_id, "api")
        try:
            end = add_days(today(), -GA4_LAG_DAYS)
            start, gap = _window("ga4_page_daily", brand_id, end, GA4_WINDOW_DAYS)
            merged, raw = fetch_ga4_pages(b, start, end)
            with tx():
                write_ga4_pages(brand_id, start, end, merged, now())
            if gap:
                log.warning("GA4 for %s has no stored data from %s to %s; run a reviewed recovery to fill it", brand_id, gap["from"], gap["to"])
            details = {"start": start, "end": end, "rows": len(merged), "rawRows": raw,
                       "dataThrough": max((d for d, _ in merged), default=None), "gap": gap}
            mark_success("ga4", brand_id, "api", details)
            return details
        except Exception as e:
            mark_error("ga4", brand_id, "api", getattr(e, "message", e))
            raise


def products_for(brand_id: str) -> list[Row]:
    return all_rows("SELECT handle, title, url, image_url, product_type, source FROM products WHERE brand_id = ? ORDER BY title", brand_id)
