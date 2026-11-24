"""Claude (Anthropic Messages API) for topic research and first drafts.

It runs the requests this dashboard makes, and each one is logged as a workflow run or an AI job. It has no
view of Claude agents running elsewhere; those report progress through the job callbacks on
POST /api/hooks/workflow (see docs/decisions/0009-ai-job-bridge.md).

Output is constrained to JSON with structured outputs (output_config.format). Server-side refusal
fallbacks are on by default (CLAUDE_FALLBACKS=false turns them off).

Failures are raised as ClaudeError (a RuntimeError, so older callers keep working) with a kind, a retryable
flag and, for rate limits, the server's Retry-After. This module retries only what is safe to retry: rate
limits, 5xx and connection errors, a bounded number of times with exponential backoff. It never retries
authentication or invalid-request errors, and it never retries a timeout, because the request may already
have been processed (the error is marked ambiguous so a person decides)."""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import date

from ..config import BrandConfig, config
from ..services.knowledge import brand_knowledge   # a leaf module: it only reads the brand's files
from ..util import HttpError

log = logging.getLogger(__name__)

_client = None
_client_lock = threading.Lock()
_usage = threading.local()
MAX_BACKOFF_SECONDS = 30.0


class ClaudeError(RuntimeError):
    """A classified Claude failure. kind: auth, rate_limit, invalid_request, refusal, truncated, invalid_output,
    server, connection, timeout. ambiguous=True means the request may already have been executed."""

    def __init__(self, message: str, kind: str, retryable: bool = False, retry_after: float | None = None, ambiguous: bool = False):
        super().__init__(message)
        self.kind = kind
        self.retryable = retryable
        self.retry_after = retry_after
        self.ambiguous = ambiguous


def configured() -> bool:
    return bool(config.anthropic_api_key)


def _get_client():
    global _client
    if not configured():
        raise HttpError(412, "ANTHROPIC_API_KEY is not set on the server.", "pending_setup")
    with _client_lock:
        if _client is None:
            import anthropic
            # Retries are done here (bounded, classified), so the SDK's own are off.
            _client = anthropic.Anthropic(api_key=config.anthropic_api_key, timeout=float(config.claude_timeout), max_retries=0)
        return _client


def take_usage() -> dict:
    """Metadata of the last Claude call made on this thread (model, tokens, request id, attempts, duration), then clear it.
    Never contains the prompt, the key or the answer."""
    u = getattr(_usage, "last", None) or {}
    _usage.last = None
    return u


def _retry_after(e: object) -> float | None:
    try:
        v = e.response.headers.get("retry-after")  # type: ignore[attr-defined]
        return max(0.0, float(v)) if v is not None else None
    except (AttributeError, TypeError, ValueError):
        return None


def _classify(e: Exception) -> ClaudeError:
    import anthropic
    if isinstance(e, anthropic.APITimeoutError):   # a subclass of APIConnectionError: test it first
        return ClaudeError("Claude did not answer in time. The request may still have been processed, so it was not retried automatically.", "timeout", ambiguous=True)
    if isinstance(e, anthropic.APIConnectionError):
        return ClaudeError("Could not reach the Claude API.", "connection", retryable=True)
    if isinstance(e, (anthropic.AuthenticationError, anthropic.PermissionDeniedError)):
        return ClaudeError("Claude rejected the API key or its permissions. Check ANTHROPIC_API_KEY.", "auth")
    if isinstance(e, anthropic.RateLimitError):
        return ClaudeError("Claude rate limit reached (429).", "rate_limit", retryable=True, retry_after=_retry_after(e))
    if isinstance(e, (anthropic.BadRequestError, anthropic.NotFoundError, anthropic.UnprocessableEntityError)):
        return ClaudeError(f"Claude rejected the request ({getattr(e, 'status_code', 400)}): {getattr(e, 'message', 'invalid request')}", "invalid_request")
    if isinstance(e, anthropic.APIStatusError):
        status = getattr(e, "status_code", 0)
        return ClaudeError(f"Claude API error {status}: {getattr(e, 'message', '')}", "server" if status >= 500 else "invalid_request",
                           retryable=status in (408, 409, 425) or status >= 500, retry_after=_retry_after(e))
    return ClaudeError(f"Unexpected Claude error: {type(e).__name__}", "server")


