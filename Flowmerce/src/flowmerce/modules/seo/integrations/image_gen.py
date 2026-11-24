"""AI image generation for blog featured images: Google Gemini (Nano Banana) or OpenAI (GPT Image), by API key.
Owner request 2026-11-23: a fully automatic chain, Claude's prompt -> image API -> the blog's featured image.

generate() sends one prompt plus up to two reference photos (the real products, as bytes) and returns the picture as
JPEG bytes. Nothing is kept here; services/image_prompts.py uploads the result to the store's Shopify Files at once,
so at most one picture (a few MB) is in memory at a time (the hosted app has 512 MB).

Request formats were taken from the providers' documentation on 2026-11-23 and have NOT yet been run against the live
APIs (no key was available). The response is therefore read defensively: the first base64 image found anywhere in the
answer is used, and an answer without one is reported as a failure with whatever text the provider gave.

- Gemini: POST https://generativelanguage.googleapis.com/v1beta/interactions, header x-goog-api-key. Default model
  gemini-3-pro-image (Nano Banana Pro, about $0.134 an image at 1K-2K). Aspect ratio and size are request settings.
- OpenAI: POST /v1/images/edits (with reference photos) or /v1/images/generations (without). Default model gpt-image-2,
  which takes an exact WIDTHxHEIGHT (multiples of 16). The account may need OpenAI's organization verification first.
"""
from __future__ import annotations

import base64
import logging
from typing import Any

from ..config import config

log = logging.getLogger(__name__)

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"
OPENAI_URL = "https://api.openai.com/v1/images"
DEFAULT_MODEL = {"gemini": "gemini-3-pro-image", "openai": "gpt-image-2"}
# Estimated US dollars per picture, for the spending limit (list prices where the provider states one).
COST_USD = {"gemini-3-pro-image": 0.134, "gemini-nano-banana-2.1": 0.101, "gemini-3.1-flash-image": 0.101}
DEFAULT_COST_USD = 0.15
NAME = {"gemini": "Google Gemini", "openai": "OpenAI"}


class ImageGenError(RuntimeError):
    """kind: auth, rate_limit, invalid_request, blocked, no_image, server, connection, timeout."""

    def __init__(self, message: str, kind: str, retryable: bool = False):
        super().__init__(message)
        self.kind = kind
        self.retryable = retryable


def provider() -> str | None:
    """Which provider is used: IMAGE_PROVIDER when its key is set, else Gemini, else OpenAI, else None."""
    keys = {"gemini": config.gemini_api_key, "openai": config.openai_api_key}
    if config.image_provider in keys:
        return config.image_provider if keys[config.image_provider] else None
    return next((p for p in ("gemini", "openai") if keys[p]), None)


def model() -> str:
    p = provider()
    return config.image_model or (DEFAULT_MODEL[p] if p else "")


def configured() -> bool:
    return provider() is not None


def cost_estimate() -> float:
    return COST_USD.get(model(), DEFAULT_COST_USD)


def status() -> dict[str, Any]:
    p = provider()
    return {"configured": bool(p), "provider": p, "providerName": NAME.get(p or "", ""), "model": model() if p else "",
            "costPerImageUsd": cost_estimate() if p else None,
            "setup": None if p else "Add GEMINI_API_KEY (from Google AI Studio) or OPENAI_API_KEY (from the OpenAI API platform) to the server's .env file, then restart Flowmerce."}


def _first_image(node: Any) -> tuple[str, str] | None:
    """(base64 data, mime type) of the first image anywhere in a provider answer, whatever its exact shape."""
    if isinstance(node, dict):
        for key in ("b64_json", "image_base64"):
            if isinstance(node.get(key), str) and len(node[key]) > 100:
                return node[key], "image/" + str(node.get("output_format") or "png").replace("jpg", "jpeg")
        inline = node.get("inlineData") or node.get("inline_data")
        if isinstance(inline, dict) and isinstance(inline.get("data"), str):
            return inline["data"], str(inline.get("mimeType") or inline.get("mime_type") or "image/png")
        if isinstance(node.get("data"), str) and len(node["data"]) > 100 and (node.get("type") == "image" or "mime_type" in node or "mimeType" in node):
            return node["data"], str(node.get("mime_type") or node.get("mimeType") or "image/png")
        for v in node.values():
            found = _first_image(v)
            if found:
                return found
    elif isinstance(node, list):
        for v in node:
            found = _first_image(v)
            if found:
                return found
    return None


