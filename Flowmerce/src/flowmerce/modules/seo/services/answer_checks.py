"""Checks an article is ready for search engines AND for answer engines and AI assistants. Owner request 2026-11-20.

Five groups, each a list of pass / fail checks with a plain fix for every failure:
  fields  every field Shopify and the dashboard need is filled (title, URL handle, SEO title, meta description,
          summary, tags, featured image and its alt text, primary keyword, enough words)
  seo     the dashboard's SEO checks (frontend/src/lib/seo.js): keyword placement, headings, internal links
  aeo     Answer Engine Optimisation: a short direct answer at the top, question-style headings, an FAQ, lists or tables
          that answer engines can lift
  geo     Generative Engine Optimisation: specific figures and facts, the brand named, sources recorded, links to the
          products the article is about, so AI-written answers can cite it
  llmo    Large Language Model Optimisation: short paragraphs, descriptive headings, images with alt text, a summary

Pure: it reads the article row only (plus the brand's name), never the network. The automatic blog pipeline
(services/auto_blog.py) runs it after Claude's draft; failures Claude can fix are sent back once as a revision request.
"""
from __future__ import annotations

import json
import re
from typing import Any

Row = dict[str, Any]

GROUPS = {"fields": "Required fields", "seo": "SEO", "aeo": "Answer engines (AEO)", "geo": "AI search (GEO)", "llmo": "AI readability (LLMO)"}
MIN_WORDS = 900
MIN_INLINE_IMAGES = 2
QUESTION_START = re.compile(r"^(how|what|why|when|where|which|who|can|do|does|is|are|should|will)\b", re.I)
FIGURE = re.compile(r"\b\d+(?:[.,]\d+)?\s?(?:%|cm|mm|m|in|inch|inches|ft|kg|g|°|x|×|thread|gsm|years?|days?|weeks?|hours?|minutes?)?\b", re.I)


def _strip(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html or "").replace("&nbsp;", " ")).strip()


def _words(text: str) -> int:
    return len(text.split()) if text else 0


def _tags(html: str, tag: str) -> list[str]:
    return [_strip(m) for m in re.findall(rf"<{tag}\b[^>]*>([\s\S]*?)</{tag}>", html or "", re.I)]


def _has(text: str, kw: str) -> bool:
    return bool(kw) and kw.lower() in (text or "").lower()


def _notes(a: Row) -> dict[str, Any]:
    try:
        v = json.loads(a.get("ai_notes_json") or "{}")
    except ValueError:
        return {}
    return v if isinstance(v, dict) else {}


