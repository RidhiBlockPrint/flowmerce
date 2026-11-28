"""What Claude is asked for, and the shape its answer must take.

Kept apart from `generate.py` so the rules the team cares about can be read without wading through
threading and budget code.

Two asks:
  * a **creative pack**: concepts built on the figures in `insights.findings`, each carrying the
    hook, the full-funnel message, a static ad, a carousel, a Reel or Stories script, a UGC brief
    and a one-variable test plan;
  * **variations** of one concept that already won, changing exactly one thing.

The guardrails are the point of this file:
  * every concept must name the figures it came from, so a suggestion can be checked;
  * nothing may be invented: no price, offer, claim, product, material or delivery promise that is
    not in the data or the brand guide;
  * one variable per test, because otherwise a result cannot be attributed;
  * Flowmerce writes words, not pictures. A "Reel" here is a script and a shot list for a person to
    film, never a claim that a video was produced.
"""

from __future__ import annotations

import json
from typing import Any

# Only the brand files that govern how the brand speaks and what it may claim are sent. The rest of
# a brand's knowledge (the master brief, the AEO playbook) runs to nearly 200,000 characters for
# Ridhi, which would cost more per call than the answer is worth and says little about ad copy.
VOICE_FILE_WORDS = ("voice", "claims", "brand")
VOICE_MAX_CHARS = 30_000

FUNNEL_STAGES = ("tof", "mof", "bof")
TEST_VARIABLES = ("hook", "angle", "format", "offer", "visual", "copy", "audience")
SUCCESS_METRICS = ("roas", "cpa", "ctr", "hook_rate", "hold_rate", "conversion_rate")


def brand_voice(brand: str) -> str:
    """The brand's voice and claims guidance, trimmed to what one Claude call should carry.

    Returns an empty string when the brand has no such file, and the caller then says so in the
    answer instead of inventing a voice.
    """
    from ..seo.services.knowledge import _files

    parts: list[str] = []
    used = 0
    for path in _files(brand):
        name = path.name.lower()
        if not any(word in name for word in VOICE_FILE_WORDS):
            continue
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            continue
        room = VOICE_MAX_CHARS - used
        if room <= 0:
            break
        if len(text) > room:
            text = text[:room] + "\n[trimmed]"
        parts.append(f'<document name="{path.name}">\n{text}\n</document>')
        used += len(text)
    return "\n\n".join(parts)


# --------------------------------------------------------------------------------- creative pack
_FORMATS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["static", "carousel", "reel", "story", "ugc"],
    "properties": {
        "static": {
            "type": "object",
            "additionalProperties": False,
            "required": ["headline", "primary_text", "visual_note"],
            "properties": {
                "headline": {"type": "string"},
                "primary_text": {"type": "string"},
                "visual_note": {"type": "string"},
            },
        },
        # `minItems: 1` is what forces content. A required array may still come back empty, and on
        # the first live call (2026-11-25) it did: the Reel shot list, the UGC talking points and
        # the test variants were all empty while the schema was satisfied. Structured outputs allow
        # `minItems` of 0 or 1 only and no `maxItems` at all (a larger value is refused with a 400),
        # so the upper bounds live in generate.clean_pack instead of here.
        "carousel": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["frame", "visual", "caption"],
                "properties": {
                    "frame": {"type": "integer"},
                    "visual": {"type": "string"},
                    "caption": {"type": "string"},
                },
            },
        },
        "reel": {
            "type": "object",
            "additionalProperties": False,
            "required": ["length_seconds", "shots"],
            "properties": {
                "length_seconds": {"type": "integer"},
                "shots": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["at_second", "visual", "on_screen_text"],
                        "properties": {
                            "at_second": {"type": "integer"},
                            "visual": {"type": "string"},
                            "on_screen_text": {"type": "string"},
                        },
                    },
                },
            },
        },
        # A Story is 9:16 and tapped through: a few full-screen frames, each with its own words and
        # one interactive element at most (a poll, a question box, a link sticker).
        "story": {
            "type": "object",
            "additionalProperties": False,
            "required": ["frames"],
            "properties": {
                "frames": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["frame", "visual", "on_screen_text", "sticker"],
                        "properties": {
                            "frame": {"type": "integer"},
                            "visual": {"type": "string"},
                            "on_screen_text": {"type": "string"},
                            "sticker": {"type": "string"},
                        },
                    },
                },
            },
        },
        "ugc": {
            "type": "object",
            "additionalProperties": False,
            "required": ["creator_brief", "talking_points", "do_not_say"],
            "properties": {
                "creator_brief": {"type": "string"},
                "talking_points": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"type": "string"},
                },
                # do_not_say may legitimately be empty when the brand guide forbids nothing.
                "do_not_say": {"type": "array", "items": {"type": "string"}},
            },
        },
    },
}

