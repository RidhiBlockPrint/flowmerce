"""What the Creative Strategist monitors: ad copy from Meta, tags, products, rules, seasons and the
winner / loser patterns. No network: Supabase is a small in-memory fake, Claude a stub."""

from __future__ import annotations

from typing import Any

import pytest
from tests.fixtures.seo import local_client

from flowmerce.modules.ads import data as ads_data
from flowmerce.modules.ads.meta import ad_copy
from flowmerce.modules.creative import patterns, products, service, tagging, taxonomy
from flowmerce.modules.creative.config import set_creative_client
from flowmerce.modules.shipping.supabase import Page, SupabaseError

CSRF = {"X-Requested-With": "blog-ops"}
RULE = {"min_spend": 100.0, "min_impressions": 1000.0, "target_roas": 2.0, "breakeven_roas": 1.0}


# ---------------------------------------------------------------------------- fake Supabase
class FakeCreative:
    """select / upsert / update over in-memory tables, with eq, lt and in filters."""

    KEYS = {
        "product": ("store", "handle"),
        "ad_tag": ("ad_id",),
        "rule": ("store",),
        "season": ("store", "season"),
    }

    def __init__(self) -> None:
        self.tables: dict[str, list[dict[str, Any]]] = {k: [] for k in self.KEYS}

    @staticmethod
    def _match(row: dict[str, Any], filters: list[tuple[str, str]]) -> bool:
        for col, cond in filters:
            if col in ("select", "order"):
                continue
            op, _, value = cond.partition(".")
            have = row.get(col)
            if op == "eq" and str(have).lower() != value.lower():
                return False
            if op == "lt" and not (have is not None and str(have) < value):
                return False
            if op == "in" and str(have) not in value.strip("()").split(","):
                return False
        return True

    def select(self, table: str, params: Any = None, **_: Any) -> Page:
        rows = [dict(r) for r in self.tables[table] if self._match(r, list(params or []))]
        return Page(rows=rows, total=None)

    def upsert(self, table: str, rows: list[dict[str, Any]], on_conflict: str) -> None:
        keys = self.KEYS[table]
        for row in rows:
            same = (r for r in self.tables[table] if all(r.get(k) == row.get(k) for k in keys))
            found = next(same, None)
            if found is None:
                self.tables[table].append(dict(row))
            else:
                found.update(row)

    def update(self, table: str, filters: list[tuple[str, str]], values: dict[str, Any]) -> None:
        for r in self.tables[table]:
            if self._match(r, filters):
                r.update(values)


@pytest.fixture
def live(monkeypatch: pytest.MonkeyPatch) -> FakeCreative:
    """Live mode with the fake creative schema and two Ridhi ads."""
    monkeypatch.setenv("CREATIVE_DEMO", "false")
    monkeypatch.delenv("DEMO_MODE", raising=False)
    fake = FakeCreative()
    set_creative_client(fake)
    ads = {
        "a1": {
            "id": "a1",
            "name": "Craft video",
            "format": "video",
            "created_time": "2026-11-02",
            "primary_text": "Printed by hand in Jaipur.",
            "headline": "Indigo quilt",
            "thumbnail_url": None,
            "link_url": "https://x.com/products/indigo-quilt",
        },
        "a2": {
            "id": "a2",
            "name": "Sale image",
            "format": "image",
            "created_time": "2026-11-01",
            "primary_text": "40% off",
            "headline": "Sale",
            "thumbnail_url": None,
            "link_url": None,
        },
    }
    monkeypatch.setattr(tagging, "store_ads", lambda brand: ads)
    yield fake
    set_creative_client(None)