def check(a: Row, brand_name: str = "", storefront: str = "") -> dict[str, Any]:
    """All checks for one article: {score, groups: {key: {label, score, checks}}, failures: [check]}.
    A check is {id, group, label, ok, detail, fix}; `fix` is an instruction a writer (or Claude) can act on."""
    body = a.get("body_html") or ""
    text = _strip(body)
    kw = (a.get("primary_keyword") or "").strip()
    words = _words(text)
    paras = [p for p in _tags(body, "p") if p]
    h2s, h3s = _tags(body, "h2"), _tags(body, "h3")
    imgs = re.findall(r"<img\b[^>]*>", body, re.I)
    imgs_alt = [i for i in imgs if re.search(r'\balt="[^"]+"', i, re.I)]
    hrefs = re.findall(r'<a\s[^>]*href="([^"]+)"', body, re.I)
    internal = [h for h in hrefs if h.startswith("/") or (storefront and storefront in h)]
    products = [h for h in internal if "/products/" in h or "/collections/" in h]
    tags = [t for t in re.split(r"\s*,\s*", a.get("tags") or "") if t]
    md = a.get("meta_description") or ""
    first = paras[0] if paras else ""
    notes = _notes(a)
    out: list[dict[str, Any]] = []

    def add(group: str, cid: str, label: str, ok: bool, detail: str, fix: str) -> None:
        out.append({"id": cid, "group": group, "label": label, "ok": bool(ok), "detail": detail, "fix": "" if ok else fix})

    # fields
    add("fields", "title", "Title", bool((a.get("title") or "").strip()), "", "Write a title.")
    add("fields", "handle", "URL handle", bool((a.get("handle") or "").strip()), f"/{a.get('handle') or ''}", "Set a short URL handle.")
    add("fields", "kw", "Primary keyword", bool(kw), kw, "Set the primary keyword the article should rank for.")
    add("fields", "meta-title", "SEO title", 0 < len(a.get("meta_title") or "") <= 60, f"{len(a.get('meta_title') or '')}/60",
        "Write an SEO title of 60 characters or fewer that contains the primary keyword.")
    add("fields", "meta-desc", "Meta description", 120 <= len(md) <= 160, f"{len(md)} characters",
        "Write a meta description of 120-160 characters that contains the primary keyword.")
    add("fields", "summary", "Blog listing summary", bool(_strip(a.get("summary_html") or "")), "", "Write a one- or two-sentence summary for the blog listing.")
    add("fields", "tags", "Tags", len(tags) >= 3, f"{len(tags)} tags", "Add 3-6 short tags.")
    add("fields", "image", "Featured image with alt text", bool(a.get("image_url")) and bool(a.get("image_alt")), "",
        "Use a product photo from the product list as the featured image and describe it in image_alt.")
    add("fields", "length", "Length", words >= MIN_WORDS, f"{words:,} words", f"Expand the article to at least {MIN_WORDS} words of useful text (never pad).")
    # seo
    add("seo", "kw-title", "Keyword in the title", _has(a.get("title") or "", kw), "", "Put the exact primary keyword in the title.")
    add("seo", "kw-meta", "Keyword in the meta description", _has(md, kw), "", "Put the exact primary keyword in the meta description.")
    add("seo", "kw-first", "Keyword in the first paragraph", _has(first, kw), "", "Use the exact primary keyword in the first paragraph.")
    add("seo", "kw-h2", "Keyword in a subheading", any(_has(h, kw) for h in h2s), "", "Use the exact primary keyword in at least one <h2>.")
    add("seo", "h2", "Subheadings", len(h2s) >= 2, f"{len(h2s)} H2", "Structure the body with at least 2 <h2> headings.")
    add("seo", "no-h1", "No H1 in the body", not re.search(r"<h1\b", body, re.I), "", "Remove any <h1> from the body.")
    add("seo", "internal", "Internal links", len(internal) >= 2, f"{len(internal)} links", "Add at least 2 internal links from the link list.")
    # aeo
    first_words = _words(first)
    add("aeo", "answer-first", "Direct answer at the top", 30 <= first_words <= 90 and _has(first, kw), f"{first_words} words",
        "Open with a 40-70 word paragraph that answers the reader's main question directly and contains the primary keyword.")
    questions = [h for h in h2s + h3s if h.endswith("?") or QUESTION_START.match(h)]
    add("aeo", "questions", "Question-style headings", len(questions) >= 3, f"{len(questions)} questions",
        "Phrase at least 3 headings as the questions readers ask (How..., What..., Which...?), each answered right below.")
    faq = any(re.search(r"faq|frequently asked|questions", h, re.I) for h in h2s)
    add("aeo", "faq", "FAQ section", faq, "", "Add an FAQ: an <h2> 'Frequently asked questions' with 3-5 <h3> questions the body does not already answer.")
    lists = len(re.findall(r"<(ul|ol|table)\b", body, re.I))
    add("aeo", "lists", "Lists or a table", lists >= 1, f"{lists}", "Add a list or a comparison table that answers engines can quote.")
    # geo
    figures = len(FIGURE.findall(text))
    add("geo", "figures", "Specific facts and figures", figures >= 5, f"{figures} figures",
        "Add specific, checkable facts: sizes, materials, care temperatures, thread counts, dates (only ones the brand documents support).")
    add("geo", "brand", "Brand named", _has(text, brand_name) if brand_name else True, brand_name, f"Mention {brand_name} by name where it helps the reader.")
    add("geo", "sources", "Sources recorded", bool(notes.get("sources")), f"{len(notes.get('sources') or [])}",
        "List the brand documents and sources you relied on in notes.sources.")
    add("geo", "products", "Links to the products discussed", len(products) >= 2, f"{len(products)} product links",
        "Link at least 2 relevant products or collections from the link list where they help the reader.")
    # llmo
    long_paras = [p for p in paras if _words(p) > 120]
    avg = round(sum(_words(p) for p in paras) / len(paras)) if paras else 0
    add("llmo", "paragraphs", "Short paragraphs", bool(paras) and not long_paras and avg <= 80, f"average {avg} words",
        "Split long paragraphs: keep each under about 80 words and none over 120.")
    vague = [h for h in h2s if _words(h) < 3]
    add("llmo", "headings", "Descriptive headings", bool(h2s) and not vague, f"{len(vague)} vague", "Make every <h2> say what its section answers (3+ words).")
    add("llmo", "images", "Images with alt text", len(imgs_alt) >= MIN_INLINE_IMAGES and len(imgs_alt) == len(imgs), f"{len(imgs_alt)}/{len(imgs)} with alt",
        f"Include at least {MIN_INLINE_IMAGES} product images in the body, each with descriptive alt text.")
    sentences = len(re.findall(r"[.!?](\s|$)", _strip(a.get("summary_html") or "")))
    add("llmo", "summary", "Short summary", 1 <= sentences <= 3, f"{sentences} sentences", "Keep the summary to one or two sentences.")

    groups: dict[str, Any] = {}
    for g, label in GROUPS.items():
        cs = [c for c in out if c["group"] == g]
        groups[g] = {"label": label, "score": round(100 * sum(c["ok"] for c in cs) / len(cs)) if cs else 100, "checks": cs}
    failures = [c for c in out if not c["ok"]]
    return {"score": round(100 * sum(c["ok"] for c in out) / len(out)), "groups": groups, "failures": failures, "words": words,
            "images": len(imgs)}


# Failures only a person (or a later step) can fix; everything else is sent to Claude as a revision request.
NOT_FOR_CLAUDE = {"image", "images", "sources", "kw"}


def revision_request(result: dict[str, Any]) -> str:
    """The failures Claude can fix, as one change request. Empty when there is nothing for Claude to fix."""
    fixes = [f"- {c['label']}: {c['fix']}" for c in result["failures"] if c["id"] not in NOT_FOR_CLAUDE and c["fix"]]
    if not fixes:
        return ""
    return ("Automatic quality check before this article is scheduled. Fix these points and keep everything else, "
            "including every <img> and link already in the body:\n" + "\n".join(fixes))
