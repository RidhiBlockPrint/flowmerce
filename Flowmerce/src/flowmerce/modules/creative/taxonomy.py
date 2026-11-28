"""The fixed vocabulary used to tag products and ads.

Claude must pick from these lists and manual edits are checked against them, so the same idea is
always stored under the same word and grouping by tag stays meaningful. To add a value, add it here
(and to the tests); existing rows keep their values.
"""

from __future__ import annotations

from typing import Final

HOOK_TYPES: Final[tuple[str, ...]] = (
    "problem_solution",  # names a problem the product solves
    "craft_story",  # hand block printing, artisans, Jaipur heritage
    "social_proof",  # reviews, ratings, "loved by" claims
    "offer_discount",  # sale, discount, free shipping
    "gift_idea",  # presented as a gift
    "seasonal_moment",  # tied to a season or holiday
    "question",  # opens with a question to the viewer
    "before_after",  # a room or table transformed
    "product_feature",  # fabric, size, softness, care
    "aesthetic_mood",  # a look or feeling ("cottagecore bedroom")
    "other",
)

VISUAL_STYLES: Final[tuple[str, ...]] = (
    "lifestyle_room",  # product styled in a real room or table setting
    "product_flatlay",  # product laid flat or on plain background
    "close_up_texture",  # macro of print, fabric, stitching
    "making_process",  # block printing, artisans at work
    "ugc_person",  # a person talking to camera or unboxing
    "model_styling",  # a model using or wearing the product
    "text_graphic",  # mostly text, graphic or collage
    "other",
)

FORMATS: Final[tuple[str, ...]] = (
    "static_image",
    "carousel",
    "video",
    "other",
)

PRINTS: Final[tuple[str, ...]] = (
    "floral",
    "paisley",
    "buti",  # small repeated motif
    "geometric",
    "stripe_check",
    "animal_bird",
    "botanical_leaf",
    "abstract",
    "solid",
    "mixed",
    "other",
)

COLORS: Final[tuple[str, ...]] = (
    "indigo_blue",
    "red",
    "pink",
    "green",
    "yellow_mustard",
    "orange",
    "purple",
    "white_cream",
    "beige_natural",
    "grey",
    "black",
    "multicolor",
    "other",
)

CATEGORIES: Final[tuple[str, ...]] = (
    "bedding",
    "quilts",
    "table_linen",
    "kitchen_linen",
    "cushion_covers",
    "curtains",
    "bath",
    "apparel",
    "accessories",
    "other",
)

SEASONS: Final[tuple[str, ...]] = ("winter", "spring", "summer", "fall", "holiday")
SEASON_FITS: Final[tuple[str, ...]] = (*SEASONS, "all_season")

# Product attributes and ad tags that can be set, with their allowed values.
PRODUCT_FIELDS: Final[dict[str, tuple[str, ...]]] = {
    "print": PRINTS,
    "color": COLORS,
    "category": CATEGORIES,
    "season_fit": SEASON_FITS,
}

AD_TAG_FIELDS: Final[dict[str, tuple[str, ...]]] = {
    "hook_type": HOOK_TYPES,
    "visual_style": VISUAL_STYLES,
    "format": FORMATS,
    "print": PRINTS,
    "color": COLORS,
}


class InvalidTagError(ValueError):
    """Raised when a tag value is not in the allowed vocabulary."""


def check_value(field: str, value: str, allowed: dict[str, tuple[str, ...]]) -> str:
    """Return ``value`` if it is allowed for ``field``; raise :class:`InvalidTagError` otherwise."""
    if field not in allowed:
        raise InvalidTagError(f"Unknown field {field!r}. Allowed fields: {', '.join(allowed)}.")
    if value not in allowed[field]:
        raise InvalidTagError(
            f"{value!r} is not an allowed {field}. Allowed: {', '.join(allowed[field])}."
        )
    return value


def as_dict() -> dict[str, list[str]]:
    """The whole vocabulary, for the API and the dashboard."""
    return {
        "hook_type": list(HOOK_TYPES),
        "visual_style": list(VISUAL_STYLES),
        "format": list(FORMATS),
        "print": list(PRINTS),
        "color": list(COLORS),
        "category": list(CATEGORIES),
        "season": list(SEASONS),
        "season_fit": list(SEASON_FITS),
    }
