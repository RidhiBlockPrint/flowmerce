"""Ads sync (modules/ads/sync.py), page answers (service.py) and routes (api.py). No network:
Supabase reads and writes go to an in-memory fake installed over modules/ads/data.py, and Meta is
a fake client."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from tests.fixtures.seo import local_client

from flowmerce.modules.ads import data, service, sync
from flowmerce.modules.ads.meta import MetaError, TokenInfo
from flowmerce.modules.ads.metrics import Totals

TODAY = datetime.now(UTC).date()
CSRF = {"X-Requested-With": "blog-ops"}
Y = TODAY - timedelta(days=1)
RATE = 88.0


def iso(d: date) -> str:
    return d.isoformat()


class FakeData:
    """The parts of schema `ads` the service and sync use, in memory."""

    def __init__(self, currency: str = "INR") -> None:
        self.account_row: dict[str, Any] | None = {
            "key": "meta:ridhi",
            "name": "Ridhi test account",
            "currency": currency,
            "timezone": "UTC",
            "first_day": iso(TODAY - timedelta(days=90)),
            "last_run_at": datetime.now(UTC).isoformat(),
            "last_status": "ok",
            "token_expires_at": (datetime.now(UTC) + timedelta(days=57, hours=1)).isoformat(),
        }
        self.saved_rules: dict[str, Any] = {}
        self.rates: dict[str, float] = {}
        self.marks: dict[str, str] = {}
        self.history: list[dict[str, Any]] = []
        self.calls: list[tuple[str, Any]] = []
        self.latest: date | None = Y
        b = RATE if currency == "INR" else 1.0
        self.struct = {
            "campaigns": [
                {
                    "id": "c_cbo",
                    "name": "CBO | Sales | Quilt | #4",
                    "objective": "OUTCOME_SALES",
                    "status": "ACTIVE",
                    "daily_budget": 1000 * b,
                    "budget_changed_at": None,
                },
                {
                    "id": "c_abo",
                    "name": "ABO | Sales | Quilt Testing",
                    "objective": "OUTCOME_SALES",
                    "status": "ACTIVE",
                    "daily_budget": None,
                    "budget_changed_at": None,
                },
            ],
            "ad_sets": [
                {"id": "s1", "campaign_id": "c_cbo", "name": "#4-1 | CBO", "status": "ACTIVE"},
                {"id": "s2", "campaign_id": "c_abo", "name": "V62 | Test", "status": "ACTIVE"},
            ],
            "ads": [
                self.ad("a1", "c_cbo", "s1", "p1", "video", 3000 * b, 60, 6000 * b),
                self.ad("a2", "c_abo", "s2", "p1", "video", 900 * b, 20, 2500 * b),
                self.ad("a3", "c_abo", "s2", "p3", "image", 400 * b, 10, 1200 * b),
                self.ad("a4", "c_abo", "s2", "p4", "image", 150 * b, 0, 0),
            ],
        }

    @staticmethod
    def ad(
        i: str, camp: str, adset: str, post: str, fmt: str, lt: float, ltp: int, ltv: float
    ) -> dict[str, Any]:
        return {
            "id": i,
            "campaign_id": camp,
            "ad_set_id": adset,
            "name": f"CR{i[1:]} | Hook {i} | Quilt",
            "status": "ACTIVE",
            "created_time": iso(TODAY - timedelta(days=40)) + "T10:00:00+0000",
            "post_id": post,
            "format": fmt,
            "video_length_s": 20.0 if fmt == "video" else None,
            "lt_spend": lt,
            "lt_purchases": ltp,
            "lt_value": ltv,
        }

    # reads
    google_row: dict[str, Any] | None = None  # set by the Google tests (test_google.py)

    def account(self, key: str, c: Any = None) -> dict[str, Any] | None:
        return self.google_row if key.startswith("google:") else self.account_row

    # Google: two campaigns (Performance Max $70 a day, brand Search $30 a day)
    G_CAMPAIGNS = (
        ("g_pmax", "PF-Max | Sales | Quilt", "PERFORMANCE_MAX", 70.0, 150.0, 1.0),
        ("g_brand", "Brand Campaign | Sales | Search", "SEARCH", 30.0, 150.0, 2.0),
    )

    def g_campaigns(self, key: str, c: Any = None) -> list[dict[str, Any]]:
        return [
            {"id": i, "name": n, "channel": ch, "status": "ENABLED", "daily_budget": sp + 5}
            for i, n, ch, sp, _v, _p in self.G_CAMPAIGNS
        ]

    def g_days(self, key: str, since: date, until: date, c: Any = None) -> list[dict[str, Any]]:
        out, d = [], since
        while d <= until:
            out.append(
                {
                    "day": iso(d),
                    "spend": 100.0,
                    "value": 300.0,
                    "purchases": 3.0,
                    "impressions": 5000,
                    "clicks": 120,
                }
            )
            d += timedelta(days=1)
        return out

    def g_sum(
        self, key: str, kind: str, since: date, until: date, c: Any = None
    ) -> list[dict[str, Any]]:
        n = (until - since).days + 1
        rows = {
            "campaign": [(i, i, nm, "", sp, v, pu) for i, nm, _ch, sp, v, pu in self.G_CAMPAIGNS],
            "group": [
                ("ag1", "g_pmax", "Quilt asset group", "asset_group", 70.0, 150.0, 1.0),
                ("ad1", "g_brand", "Brand words", "ad_group", 30.0, 150.0, 2.0),
            ],
            "term": [
                ("ridhi block print", "g_brand", "ridhi block print", "", 20.0, 120.0, 1.5),
                ("Ridhi Block Print", "g_brand", "Ridhi Block Print", "", 5.0, 30.0, 0.5),
                ("quilt king", "g_brand", "quilt king", "", 5.0, 0.0, 0.0),
            ],
            "keyword": [
                ("1~1", "g_brand", "Ridhi Block Print", "BROAD", 25.0, 150.0, 2.0),
                ("2~1", "g_brand", "Ridhi Block Print", "PHRASE", 5.0, 0.0, 0.0),
            ],
            "product": [
                ("p1", "g_pmax", "Quilt | Sage Queen", "", 50.0, 150.0, 1.0),
                ("p2", "g_pmax", "Pillow cover", "", 0.0, 0.0, 0.0),
            ],
        }[kind]
        return [
            {
                "item": it,
                "campaign_id": cid,
                "label": lb,
                "extra": ex,
                "spend": sp * n,
                "value": v * n,
                "purchases": pu * n,
                "impressions": 1000 * n,
                "clicks": 40 * n,
            }
            for it, cid, lb, ex, sp, v, pu in rows
        ]

    def g_latest_day(self, key: str, c: Any = None) -> date | None:
        return self.latest

    def rules(self, brand: str, c: Any = None) -> dict[str, Any]:
        return dict(self.saved_rules)

    def fx_rate(self, currency: str, on: date, c: Any = None) -> float:
        return 1.0 if currency == "USD" else self.rates.get(currency, RATE)

    def fx_since(self, currency: str, c: Any = None) -> str:
        return "2000-01-01"

    def structure(self, key: str, c: Any = None, *, fresh: bool = False) -> dict[str, Any]:
        return self.struct

    def account_days(
        self, key: str, since: date, until: date, c: Any = None
    ) -> list[dict[str, Any]]:
        out, d = [], since
        while d <= until:
            out.append(
                {
                    "day": iso(d),
                    "spend": 1000.0,
                    "value": 1800.0,
                    "impressions": 50000,
                    "vimp": 30000,
                    "clicks": 1500,
                    "link_clicks": 1550,
                    "lpv": 1400,
                    "atc": 200,
                    "ic": 60,
                    "purchases": 20,
                    "v3": 9000,
                }
            )
            d += timedelta(days=1)
        return out

    def store_days(
        self, store: str, tz: str, since: date, until: date, bulk_min: float, c: Any = None
    ) -> list[dict[str, Any]]:
        self.calls.append(("store_days", (store, tz)))
        out, d = [], since
        while d <= until:
            bulk = 5000.0 if d == Y - timedelta(days=2) and bulk_min <= 5000 else 0.0
            extra = 5000.0 if d == Y - timedelta(days=2) else 0.0
            out.append(
                {
                    "day": iso(d),
                    "orders": 20 + (1 if extra else 0),
                    "sales": 2200.0 + extra,
                    "bulk_orders": 1 if bulk else 0,
                    "bulk_amount": bulk,
                }
            )
            d += timedelta(days=1)
        return out

    def ad_windows(
        self, key: str, since: date, until: date, pf: date, pt: date, c: Any = None
    ) -> list[dict[str, Any]]:
        def w(
            ad: str, win: str, spend: float, purchases: float, value: float, video: bool = False
        ) -> dict[str, Any]:
            imp = int(spend * 20)
            return {
                "ad_id": ad,
                "w": win,
                "spend": spend,
                "value": value,
                "purchases": purchases,
                "impressions": imp,
                "clicks": int(imp * 0.03),
                "lpv": int(imp * 0.028),
                "atc": int(imp * 0.004),
                "ic": 0,
                "v3": int(imp * 0.3) if video else 0,
                "p25": int(imp * 0.2) if video else 0,
                "p50": int(imp * 0.1) if video else 0,
                "p75": int(imp * 0.06) if video else 0,
                "p95": int(imp * 0.04) if video else 0,
                "plays": imp if video else 0,
                "watch_s": imp * 5.0 if video else 0,
            }

        rows = []
        for win in ("cur", "d7"):
            rows += [
                w("a1", win, 700, 21, 2100, True),
                w("a3", win, 100, 3, 400),
                w("a4", win, 120, 0, 0),
            ]
        rows += [
            w("a1", "d3", 300, 9, 900, True),
            w("a1", "d14", 1400, 40, 4000, True),
            w("a1", "prev", 600, 12, 1200, True),
            w("a3", "d3", 40, 1, 120),
            w("a4", "d3", 50, 0, 0),
        ]
        return rows

    def action_status(self, brand: str, c: Any = None) -> dict[str, str]:
        return dict(self.marks)

    def action_history(self, brand: str, limit: int = 30, c: Any = None) -> list[dict[str, Any]]:
        return list(self.history)

    # writes
    def set_action_status(
        self, brand: str, action: dict[str, Any], status: str, by: str, c: Any = None
    ) -> None:
        if status == "open":
            self.marks.pop(action["id"], None)
        else:
            self.marks[action["id"]] = status
        self.history.insert(
            0,
            {
                "id": len(self.history) + 1,
                "action_id": action["id"],
                "title": action["title"],
                "grp": action["group"],
                "status": status,
                "by_user": by,
                "at": "now",
            },
        )

    def save_rules(self, brand: str, values: dict[str, Any], by: str, c: Any = None) -> None:
        self.saved_rules = dict(values)

    def set_fx_rate(self, currency: str, on: date, rate: float, by: str, c: Any = None) -> None:
        self.rates[currency] = rate

    def forget(self, key: str | None = None) -> None:
        self.calls.append(("forget", key))


@pytest.fixture(autouse=True)
def _nothing_kept() -> None:
    """Each test starts with no kept rows or answers (data.py keeps them per process)."""
    data._changed()


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeData:
    f = FakeData()
    # The fake changes between calls of one test, so no answer is kept here (test_kept_answers
    # checks the keeping itself).
    monkeypatch.setattr(data, "ANSWER_SECONDS", 0)
    monkeypatch.setattr(data, "latest_day", lambda key, c=None: f.latest)
    # Google is off unless a test sets it up (test_google.py): the real .env is not used.
    for name in (
        "GOOGLE_ADS_CLIENT_ID",
        "GOOGLE_ADS_CLIENT_SECRET",
        "GOOGLE_ADS_REFRESH_TOKEN",
        "GOOGLE_ADS_DEVELOPER_TOKEN",
        "GOOGLE_ADS_LOGIN_CUSTOMER_ID",
        "RIDHI_GOOGLE_ADS_CUSTOMER_ID",
        "CPC_GOOGLE_ADS_CUSTOMER_ID",
    ):
        monkeypatch.delenv(name, raising=False)
    for name in ("g_campaigns", "g_days", "g_sum", "g_latest_day"):
        monkeypatch.setattr(data, name, getattr(f, name))
    for name in (
        "account",
        "rules",
        "fx_rate",
        "fx_since",
        "structure",
        "account_days",
        "store_days",
        "ad_windows",
        "action_status",
        "action_history",
        "set_action_status",
        "save_rules",
        "set_fx_rate",
        "forget",
    ):
        monkeypatch.setattr(data, name, getattr(f, name))
    monkeypatch.setenv("RIDHI_META_AD_ACCOUNT_ID", "123")
    monkeypatch.setenv("RIDHI_META_ACCESS_TOKEN", "test-token")
    return f


# ------------------------------------------------------------------ requests that cannot be
# answered
def test_unknown_brand_google_and_missing_keys(
    fake: FakeData, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(service.InputError):
        service.overview("all", "all", None, None, None)
    with pytest.raises(service.GoogleNotConnectedError):
        service.overview("ridhi", "google", None, None, None)
    with pytest.raises(service.InputError):
        service.overview("ridhi", "all", "2025-01-01", iso(Y), None)  # more than 366 days
    fake.account_row = {"key": "meta:ridhi", "first_day": None, "last_error": "token expired"}
    with pytest.raises(service.NotReadyError) as e:
        service.overview("ridhi", "all", None, None, None)
    assert e.value.code == "not_synced" and "token expired" in e.value.message
    monkeypatch.delenv("RIDHI_META_ACCESS_TOKEN")
    with pytest.raises(service.NotReadyError) as e:
        service.overview("ridhi", "all", None, None, None)
    assert e.value.code == "not_configured"


# ------------------------------------------------------------------ overview
def test_overview_mer_bulk_orders_and_the_gate(fake: FakeData) -> None:
    o = service.overview("ridhi", "all", None, None, None)
    m = o["metrics"]
    assert o["from"] == iso(Y - timedelta(days=6)) and o["to"] == iso(Y) and o["days"] == 7
    assert m["spend"]["value"] == 7000 and m["sales"]["value"] == 7 * 2200 + 5000
    assert m["sales_ex_bulk"]["value"] == 7 * 2200 and m["mer_ex_bulk"]["value"] == 2.2
    assert "roas" not in m  # no combined platform ROAS when both platforms are chosen
    assert o["bulk"] == {"min_order": 1500.0, "orders": 1, "amount": 5000.0}
    assert m["aov"]["value"] == 110.0  # bulk order left out of orders too
    assert o["gate"]["state"] == "green" and o["gate"]["mer_7d"] == 2.2
    assert len(o["trend"]) == 14 and o["trend"][-1]["colour"] == "green"
    assert o["platforms"][1]["platform"] == "google" and o["platforms"][1]["spend"] is None
    assert any("Google Ads is not connected" in n for n in o["notes"])
    assert (
        "store_days",
        ("RBP", "America/New_York"),
    ) in fake.calls  # Shopify's zone, not ops.stores
    meta = service.overview("ridhi", "meta", None, None, "none")
    assert meta["metrics"]["roas"]["value"] == 1.8 and meta["compare"] is None
    assert meta["metrics"]["spend"]["change_pct"] is None


def test_range_ends_today_at_the_latest_and_defaults_to_seven_complete_days(fake: FakeData) -> None:
    o = service.overview(
        "ridhi", "all", iso(TODAY - timedelta(days=3)), iso(TODAY + timedelta(days=5)), None
    )
    assert o["to"] == iso(TODAY) and o["days"] == 4
    d = service.overview("ridhi", "all", None, None, None)
    assert d["to"] == iso(Y) and d["days"] == 7 and d["compare"]["key"] == "previous"


@pytest.mark.parametrize(
    ("cmp", "back"),
    [
        ("previous", 7),
        ("previous_year_dow", 364),
        ("last_week", 7),
        ("4week_avg", 7),
        ("nonsense", 7),
    ],
)
def test_comparisons_cover_as_many_days_as_the_chosen_ones(
    fake: FakeData, cmp: str, back: int
) -> None:
    o = service.overview("ridhi", "all", None, None, cmp)
    frm = Y - timedelta(days=6)
    assert o["compare"]["from"] == iso(frm - timedelta(days=back))
    assert o["compare"]["to"] == iso(frm - timedelta(days=back - 6))


def test_previous_year_custom_and_none(fake: FakeData) -> None:
    o = service.overview("ridhi", "all", "2024-02-27", "2024-03-01", "previous_year")
    assert o["compare"]["from"] == "2023-02-27" and o["compare"]["to"] == "2023-03-02"
    leap = service.overview("ridhi", "all", "2024-02-29", "2024-02-29", "previous_year")
    assert leap["compare"]["from"] == "2023-02-28"
    c = service.overview(
        "ridhi", "all", iso(Y - timedelta(days=6)), iso(Y), "custom", iso(Y - timedelta(days=40))
    )
    assert c["compare"]["from"] == iso(Y - timedelta(days=40)) and c["compare"]["to"] == iso(
        Y - timedelta(days=34)
    )
    assert service.overview("ridhi", "all", None, None, "custom")["compare"]["key"] == "previous"
    with pytest.raises(service.InputError):
        service.overview(
            "ridhi", "all", iso(Y - timedelta(days=6)), iso(Y), "custom", iso(Y - timedelta(days=3))
        )
    assert service.overview("ridhi", "all", None, None, "none")["compare"] is None


def test_a_comparison_before_the_loaded_days_says_so(fake: FakeData) -> None:
    o = service.overview("ridhi", "all", None, None, "previous_year")
    assert "loaded from" in o["compare"]["note"]
    assert "note" not in service.overview("ridhi", "all", None, None, None)["compare"]


# ------------------------------------------------------------------ creatives, campaigns, gap
def test_creatives_verdicts_and_video(fake: FakeData) -> None:
    d = service.creatives("ridhi", None, None)
    ads = {a["id"]: a for a in d["ads"]}
    assert set(ads) == {"a1", "a2", "a3", "a4"}  # a2 has no spend but is active
    assert ads["a1"]["verdict"] == "scale" and ads["a1"]["video"]["hook_rate"] == 30.0
    assert ads["a1"]["video"]["avg_watch_s"] == 5 and ads["a1"]["video"]["length_s"] == 20.0
    assert ads["a4"]["verdict"] == "stop" and ads["a4"]["video"] is None
    assert ads["a3"]["lifetime"] == {
        "spend": 400.0,
        "purchases": 10,
        "roas": 3.0,
    }  # INR -> USD at 88
    assert ads["a3"]["verdict"] in ("graduate", "scale", "iterate")
    assert not any(k.startswith("_") for k in ads["a1"])
    assert sum(d["counts"].values()) == 4 and d["account"]["hook_rate"] == 30.0


def test_campaigns_cbo_health_in_dollars(fake: FakeData) -> None:
    rows = {c["id"]: c for c in service.campaigns("ridhi", "all", None, None)["campaigns"]}
    cbo = rows["c_cbo"]
    assert cbo["type"] == "cbo" and cbo["daily_budget"] == 1000.0
    assert cbo["health"]["delivering_ads"] == 1 and cbo["health"]["top_ad_share"] == 100
    assert (
        cbo["health"]["call"]["key"] == "increase" and cbo["health"]["call"]["new_budget"] == 1200
    )
    assert (
        rows["c_abo"]["type"] == "abo"
        and rows["c_abo"]["daily_budget"] is None
        and rows["c_abo"]["health"] is None
    )


def test_gap_matches_ads_by_post(fake: FakeData) -> None:
    g = service.gap("ridhi")
    rows = {r["id"]: r for r in g["pairs"][0]["rows"]}
    assert g["pairs"][0]["scale_campaign"] == "CBO | Sales | Quilt | #4"
    assert rows["a2"]["verdict"] == "already"  # same post as a1 in the CBO
    assert rows["a3"]["verdict"] == "add" and g["missing"] == 1
    assert rows["a4"]["verdict"] == "stop"


# ------------------------------------------------------------------ actions and rules
def test_actions_marked_and_reopened(fake: FakeData) -> None:
    d = service.actions("ridhi", "all")
    ids = [a["id"] for a in d["actions"]]
    assert "budget:c_cbo" in ids and "add:a3" in ids and "stop:a4" in ids
    assert service.actions("ridhi", "google")["actions"] == []
    service.mark_action("ridhi", "add:a3", "done", "owner@example.com")
    again = {a["id"]: a for a in service.actions("ridhi", "all")["actions"]}
    assert (
        again["add:a3"]["status"] == "done"
        and service.actions("ridhi", "all")["history"][0]["status"] == "done"
    )
    service.mark_action("ridhi", "add:a3", "open", "owner@example.com")
    assert {a["id"]: a for a in service.actions("ridhi", "all")["actions"]}["add:a3"][
        "status"
    ] == "open"
    with pytest.raises(LookupError):
        service.mark_action("ridhi", "nope", "done", "x")
    with pytest.raises(service.InputError):
        service.mark_action("ridhi", "add:a3", "maybe", "x")


def test_rules_and_the_rupee_rate(fake: FakeData) -> None:
    r = service.rules("ridhi")
    assert (
        r["rules"]["fx_rate"] == 88
        and r["meta_currency"] == "INR"
        and r["defaults"]["fx_rate"] == 88
    )
    out = service.save_rules("ridhi", {"fx_rate": 95, "stop_roas": 1.4}, "owner")
    assert fake.rates["INR"] == 95 and fake.saved_rules == {"stop_roas": 1.4}
    assert out["rules"]["fx_rate"] == 95 and out["rules"]["stop_roas"] == 1.4
    with pytest.raises(service.InputError):
        service.save_rules("ridhi", {"stop_roas": -1}, "owner")
    with pytest.raises(service.InputError):
        service.save_rules("ridhi", {}, "owner")
    fake.account_row = {**(fake.account_row or {}), "currency": "USD"}
    with pytest.raises(service.InputError):
        service.save_rules("ridhi", {"fx_rate": 90}, "owner")


def test_settings_say_when_the_sign_in_expires(fake: FakeData) -> None:
    s = service.settings("ridhi")
    acc = s["accounts"][0]
    assert acc["token_days_left"] == 57 and acc["converted_at"] == 88 and s["today"] == iso(TODAY)
    assert s["google"]["connected"] is False


# ------------------------------------------------------------------ sync
class FakeMeta:
    def __init__(self, fail_daily: bool = False) -> None:
        self.fail_daily = fail_daily
        self.spans: list[tuple[date, date]] = []

    def account_info(self) -> dict[str, Any]:
        return {
            "account_id": "123",
            "name": "Ridhi",
            "currency": "INR",
            "timezone_name": "UTC",
            "account_status": 1,
        }

    def token_info(self) -> TokenInfo:
        return TokenInfo(True, None)

    def budget_changes(self, since: datetime) -> dict[str, datetime]:
        return {}

    def campaigns(self) -> list[dict[str, Any]]:
        return [
            {
                "id": "c1",
                "name": "CBO | Quilt",
                "effective_status": "ACTIVE",
                "daily_budget": "8800000",
            }
        ]

    def ad_sets(self) -> list[dict[str, Any]]:
        return [{"id": "s1", "name": "s", "campaign_id": "c1", "effective_status": "ACTIVE"}]

    def ads(self) -> list[dict[str, Any]]:
        return [
            {
                "id": "a1",
                "name": "CR1 | x",
                "campaign_id": "c1",
                "adset_id": "s1",
                "effective_status": "ACTIVE",
                "creative": {"video_id": "v1"},
            }
        ]

    def daily(self, since: date, until: date) -> list[dict[str, Any]]:
        if self.fail_daily:
            raise MetaError("rate_limited", "limit reached")
        self.spans.append((since, until))
        return [{"ad_id": "a1", "day": iso(until), "spend": 10}]

    def lifetime(self) -> list[dict[str, Any]]:
        return [{"ad_id": "a1", "spend": 100.0, "purchases": 2.0, "value": 300.0}]


class SyncData:
    def __init__(self, lock: dict[str, Any] | None) -> None:
        self.lock = lock
        self.log: list[tuple[str, Any]] = []

    def install(self, mp: pytest.MonkeyPatch) -> None:
        mp.setattr(data, "save_account", lambda row, c=None: self.log.append(("account", row)))
        mp.setattr(data, "begin_sync", lambda key, c=None: self.lock)
        mp.setattr(
            data,
            "end_sync",
            lambda key, ok, err, full, first, c=None: self.log.append(
                ("end", (ok, err, full, first))
            ),
        )
        mp.setattr(data, "budgets", lambda key, c=None: {})
        mp.setattr(
            data, "save_structure", lambda table, rows, c=None: self.log.append((table, rows))
        )
        mp.setattr(data, "replace_daily", lambda key, a, b, rows, c=None: len(rows))
        mp.setattr(
            data, "save_lifetime", lambda key, rows, at, c=None: self.log.append(("lifetime", rows))
        )
        mp.setattr(data, "forget", lambda key=None: None)
        mp.setattr(data, "account", lambda key, c=None: {"key": key})
        mp.setattr(
            data, "mark_loaded_from", lambda key, day, c=None: self.log.append(("loaded_from", day))
        )


def test_plan_and_spans() -> None:
    now = datetime(2026, 11, 24, 12, tzinfo=UTC)
    today = date(2026, 11, 24)
    assert sync.plan_days(today, None, None, now) == (today - timedelta(days=89), True)
    assert sync.plan_days(today, date(2026, 9, 1), now - timedelta(hours=30), now) == (
        today - timedelta(days=27),
        True,
    )
    assert sync.plan_days(today, date(2026, 9, 1), now - timedelta(hours=2), now) == (
        today - timedelta(days=2),
        False,
    )
    s = sync.spans(date(2026, 11, 1), date(2026, 11, 16))
    assert s[0] == (date(2026, 11, 1), date(2026, 11, 7)) and s[-1] == (
        date(2026, 11, 15),
        date(2026, 11, 16),
    )


def test_budget_change_is_noticed() -> None:
    now = datetime(2026, 11, 24, 12, tzinfo=UTC)
    raw = [
        {"id": "c1", "name": "x", "daily_budget": "12000"},
        {"id": "c2", "name": "y", "daily_budget": "5000"},
    ]
    stored = {
        "c1": {"daily_budget": 100.0, "budget_changed_at": None},
        "c2": {"daily_budget": 50.0},
    }
    rows = {r["id"]: r for r in sync.campaign_rows("k", raw, stored, {}, now)}
    assert (
        rows["c1"]["budget_changed_at"] == now.isoformat() and rows["c1"]["daily_budget"] == 120.0
    )
    assert rows["c2"]["budget_changed_at"] is None


def test_first_sync_loads_90_days_and_lifetime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RIDHI_META_AD_ACCOUNT_ID", "123")
    monkeypatch.setenv("RIDHI_META_ACCESS_TOKEN", "test-token")
    sd = SyncData({"got_lock": True, "full_at": None, "loaded_from": None})
    sd.install(monkeypatch)
    meta = FakeMeta()
    now = datetime(2026, 11, 24, 12, tzinfo=UTC)
    res = sync.sync_brand("ridhi", meta=meta, now=now)  # type: ignore[arg-type]
    assert res["state"] == "ok" and res["full"] and res["from"] == "2026-08-27"
    assert (
        meta.spans[0][0] == date(2026, 8, 27)
        and meta.spans[-1][1] == date(2026, 11, 24)
        and len(meta.spans) == 13
    )
    tables = [t for t, _ in sd.log]
    assert "campaigns" in tables and "ads" in tables and "lifetime" in tables
    assert ("end", (True, None, True, date(2026, 8, 27))) in sd.log
    camp = next(rows for t, rows in sd.log if t == "campaigns")[0]
    assert camp["daily_budget"] == 88000.0


def test_a_meta_problem_is_recorded_and_returned(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RIDHI_META_AD_ACCOUNT_ID", "123")
    monkeypatch.setenv("RIDHI_META_ACCESS_TOKEN", "test-token")
    sd = SyncData(
        {"got_lock": True, "full_at": datetime.now(UTC).isoformat(), "loaded_from": "2026-09-01"}
    )
    sd.install(monkeypatch)
    res = sync.sync_brand("ridhi", meta=FakeMeta(fail_daily=True))  # type: ignore[arg-type]
    assert res["state"] == "failed" and res["reason"] == "rate_limited"
    assert ("end", (False, "limit reached", False, None)) in sd.log
    sd.lock = None
    assert sync.sync_brand("ridhi", meta=FakeMeta())["state"] == "locked"  # type: ignore[arg-type]
    monkeypatch.delenv("RIDHI_META_ACCESS_TOKEN")
    assert sync.sync_brand("ridhi")["state"] == "not_configured"


def test_totals_roas() -> None:
    assert Totals(spend=100, value=250).roas == 2.5 and Totals().roas == 0


# ------------------------------------------------------------------ routes
@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch) -> Any:
    from flowmerce.modules.seo.app import create_app

    for b in ("RIDHI", "CPC"):
        monkeypatch.delenv(f"{b}_META_AD_ACCOUNT_ID", raising=False)
        monkeypatch.delenv(f"{b}_META_ACCESS_TOKEN", raising=False)
        monkeypatch.delenv(f"{b}_GOOGLE_ADS_CUSTOMER_ID", raising=False)  # no network in tests
    return create_app()


def test_routes_are_mounted_and_explain_what_is_missing(app: Any) -> None:
    c = local_client(app)
    r = c.get("/api/ads/overview?brand=ridhi")
    assert r.status_code == 503 and r.json()["code"] == "not_configured"
    r = c.get("/api/ads/overview?brand=nope")
    assert r.status_code == 400 and r.json()["code"] == "bad_request"
    r = c.get("/api/ads/search-terms?brand=ridhi")  # no Meta account either: that is said first
    assert r.status_code == 503 and r.json()["code"] == "not_configured"
    assert c.post("/api/ads/sync?brand=ridhi").status_code == 403  # changes need the CSRF header
    assert c.post("/api/ads/sync?brand=ridhi", headers=CSRF).json()["state"] == "not_configured"


def test_routes_answer_from_the_service(app: Any, fake: FakeData) -> None:
    c = local_client(app)
    r = c.get(f"/api/ads/overview?brand=ridhi&from={iso(Y)}&to={iso(Y)}")
    assert r.status_code == 200 and r.json()["days"] == 1
    r = c.patch("/api/ads/actions/add:a3?brand=ridhi", json={"status": "skipped"}, headers=CSRF)
    assert r.status_code == 200 and fake.marks == {"add:a3": "skipped"}
    r = c.patch("/api/ads/rules?brand=ridhi", json={"stop_roas": 999999}, headers=CSRF)
    assert r.status_code == 400


def test_funnel_starts_from_link_clicks(fake: FakeData) -> None:
    f = service.funnel("ridhi", "all", None, None, None)
    steps = {s["key"]: s for s in f["meta"]["steps"]}
    assert list(steps) == ["impressions", "link_clicks", "lpv", "atc", "ic", "purchases"]
    assert steps["link_clicks"]["value"] == 7 * 1550 and steps["lpv"]["rate"] == round(
        1400 / 1550 * 100, 1
    )
    assert f["google"] is None and f["store"]["orders"]["value"] == 7 * 20 + 1


def test_a_weak_week_on_little_spend_says_why_it_is_not_stopped() -> None:
    from flowmerce.modules.ads import metrics

    r = metrics.rules_for("ridhi", {})
    v, why = metrics.verdict(Totals(), Totals(spend=60), Totals(900, 20, 1600), False, r)
    assert v == "iterate" and "only $60" in why and "between" not in why


class LimitedMeta(FakeMeta):
    """Meta's request limit is reached after `ok_spans` spans of daily figures."""

    def __init__(self, ok_spans: int) -> None:
        super().__init__()
        self.ok_spans = ok_spans

    def daily(self, since: date, until: date) -> list[dict[str, Any]]:
        if len(self.spans) >= self.ok_spans:
            raise MetaError("rate_limited", "limit")
        return super().daily(since, until)


