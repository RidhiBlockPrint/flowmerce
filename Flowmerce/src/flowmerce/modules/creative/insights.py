"""Working out what the ads actually showed: the Research and Insight steps of the loop.

This file contains no AI and no network: it takes rows of ad-level daily figures (the shape of
ads.v_ad_daily) and groups them, so the arithmetic can be read, argued with and unit tested. The AI
step later writes *words* about these findings; it never produces the numbers.

Two groupings matter for creatives:
  * by format (image, video, carousel): which kind of creative earns its spend
  * by hook, meaning the first words of the ad's own copy: which opening line holds attention

Every group carries `sample_ok`: whether there is enough spend and impressions behind it to be worth
acting on. A group below that is still returned, marked, rather than hidden.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# How many words of the ad's copy count as "the hook". The opening line is what a viewer reads or
# hears first, so ads sharing an opening are compared as one idea.
HOOK_WORDS = 6


@dataclass
class Group:
    """Added-up figures for one group of ads (a format, a hook, a concept)."""

    key: str
    label: str
    spend: float = 0.0
    impressions: int = 0
    clicks: int = 0
    purchases: float = 0.0
    purchase_value: float = 0.0
    video_3s: int = 0
    thruplays: int = 0
    ads: int = 0
    examples: list[str] = field(default_factory=list)

    # ---------------------------------------------------------- derived rates
    @property
    def ctr(self) -> float | None:
        """Clicks per 100 impressions."""
        return round(self.clicks / self.impressions * 100, 2) if self.impressions else None

    @property
    def roas(self) -> float | None:
        """Platform-reported value for each unit of spend."""
        return round(self.purchase_value / self.spend, 2) if self.spend > 0 else None

    @property
    def cpa(self) -> float | None:
        """Spend per platform-reported purchase."""
        return round(self.spend / self.purchases, 2) if self.purchases > 0 else None

    @property
    def hook_rate(self) -> float | None:
        """Share of impressions that watched three seconds: did the opening stop the scroll.

        None for a group with no video views at all, which is what an image or a search ad is.
        A flat 0% there is not a bad hook, it is a metric the format does not have, and returning
        the number would let a still image come last in a comparison of video openings.
        """
        if not self.impressions or not self.video_3s:
            return None
        return round(self.video_3s / self.impressions * 100, 2)

    @property
    def hold_rate(self) -> float | None:
        """Share of three-second views that reached a thruplay: did the middle hold them."""
        return round(self.thruplays / self.video_3s * 100, 2) if self.video_3s else None

    def sample_ok(self, min_impressions: int, min_spend: float) -> bool:
        """Whether there is enough behind this group to act on it."""
        return self.impressions >= min_impressions and self.spend >= min_spend

    def as_dict(self, min_impressions: int, min_spend: float) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "ads": self.ads,
            "spend": round(self.spend, 2),
            "impressions": self.impressions,
            "clicks": self.clicks,
            "purchases": round(self.purchases, 2),
            "purchaseValue": round(self.purchase_value, 2),
            "ctr": self.ctr,
            "roas": self.roas,
            "cpa": self.cpa,
            "hookRate": self.hook_rate,
            "holdRate": self.hold_rate,
            "sampleOk": self.sample_ok(min_impressions, min_spend),
            "examples": self.examples[:3],
        }


def hook_of(text: str | None, fallback: str = "") -> tuple[str, str]:
    """The first few words of an ad's copy, as (key, label).

    The key is lower-cased and stripped of punctuation so the same opening written with different
    emoji or capitals groups together; the label keeps the original words for the page to show.
    """
    raw = (text or fallback or "").strip()
    if not raw:
        return "", ""
    # Split on the first sentence end, then take at most HOOK_WORDS words of it.
    first = re.split(r"[.!?\n]", raw, maxsplit=1)[0].strip()
    words = first.split()[:HOOK_WORDS]
    label = " ".join(words)
    key = re.sub(r"[^a-z0-9 ]+", "", label.lower()).strip()
    key = re.sub(r"\s+", " ", key)
    return key, label


def _add(group: Group, row: dict[str, Any]) -> None:
    """Add one ad-day row into a group."""
    group.spend += float(row.get("spend") or 0)
    group.impressions += int(row.get("impressions") or 0)
    group.clicks += int(row.get("clicks") or 0)
    group.purchases += float(row.get("purchases") or 0)
    group.purchase_value += float(row.get("purchase_value") or row.get("purchaseValue") or 0)
    group.video_3s += int(row.get("video_3s_views") or 0)
    group.thruplays += int(row.get("video_thruplays") or 0)


def _collect(rows: list[dict[str, Any]], key_of) -> list[Group]:  # type: ignore[no-untyped-def]
    """Group the daily rows by whatever key_of returns, counting distinct ads per group."""
    groups: dict[str, Group] = {}
    seen_ads: dict[str, set[str]] = {}
    for row in rows:
        key, label = key_of(row)
        if not key:
            continue
        group = groups.get(key)
        if group is None:
            group = groups[key] = Group(key=key, label=label)
            seen_ads[key] = set()
        _add(group, row)
        ad_id = str(row.get("ad_id") or row.get("adId") or "")
        if ad_id and ad_id not in seen_ads[key]:
            seen_ads[key].add(ad_id)
            group.ads += 1
            name = str(row.get("ad_name") or row.get("adName") or "").strip()
            if name and len(group.examples) < 3:
                group.examples.append(name)
    return sorted(groups.values(), key=lambda g: g.spend, reverse=True)


def by_format(rows: list[dict[str, Any]]) -> list[Group]:
    """Group the rows by creative format (image, video, carousel, ...)."""

    def key_of(row: dict[str, Any]) -> tuple[str, str]:
        raw = str(row.get("ad_format") or row.get("adFormat") or "").strip().lower()
        return (raw, raw) if raw else ("unknown", "unknown format")

    return _collect(rows, key_of)


def by_hook(rows: list[dict[str, Any]]) -> list[Group]:
    """Group the rows by the opening words of the ad's copy."""

    def key_of(row: dict[str, Any]) -> tuple[str, str]:
        return hook_of(
            str(row.get("primary_text") or row.get("primaryText") or ""),
            str(row.get("headline") or ""),
        )

    return _collect(rows, key_of)