_TEST_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["hypothesis", "variable", "variants", "success_metric"],
    "properties": {
        "hypothesis": {"type": "string"},
        "variable": {"type": "string", "enum": list(TEST_VARIABLES)},
        # A test needs two variants: one thing against another, or there is nothing to compare.
        "variants": {"type": "array", "minItems": 1, "items": {"type": "string"}},
        "success_metric": {"type": "string", "enum": list(SUCCESS_METRICS)},
    },
}

PACK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["summary", "data_caveat", "concepts"],
    "properties": {
        "summary": {"type": "string"},
        "data_caveat": {"type": "string"},
        "concepts": {
            "type": "array",
            # The first live call (2026-11-25) returned a single concept. The schema cannot ask for
            # three (structured outputs take `minItems` of 0 or 1 only), so the count is stated as a
            # hard rule in PACK_SYSTEM and the ceiling is applied in generate.clean_pack.
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "title",
                    "hook",
                    "alternative_hooks",
                    "angle",
                    "message",
                    "offer",
                    "funnel_stage",
                    "persona",
                    "evidence",
                    "formats",
                    "test",
                ],
                "properties": {
                    "title": {"type": "string"},
                    "hook": {"type": "string"},
                    "alternative_hooks": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"type": "string"},
                    },
                    "angle": {"type": "string"},
                    "message": {"type": "string"},
                    "offer": {"type": "string"},
                    "funnel_stage": {"type": "string", "enum": list(FUNNEL_STAGES)},
                    "persona": {"type": "string"},
                    "evidence": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"type": "string"},
                    },
                    "formats": _FORMATS_SCHEMA,
                    "test": _TEST_SCHEMA,
                },
            },
        },
    },
}

VARIATIONS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["variable", "kept", "variations"],
    "properties": {
        "variable": {"type": "string", "enum": list(TEST_VARIABLES)},
        "kept": {"type": "string"},
        "variations": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["label", "hook", "what_changed", "why"],
                "properties": {
                    "label": {"type": "string"},
                    "hook": {"type": "string"},
                    "what_changed": {"type": "string"},
                    "why": {"type": "string"},
                },
            },
        },
    },
}