def test_a_first_load_stopped_late_still_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RIDHI_META_AD_ACCOUNT_ID", "123")
    monkeypatch.setenv("RIDHI_META_ACCESS_TOKEN", "test-token")
    now = datetime(2026, 11, 24, 12, tzinfo=UTC)
    sd = SyncData({"got_lock": True, "full_at": None, "loaded_from": None})
    sd.install(monkeypatch)
    sync.sync_brand("ridhi", meta=LimitedMeta(10), now=now)  # type: ignore[arg-type]
    assert ("loaded_from", date(2026, 8, 27)) in sd.log  # 10 of 13 spans: reaches the last 4 weeks
    sd.log.clear()
    sync.sync_brand("ridhi", meta=LimitedMeta(3), now=now)  # type: ignore[arg-type]
    assert not any(k == "loaded_from" for k, _ in sd.log)  # too early: the next run starts again


def test_overview_says_when_the_newest_days_are_not_saved_yet(fake: FakeData) -> None:
    assert not any(
        "saved up to" in n for n in service.overview("ridhi", "all", None, None, None)["notes"]
    )
    fake.latest = Y - timedelta(days=5)
    o = service.overview("ridhi", "all", None, None, None)
    assert o["notes"][0].startswith(f"Meta figures are saved up to {fake.latest:%d %b}")
    assert o["meta_saved_to"] == iso(fake.latest) and o["meta_saved_to"] < o["to"]
    assert o["gate"]["state"] == "unknown"