def _structured(system: str | list[dict], prompt: str | list[dict], schema: dict, effort: str, max_tokens: int = 32000) -> tuple[dict, str]:
    """`prompt` is text, or a list of content blocks (text and images) for a request that shows Claude pictures."""
    import anthropic
    client = _get_client()
    extra: dict = {"output_config": {"effort": effort, "format": {"type": "json_schema", "schema": schema}}}
    params = dict(model=config.claude_model, max_tokens=max_tokens, thinking={"type": "adaptive"}, system=system,
                  messages=[{"role": "user", "content": prompt}])
    started, attempt, message = time.monotonic(), 0, None
    while True:
        attempt += 1
        try:
            if config.claude_fallbacks:
                extra["fallbacks"] = "default"
                with client.beta.messages.stream(**params, betas=["server-side-fallback-2026-07-01"], extra_body=extra) as stream:
                    message = stream.get_final_message()
            else:
                with client.messages.stream(**params, extra_body=extra) as stream:
                    message = stream.get_final_message()
            break
        except anthropic.AnthropicError as e:
            err = _classify(e)
            if not err.retryable or attempt > config.claude_max_retries:
                log.warning("Claude call failed: kind=%s attempts=%d", err.kind, attempt)
                raise err from e
            wait = min(MAX_BACKOFF_SECONDS, err.retry_after if err.retry_after is not None else 2.0 ** attempt)
            log.info("Claude call retrying after %s: attempt %d, waiting %.1fs", err.kind, attempt, wait)
            time.sleep(wait)
    u = getattr(message, "usage", None)
    _usage.last = {"model": message.model, "requestId": getattr(message, "_request_id", None), "attempts": attempt,
                   "inputTokens": getattr(u, "input_tokens", None), "outputTokens": getattr(u, "output_tokens", None),
                   "cacheWriteTokens": getattr(u, "cache_creation_input_tokens", None) or 0,
                   "cacheReadTokens": getattr(u, "cache_read_input_tokens", None) or 0,
                   "durationMs": int((time.monotonic() - started) * 1000), "stopReason": message.stop_reason}
    log.info("Claude call finished: %s", _usage.last)
    if message.stop_reason == "refusal":
        raise ClaudeError("Claude declined this request (refusal). Rephrase the topic and retry.", "refusal")
    if message.stop_reason == "max_tokens":
        raise ClaudeError("Claude ran out of output tokens before finishing. Retry or narrow the request.", "truncated")
    text = "".join(b.text for b in message.content if getattr(b, "type", "") == "text")
    try:
        data = json.loads(text)
    except ValueError as e:
        raise ClaudeError("Claude returned output that is not valid JSON.", "invalid_output") from e
    if not isinstance(data, dict):
        raise ClaudeError("Claude returned JSON that is not an object.", "invalid_output")
    return data, message.model


# ---------------------------------------------------------------- the system prompt

def _brand_system(b: BrandConfig, v: dict) -> list[dict]:
    """System prompt as two blocks. The first (role, ground rules and the brand's own documents) is identical for every
    request of a brand, so it is cached. The second holds what people edit on the dashboard (voice fields and standing
    instructions); it sits after the cache breakpoint, so editing it never invalidates the cached documents."""
    docs = brand_knowledge(b.id)
    head = "\n".join([
        f"You are the SEO content strategist and blog writer for {b.name} ({b.storefront_domain}), an online store selling hand block-printed cotton home textiles.",
        "Write for people first and search engines second. Do not invent statistics, awards, certifications, prices, shipping promises, reviews, "
        "quotes, product facts or URLs. If a fact about the store is not given to you, leave it out or list it under notes.needs_confirmation.",
        "Internal business figures (sales, revenue, order counts, shares) are background only: never put them in public article text.",
        "",
        f"{b.name}'s own brand documents follow. They are your operating specification: follow their voice, vocabulary, banned words, "
        "claims rules and approved article shape exactly.",
        "Some documents describe tools and steps you do not have here (Shopify or Dropbox connectors, saving drafts, publishing, approval gates). "
        "In this setting you only return the JSON asked for; Flowmerce saves it as an unpublished draft and people review and publish it. "
        "Put anything those steps need a person to check under notes.",
        "Approval in this setup: the owner has allowed Flowmerce to approve topics and drafts automatically and save them as hidden "
        "Shopify drafts. Going live still needs a person. Do not list missing topic or draft approvals as a problem; do list facts to confirm.",
    ])
    first: dict = {"type": "text", "text": f"{head}\n\n{docs}" if docs else head}
    if docs:
        first["cache_control"] = {"type": "ephemeral"}
    tail = [
        f"Voice note from the dashboard: {v['voice']}" if v.get("voice") else "",
        f"Audience note from the dashboard: {v['audience']}" if v.get("audience") else "",
        f"Never: {v['avoid']}" if v.get("avoid") else "",
    ]
    standing = str(v.get("claudeInstructions") or "").strip()
    if standing:
        tail += ["", "Standing instructions from the team (follow them; where they conflict with the documents they win, "
                     "except that you still never invent facts):", standing]
    blocks = [first]
    tail_text = "\n".join(tail).strip()
    if tail_text:
        blocks.append({"type": "text", "text": tail_text})
    return blocks