class StubClaude:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, prompt: str, image_url: str | None, schema: dict[str, Any], brand: str):
        self.calls.append(prompt)
        if schema is tagging.AD_SCHEMA:
            return (
                {
                    "hook_type": "craft_story",
                    "hook_text": "Printed by hand",
                    "visual_style": "making_process",
                    "print": "floral",
                    "color": "indigo_blue",
                    "note": "",
                },
                "stub-model",
            )
        return (
            {
                "print": "paisley",
                "color": "red",
                "category": "quilts",
                "season_fit": "all_season",
                "note": "",
            },
            "stub-model",
        )


# ------------------------------------------------------------------------------ Meta ad copy
def test_ad_copy_reads_text_headline_and_link_from_each_creative_shape() -> None:
    video = {
        "creative": {
            "object_story_spec": {
                "video_data": {
                    "message": "Watch it printed.",
                    "title": "Hand printed",
                    "call_to_action": {"value": {"link": "https://r.com/products/quilt"}},
                }
            }
        }
    }
    assert ad_copy(video) == {
        "primary_text": "Watch it printed.",
        "headline": "Hand printed",
        "link_url": "https://r.com/products/quilt",
    }
    carousel = {
        "creative": {
            "object_story_spec": {
                "link_data": {
                    "message": "Swipe",
                    "child_attachments": [{"name": "Card one", "link": "https://r.com/a"}],
                }
            }
        }
    }
    assert ad_copy(carousel)["headline"] == "Card one"
    assert ad_copy(carousel)["link_url"] == "https://r.com/a"
    dynamic = {
        "creative": {
            "asset_feed_spec": {
                "bodies": [{"text": "Body A"}],
                "titles": [{"text": "Title A"}],
                "link_urls": [{"website_url": "https://r.com/b"}],
            }
        }
    }
    assert ad_copy(dynamic) == {
        "primary_text": "Body A",
        "headline": "Title A",
        "link_url": "https://r.com/b",
    }
    assert ad_copy({}) == {"primary_text": None, "headline": None, "link_url": None}


def test_ads_are_still_saved_before_the_copy_columns_exist(monkeypatch: pytest.MonkeyPatch) -> None:
    saved: list[list[dict[str, Any]]] = []

    def save(table: str, rows: list[dict[str, Any]], c: Any = None) -> None:
        if any("primary_text" in r for r in rows):
            raise SupabaseError("bad_request", "column not found", 400, "PGRST204")
        saved.append(rows)

    monkeypatch.setattr(ads_data, "save_structure", save)
    monkeypatch.setattr(ads_data, "_copy_columns_missing", False)
    ads_data.save_ads(
        [{"id": "1", "name": "x", "primary_text": "hi", "headline": None, "link_url": None}]
    )
    assert saved == [[{"id": "1", "name": "x"}]]


def test_other_database_errors_still_fail_the_ad_save(monkeypatch: pytest.MonkeyPatch) -> None:
    def save(table: str, rows: list[dict[str, Any]], c: Any = None) -> None:
        raise SupabaseError("permission_denied", "no", 403, "42501")

    monkeypatch.setattr(ads_data, "save_structure", save)
    monkeypatch.setattr(ads_data, "_copy_columns_missing", False)
    with pytest.raises(SupabaseError):
        ads_data.save_ads([{"id": "1"}])


# ------------------------------------------------------------------------------- patterns
def row(
    ad: str,
    day: str,
    spend: float,
    imp: int,
    value: float,
    fmt: str = "image",
    link: str | None = None,
    v3: int = 0,
    thru: int = 0,
) -> dict[str, Any]:
    return {
        "ad_id": ad,
        "day": day,
        "ad_name": f"Ad {ad}",
        "ad_format": fmt,
        "spend": spend,
        "impressions": imp,
        "clicks": imp // 100,
        "purchases": 1,
        "purchase_value": value,
        "video_3s_views": v3,
        "video_thruplays": thru,
        "link_url": link,
    }


