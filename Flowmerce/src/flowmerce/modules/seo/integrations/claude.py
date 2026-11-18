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

from ..config import BrandConfig, config
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


def _structured(system: str, prompt: str, schema: dict, effort: str) -> tuple[dict, str]:
    import anthropic
    client = _get_client()
    extra: dict = {"output_config": {"effort": effort, "format": {"type": "json_schema", "schema": schema}}}
    params = dict(model=config.claude_model, max_tokens=32000, thinking={"type": "adaptive"}, system=system,
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


def _brand_system(b: BrandConfig, v: dict) -> str:
    lines = [
        f"You are the SEO content strategist for {b.name} ({b.storefront_domain}), an online store selling hand block-printed cotton home textiles made by artisans in India.",
        f"Brand voice: {v['voice']}" if v.get("voice") else "",
        f"Audience: {v['audience']}" if v.get("audience") else "",
        f"Never: {v['avoid']}" if v.get("avoid") else "",
        "Write for people first and search engines second. Do not invent statistics, awards, certifications, prices, shipping promises or customer quotes. If a fact about the store is not given to you, leave it out.",
    ]
    return "\n".join(x for x in lines if x)


def research_topics(b: BrandConfig, v: dict, existing_titles: list[str], products: list[str], queries: list[str], count: int, focus: str = "") -> tuple[dict, str]:
    schema = {
        "type": "object", "additionalProperties": False, "required": ["topics"],
        "properties": {"topics": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["title", "primary_keyword", "secondary_keywords", "intent", "rationale"],
            "properties": {
                "title": {"type": "string"}, "primary_keyword": {"type": "string"},
                "secondary_keywords": {"type": "array", "items": {"type": "string"}},
                "intent": {"type": "string", "enum": ["informational", "commercial", "transactional", "navigational"]},
                "rationale": {"type": "string"},
            }}}},
    }
    parts = [
        f"Propose {count} new blog topics for {b.name}.",
        f"Focus: {focus}" if focus else "",
        "Each topic needs one primary keyword a shopper would actually type, 2–5 secondary keywords, the search intent, and one or two sentences on why it fits this store.",
        "Do not repeat or closely overlap these existing articles:",
        *[f"- {t}" for t in existing_titles[:80]],
        ("\nProducts the store sells (link-worthy):\n" + "\n".join(f"- {p}" for p in products[:60])) if products else "",
        ("\nSearch queries that already bring visitors to the blog (from Search Console):\n" + "\n".join(f"- {q}" for q in queries[:40])) if queries else "",
        "You have no keyword-volume data: do not state or guess search volumes.",
    ]
    return _structured(_brand_system(b, v), "\n".join(p for p in parts if p), schema, "medium")


def generate_draft(b: BrandConfig, v: dict, topic: dict, links: list[dict]) -> tuple[dict, str]:
    fields = ["title", "handle", "meta_title", "meta_description", "summary_html", "body_html", "tags", "image_alt"]
    schema = {
        "type": "object", "additionalProperties": False, "required": fields,
        "properties": {**{f: {"type": "string"} for f in fields if f != "tags"}, "tags": {"type": "array", "items": {"type": "string"}}},
    }
    parts = [
        f"Write a complete blog article for {b.name}.",
        f"Working title: {topic['title']}",
        f"Primary keyword: {topic['primary_keyword']}",
        f"Secondary keywords: {topic['secondary_keywords']}" if topic.get("secondary_keywords") else "",
        f"Search intent: {topic['intent']}",
        f"Editor notes: {topic['notes']}" if topic.get("notes") else "",
        "",
        "Requirements:",
        "- body_html: 1,200–1,800 words of clean HTML using only <h2>, <h3>, <p>, <ul>, <ol>, <li>, <strong>, <em>, <a>, <blockquote>. No <h1> (the theme renders the title), no inline styles, no scripts, no images.",
        "- Use the primary keyword in the first paragraph and in at least one <h2>, naturally.",
        "- Add 2–4 internal links, chosen only from the list below, with descriptive anchor text. Use the URLs exactly as given.",
        "- End with a short FAQ section (<h2>Frequently asked questions</h2> with 3–4 <h3> questions).",
        "- meta_title at most 60 characters; meta_description 140–155 characters; handle is a short lowercase-hyphenated URL slug.",
        "- summary_html: one or two sentences in a <p> for the blog listing.",
        "- tags: 3–6 short tags. image_alt: alt text for a featured image of the main product type.",
        "",
        "Internal link targets:",
        *[f"- {l['title']}: {l['url']}" for l in links[:40]],
    ]
    return _structured(_brand_system(b, v), "\n".join(parts), schema, "high")


def ping() -> dict:
    m = _get_client().models.retrieve(config.claude_model)
    return {"model": m.id}