def _events_lines(events: list[dict] | None) -> list[str]:
    if not events:
        return []
    return ["", "Upcoming events and seasons (event date, name, the latest date an article for it should be live):",
            *[f"- {e['date']}: {e['name']} (publish by {e['publish_by']})" + (f" - {e['note']}" if e.get("note") else "") for e in events[:20]]]


# ---------------------------------------------------------------- topics

TOPIC_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["title", "primary_keyword", "secondary_keywords", "intent", "rationale"],
    "properties": {
        "title": {"type": "string"}, "primary_keyword": {"type": "string"},
        "secondary_keywords": {"type": "array", "items": {"type": "string"}},
        "intent": {"type": "string", "enum": ["informational", "commercial", "transactional", "navigational"]},
        "rationale": {"type": "string"},
    }}


def research_topics(b: BrandConfig, v: dict, existing_titles: list[str], products: list[str], queries: list[str], count: int, focus: str = "",
                    events: list[dict] | None = None) -> tuple[dict, str]:
    schema = {"type": "object", "additionalProperties": False, "required": ["topics"],
              "properties": {"topics": {"type": "array", "items": TOPIC_SCHEMA}}}
    parts = [
        f"Today is {date.today().isoformat()}. Propose {count} new blog topics for {b.name}.",
        f"Focus: {focus}" if focus else "",
        "Each topic needs one primary keyword a shopper would actually type, 2-5 secondary keywords, the search intent, "
        "and one or two sentences on why it fits this store and this moment.",
        "Prefer topics that fit the brand documents' content pillars and gaps, and upcoming events whose publish-by date is still ahead.",
        "Do not repeat or closely overlap these existing articles:",
        *[f"- {t}" for t in existing_titles[:80]],
        ("\nProducts the store sells (link-worthy):\n" + "\n".join(f"- {p}" for p in products[:60])) if products else "",
        ("\nSearch queries that already bring visitors to the blog (from Search Console):\n" + "\n".join(f"- {q}" for q in queries[:40])) if queries else "",
        *_events_lines(events),
        "You have no keyword-volume data: do not state or guess search volumes.",
    ]
    return _structured(_brand_system(b, v), "\n".join(p for p in parts if p), schema, "medium")


# ---------------------------------------------------------------- drafts

# The dashboard's SEO score (frontend/src/lib/seo.js). Keep the two in step.
SEO_RULES = """The dashboard scores every article with these checks. Meet all of them:
- title: 30-70 characters, contains the primary keyword (the exact phrase, any case).
- meta_title: 60 characters or fewer, contains the primary keyword.
- meta_description: 120-160 characters (aim for 140-155), contains the primary keyword, says what the reader gets.
- body_html: the exact primary keyword appears in the first <p> and in at least one <h2>; at least 2 <h2> headings; no <h1> (the theme renders the title).
- body_html: at least 900 words of useful text (usually 1,200-1,800). Never pad.
- body_html: at least 2 internal links (aim for 3-8, never more than 10: link only where it helps the reader), with hrefs copied exactly from the link list below, and descriptive anchor text. Do not link the same page twice.
- handle: lowercase words joined by hyphens, 75 characters or fewer, containing the main words of the primary keyword.
- image_url: the featured image. Copy the image URL of the most relevant product from the product list exactly, or "" if none fits.
- image_alt: describe what that product photo shows, using its product name; not a keyword list. Empty when image_url is empty.
- Prefer no inline <img>. If you add one, it needs alt text and its src must be a product image from the list."""