ROWS = [
    row(
        "w",
        "2026-11-20",
        200,
        5000,
        600,
        "video",
        "https://r.com/products/indigo-quilt",
        v3=1500,
        thru=300,
    ),
    row("w", "2026-11-21", 100, 5000, 300, "video", "https://r.com/products/indigo-quilt"),
    row("l", "2026-07-04", 300, 8000, 90),
    row("m", "2026-11-22", 150, 3000, 225),
    row("t", "2026-11-22", 10, 200, 50),
]


def test_verdicts_rates_and_context_per_ad() -> None:
    tags = {
        "l": {
            "hook_type": "offer_discount",
            "print": None,
            "color": "red",
            "source": "manual",
            "confirmed": True,
        }
    }
    prods = {
        "indigo-quilt": {
            "title": "Indigo Quilt",
            "print": "floral",
            "color": "indigo_blue",
            "category": "quilts",
        }
    }
    ads = {
        a["adId"]: a
        for a in patterns.ad_performance(ROWS, tags, prods, patterns.DEFAULT_SEASONS, RULE)
    }
    assert {k: a["verdict"] for k, a in ads.items()} == {
        "w": "winner",
        "l": "loser",
        "m": "average",
        "t": "insufficient_data",
    }
    w = ads["w"]
    assert w["sums"]["spend"] == 300 and w["rates"]["roas"] == 3.0
    assert w["rates"]["hookRate"] == 15.0  # 1500 three-second views / 10000 video impressions
    assert w["tags"]["print"] == "floral"  # from the linked product
    assert w["tags"]["category"] == "quilts" and w["productTitle"] == "Indigo Quilt"
    assert w["tags"]["season"] == "holiday"
    assert ads["l"]["tags"]["season"] == "summer" and ads["l"]["tags"]["color"] == "red"
    assert ads["l"]["rates"]["hookRate"] is None  # an image has no hook rate


def test_summary_groups_by_every_tag() -> None:
    ads = patterns.ad_performance(ROWS, {}, {}, patterns.DEFAULT_SEASONS, RULE)
    out = patterns.summary(ads, RULE)
    assert out["verdicts"] == {"winner": 1, "average": 1, "loser": 1, "insufficient_data": 1}
    assert out["untagged"] == 4
    assert set(out["dimensions"]) == set(patterns.DIMENSIONS)
    formats = {g["value"]: g for g in out["dimensions"]["format"]}
    assert formats["video"]["winners"] == 1 and formats["image"]["ads"] == 3
    assert [g["value"] for g in out["dimensions"]["hook_type"]] == [patterns.UNTAGGED]
    assert out["topWinners"][0]["adId"] == "w"


def test_season_ranges_can_wrap_past_new_year() -> None:
    cal = [{"season": "holiday", "start": "11-15", "end": "01-10"}]
    assert patterns.season_for("2027-01-05", cal) == "holiday"
    assert patterns.season_for("2027-02-05", cal) is None


def test_rules_and_seasons_are_checked() -> None:
    assert patterns.check_rule({"target_roas": 3}, RULE)["target_roas"] == 3.0
    for bad in ({"breakeven_roas": 5}, {"min_spend": "lots"}, {"min_spend": -1}, {"x": 1}):
        with pytest.raises(patterns.RuleError):
            patterns.check_rule(bad, RULE)
    with pytest.raises(patterns.RuleError):
        patterns.check_seasons([{"season": "monsoon", "start": "06-01", "end": "09-01"}])
    with pytest.raises(patterns.RuleError):
        patterns.check_seasons([{"season": "summer", "start": "6/1", "end": "09-01"}])


