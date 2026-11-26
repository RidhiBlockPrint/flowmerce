"""Claude's creative pack and variations: the prompt, the cleaning, the budget and the routes.

No network and no API key: `claude._structured` is replaced with a fake that records what it was
asked and answers with a fixed pack, so the rules in `prompts.py` and the cleaning in `generate.py`
are tested without spending anything.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from tests.fixtures.seo import local_client

from flowmerce.modules.creative import generate, prompts
from flowmerce.modules.seo.db import run
from flowmerce.modules.seo.integrations import claude
from flowmerce.modules.seo.services import ai_budget

ENV_KEYS = (
    "META_SYSTEM_USER_TOKEN",
    "RIDHI_META_AD_ACCOUNT_ID",
    "GOOGLE_ADS_CLIENT_ID",
    "GOOGLE_ADS_CLIENT_SECRET",
    "GOOGLE_ADS_REFRESH_TOKEN",
    "RIDHI_GOOGLE_ADS_CUSTOMER_ID",
    "ADS_DEMO",
    "CREATIVE_DEMO",
    "DEMO_MODE",
)

FULL_CONCEPT: dict[str, Any] = {
    "title": "Karigar ka haath",
    "hook": "Ye block banane me teen din lagte hain.",
    "alternative_hooks": ["Teen din, ek block.", "Ye nishaan machine nahi bana sakti."],
    "angle": "Video earns 5.88 ROAS against image 2.76, so lead with how it is made.",
    "message": "Every cloth is hand block printed in Jaipur.",
    "offer": "",
    "funnel_stage": "tof",
    "persona": "Home decorators who care how things are made",
    "evidence": ["video ROAS 5.88 vs image 2.76", "craft hook CTR 1.66%"],
    "formats": {
        "static": {
            "headline": "Hand block printed",
            "primary_text": "Three days for one block.",
            "visual_note": "Close-up of the carved block",
        },
        "carousel": [
            {"frame": 1, "visual": "The carver's hands", "caption": "Day one"},
            {"frame": 2, "visual": "Dye tray", "caption": "Day two"},
        ],
        "reel": {
            "length_seconds": 20,
            "shots": [
                {"at_second": 0, "visual": "Block hits cloth", "on_screen_text": "Teen din"},
                {"at_second": 6, "visual": "Pattern repeats", "on_screen_text": "Ek block"},
            ],
        },
        "ugc": {
            "creator_brief": "Film your own table being laid.",
            "talking_points": ["How it washes", "The small wobble is the proof"],
            "do_not_say": ["organic", "certified"],
        },
    },
    "test": {
        "hypothesis": "A craft hook lifts CTR against the discount hook.",
        "variable": "hook",
        "variants": ["Craft hook", "Discount hook"],
        "success_metric": "ctr",
    },
}

PACK_ANSWER: dict[str, Any] = {
    "summary": "Video earns its spend; the discount image does not.",
    "data_caveat": "28 days, and only one format has video data.",
    "concepts": [FULL_CONCEPT],
}


class FakeClaude:
    """Records every ask and answers with a fixed pack. Never touches the network."""

    def __init__(self, answer: dict[str, Any] | None = None) -> None:
        self.answer = answer if answer is not None else PACK_ANSWER
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self, system: Any, prompt: str, schema: dict[str, Any], effort: str, max_tokens: int = 0
    ) -> tuple[dict[str, Any], str]:
        self.calls.append(
            {
                "system": system,
                "prompt": prompt,
                "schema": schema,
                "effort": effort,
                "max_tokens": max_tokens,
            }
        )
        return self.answer, "claude-test-model"


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeClaude:
    """A configured Claude that costs nothing, with no ad credentials so the figures are samples."""
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    stub = FakeClaude()
    monkeypatch.setattr(claude, "_structured", stub)
    monkeypatch.setattr(claude, "configured", lambda: True)
    monkeypatch.setattr(claude, "take_usage", dict)
    # Clear anything an earlier test kept for this store, so `state` starts from nothing.
    run("DELETE FROM app_settings WHERE key LIKE 'creative_pack:%'")
    run("DELETE FROM app_settings WHERE key LIKE 'creative_recs:%'")
    run("DELETE FROM claude_usage")
    return stub


# ---------------------------------------------------------------- brand voice in the prompt
def test_brand_voice_sends_only_the_voice_and_claims_files() -> None:
    """A brand's full knowledge runs to ~200,000 characters; only the voice rules belong in an ad
    prompt, and the rest would cost more than the answer is worth."""
    voice = prompts.brand_voice("ridhi")
    assert voice, "Ridhi has a brand voice file, so something must be sent"
    assert len(voice) <= prompts.VOICE_MAX_CHARS + 200
    assert "brand-voice" in voice  # the document name is kept so Claude can cite it
    assert "aeo-geo-playbook" not in voice
    assert "master-brief" not in voice


def test_brand_voice_is_empty_for_a_brand_without_one() -> None:
    assert prompts.brand_voice("no-such-brand") == ""


def test_pack_prompt_carries_the_figures_and_says_what_is_missing() -> None:
    findings = {"formats": [{"key": "video", "sampleOk": True}], "source": "demo"}
    with_guide = prompts.pack_prompt(findings, "ridhi")
    assert '"key":"video"' in with_guide  # compact JSON, no wasted tokens
    assert "<brand_guide>" in with_guide

    without = prompts.pack_prompt(findings, "no-such-brand")
    assert "<brand_guide>" not in without
    assert "No brand guide is available" in without


def test_pack_prompt_includes_team_notes_when_there_are_any() -> None:
    findings: dict[str, Any] = {"formats": []}
    assert "<team_notes>" not in prompts.pack_prompt(findings, "ridhi", "   ")
    assert "we already run Reels" in prompts.pack_prompt(findings, "ridhi", "we already run Reels")


def _walk(node: Any, path: str = "") -> list[tuple[str, dict[str, Any]]]:
    """Every array in a schema, with the path that reaches it."""
    found: list[tuple[str, dict[str, Any]]] = []
    if not isinstance(node, dict):
        return found
    if node.get("type") == "array":
        found.append((path or "(root)", node))
    for key in ("properties", "items", "$defs"):
        child = node.get(key)
        if isinstance(child, dict) and key in ("items",):
            found += _walk(child, f"{path}[]")
        elif isinstance(child, dict):
            for name, value in child.items():
                found += _walk(value, f"{path}.{name}" if path else name)
    return found


@pytest.mark.parametrize(
    "schema", [prompts.PACK_SCHEMA, prompts.VARIATIONS_SCHEMA, prompts.RECS_SCHEMA]
)
def test_every_array_uses_only_constraints_structured_outputs_accepts(
    schema: dict[str, Any],
) -> None:
    """Structured outputs take `minItems` of 0 or 1 and no `maxItems`; anything else is a 400.

    The second live call (2026-11-25) was refused outright for exactly this: "For 'array' type,
    'minItems' values other than 0 or 1 are not supported". A schema the API refuses costs a whole
    round trip to discover, so it is checked here instead.
    """
    arrays = _walk(schema)
    assert arrays, "the schema should contain arrays"
    for path, array in arrays:
        assert array.get("minItems", 0) in (0, 1), f"{path}: minItems must be 0 or 1"
        assert "maxItems" not in array, f"{path}: maxItems is not supported"
        assert "uniqueItems" not in array, f"{path}: only minItems is accepted on an array"


def test_the_schema_forces_content_not_just_the_right_shape() -> None:
    """The first live call (2026-11-25) obeyed the schema and still came back with an empty Reel
    shot list, no UGC talking points and no test variants: `required` is satisfied by an empty
    array. `minItems: 1` is what actually makes the model fill them, so it is pinned here."""
    item = prompts.PACK_SCHEMA["properties"]["concepts"]["items"]["properties"]
    assert item["alternative_hooks"]["minItems"] == 1
    assert item["evidence"]["minItems"] == 1
    formats = item["formats"]["properties"]
    assert formats["carousel"]["minItems"] == 1
    assert formats["reel"]["properties"]["shots"]["minItems"] == 1
    assert formats["ugc"]["properties"]["talking_points"]["minItems"] == 1
    assert item["test"]["properties"]["variants"]["minItems"] == 1
    # do_not_say may legitimately be empty when the brand guide forbids nothing.
    assert "minItems" not in formats["ugc"]["properties"]["do_not_say"]
    assert prompts.VARIATIONS_SCHEMA["properties"]["variations"]["minItems"] == 1
    # The counts the schema cannot ask for are stated as rules instead, and capped in code.
    assert "never fewer than 3" in prompts.PACK_SYSTEM
    assert generate.MAX_CONCEPTS == 5


def test_the_prompt_rules_forbid_inventing_and_demand_one_variable() -> None:
    """These two rules are why the output can be trusted, so they are pinned by a test."""
    assert "Never invent a figure" in prompts.PACK_SYSTEM
    assert "exactly ONE variable" in prompts.PACK_SYSTEM
    assert "sampleOk`: false" in prompts.PACK_SYSTEM or "sampleOk: false" in prompts.PACK_SYSTEM
    assert "writing words, not making pictures" in prompts.PACK_SYSTEM
    assert "ONE variable" in prompts.VARIATIONS_SYSTEM


# ---------------------------------------------------------------- cleaning
def test_clean_pack_keeps_a_full_concept_intact() -> None:
    out = generate.clean_pack(PACK_ANSWER)
    assert out["summary"].startswith("Video earns")
    concept = out["concepts"][0]
    assert concept["funnel_stage"] == "tof"
    assert concept["test"]["variable"] == "hook"
    assert len(concept["formats"]["carousel"]) == 2
    assert concept["formats"]["reel"]["length_seconds"] == 20
    assert concept["formats"]["ugc"]["do_not_say"] == ["organic", "certified"]


def test_clean_pack_replaces_values_the_rest_of_the_code_cannot_use() -> None:
    """A model that ignores an enum or a type must not put unusable data on the page."""
    out = generate.clean_pack(
        {
            "summary": "",
            "concepts": [
                {
                    "title": "",
                    "funnel_stage": "middle-of-funnel",
                    "evidence": "not a list",
                    "formats": {"carousel": ["not a frame"], "reel": {"length_seconds": "soon"}},
                    "test": {"variable": "everything", "success_metric": "vibes"},
                }
            ],
        }
    )
    concept = out["concepts"][0]
    assert concept["title"] == "Untitled concept"
    assert concept["funnel_stage"] == "tof"
    assert concept["evidence"] == []
    assert concept["formats"]["carousel"] == []
    assert concept["formats"]["reel"]["length_seconds"] == 20
    assert concept["test"]["variable"] == "hook"
    assert concept["test"]["success_metric"] == "roas"


def test_clean_pack_caps_how_many_concepts_are_kept() -> None:
    many = {"concepts": [{"title": f"Idea {i}"} for i in range(12)]}
    assert len(generate.clean_pack(many)["concepts"]) == generate.MAX_CONCEPTS


def test_clean_variations_labels_an_unlabelled_variant() -> None:
    out = generate.clean_variations(
        {"variable": "nonsense", "variations": [{"hook": "a"}, {"hook": "b"}, "junk"]}
    )
    assert out["variable"] == "hook"
    assert [v["label"] for v in out["variations"]] == ["Variant 1", "Variant 2"]


# ---------------------------------------------------------------- the run
def test_pack_is_written_stored_and_read_back(fake: FakeClaude) -> None:
    generate._work("ridhi", "tester")  # the thread body, run directly
    saved = generate.state("ridhi")
    assert saved["status"] == "ready"
    assert saved["model"] == "claude-test-model"
    assert saved["source"] == "demo"
    assert saved["fresh"] is True
    assert saved["pack"]["concepts"][0]["title"] == "Karigar ka haath"
    assert len(fake.calls) == 1
    assert fake.calls[0]["effort"] == "high"
    # The real figures reached Claude, not a placeholder.
    assert "video" in fake.calls[0]["prompt"]


def test_a_failed_call_is_reported_and_does_not_lose_an_earlier_pack(
    fake: FakeClaude, monkeypatch: pytest.MonkeyPatch
) -> None:
    generate._work("ridhi", "tester")
    assert generate.state("ridhi")["status"] == "ready"

    def boom(*_a: Any, **_k: Any) -> Any:
        raise claude.ClaudeError("Claude is overloaded.", "server")

    monkeypatch.setattr(claude, "_structured", boom)
    generate._work("ridhi", "tester")
    after = generate.state("ridhi")
    assert after["status"] == "ready", "the pack already written must survive a later failure"
    assert "overloaded" in (after["error"] or "")
    assert after["pack"]["concepts"][0]["title"] == "Karigar ka haath"


def test_state_without_a_pack_reports_none(fake: FakeClaude) -> None:
    out = generate.state("cpc")
    assert out["status"] == "none"
    assert out["pack"] is None
    assert out["fresh"] is False
    assert out["estimate_usd"] == ai_budget.ESTIMATE_USD["creative_pack"]


def test_start_refuses_when_claude_is_not_configured(
    fake: FakeClaude, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(claude, "configured", lambda: False)
    with pytest.raises(Exception) as exc:
        generate.start("ridhi", "tester")
    assert getattr(exc.value, "code", "") == "pending_setup"


def test_start_refuses_an_unknown_brand(fake: FakeClaude) -> None:
    with pytest.raises(ValueError, match="Unknown brand"):
        generate.start("nope", "tester")


def test_the_daily_limit_stops_a_request_before_anything_is_sent(
    fake: FakeClaude, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Money is checked first: a refused request must not reach Claude at all."""

    def used_up(_kind: str) -> None:
        from flowmerce.modules.seo.util import HttpError

        raise HttpError(429, "Today's Claude limit is used up.", "daily_limit")

    monkeypatch.setattr(ai_budget, "check", used_up)
    with pytest.raises(Exception) as exc:
        generate.start("ridhi", "tester")
    assert getattr(exc.value, "code", "") == "daily_limit"
    assert fake.calls == [], "nothing may be sent to Claude once the limit refuses the request"


