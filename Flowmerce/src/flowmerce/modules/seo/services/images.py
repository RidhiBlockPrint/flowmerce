"""Featured images uploaded from a person's computer (article editor, "From your computer"). Owner request 2026-11-20.

The picture goes to the brand's Shopify Files (served from the Shopify CDN), and its public URL becomes the article's
image URL, so the hidden draft and the live article use it like any other image. Checks before anything is sent: a known
brand, an image type Shopify accepts (JPG, PNG, WebP, GIF, confirmed from the file's first bytes, not only its name) and
at most MAX_BYTES. Shopify needs the `write_files` scope for this; without it the person is told how to add it."""
from __future__ import annotations

import re

from ..audit import audit
from ..config import is_brand
from ..integrations import shopify
from ..util import HttpError
from .brands import brand

MAX_BYTES = 15 * 1024 * 1024
EXTENSION = {"image/jpeg": "jpg", "image/png": "png", "image/gif": "gif", "image/webp": "webp"}
SCOPE_HELP = ("Shopify needs one more permission for uploads. In Shopify admin open Settings, Apps and sales channels, "
              "Develop apps, the Flowmerce app, Configuration: tick write_files under Admin API scopes, save and reinstall "
              "the app (and update the access token in Flowmerce if Shopify shows a new one). Until then, paste an image link instead.")


def sniff(data: bytes) -> str | None:
    """The image type from the file's first bytes, or None when it is not an accepted image."""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def clean_name(name: str, mime: str) -> str:
    """A safe file name with the extension of the real image type."""
    stem = re.sub(r"[^a-zA-Z0-9._-]+", "-", (name or "image").rsplit(".", 1)[0]).strip("-.")[:80] or "image"
    return f"{stem}.{EXTENSION[mime]}"


def upload(user: dict, brand_id: str, data: bytes, filename: str, alt: str = "") -> dict:
    """Store an uploaded image in the brand's Shopify Files and return {url, alt, filename}."""
    if not is_brand(brand_id):
        raise HttpError(400, "Pick the article's brand first.")
    if not data:
        raise HttpError(400, "The file is empty.")
    if len(data) > MAX_BYTES:
        raise HttpError(413, f"The image is larger than {MAX_BYTES // (1024 * 1024)} MB. Make it smaller and try again.", "payload_too_large")
    mime = sniff(data)
    if not mime:
        raise HttpError(415, "That file is not a JPG, PNG, WebP or GIF image.", "unsupported_type")
    b = brand(brand_id)
    if not shopify.configured(b):
        raise HttpError(412, f"Shopify is not connected for {b.name}, so the image cannot be stored. Paste an image link instead.", "pending_setup")
    name = clean_name(filename, mime)
    try:
        url = shopify.upload_image(b, data, name, mime, alt)
    except shopify.MissingScope:
        raise HttpError(403, SCOPE_HELP, "missing_scope") from None
    except RuntimeError as e:
        raise HttpError(502, str(e), "shopify_error") from None
    audit(user, "image.upload", "shopify_file", name, brand_id, f"{len(data) // 1024} KB")
    return {"url": url, "alt": alt, "filename": name}