PACK_SYSTEM = (
    "You are a performance creative strategist for a small home-textile brand that sells hand "
    "block printed goods. You are given that brand's own ad figures for a period, grouped by "
    "creative format and by hook. You turn those figures into creative concepts the team can "
    "actually produce this week.\n"
    "\n"
    "How to work:\n"
    "1. Read the figures first. A concept is worth proposing only when a figure supports it: a "
    "format or hook that earns its spend, one that clearly does not, or a gap between them. "
    "Name those figures in `evidence`, with the real numbers and what they are compared with.\n"
    "   When <patterns> are given, they are the same ads tagged by the team: hook type, visual "
    "style, print, color, category, season and product, each group with a verdict (winner, "
    "average, loser, insufficient_data), plus the top winning and losing ads with their own copy. "
    "Build on what wins there and avoid repeating what loses; a group or ad marked "
    "insufficient_data or untagged proves nothing.\n"
    "2. Keep what is working and change one thing at a time. If the craft hook earns well, the "
    "next concept builds on it rather than replacing it.\n"
    "3. Write for production. Somebody has to shoot or design this: say what is in the frame, in "
    "what order, and what the words on screen are.\n"
    "\n"
    "Rules:\n"
    "- Never invent a figure, a product, a price, a discount, a material, a size, a delivery time "
    "or a review. If the data and the brand guide do not say it, it does not go in the ad. Leave "
    "`offer` empty rather than making one up.\n"
    "- A group marked `sampleOk: false` has too little spend behind it to judge. You may say it "
    "needs more data; you may not build a concept on it as though it had won or lost.\n"
    "- `hook_rate` and `hold_rate` only exist for video. A format shown as null there has no "
    "video, which is not a weakness; do not treat it as one.\n"
    "- Every test changes exactly ONE variable against the current ad. Say which in "
    "`test.variable` and list the variants of that one thing. A test that changes the hook and "
    "the visual together teaches nothing.\n"
    "- You are writing words, not making pictures. A Reel here is a script and a shot list for a "
    "person to film. Never imply a video or image already exists.\n"
    "- Follow the brand guide's voice and its claims register exactly. If no brand guide is given, "
    "write plainly and make no claim about materials, origin, durability or certification, and say "
    "so in `data_caveat`.\n"
    "- Give 3 to 5 concepts, never fewer than 3. Thin data is a reason to say so in `data_caveat` "
    "and to mark a concept as needing more spend before it is trusted, not a reason to give one "
    "concept. Spread them across the funnel: at least one `tof` and one `bof`.\n"
    "- Fill every field. An empty shot list, an empty set of talking points or a test with one "
    "variant is not an answer; if a format does not suit the concept, write the simplest honest "
    "version of it rather than leaving it blank.\n"
    "- `data_caveat` is one or two sentences on what the figures do NOT cover, for example a short "
    "period, thin spend, or no video data at all. Write it even when the data is good, saying so.\n"
    "\n"
    "Lengths, because the page shows each concept as a card:\n"
    "  `title`: at most 8 words. `hook`: the first line a viewer reads, at most 12 words.\n"
    "  `alternative_hooks`: 2-3 more, same length, same idea said differently.\n"
    "  `angle`: one sentence, at most 25 words, naming the figure behind it.\n"
    "  `message`: at most 2 sentences and 40 words.\n"
    "  `persona`: at most 12 words. `evidence`: 2-4 lines, each at most 20 words.\n"
    "  `static.primary_text`: at most 60 words. `carousel`: 3-5 frames.\n"
    "  `reel.shots`: 3-6 shots inside `length_seconds` (15-30).\n"
    "  `story.frames`: 3-4 full-screen 9:16 frames; `on_screen_text` at most 10 words; `sticker` "
    "is one link, poll or question sticker, or empty.\n"
    "  `ugc.talking_points`: 3-5 lines; `ugc.do_not_say`: the claims the brand guide forbids.\n"
    "  `test.hypothesis`: one sentence naming the metric it should move.\n"
    "  `summary`: 2-3 sentences, at most 70 words: which format and hook earn their spend, which "
    "do not, and anything in the current ads that breaks the brand guide.\n"
    "  `data_caveat`: 1-2 sentences, at most 40 words.\n"
    "- Write in plain British English for a team who are not analysts. Hindi or Hinglish only "
    "inside ad copy when the brand guide shows the brand speaks that way."
)

VARIATIONS_SYSTEM = (
    "You are a performance creative strategist. You are given one concept that is already running "
    "and performing, and the figures behind it. Produce fresh variations of it for the next test "
    "round.\n"
    "\n"
    "Rules:\n"
    "- Change exactly ONE variable across every variation, and say which in `variable`. List in "
    "`kept` what stays identical, so whoever produces them knows what not to touch.\n"
    "- Each variation is a real alternative, not a reworded copy: a different reason to care, a "
    "different proof, a different opening image. Say in `what_changed` what is different and in "
    "`why` which figure suggests it is worth trying.\n"
    "- Never invent a figure, product, price, offer, material or claim. Keep the brand's voice and "
    "its claims register.\n"
    "- 3-5 variations. `hook` at most 12 words; `what_changed` and `why` one sentence each."
)