# ---------------------------------------------------------------- variations
def test_variations_change_one_variable_and_are_not_stored(
    fake: FakeClaude, monkeypatch: pytest.MonkeyPatch
) -> None:
    answer = {
        "variable": "hook",
        "kept": "Same video, same offer.",
        "variations": [
            {"label": "A", "hook": "Teen din, ek block.", "what_changed": "Shorter", "why": "CTR"},
        ],
    }
    monkeypatch.setattr(claude, "_structured", FakeClaude(answer))
    out = generate.variations("ridhi", FULL_CONCEPT)
    assert out["variable"] == "hook"
    assert out["variations"][0]["label"] == "A"
    assert out["source"] == "demo"
    # Variations are returned for the team to read, never saved over the stored pack.
    assert generate.state("ridhi")["pack"] is None


def test_variations_need_a_concept(fake: FakeClaude) -> None:
    from flowmerce.modules.creative import service

    with pytest.raises(service.InputError):
        generate.variations("ridhi", {})
    assert fake.calls == []


# ---------------------------------------------------------------- routes
@pytest.fixture
def app(fake: FakeClaude) -> Any:
    from flowmerce.modules.seo.app import create_app

    return create_app()


def test_pack_route_reads_without_spending(app: Any, fake: FakeClaude) -> None:
    response = local_client(app).get("/api/creative/pack?brand=ridhi")
    assert response.status_code == 200
    assert response.json()["status"] == "none"
    assert fake.calls == [], "opening the page must never ask Claude for anything"