BODY_HTML_RULES = ("body_html: clean HTML using only <h2>, <h3>, <p>, <ul>, <ol>, <li>, <strong>, <em>, <a>, <blockquote>, "
                   "<table>, <thead>, <tbody>, <tr>, <th>, <td>. No inline styles, no scripts. Open with a short answer paragraph "
                   "(40-70 words) that answers the main question and contains the primary keyword. Use the article shape the brand "
                   "documents approve. Add an FAQ (an <h2> with <h3> questions) only for questions the body does not already answer.")

NOTES_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["secondary_keywords", "needs_confirmation", "recommendations", "technical_checks", "sources", "next_article", "image_brief"],
    "properties": {
        "secondary_keywords": {"type": "array", "items": {"type": "string"}},
        "needs_confirmation": {"type": "array", "items": {"type": "string"}},
        "recommendations": {"type": "array", "items": {"type": "string"}},
        "technical_checks": {"type": "array", "items": {"type": "string"}},
        "sources": {"type": "array", "items": {"type": "string"}},
        "next_article": {"type": "string"},
        "image_brief": {"type": "string"},
    }}
NOTES_RULES = """notes (shown to the team beside the draft, never published):
- secondary_keywords: the related terms the article covers.
- needs_confirmation: every claim, fact or brand decision a person must confirm before publishing (open questions from the brand documents that this article touches, facts you could not verify). Be specific.
- recommendations: concrete actions that would make this article or its results better (photos to take, older posts that should link here, a product page to fix, outreach ideas). At most 8.
- technical_checks: checks an admin should do in Shopify or Search Console for this article (indexing, schema the theme already outputs, broken pages the documents mention).
- sources: the brand documents (by file name) and any external sources you relied on. Never invent a URL.
- next_article: the next helpful article in the reader's journey, as a working title.
- image_brief: if no product photo fits, a short brief for the photo to take; otherwise ""."""

ARTICLE_FIELDS = ["title", "handle", "meta_title", "meta_description", "summary_html", "body_html", "tags", "image_url", "image_alt", "notes"]
ARTICLE_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ARTICLE_FIELDS,
    "properties": {**{f: {"type": "string"} for f in ARTICLE_FIELDS if f not in ("tags", "notes")},
                   "tags": {"type": "array", "items": {"type": "string"}}, "notes": NOTES_SCHEMA},
}


def _link_lines(links: list[dict]) -> list[str]:
    products = [x for x in links if x.get("kind") != "article"]
    articles = [x for x in links if x.get("kind") == "article"]
    out = ["", "Internal link targets (use these hrefs exactly; pages the brand documents list as verified live may also be used):"]
    out += [f"- Product: {x['title']} | {x['url']}" + (f" | image: {x['image_url']}" if x.get("image_url") else "") for x in products[:60]]
    out += [f"- Article: {x['title']} | {x['url']}" for x in articles[:20]]
    return out


def generate_draft(b: BrandConfig, v: dict, topic: dict, links: list[dict]) -> tuple[dict, str]:
    parts = [
        f"Today is {date.today().isoformat()}. Write a complete blog article for {b.name}.",
        f"Working title: {topic['title']}",
        f"Primary keyword: {topic['primary_keyword']}",
        f"Secondary keywords: {topic['secondary_keywords']}" if topic.get("secondary_keywords") else "",
        f"Search intent: {topic['intent']}",
        f"Editor notes: {topic['notes']}" if topic.get("notes") else "",
        "",
        SEO_RULES,
        "",
        "Other fields:",
        f"- {BODY_HTML_RULES}",
        "- summary_html: one or two sentences in a <p> for the blog listing.",
        "- tags: 3-6 short, useful tags (categories for readers, not keyword lists).",
        "",
        NOTES_RULES,
        *_link_lines(links),
    ]
    return _structured(_brand_system(b, v), "\n".join(parts), ARTICLE_SCHEMA, "high")


REVISABLE = ("title", "handle", "primary_keyword", "meta_title", "meta_description", "summary_html", "body_html", "tags", "image_url", "image_alt")