def _texts(node: Any, out: list[str]) -> list[str]:
    if isinstance(node, dict):
        for k, v in node.items():
            if k in ("text", "message", "reason", "finish_reason", "finishReason", "blockReason", "refusal") and isinstance(v, str):
                out.append(v)
            else:
                _texts(v, out)
    elif isinstance(node, list):
        for v in node:
            _texts(v, out)
    return out


def _post(url: str, headers: dict[str, str], body: dict[str, Any]) -> dict[str, Any]:
    import httpx
    try:
        r = httpx.post(url, headers=headers, json=body, timeout=float(config.image_timeout))
    except httpx.TimeoutException as e:
        raise ImageGenError("The image service did not answer in time.", "timeout", retryable=True) from e
    except httpx.HTTPError as e:
        raise ImageGenError(f"Could not reach the image service ({type(e).__name__}).", "connection", retryable=True) from e
    if r.status_code in (401, 403):
        raise ImageGenError("The image service rejected the API key or its permissions (for OpenAI, the organization may need verifying).", "auth")
    if r.status_code == 429:
        raise ImageGenError("The image service's rate limit or quota was reached.", "rate_limit", retryable=True)
    if r.status_code >= 500:
        raise ImageGenError(f"The image service had an error ({r.status_code}).", "server", retryable=True)
    try:
        data = r.json()
    except ValueError as e:
        raise ImageGenError(f"The image service answered {r.status_code} with something that is not JSON.", "server", retryable=r.status_code >= 500) from e
    if r.status_code >= 400:
        detail = " ".join(_texts(data, []))[:300] or f"HTTP {r.status_code}"
        kind = "blocked" if any(w in detail.lower() for w in ("safety", "policy", "blocked", "moderation")) else "invalid_request"
        raise ImageGenError(f"The image service refused the request: {detail}", kind)
    return data


def _gemini(prompt: str, refs: list[tuple[bytes, str]], ratio: str) -> dict[str, Any]:
    parts: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    parts += [{"type": "image", "mime_type": mime, "data": base64.b64encode(data).decode()} for data, mime in refs]
    body = {"model": model(), "input": parts,
            "response_format": {"type": "image", "mime_type": "image/jpeg", "aspect_ratio": ratio, "image_size": "2K"}}
    return _post(GEMINI_URL, {"x-goog-api-key": config.gemini_api_key, "Content-Type": "application/json"}, body)


def _openai(prompt: str, refs: list[tuple[bytes, str]], width: int, height: int) -> dict[str, Any]:
    size = f"{width // 16 * 16}x{height // 16 * 16}"
    body: dict[str, Any] = {"model": model(), "prompt": prompt, "size": size, "quality": "high", "output_format": "jpeg", "n": 1}
    headers = {"Authorization": f"Bearer {config.openai_api_key}", "Content-Type": "application/json"}
    if refs:
        body["images"] = [{"image_url": f"data:{mime};base64,{base64.b64encode(data).decode()}"} for data, mime in refs]
        return _post(f"{OPENAI_URL}/edits", headers, body)
    return _post(f"{OPENAI_URL}/generations", headers, body)


def generate(prompt: str, refs: list[tuple[bytes, str]], ratio: str, width: int, height: int) -> tuple[bytes, str]:
    """One picture for `prompt`, with `refs` as reference photos [(bytes, mime)]. Returns (image bytes, mime type)."""
    p = provider()
    if not p:
        raise ImageGenError("No image API key is set on the server.", "auth")
    data = _gemini(prompt, refs, ratio) if p == "gemini" else _openai(prompt, refs, width, height)
    found = _first_image(data)
    if not found:
        said = " ".join(_texts(data, []))[:300]
        raise ImageGenError("The image service returned no picture" + (f": {said}" if said else " (it may have been blocked)."), "no_image")
    try:
        raw = base64.b64decode(found[0], validate=False)
    except ValueError as e:
        raise ImageGenError("The image service returned a picture that could not be read.", "no_image") from e
    mime = sniff(raw)
    if not mime:
        raise ImageGenError("The image service returned something that is not a JPG, PNG or WebP picture.", "no_image")
    log.info("Image generated: provider=%s model=%s bytes=%d", p, model(), len(raw))
    return raw, mime


def sniff(data: bytes) -> str | None:
    """The picture's real type from its first bytes (what a provider says about it is not trusted)."""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    return None