def test_post_pack_route_asks_claude(app: Any, fake: FakeClaude) -> None:
    client = local_client(app)
    response = client.post(
        "/api/creative/pack?brand=ridhi", headers={"X-Requested-With": "blog-ops"}
    )
    assert response.status_code == 200
    assert response.json()["status"] in ("running", "ready")


def test_variations_route_rejects_an_empty_body(app: Any) -> None:
    response = local_client(app).post(
        "/api/creative/variations?brand=ridhi",
        headers={"X-Requested-With": "blog-ops"},
        content=json.dumps({}),
    )
    assert response.status_code == 400
    assert response.json()["code"] == "bad_request"


def test_write_routes_need_the_csrf_header(app: Any) -> None:
    """The app's CSRF guard must cover the new write routes like every other one."""
    response = local_client(app).post("/api/creative/pack?brand=ridhi")
    assert response.status_code == 403
    assert response.json()["code"] == "csrf"


# ---------------------------------------------------------------- recommendations
RECS_ANSWER: dict[str, Any] = {
    "summary": "Video is earning its spend; the discount image is not.",
    "recommendations": [
        {
            "title": "Shift budget toward video",
            "diagnosis": "Video ROAS 5.88 against image 2.76 over the period.",
            "evidence": ["video ROAS 5.88", "image ROAS 2.76"],
            "action": "Move 20% of the image budget to the best-performing video ad.",
            "priority": "high",
        },
        {
            "title": "Watch the discount hook",
            "diagnosis": "CTR on the discount hook is the lowest of any group.",
            "evidence": ["discount hook CTR 1.2%"],
            "action": "Pause it if CTR has not improved after another week of spend.",
            "priority": "medium",
        },
    ],
}