def _compact(value: Any) -> str:
    """JSON for a prompt: no indentation, so the figures cost as few tokens as they can."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _ad_brief(ad: dict[str, Any]) -> dict[str, Any]:
    """One ad from the patterns, cut to what a prompt needs."""
    tags = ad.get("tags") or {}
    sums = ad.get("sums") or {}
    rates = ad.get("rates") or {}
    return {
        "name": ad.get("name"),
        "headline": ad.get("headline"),
        "primaryText": str(ad.get("primaryText") or "")[:300] or None,
        "product": ad.get("productTitle") or tags.get("product"),
        "tags": {
            k: tags.get(k)
            for k in ("hook_type", "hook_text", "visual_style", "format", "print", "color",
                      "category", "season")
        },
        "verdict": ad.get("verdict"),
        "spend": sums.get("spend"),
        "roas": rates.get("roas"),
        "ctr": rates.get("ctr"),
        "hookRate": rates.get("hookRate"),
    }


def patterns_for_prompt(
    patterns: dict[str, Any] | None, groups: int = 8
) -> dict[str, Any] | None:
    """The tag patterns (`service.creative_patterns`), trimmed so a prompt stays small: the rule,
    the verdict counts, the biggest groups of every tag, and the top winning and losing ads."""
    if not patterns or not patterns.get("adCount"):
        return None
    dims: dict[str, list[dict[str, Any]]] = {}
    for dim, rows in (patterns.get("dimensions") or {}).items():
        dims[dim] = [
            {
                "value": g.get("value"),
                "ads": g.get("ads"),
                "verdict": g.get("verdict"),
                "spend": (g.get("sums") or {}).get("spend"),
                "roas": (g.get("rates") or {}).get("roas"),
                "ctr": (g.get("rates") or {}).get("ctr"),
                "hookRate": (g.get("rates") or {}).get("hookRate"),
            }
            for g in (rows or [])[:groups]
        ]
    return {
        "currency": patterns.get("currency"),
        "rule": patterns.get("rule"),
        "verdicts": patterns.get("verdicts"),
        "untaggedAds": patterns.get("untagged"),
        "groups": dims,
        "topWinners": [_ad_brief(a) for a in patterns.get("topWinners") or []],
        "topLosers": [_ad_brief(a) for a in patterns.get("topLosers") or []],
    }


def pack_prompt(
    findings: dict[str, Any], brand: str, notes: str = "", patterns: dict[str, Any] | None = None
) -> str:
    """The ask for a creative pack: the figures, the tag patterns when there are any, the brand
    guide, and the team's own notes."""
    voice = brand_voice(brand)
    parts = [
        "Here are this store's ad figures for the period. Groups are by creative format, by the "
        "opening words of the ad copy (the hook), and by platform. `sampleOk` says whether there "
        "is enough spend and impressions behind a group to judge it.",
        f"<figures>\n{_compact(findings)}\n</figures>",
    ]
    trimmed = patterns_for_prompt(patterns)
    if trimmed:
        parts.append(
            "The same ads tagged by the team, with each group's verdict and the top winners and "
            "losers. Spend is in the account currency.\n"
            f"<patterns>\n{_compact(trimmed)}\n</patterns>"
        )
    if voice:
        parts.append(
            "The brand guide below governs the voice and what may be claimed. Follow it exactly.\n"
            f"<brand_guide>\n{voice}\n</brand_guide>"
        )
    else:
        parts.append(
            "No brand guide is available for this store. Write plainly and make no claim about "
            "materials, origin, durability or certification, and say so in `data_caveat`."
        )
    if notes.strip():
        parts.append(
            "The team's own notes about this store. Treat them as context, not as figures.\n"
            f"<team_notes>\n{notes.strip()}\n</team_notes>"
        )
    parts.append(
        "Produce 3 to 5 concepts, each resting on a figure above, each with a static ad, a "
        "carousel, a Reel script, a Story, a UGC brief and a one-variable test."
    )
    return "\n\n".join(parts)


# --------------------------------------------------------------------------------- recommendations
RECOMMENDATION_PRIORITIES = ("high", "medium", "low")

RECS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["summary", "recommendations"],
    "properties": {
        "summary": {"type": "string"},
        "recommendations": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["title", "diagnosis", "evidence", "action", "priority"],
                "properties": {
                    "title": {"type": "string"},
                    "diagnosis": {"type": "string"},
                    "evidence": {"type": "array", "minItems": 1, "items": {"type": "string"}},
                    "action": {"type": "string"},
                    "priority": {"type": "string", "enum": list(RECOMMENDATION_PRIORITIES)},
                },
            },
        },
    },
}