# --------------------------------------------------------------------------------- tagging
def test_claude_tags_untagged_ads_but_never_a_manual_one(
    live: FakeCreative, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub = StubClaude()
    monkeypatch.setattr(tagging, "_ask", stub)
    tagging.update_ad("ridhi", "a2", {"hook_type": "offer_discount"})
    out = tagging.tag_ads("ridhi", 10, retag=True)
    assert out["tagged"] == 1 and len(stub.calls) == 1
    tags = tagging.tags_by_ad("ridhi")
    assert tags["a1"]["hook_type"] == "craft_story" and tags["a1"]["source"] == "ai"
    assert tags["a2"]["hook_type"] == "offer_discount" and tags["a2"]["source"] == "manual"


def test_manual_tag_values_must_be_in_the_vocabulary(live: FakeCreative) -> None:
    with pytest.raises(taxonomy.InvalidTagError):
        tagging.update_ad("ridhi", "a1", {"hook_type": "drop table"})
    with pytest.raises(products.NotFoundError):
        tagging.update_ad("ridhi", "zzz", {"hook_type": "question"})


def test_products_sync_keeps_tags_and_marks_gone_products(
    live: FakeCreative, monkeypatch: pytest.MonkeyPatch
) -> None:
    from flowmerce.modules.seo.integrations import shopify

    listing = [
        {
            "handle": "indigo-quilt",
            "title": "Indigo Quilt",
            "type": "Quilt",
            "image": "",
            "url": "",
        },
        {"handle": "rose-sheet", "title": "Rose Sheet", "type": "", "image": "", "url": ""},
    ]
    monkeypatch.setattr(shopify, "configured", lambda b: True)
    monkeypatch.setattr(shopify, "list_products", lambda b: list(listing))
    assert products.sync("ridhi")["products"] == 2
    monkeypatch.setattr(tagging, "_ask", StubClaude())
    assert tagging.tag_products("ridhi", 10)["tagged"] == 2
    products.update("ridhi", "rose-sheet", {"color": "pink"})
    listing.pop(0)
    products.sync("ridhi")
    rows = {r["handle"]: r for r in live.tables["product"]}
    assert rows["rose-sheet"]["color"] == "pink" and rows["rose-sheet"]["source"] == "manual"
    assert rows["indigo-quilt"]["active"] is False
    assert [p["handle"] for p in products.listing("ridhi")] == ["rose-sheet"]


def test_rules_are_saved_per_store(live: FakeCreative) -> None:
    out = service.save_rule("ridhi", {"target_roas": 3}, "tester")
    assert out["rule"]["target_roas"] == 3.0
    out = service.save_seasons("ridhi", [{"season": "summer", "start": "05-15", "end": "08-31"}])
    assert {"season": "summer", "start": "05-15", "end": "08-31"} in out["seasons"]
    assert service.rules("cpc")["rule"]["target_roas"] == patterns.DEFAULT_RULE["target_roas"]


# ------------------------------------------------------------------------- routes, demo mode
@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch) -> Any:
    for key in (
        "RIDHI_META_AD_ACCOUNT_ID",
        "RIDHI_META_ACCESS_TOKEN",
        "CPC_META_AD_ACCOUNT_ID",
        "CPC_META_ACCESS_TOKEN",
        "CREATIVE_DEMO",
        "DEMO_MODE",
    ):
        monkeypatch.delenv(key, raising=False)
    from flowmerce.modules.seo.app import create_app

    return create_app()


def test_demo_routes_answer_and_writes_explain_why_not(app: Any) -> None:
    client = local_client(app)
    body = client.get("/api/creative/patterns?brand=ridhi").json()
    assert body["source"] == "demo" and body["adCount"] == 6
    assert set(body["dimensions"]) == set(patterns.DIMENSIONS)
    assert client.get("/api/creative/rules?brand=cpc").json()["source"] == "demo"
    assert client.get("/api/creative/products?brand=ridhi").json()["products"] == []
    assert "craft_story" in client.get("/api/creative/taxonomy").json()["hook_type"]
    res = client.put("/api/creative/rules?brand=ridhi", json={"target_roas": 3}, headers=CSRF)
    assert res.status_code == 412 and res.json()["code"] == "pending_setup"
    res = client.post("/api/creative/tags/run?brand=ridhi", json={}, headers=CSRF)
    assert res.status_code == 412