def test_clean_recs_keeps_recommendations_and_sorts_by_priority() -> None:
    out = generate.clean_recs(
        {
            "summary": "ok",
            "recommendations": [
                {"title": "Low one", "priority": "low", "evidence": ["a"]},
                {"title": "High one", "priority": "high", "evidence": ["b"]},
            ],
        }
    )
    assert [r["title"] for r in out["recommendations"]] == ["High one", "Low one"]


def test_clean_recs_replaces_values_the_rest_of_the_code_cannot_use() -> None:
    out = generate.clean_recs(
        {"recommendations": [{"title": "", "priority": "urgent!!", "evidence": "not a list"}]}
    )
    rec = out["recommendations"][0]
    assert rec["title"] == "Untitled recommendation"
    assert rec["priority"] == "medium"
    assert rec["evidence"] == []


def test_clean_recs_caps_how_many_are_kept() -> None:
    many = {"recommendations": [{"title": f"Idea {i}"} for i in range(12)]}
    assert len(generate.clean_recs(many)["recommendations"]) == generate.MAX_RECOMMENDATIONS


def test_recommendations_are_written_stored_and_read_back(
    fake: FakeClaude, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(claude, "_structured", FakeClaude(RECS_ANSWER))
    generate._work_recs("ridhi", "tester")  # the thread body, run directly
    saved = generate.state_recs("ridhi")
    assert saved["status"] == "ready"
    assert saved["model"] == "claude-test-model"
    assert saved["source"] == "demo"
    assert saved["fresh"] is True
    assert saved["recs"]["recommendations"][0]["title"] == "Shift budget toward video"


def test_recommendations_failure_does_not_lose_an_earlier_round(
    fake: FakeClaude, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(claude, "_structured", FakeClaude(RECS_ANSWER))
    generate._work_recs("ridhi", "tester")
    assert generate.state_recs("ridhi")["status"] == "ready"

    def boom(*_a: Any, **_k: Any) -> Any:
        raise claude.ClaudeError("Claude is overloaded.", "server")

    monkeypatch.setattr(claude, "_structured", boom)
    generate._work_recs("ridhi", "tester")
    after = generate.state_recs("ridhi")
    assert after["status"] == "ready", "recommendations already written must survive a failure"
    assert "overloaded" in (after["error"] or "")


def test_state_recs_without_a_round_reports_none(fake: FakeClaude) -> None:
    out = generate.state_recs("cpc")
    assert out["status"] == "none"
    assert out["recs"] is None
    assert out["estimate_usd"] == ai_budget.ESTIMATE_USD["creative_recommendations"]


def test_start_recs_refuses_when_claude_is_not_configured(
    fake: FakeClaude, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(claude, "configured", lambda: False)
    with pytest.raises(Exception) as exc:
        generate.start_recs("ridhi", "tester")
    assert getattr(exc.value, "code", "") == "pending_setup"


def test_recommendations_route_reads_without_spending(app: Any, fake: FakeClaude) -> None:
    response = local_client(app).get("/api/creative/recommendations?brand=ridhi")
    assert response.status_code == 200
    assert response.json()["status"] == "none"
    assert fake.calls == [], "opening the page must never ask Claude for anything"


def test_post_recommendations_route_asks_claude(app: Any, fake: FakeClaude) -> None:
    client = local_client(app)
    response = client.post(
        "/api/creative/recommendations?brand=ridhi", headers={"X-Requested-With": "blog-ops"}
    )
    assert response.status_code == 200
    assert response.json()["status"] in ("running", "ready")