RECS_SYSTEM = (
    "You are a performance media analyst for a small home-textile brand. You are given a "
    "day-by-day trend (spend, CTR, ROAS) for the period and the same figures grouped by format, "
    "hook and platform that a creative pack would use. Your job is to say what changed and what "
    "to do about it, not to write ad copy.\n"
    "\n"
    "What you can and cannot see: this is ad-platform data only (spend, clicks, platform-reported "
    "purchases). You cannot see the store's website, its checkout, or its true conversion rate; "
    "`purchases` here is what the ad platform claims, not a confirmed Shopify order. Never claim a "
    "website or checkout problem from this data alone; say so as a possibility to check elsewhere "
    "when the figures point that way (for example, clicks rising while platform-reported purchases "
    "do not).\n"
    "\n"
    "How to work:\n"
    "1. Read the trend first. A single bad or good day is noise; a recommendation needs a real "
    "span of days moving the same way, or a clear gap between groups that `sampleOk` confirms is "
    "large enough to trust.\n"
    "2. Each recommendation names the figures behind it in `evidence`, with real numbers, so a "
    "reader can check it against the page.\n"
    "3. `action` is one concrete next step the team can take this week: shift budget toward a "
    "format or platform, pause or rework a specific one, run a named test, or watch a metric "
    "another week before acting (when the data is too thin to act on yet).\n"
    "\n"
    "Rules:\n"
    "- Never invent a figure, a cause, or a fix that is not supported by the data given.\n"
    "- A group marked `sampleOk: false` has too little spend behind it to act on; say it needs "
    "more data rather than treating it as a finding.\n"
    "- 3 to 5 recommendations, ordered by `priority`, most urgent first. Do not pad the list: "
    "fewer, well-evidenced recommendations beat five generic ones.\n"
    "- `title`: at most 8 words. `diagnosis`: 1-2 sentences, at most 35 words, naming what "
    "changed. `evidence`: 1-3 lines, each at most 20 words, with real numbers. `action`: one "
    "sentence, at most 25 words, naming what to actually do.\n"
    "  `summary`: 1-2 sentences, at most 40 words, on the overall direction (improving, flat or "
    "declining) and why.\n"
    "- Write in plain British English for a team who are not analysts."
)


def recs_prompt(
    trend: dict[str, Any], findings: dict[str, Any], brand: str, notes: str = ""
) -> str:
    """The ask for trend-based recommendations: the daily trend, the same groupings a pack uses,
    and the team's own notes."""
    parts = [
        "Here is this store's day-by-day ad trend for the period (spend, CTR, ROAS):",
        f"<trend>\n{_compact(trend)}\n</trend>",
        "And the same figures grouped by format, hook and platform, with `sampleOk` saying whether "
        "there is enough spend and impressions behind a group to trust it:",
        f"<figures>\n{_compact(findings)}\n</figures>",
    ]
    if notes.strip():
        parts.append(
            "The team's own notes about this store. Treat them as context, not as figures.\n"
            f"<team_notes>\n{notes.strip()}\n</team_notes>"
        )
    parts.append(
        "Say what changed over the period and what to do about it: 3 to 5 recommendations, each "
        "resting on a figure above."
    )
    return "\n\n".join(parts)


def variations_prompt(concept: dict[str, Any], findings: dict[str, Any], brand: str) -> str:
    """The ask for variations of one winning concept."""
    voice = brand_voice(brand)
    parts = [
        "This concept is already running and performing. Produce variations for the next test.",
        f"<concept>\n{_compact(concept)}\n</concept>",
        "The store's ad figures for the period, for picking what to vary:",
        f"<figures>\n{_compact(findings)}\n</figures>",
    ]
    if voice:
        parts.append(f"<brand_guide>\n{voice}\n</brand_guide>")
    else:
        parts.append(
            "No brand guide is available for this store, so make no claim about materials, "
            "origin, durability or certification."
        )
    return "\n\n".join(parts)