def revise_draft(b: BrandConfig, v: dict, article: dict, instructions: str, links: list[dict]) -> tuple[dict, str]:
    """Apply a person's change request to an existing draft and return the whole updated article (same shape as a new draft)."""
    current = {f: article.get(f, "") or "" for f in REVISABLE}
    parts = [
        f"Today is {date.today().isoformat()}. Revise this {b.name} blog draft.",
        "",
        "Requested changes from the team:",
        instructions.strip(),
        "",
        "Apply the requested changes. Keep everything else as it is unless a change is needed to keep the brand rules or the SEO checks below.",
        f"The primary keyword stays: {current['primary_keyword']}" if current["primary_keyword"] else "",
        "Return the complete updated article, not only the changed parts. Start notes.recommendations with one line saying what you changed.",
        "",
        "Current draft (JSON):",
        json.dumps(current, ensure_ascii=False),
        "",
        SEO_RULES,
        "",
        f"- {BODY_HTML_RULES}",
        "",
        NOTES_RULES,
        *_link_lines(links),
    ]
    return _structured(_brand_system(b, v), "\n".join(parts), ARTICLE_SCHEMA, "high")


# ---------------------------------------------------------------- Ask Claude (small, synchronous helpers)

ASSIST_KINDS = ("topic", "keywords", "seo_fields")
_ASSIST_SCHEMAS: dict[str, dict] = {
    "topic": {"type": "object", "additionalProperties": False, "required": ["suggestions"],
              "properties": {"suggestions": {"type": "array", "items": TOPIC_SCHEMA}}},
    "keywords": {"type": "object", "additionalProperties": False, "required": ["primary_keyword", "secondary_keywords", "intent", "rationale"],
                 "properties": {"primary_keyword": {"type": "string"}, "secondary_keywords": {"type": "array", "items": {"type": "string"}},
                                "intent": {"type": "string", "enum": ["informational", "commercial", "transactional", "navigational"]},
                                "rationale": {"type": "string"}}},
    "seo_fields": {"type": "object", "additionalProperties": False,
                   "required": ["title", "meta_title", "meta_description", "handle", "summary", "tags", "image_alt"],
                   "properties": {"title": {"type": "string"}, "meta_title": {"type": "string"}, "meta_description": {"type": "string"},
                                  "handle": {"type": "string"}, "summary": {"type": "string"},
                                  "tags": {"type": "array", "items": {"type": "string"}}, "image_alt": {"type": "string"}}},
}


def assist(b: BrandConfig, v: dict, kind: str, context: dict, existing_titles: list[str] | None = None,
           events: list[dict] | None = None) -> tuple[dict, str]:
    """One quick suggestion for a field a person is filling in. Nothing is saved: the dashboard shows it and the person decides."""
    ctx = json.dumps(context, ensure_ascii=False)[:20000]
    if kind == "topic":
        parts = [f"Today is {date.today().isoformat()}. Suggest 3 blog topics for {b.name} based on what the person has typed so far (it may be partial or empty):",
                 ctx, "Each needs a title, one primary keyword a shopper would actually type, 2-5 secondary keywords, the intent and a one-sentence rationale.",
                 "Avoid overlapping these existing articles:", *[f"- {t}" for t in (existing_titles or [])[:80]], *_events_lines(events),
                 "You have no keyword-volume data: do not state or guess search volumes."]
    elif kind == "keywords":
        parts = [f"Choose the keywords for this {b.name} blog topic:", ctx,
                 "Return the one primary keyword a shopper would actually type (a phrase that can appear naturally in the title), "
                 "3-6 secondary keywords, the intent, and one sentence on why.",
                 "You have no keyword-volume data: do not state or guess search volumes."]
    elif kind == "seo_fields":
        parts = [f"Write the SEO fields for this {b.name} article. The current values and the article text follow:", ctx, "", SEO_RULES,
                 "summary: one or two sentences for the blog listing (plain text). tags: 3-6 useful tags. "
                 "image_alt: describe the featured image if its product is known, else \"\"."]
    else:
        raise ValueError(f"unknown assist kind {kind}")
    return _structured(_brand_system(b, v), "\n".join(p for p in parts if p), _ASSIST_SCHEMAS[kind], "low", max_tokens=16000)


# ---------------------------------------------------------------- AI image prompts (services/image_prompts.py)

