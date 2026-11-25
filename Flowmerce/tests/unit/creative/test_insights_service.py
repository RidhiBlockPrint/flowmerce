"""Creative Strategist: the grouping arithmetic, the brief template and the demo answers.

No network and no credentials: the service runs in demo mode, and the grouping is pure arithmetic.
"""

from __future__ import annotations

import pytest

from flowmerce.modules.creative import insights, service
from flowmerce.modules.creative.config import creative_config

ENV_KEYS = (
    "CREATIVE_DEMO",
    "CREATIVE_INSIGHT_DAYS",
    "CREATIVE_MIN_IMPRESSIONS",
    "CREATIVE_MAX_CONCEPTS",
    "DEMO_MODE",
    "META_SYSTEM_USER_TOKEN",
    "RIDHI_META_AD_ACCOUNT_ID",
    "GOOGLE_ADS_CLIENT_ID",
    "GOOGLE_ADS_CLIENT_SECRET",
    "GOOGLE_ADS_REFRESH_TOKEN",
    "RIDHI_GOOGLE_ADS_CUSTOMER_ID",
    "ADS_DEMO",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """No credentials set, so Creative follows Ads into demo mode."""
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


# ---------------------------------------------------------------- hooks
def test_hook_of_takes_the_opening_words_and_normalises_the_key() -> None:
    key, label = insights.hook_of("Dekhiye ye kurta kaise banta hai. Har block haath se.")
    # Only the first sentence counts, and the full stop that ended it is not part of the hook.
    assert label == "Dekhiye ye kurta kaise banta hai"
    assert key == "dekhiye ye kurta kaise banta hai"
    # Different punctuation and capitals group as the same hook.
    other, _ = insights.hook_of("DEKHIYE ye kurta, kaise banta hai!")
    assert other == key


def test_hook_of_falls_back_to_the_headline_and_handles_nothing() -> None:
    _, label = insights.hook_of("", "Made by hand in Jaipur")
    assert label == "Made by hand in Jaipur"
    assert insights.hook_of(None) == ("", "")


# ---------------------------------------------------------------- grouping
ROWS = [
    {"ad_id": "1", "ad_name": "video a", "ad_format": "video", "platform": "meta",
     "primary_text": "Dekhiye ye kurta kaise banta hai.",
     "spend": 1000.0, "impressions": 100_000, "clicks": 2_000, "purchases": 10.0,
     "purchase_value": 5_000.0, "video_3s_views": 20_000, "video_thruplays": 5_000},
    {"ad_id": "2", "ad_name": "video b", "ad_format": "video", "platform": "meta",
     "primary_text": "Dekhiye ye kurta kaise banta hai, dhaage se.",
     "spend": 1000.0, "impressions": 100_000, "clicks": 1_000, "purchases": 6.0,
     "purchase_value": 3_000.0, "video_3s_views": 10_000, "video_thruplays": 2_000},
    {"ad_id": "3", "ad_name": "image a", "ad_format": "image", "platform": "meta",
     "primary_text": "Flat 50% off on all kurtas.",
     "spend": 2000.0, "impressions": 200_000, "clicks": 2_000, "purchases": 8.0,
     "purchase_value": 4_000.0, "video_3s_views": 0, "video_thruplays": 0},
    {"ad_id": "4", "ad_name": "tiny", "ad_format": "image", "platform": "meta",
     "primary_text": "New arrivals are here.",
     "spend": 50.0, "impressions": 500, "clicks": 5, "purchases": 0.0,
     "purchase_value": 0.0, "video_3s_views": 0, "video_thruplays": 0},
]


def test_by_format_adds_up_and_counts_distinct_ads() -> None:
    groups = {g.key: g for g in insights.by_format(ROWS)}
    video = groups["video"]
    assert video.ads == 2
    assert video.spend == 2000.0
    assert video.impressions == 200_000
    assert video.ctr == 1.5  # 3,000 clicks on 200,000 impressions
    assert video.roas == 4.0  # 8,000 value on 2,000 spend
    assert video.hook_rate == 15.0  # 30,000 three-second views on 200,000 impressions
    assert video.hold_rate == round(7_000 / 30_000 * 100, 2)
    assert video.examples == ["video a", "video b"]


def test_by_hook_groups_the_same_opening_across_ads() -> None:
    groups = {g.key: g for g in insights.by_hook(ROWS)}
    craft = groups["dekhiye ye kurta kaise banta hai"]
    assert craft.ads == 2
    assert craft.impressions == 200_000


def test_groups_are_sorted_by_spend() -> None:
    assert [g.key for g in insights.by_format(ROWS)][0] == "image"  # 2,050 spend vs video's 2,000


def test_sample_ok_marks_a_group_with_too_little_behind_it() -> None:
    small = insights.Group(key="x", label="x", spend=50.0, impressions=500)
    assert small.sample_ok(1000, 1000.0) is False
    big = insights.Group(key="y", label="y", spend=5000.0, impressions=50_000)
    assert big.sample_ok(1000, 1000.0) is True


def test_hook_rate_is_none_for_a_format_that_has_no_video() -> None:
    """An image ad has no three-second views, so it has no hook rate: 0% would be a wrong answer,
    and it would make a still image lose a comparison of video openings."""
    groups = {g.key: g for g in insights.by_format(ROWS)}
    assert groups["image"].hook_rate is None
    assert groups["video"].hook_rate == 15.0
    # So a hook-rate comparison only ever weighs the formats that actually have video.
    out = insights.compare(insights.by_format(ROWS), "hook_rate", 1000, 1000.0)
    assert out["usable"] == 1
    assert out["best"]["key"] == "video"


def test_rates_are_none_when_there_is_nothing_to_divide_by() -> None:
    empty = insights.Group(key="x", label="x")
    assert empty.ctr is None
    assert empty.roas is None
    assert empty.cpa is None
    assert empty.hold_rate is None


# ---------------------------------------------------------------- compare
def test_compare_names_a_best_and_worst_and_ignores_thin_groups() -> None:
    groups = insights.by_format(ROWS)
    out = insights.compare(groups, "roas", 1000, 1000.0)
    assert out["best"]["key"] == "video"
    assert out["worst"]["key"] == "image"
    assert out["usable"] == 2


def test_compare_treats_a_lower_cost_per_purchase_as_better() -> None:
    groups = insights.by_format(ROWS)
    out = insights.compare(groups, "cpa", 1000, 1000.0)
    # video: 2,000 spend / 16 purchases = 125; image: 2,050 / 8 = 256.25
    assert out["best"]["key"] == "video"
    assert out["worst"]["key"] == "image"


def test_compare_returns_nothing_usable_when_every_group_is_thin() -> None:
    thin = [ROWS[3]]
    out = insights.compare(insights.by_format(thin), "roas", 1000, 1000.0)
    assert out["usable"] == 0
    assert out["best"] is None


def test_compare_refuses_an_unknown_metric() -> None:
    with pytest.raises(ValueError, match="Unknown metric"):
        insights.compare([], "vibes", 1000, 1000.0)


# ---------------------------------------------------------------- service
def test_creative_follows_ads_into_demo_mode() -> None:
    assert creative_config().demo is True


def test_demo_mode_overrides_creative_demo_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("CREATIVE_DEMO", "false")
    assert creative_config().demo is True


def test_findings_are_labelled_demo_and_mark_the_thin_group() -> None:
    out = service.findings("ridhi")
    assert out["source"] == "demo"
    assert out["adsSeen"] == 6
    formats = {g["key"]: g for g in out["formats"]}
    assert set(formats) >= {"video", "image", "carousel", "rsa"}
    # In US dollars a $1,000 spend floor is a real bar for a small brand, so several hook groups
    # are honestly "too early to judge"; the sample keeps that visible instead of hiding it.
    thin = {g["key"] for g in out["hooks"] if not g["sampleOk"]}
    assert thin, "the sample set must include groups that are too early to judge"
    assert any("new arrivals" in key for key in thin)
    # The big groups are still judged, so the page can still name a winner.
    judged = {g["key"] for g in out["formats"] if g["sampleOk"]}
    assert {"video", "image", "rsa"} <= judged
    assert out["comparisons"]["formatRoas"]["best"] is not None


def test_findings_reject_an_impossible_range() -> None:
    with pytest.raises(service.InputError):
        service.findings("ridhi", days=0)


def test_concepts_are_sample_concepts_in_demo_mode() -> None:
    out = service.concepts("ridhi")
    assert out["source"] == "demo"
    assert len(out["concepts"]) == 3
    assert {c["funnel_stage"] for c in out["concepts"]} == {"tof", "mof", "bof"}


def test_brief_markdown_contains_the_hook_stage_and_rules() -> None:
    out = service.brief_for(1, "ridhi")
    text = out["markdown"]
    assert out["source"] == "demo"
    assert "From the carved block to your table" in text
    assert "One block. Pressed by hand, hundreds of times." in text
    assert "TOF" in text
    assert "One variable changes" in text
    assert "## Why this idea" in text  # the evidence is always shown


def test_brief_for_an_unknown_concept_is_a_plain_error() -> None:
    with pytest.raises(service.InputError, match="No sample concept"):
        service.brief_for(999, "ridhi")


def test_brief_markdown_says_what_is_missing_rather_than_leaving_a_gap() -> None:
    text = service.brief_markdown({"title": "Bare idea"})
    assert "(hook not set)" in text
    assert "(angle not set)" in text