# --------------------------------------------------------------------- variations of a winning ad
def ad_variations_prompt(ad: dict[str, Any], patterns: dict[str, Any] | None, brand: str) -> str:
    """The ask for variations of one real ad (usually a winner), with its own copy and tags."""
    voice = brand_voice(brand)
    parts = [
        "This is one of the store's own ads, with its copy, tags and figures. Produce variations "
        "of it for the next test round. Treat its copy as the current version to keep or change.",
        f"<ad>\n{_compact(_ad_brief(ad))}\n</ad>",
    ]
    trimmed = patterns_for_prompt(patterns, groups=5)
    if trimmed:
        parts.append(
            "What wins and loses across the store's other ads, for picking the variable:\n"
            f"<patterns>\n{_compact(trimmed)}\n</patterns>"
        )
    if voice:
        parts.append(f"<brand_guide>\n{voice}\n</brand_guide>")
    else:
        parts.append(
            "No brand guide is available for this store, so make no claim about materials, "
            "origin, durability or certification."
        )
    return "\n\n".join(parts)


# ------------------------------------------------------------------------------- designer brief
BRIEF_SIZES = ("9:16", "4:5", "1:1", "16:9")

DESIGNER_BRIEF_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "objective",
        "sizes",
        "product",
        "print_color",
        "visual_direction",
        "reference",
        "on_screen_text",
        "must_say",
        "must_not_say",
        "deliverables",
    ],
    "properties": {
        "objective": {"type": "string"},
        "sizes": {
            "type": "array",
            "minItems": 1,
            "items": {"type": "string", "enum": list(BRIEF_SIZES)},
        },
        "product": {"type": "string"},
        "print_color": {"type": "string"},
        "visual_direction": {"type": "string"},
        "reference": {"type": "string"},
        "on_screen_text": {"type": "array", "minItems": 1, "items": {"type": "string"}},
        "must_say": {"type": "array", "items": {"type": "string"}},
        "must_not_say": {"type": "array", "items": {"type": "string"}},
        "deliverables": {"type": "array", "minItems": 1, "items": {"type": "string"}},
    },
}

DESIGNER_BRIEF_SYSTEM = (
    "You write the brief a designer or video editor works from, for a small brand that sells hand "
    "block printed home textiles. You are given one creative concept, the store's tag patterns "
    "(what wins and loses by hook, visual style, print, color, category and season) and some of "
    "its products with their print and color.\n"
    "\n"
    "Rules:\n"
    "- Be concrete enough to produce without a meeting: what is in the frame, in what order, the "
    "exact words on screen, the sizes.\n"
    "- `product`: name a real product from the list when the concept fits one; otherwise say the "
    "range it shows. Never invent a product, price, offer, material or claim.\n"
    "- `reference`: point at the visual style and print/color that win in the patterns, with the "
    "figure (for example 'lifestyle_room: winner, ROAS 3.1'). Say when there is no winner yet.\n"
    "- `must_not_say`: the claims the brand guide forbids, plus anything the concept must avoid.\n"
    "- Lengths: `objective` one sentence; `visual_direction` at most 80 words; `on_screen_text` "
    "2-5 lines of at most 10 words; `deliverables` 2-6 lines, each one file with its size and "
    "length.\n"
    "- Plain British English, for a designer, not an analyst."
)


def designer_brief_prompt(
    concept: dict[str, Any],
    patterns: dict[str, Any] | None,
    products: list[dict[str, Any]],
    brand: str,
) -> str:
    """The ask for a designer brief for one saved concept."""
    voice = brand_voice(brand)
    keep = ("title", "hook", "angle", "message", "offer", "funnel_stage", "persona", "evidence")
    parts = [f"<concept>\n{_compact({k: concept.get(k) for k in keep})}\n</concept>"]
    trimmed = patterns_for_prompt(patterns, groups=5)
    if trimmed:
        parts.append(f"<patterns>\n{_compact(trimmed)}\n</patterns>")
    if products:
        listed = [
            {k: p.get(k) for k in ("title", "category", "print", "color", "season_fit")}
            for p in products[:40]
        ]
        parts.append(f"<products>\n{_compact(listed)}\n</products>")
    if voice:
        parts.append(f"<brand_guide>\n{voice}\n</brand_guide>")
    else:
        parts.append(
            "No brand guide is available for this store, so make no claim about materials, "
            "origin, durability or certification."
        )
    return "\n\n".join(parts)