def _image_system(b: BrandConfig, v: dict) -> str:
    """A short system prompt for image work. The brand's writing documents are not sent: they are long and about words,
    and the brand's look comes from its own photographs instead (the visual style below)."""
    return "\n".join(p for p in [
        f"You are the art director for {b.name} ({b.storefront_domain}), an online store selling hand block-printed cotton home textiles.",
        "You write prompts that a person pastes into an AI image tool (Gemini, ChatGPT or any other) to make the featured banner of a blog article.",
        "Brand rules you must keep:",
        "- A real product may appear only when its real photo is attached as a reference, and the prompt must say to keep its print, colours "
        "and proportions exactly as in that photo. Never ask the tool to invent a print and present it as the store's product.",
        "- Without a reference photo, show the scene, room, table, hands at work, materials or mood the article is about, with textiles that read as "
        "hand block-printed cotton in general, never a specific product.",
        "- The image must look like a real photograph: no illustration, cartoon, 3D render or obvious AI gloss.",
        "- No words, letters, numbers, logos, watermarks, borders, frames or collages in the image.",
        f"Audience note from the dashboard: {v['audience']}" if v.get("audience") else "",
        f"Never: {v['avoid']}" if v.get("avoid") else "",
    ] if p)


def _image_block(url: str) -> dict:
    return {"type": "image", "source": {"type": "url", "url": url}}


IMAGE_STYLE_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["style"], "properties": {"style": {"type": "string"}}}


def image_style(b: BrandConfig, v: dict, images: list[dict]) -> tuple[dict, str]:
    """Read the store's own photographs and describe its look, for every later image prompt. `images`: [{url, label}].
    The pictures are passed by link: Claude fetches them, so this server never holds them in memory."""
    content: list[dict] = [{"type": "text", "text": f"These are {len(images)} photographs {b.name} already uses (product photos and blog banners)."}]
    for i, im in enumerate(images, 1):
        content += [{"type": "text", "text": f"Photo {i}: {im['label']}"}, _image_block(im["url"])]
    content.append({"type": "text", "text": "\n".join([
        "Describe this store's visual style so that new AI-made blog banners look like they belong with these photos.",
        "Write 150-250 words of plain sentences under these labels, each on its own line: Light, Colour palette, Backgrounds and surfaces, "
        "Props and styling, Composition and camera, Mood, Avoid.",
        "Describe what you see across the set, not any one product. Do not name products.",
    ])})
    return _structured(_image_system(b, v), content, IMAGE_STYLE_SCHEMA, "low", max_tokens=8000)


IMAGE_PROMPT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["payoff", "concept", "scene", "pin_scene", "references", "alt_text", "file_name"],
    "properties": {"payoff": {"type": "string"}, "concept": {"type": "string"}, "scene": {"type": "string"}, "pin_scene": {"type": "string"},
                   "references": {"type": "array", "items": {"type": "integer"}},
                   "alt_text": {"type": "string"}, "file_name": {"type": "string"}}}

# How a professional blog editor judges a hero image (owner review 2026-11-23: the first banners were clean but read like
# catalogue shots). Claude is held to these, in this order.
EDITORIAL_RULES = """Art direction, as a professional blog editor would brief a photographer:
1. Show the answer, not just the product. Decide first what the reader gets from this article (the payoff), then make the picture show it:
   warmth and layering for "is it warm enough", the overhang against the table edge for "what size", the step in progress for a how-to,
   the finished occasion for an ideas article. A reader who sees only the picture and the title should guess the answer.
2. Catch a moment. Prefer a scene with life in it: hands at work (folding, smoothing, setting down a cup, pressing a block), a task half done,
   a person partly in frame. Keep faces out of frame or turned away. A still life is fine only when the moment is in the objects
   (steam rising, a napkin just unfolded, a bed just turned down).
3. Frame it like an editorial photo, not a product listing: off-centre subject, a strong diagonal or leading line, a close detail with depth
   behind, a top-down flat lay, or a view through a doorway. Never the straight-on, centred, symmetrical catalogue shot. Choose the framing
   that tells this article's story best.
4. Keep it real: a little natural imperfection (a crease, a slipped corner, crumbs, a ruffled pillow, uneven light) so it reads as photographed.
5. One clear focal point that still reads when the picture is shown small in a blog list."""


