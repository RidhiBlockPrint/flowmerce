"""Creative Strategist outputs: the pack reads the tag patterns and writes a Story, variations of a
winning ad, and designer briefs kept as drafts and approved. No network: Claude, the budget and
Supabase are fakes."""

from __future__ import annotations

from typing import Any

import pytest
from tests.unit.creative.test_tags_patterns import FakeCreative

from flowmerce.modules.creative import generate, products, prompts, service
from flowmerce.modules.creative.config import set_creative_client
from flowmerce.modules.seo.integrations import claude
from flowmerce.modules.seo.services import ai_budget

WINNER = {
    "adId": "w1",
    "name": "Craft video",
    "headline": "Printed by hand",
    "primaryText": "Every block is carved by hand in Jaipur.",
    "productTitle": "Indigo Quilt",
    "tags": {
        "hook_type": "craft_story",
        "hook_text": "Every block",
        "visual_style": "making_process",
        "format": "video",
        "print": "floral",
        "color": "indigo_blue",
        "category": "quilts",
        "season": "holiday",
        "product": "indigo-quilt",
        "source": "ai",
        "confirmed": True,
    },
    "verdict": "winner",
    "sums": {"spend": 3000.0},
    "rates": {"roas": 3.4, "ctr": 2.1, "hookRate": 30.0},
}
PATTERNS = {
    "source": "live",
    "currency": "INR",
    "adCount": 1,
    "untagged": 0,
    "rule": {
        "min_spend": 1000.0,
        "min_impressions": 1000.0,
        "target_roas": 2.0,
        "breakeven_roas": 1.0,
    },
    "verdicts": {"winner": 1, "average": 0, "loser": 0, "insufficient_data": 0},
    "dimensions": {
        "hook_type": [
            {
                "value": "craft_story",
                "ads": 1,
                "verdict": "winner",
                "sums": {"spend": 3000.0},
                "rates": {"roas": 3.4},
            }
        ]
    },
    "topWinners": [WINNER],
    "topLosers": [],
    "ads": [WINNER],
}


class FakeClaude:
    def __init__(self, answer: dict[str, Any]) -> None:
        self.answer = answer
        self.prompts: list[str] = []

    def __call__(
        self, system: Any, prompt: Any, schema: dict[str, Any], effort: str, max_tokens: int = 0
    ) -> tuple[dict[str, Any], str]:
        self.prompts.append(str(prompt))
        return self.answer, "fake-model"


@pytest.fixture
def no_spend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(claude, "configured", lambda: True)
    monkeypatch.setattr(claude, "take_usage", lambda: {})
    monkeypatch.setattr(ai_budget, "check", lambda kind: None)
    monkeypatch.setattr(ai_budget, "record", lambda usage, brand, kind, job_id=None: 0.0)


# ------------------------------------------------------------------------------ pack and Story
def test_the_pack_prompt_carries_the_patterns_only_when_there_are_some() -> None:
    findings = {"formats": [], "hooks": []}
    with_patterns = prompts.pack_prompt(findings, "ridhi", "", PATTERNS)
    assert "<patterns>" in with_patterns and "craft_story" in with_patterns
    assert "Every block is carved" in with_patterns  # the winner's own copy
    assert "<patterns>" not in prompts.pack_prompt(findings, "ridhi", "", None)
    assert "<patterns>" not in prompts.pack_prompt(
        findings, "ridhi", "", {**PATTERNS, "adCount": 0}
    )


def test_the_pack_asks_for_and_keeps_a_story() -> None:
    assert (
        "story"
        in prompts.PACK_SCHEMA["properties"]["concepts"]["items"]["properties"]["formats"][
            "required"
        ]
    )
    formats = generate._formats(
        {
            "story": {
                "frames": [
                    {
                        "frame": 1,
                        "visual": "Cloth unfolds",
                        "on_screen_text": "Made by hand",
                        "sticker": "poll",
                    },
                    "not a frame",
                ]
            }
        }
    )
    assert formats["story"]["frames"] == [
        {"frame": 1, "visual": "Cloth unfolds", "on_screen_text": "Made by hand", "sticker": "poll"}
    ]
    assert generate._formats({})["story"] == {"frames": []}  # missing: empty, never invented