# ------------------------------------------------------------------ kept rows and answers (speed)
def test_kept_answers_are_reused_until_something_changes(
    fake: FakeData, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(data, "ANSWER_SECONDS", 300)
    first = service.overview("ridhi", "all", None, None, None)
    assert service.overview("ridhi", "all", None, None, None) is first
    assert service.overview("ridhi", "meta", None, None, None) is not first  # other arguments
    data._changed()  # what every write and every Meta read does
    again = service.overview("ridhi", "all", None, None, None)
    assert again is not first and again == first


def test_kept_answers_stay_few(fake: FakeData, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(data, "ANSWER_SECONDS", 300)
    monkeypatch.setattr(data, "ANSWER_MAX", 3)
    for days in range(1, 6):
        service.funnel("ridhi", "all", iso(Y - timedelta(days=days)), iso(Y), None)
    assert len(data._answers) == 3


class CountingClient:
    """Counts the reads that reach the database; writes do nothing."""

    def __init__(self) -> None:
        self.reads = 0

    def select(self, table: str, params: Any = None, **kw: Any) -> Any:
        self.reads += 1
        rows = {"rules": [{"rules": {"target_roas": 2.5}}], "fx_rates": [{"rate": 88}]}
        return type("Page", (), {"rows": rows.get(table, [])})()

    def upsert(self, *a: Any, **kw: Any) -> None:
        return None


def test_rarely_changing_rows_are_kept_and_cleared_by_a_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cl = CountingClient()
    monkeypatch.setattr(data, "ads_client", lambda: cl)
    rules = data.rules("ridhi")
    rules["target_roas"] = 9.0  # a caller changing its copy does not change the kept row
    assert data.rules("ridhi") == {"target_roas": 2.5}
    assert data.fx_rate("INR", TODAY) == data.fx_rate("INR", TODAY) == 88.0
    assert cl.reads == 2
    data.save_rules("ridhi", {"target_roas": 3.0}, "test")
    data.rules("ridhi")
    assert cl.reads == 3  # read again after the write
    assert data.rules("ridhi", CountingClient()) == {"target_roas": 2.5}  # own client: not kept
    assert cl.reads == 3


# ------------------------------------------------------------------ both brands (company view)
def test_company_adds_spend_and_sales_and_keeps_each_brand(
    fake: FakeData, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CPC_META_AD_ACCOUNT_ID", raising=False)  # this computer's .env has CPC's
    monkeypatch.delenv("CPC_META_ACCESS_TOKEN", raising=False)
    one = service.company(None, None, None)
    ridhi, cpc = one["brands"]
    assert ridhi["ready"] and not cpc["ready"] and "CPC_META_AD_ACCOUNT_ID" in cpc["message"]
    o = service.overview("ridhi", "all", None, None, None)
    assert one["metrics"]["spend"]["value"] == o["metrics"]["total_spend"]["value"]
    assert ridhi["share_of_spend"] == 100.0 and ridhi["gate"] == o["gate"]

    monkeypatch.setenv(
        "CPC_META_AD_ACCOUNT_ID", "456"
    )  # the fake answers CPC with the same figures
    monkeypatch.setenv("CPC_META_ACCESS_TOKEN", "test-token")
    two = service.company(None, None, None)
    m = two["metrics"]
    assert m["spend"]["value"] == 2 * o["metrics"]["total_spend"]["value"]
    assert m["sales_ex_bulk"]["value"] == 2 * o["metrics"]["sales_ex_bulk"]["value"]
    assert (
        m["mer_ex_bulk"]["value"] == o["metrics"]["mer_ex_bulk"]["value"]
    )  # same brands: same MER
    assert [b["share_of_spend"] for b in two["brands"]] == [50.0, 50.0]
    day = two["trend"][-1]
    assert day["spend"] == day["ridhi_spend"] + day["cpc_spend"]
    # each platform's spend is added over both brands; shares are of the company's spend
    meta = next(p for p in two["platforms"] if p["platform"] == "meta")
    own = next(p for p in o["platforms"] if p["platform"] == "meta")
    assert meta["spend"] == round(2 * own["spend"], 2)
    assert abs(sum(p["share_of_spend"] for p in two["platforms"]) - 100) < 0.2
    assert "ridhi_mer_ex_bulk" in day and two["from"] == o["from"]


def test_company_with_no_brand_ready_says_why(
    fake: FakeData, monkeypatch: pytest.MonkeyPatch
) -> None:
    for b in ("RIDHI", "CPC"):
        monkeypatch.delenv(f"{b}_META_AD_ACCOUNT_ID", raising=False)
    with pytest.raises(service.NotReadyError) as e:
        service.company(None, None, None)
    assert e.value.code == "not_configured"