def image_prompt(b: BrandConfig, v: dict, style: str, article: dict, products: list[dict], used: list[str], fmt: str, pin_fmt: str) -> tuple[dict, str]:
    """The banner prompt and a tall Pinterest prompt for one article. `products`: [{url, title}] candidate reference photos,
    shown to Claude; `used`: concepts already given to the brand's other articles, which this one must not repeat."""
    content: list[dict] = [{"type": "text", "text": "\n".join(p for p in [
        f"Write the image prompts for the featured banner of this {b.name} blog article, and for a tall Pinterest pin of it.",
        f"Title: {article['title']}",
        f"Primary keyword: {article['primary_keyword']}" if article.get("primary_keyword") else "",
        f"Summary: {article['summary']}" if article.get("summary") else "",
        ("Sections:\n" + "\n".join(f"- {h}" for h in article["headings"])) if article.get("headings") else "",
        f"Opening text: {article['opening']}" if article.get("opening") else "",
        "",
        f"The store's visual style (from its own photos). Use it for light, palette and surfaces, not for framing:\n{style}" if style else "",
        "",
        EDITORIAL_RULES,
        "",
        f"Banner format: {fmt}. Pinterest pin format: {pin_fmt}.",
    ] if p)}]
    if products:
        content.append({"type": "text", "text": "Product photos you may use as references (by number). They are catalogue shots: take the product from them, never their framing:"})
        for i, p in enumerate(products, 1):
            content += [{"type": "text", "text": f"{i}. {p['title']}"}, _image_block(p["url"])]
    content.append({"type": "text", "text": "\n".join(p for p in [
        ("Concepts already used for this store's other articles. Yours must clearly differ from every one of them in setting, "
         "framing, viewpoint, moment and colour mood:\n" + "\n".join(f"- {u}" for u in used)) if used else "",
        "",
        "Return:",
        "- payoff: one sentence, the answer or benefit the reader gets from this article (your starting point; not shown in the prompt).",
        "- concept: one line naming the setting, framing and viewpoint, the moment, the main subject and the colour mood (kept so later articles look different).",
        "- scene: the banner prompt, 130-230 words of plain sentences for an image tool, following the art direction: the moment and how it shows "
        "the payoff, subject, setting, light, colours, surfaces and props, the framing and camera angle, lens feel, depth of field, mood. "
        "Compose for the banner format. Do not mention the size, aspect ratio or a list of things to avoid: Flowmerce adds those. "
        "Do not use the words 'AI' or 'prompt'.",
        "- pin_scene: the Pinterest prompt, 100-180 words, the same idea and products recomposed for a tall picture: a vertical layout "
        "(top-down, a tall room view, or a close detail with depth above), with calm, uncluttered space in the top quarter where a title can be "
        "added later. Same rules as scene.",
        "- references: the numbers of the product photos the scenes show (at most 2), or [] for scenes without a specific product. "
        "Use a product only if it fits the article; when you do, describe it as in its photo. In the scenes, name such a product "
        "as 'the <product name> from the attached photo', never by its number (the person sees no numbers), and do not add an instruction to "
        "keep its print unchanged: Flowmerce adds that.",
        "- alt_text: one sentence describing what the finished banner shows, for screen readers and search engines (not a keyword list).",
        "- file_name: lowercase words joined by hyphens, ending in .jpg, describing the banner.",
    ] if p)})
    return _structured(_image_system(b, v), content, IMAGE_PROMPT_SCHEMA, "medium", max_tokens=10000)


IMAGE_CHECK_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["faithful", "looks_real", "problems"],
    "properties": {"faithful": {"type": "boolean"}, "looks_real": {"type": "boolean"}, "problems": {"type": "string"}}}


def image_check(b: BrandConfig, v: dict, refs: list[dict], image_url: str) -> tuple[dict, str]:
    """Compare an AI-made banner with the real product photos it was made from. `refs`: [{url, title}]; all by link."""
    content: list[dict] = [{"type": "text", "text": "The real product photos:"}]
    for r in refs:
        content += [{"type": "text", "text": r["title"]}, _image_block(r["url"])]
    content += [{"type": "text", "text": "The AI-made blog banner that should show those products:"}, _image_block(image_url),
                {"type": "text", "text": "\n".join([
                    "Check the banner as the brand's product manager would before it goes on the blog.",
                    "- faithful: true only if every product in the banner has the same print motifs, colours, border and scale as its photo. "
                    "Small differences of light and angle are fine; a changed, simplified or invented print is not.",
                    "- looks_real: true if it reads as a real photograph (no warped objects, melted details, extra fingers, garbled patterns or text).",
                    "- problems: what is wrong, in one or two short sentences, or \"\".",
                ])}]
    return _structured(_image_system(b, v), content, IMAGE_CHECK_SCHEMA, "low", max_tokens=4000)


def ping() -> dict:
    m = _get_client().models.retrieve(config.claude_model)
    return {"model": m.id}