def by_platform(rows: list[dict[str, Any]]) -> list[Group]:
    """Group the rows by platform, so Meta and Google can be compared side by side."""

    def key_of(row: dict[str, Any]) -> tuple[str, str]:
        raw = str(row.get("platform") or "").strip().lower()
        return (raw, raw) if raw else ("unknown", "unknown platform")

    return _collect(rows, key_of)


def compare(
    groups: list[Group], metric: str, min_impressions: int, min_spend: float
) -> dict[str, Any]:
    """Best and worst group on one metric, counting only groups with enough data behind them.

    Returns the two groups and the median, so the page can say "this is 40% above the middle"
    rather than only naming a winner. An empty answer means nothing had enough data yet.
    """
    if metric not in ("ctr", "roas", "cpa", "hook_rate", "hold_rate"):
        raise ValueError(f"Unknown metric {metric!r}.")
    usable = [
        g
        for g in groups
        if g.sample_ok(min_impressions, min_spend) and getattr(g, metric) is not None
    ]
    if not usable:
        return {"metric": metric, "best": None, "worst": None, "median": None, "usable": 0}
    # For cost per purchase, lower is better; for every other metric, higher is.
    reverse = metric != "cpa"
    ordered = sorted(usable, key=lambda g: float(getattr(g, metric)), reverse=reverse)
    values = sorted(float(getattr(g, metric)) for g in usable)
    middle = len(values) // 2
    median = (
        values[middle] if len(values) % 2 else round((values[middle - 1] + values[middle]) / 2, 2)
    )
    return {
        "metric": metric,
        "best": ordered[0].as_dict(min_impressions, min_spend),
        "worst": ordered[-1].as_dict(min_impressions, min_spend),
        "median": median,
        "usable": len(usable),
    }