# --------------------------------------------------------------------- variations of a winning ad
def test_variations_of_a_winning_ad_read_its_own_copy(
    monkeypatch: pytest.MonkeyPatch, no_spend: None
) -> None:
    monkeypatch.setattr(service, "creative_patterns", lambda brand: PATTERNS)
    fake = FakeClaude(
        {
            "variable": "visual",
            "kept": "The craft hook and the copy",
            "variations": [
                {
                    "label": "A",
                    "hook": "Every block",
                    "what_changed": "Lifestyle room",
                    "why": "lifestyle wins elsewhere",
                }
            ],
        }
    )
    monkeypatch.setattr(claude, "_structured", fake)
    out = generate.ad_variations("ridhi", "w1")
    assert out["variable"] == "visual" and out["adName"] == "Craft video"
    assert len(out["variations"]) == 1
    assert "Every block is carved by hand" in fake.prompts[0]
    with pytest.raises(products.NotFoundError):
        generate.ad_variations("ridhi", "nope")


# ------------------------------------------------------------------------------ designer briefs
class FakeWithBriefs(FakeCreative):
    KEYS = {**FakeCreative.KEYS, "concept": ("id",), "brief": ("id",)}

    def __init__(self) -> None:
        super().__init__()
        self.tables["concept"] = [
            {"id": 7, "store": "RBP", "title": "From block to table", "hook": "One block, by hand"},
            {"id": 8, "store": "CPC", "title": "Other store's idea", "hook": "x"},
        ]
        self.tables["brief"] = []

    def insert_returning(self, table: str, row: dict[str, Any]) -> dict[str, Any]:
        saved = {"id": len(self.tables[table]) + 1, **row}
        self.tables[table].append(saved)
        return dict(saved)


@pytest.fixture
def live_briefs(monkeypatch: pytest.MonkeyPatch) -> FakeWithBriefs:
    monkeypatch.setenv("CREATIVE_DEMO", "false")
    monkeypatch.delenv("DEMO_MODE", raising=False)
    fake = FakeWithBriefs()
    set_creative_client(fake)
    monkeypatch.setattr(generate, "_patterns", lambda brand: PATTERNS)
    yield fake
    set_creative_client(None)


BRIEF = {
    "objective": "Show the craft.",
    "sizes": ["9:16", "1:1", "3:2"],
    "product": "Indigo Quilt",
    "print_color": "Floral, indigo",
    "visual_direction": "Hands, block, cloth.",
    "reference": "making_process: winner, ROAS 3.4",
    "on_screen_text": ["One block", "By hand"],
    "must_say": ["Hand block printed"],
    "must_not_say": ["organic"],
    "deliverables": ["Reel 9:16, 15s", "Static 1:1"],
}


def test_designer_brief_is_kept_as_a_draft_and_approved(
    live_briefs: FakeWithBriefs, monkeypatch: pytest.MonkeyPatch, no_spend: None
) -> None:
    monkeypatch.setattr(claude, "_structured", FakeClaude(BRIEF))
    out = generate.designer_brief("ridhi", 7, "owner@test")
    brief = out["brief"]
    assert brief["status"] == "draft" and brief["concept_id"] == 7
    assert brief["requirements"]["sizes"] == ["9:16", "1:1"]  # an unknown size is dropped
    assert "# Designer brief: From block to table" in brief["body_md"]
    assert "- organic" in brief["body_md"] and "> One block, by hand" in brief["body_md"]
    assert [b["id"] for b in service.briefs_for("ridhi", 7)["briefs"]] == [brief["id"]]
    approved = service.approve_brief("ridhi", brief["id"], "owner@test")
    assert approved["status"] == "approved" and approved["approved_by"] == "owner@test"


def test_a_brief_cannot_be_written_or_approved_for_another_store(
    live_briefs: FakeWithBriefs, monkeypatch: pytest.MonkeyPatch, no_spend: None
) -> None:
    monkeypatch.setattr(claude, "_structured", FakeClaude(BRIEF))
    with pytest.raises(products.NotFoundError):
        generate.designer_brief("ridhi", 8, "owner@test")  # concept 8 belongs to CPC
    cpc = generate.designer_brief("cpc", 8, "owner@test")["brief"]
    with pytest.raises(products.NotFoundError):
        service.approve_brief("ridhi", cpc["id"], "owner@test")


def test_designer_brief_is_refused_in_demo_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CREATIVE_DEMO", "true")
    with pytest.raises(products.NotConfiguredError):
        generate.designer_brief("ridhi", 1, "owner@test")
    assert service.briefs_for("ridhi", 1)["briefs"] == []
