"""Brand knowledge: the brand's own guides (voice, claims, products, playbooks) that every Claude request for that brand carries.

The files live in `modules/seo/knowledge/<brand_id>/` and are read once per process. They are sent as the cached part of the
system prompt, so a run of several requests pays for them in full only once (see integrations/claude.py)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

KNOWLEDGE_DIR = Path(__file__).resolve().parent.parent / "knowledge"
SUFFIXES = {".md", ".txt"}


def _files(brand_id: str) -> list[Path]:
    folder = KNOWLEDGE_DIR / brand_id
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in SUFFIXES and p.name.lower() != "readme.md")


@lru_cache(maxsize=None)
def brand_knowledge(brand_id: str) -> str:
    """All of a brand's knowledge files as one text, each wrapped in a <document> tag with its file name. Empty when there are none."""
    parts = []
    for p in _files(brand_id):
        text = p.read_text(encoding="utf-8").strip()
        if text:
            parts.append(f'<document name="{p.name}">\n{text}\n</document>')
    return "\n\n".join(parts)


def knowledge_files(brand_id: str) -> list[dict[str, object]]:
    """The file names and sizes, for the dashboard. Never the content."""
    return [{"name": p.name, "chars": len(p.read_text(encoding="utf-8"))} for p in _files(brand_id)]
