"""Google Ads (phase 3): the read-only client (modules/ads/google_ads.py; Google is an
httpx.MockTransport), the sync (google_sync.py; Supabase is a fake) and the page answers with Google
next to Meta (service.py; the in-memory fake of test_sync_service.py). No network, no real keys."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import pytest
from tests.fixtures.seo import local_client
from tests.unit.ads.test_sync_service import RATE, FakeData, Y, iso

from flowmerce.modules.ads import data, google_sync, service
from flowmerce.modules.ads.config import GoogleAccount, google_account
from flowmerce.modules.ads.google_ads import GoogleAdsClient, GoogleAdsError, counts_as_purchase

ACC = GoogleAccount("ridhi", "1234567890", "cid", "csecret", "refresh-secret", "", "")
GOOGLE_ENV = {
    "GOOGLE_ADS_CLIENT_ID": "cid",
    "GOOGLE_ADS_CLIENT_SECRET": "csecret",
    "GOOGLE_ADS_REFRESH_TOKEN": "refresh-secret",
    "RIDHI_GOOGLE_ADS_CUSTOMER_ID": "123-456-7890",
}


# ------------------------------------------------------------------ settings
def test_google_account_needs_the_login_and_a_ten_digit_customer_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for k in [*GOOGLE_ENV, "CPC_GOOGLE_ADS_CUSTOMER_ID", "GOOGLE_ADS_LOGIN_CUSTOMER_ID"]:
        monkeypatch.delenv(k, raising=False)
    assert google_account("ridhi") is None
    for k, v in GOOGLE_ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("GOOGLE_ADS_LOGIN_CUSTOMER_ID", "168-234-1048")
    a = google_account("ridhi")
    assert a is not None and a.customer_id == "1234567890" and a.key == "google:ridhi"
    assert a.login_customer_id == "1682341048" and a.developer_token == ""
    assert google_account("cpc") is None  # no customer id for CPC
    monkeypatch.setenv("CPC_GOOGLE_ADS_CUSTOMER_ID", "12345")
    assert google_account("cpc") is None  # not ten digits


def test_only_real_purchases_count() -> None:
    assert counts_as_purchase("Google Shopping App Purchase (3)", "PURCHASE")
    assert not counts_as_purchase("Ridhi Shopify (web) click", "PURCHASE")
    assert not counts_as_purchase("GA4 Add to Cart", "ADD_TO_CART")


# ------------------------------------------------------------------ client
class FakeGoogle:
    """Google's sign-in and googleAds:search, answering by what the query asks for."""

    def __init__(self, token_status: int = 200, token_error: str = "") -> None:
        self.token_status = token_status
        self.token_error = token_error
        self.queries: list[str] = []
        self.headers: list[httpx.Headers] = []
        self.tokens = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.googleapis.com":
            self.tokens += 1
            if self.token_status != 200:
                return httpx.Response(self.token_status, json={"error": self.token_error})
            return httpx.Response(
                200, json={"access_token": f"access-{self.tokens}", "expires_in": 3600}
            )
        body = json.loads(request.content)
        q = body["query"]
        self.queries.append(q)
        self.headers.append(request.headers)
        if "FROM customer" in q:
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "customer": {
                                "descriptiveName": "Ridhi",
                                "currencyCode": "USD",
                                "timeZone": "Asia/Calcutta",
                            }
                        }
                    ]
                },
            )
        if "segments.conversion_action_name" in q:  # purchases by action
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "campaign": {"id": "1", "name": "PMax"},
                            "segments": {
                                "date": "2026-11-20",
                                "conversionActionName": "Shop Purchase",
                                "conversionActionCategory": "PURCHASE",
                            },
                            "metrics": {"conversions": 2.0, "conversionsValue": 210.5},
                        },
                        {
                            "campaign": {"id": "1", "name": "PMax"},
                            "segments": {
                                "date": "2026-11-20",
                                "conversionActionName": "Web click",
                                "conversionActionCategory": "PURCHASE",
                            },
                            "metrics": {"conversions": 5.0, "conversionsValue": 5.0},
                        },
                    ]
                },
            )
        if "FROM campaign WHERE" in q:  # figures, in two pages
            if not body.get("pageToken"):
                return httpx.Response(
                    200,
                    json={
                        "results": [
                            {
                                "campaign": {"id": "1", "name": "PMax"},
                                "segments": {"date": "2026-11-20"},
                                "metrics": {
                                    "costMicros": "40500000",
                                    "impressions": "900",
                                    "clicks": "30",
                                },
                            }
                        ],
                        "nextPageToken": "p2",
                    },
                )
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "campaign": {"id": "2", "name": "Brand"},
                            "segments": {"date": "2026-11-20"},
                            "metrics": {
                                "costMicros": "9500000",
                                "impressions": "100",
                                "clicks": "20",
                            },
                        }
                    ]
                },
            )
        if "FROM campaign" in q:
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "campaign": {
                                "id": "1",
                                "name": "PMax",
                                "advertisingChannelType": "PERFORMANCE_MAX",
                                "status": "ENABLED",
                                "biddingStrategyType": "MAXIMIZE_CONVERSION_VALUE",
                            },
                            "campaignBudget": {"amountMicros": "25000000"},
                        }
                    ]
                },
            )
        return httpx.Response(200, json={"results": []})


def client(fake: FakeGoogle) -> GoogleAdsClient:
    return GoogleAdsClient(ACC, transport=httpx.MockTransport(fake), sleep=lambda s: None)


def test_daily_merges_figures_and_purchases_and_reads_every_page() -> None:
    fg = FakeGoogle()
    rows = {
        r["item"]: r for r in client(fg).daily("campaign", date(2026, 11, 20), date(2026, 11, 20))
    }
    assert rows["1"]["spend"] == 40.5 and rows["1"]["clicks"] == 30
    assert (
        rows["1"]["purchases"] == 2.0 and rows["1"]["value"] == 210.5
    )  # the click action is left out
    assert rows["2"]["spend"] == 9.5 and rows["2"]["purchases"] == 0
    assert fg.tokens == 1  # one sign-in for every request
    assert all("2026-11-20" in q for q in fg.queries if "segments.date" in q)
    h = fg.headers[0]
    assert h["authorization"] == "Bearer access-1" and "developer-token" not in h


def test_campaigns_and_account() -> None:
    g = client(FakeGoogle())
    assert g.account_info() == {"name": "Ridhi", "currency": "USD", "timezone": "Asia/Calcutta"}
    c = g.campaigns()[0]
    assert (
        c["channel"] == "PERFORMANCE_MAX" and c["daily_budget"] == 25.0 and c["status"] == "ENABLED"
    )


def test_a_refused_sign_in_says_so_without_the_token() -> None:
    with pytest.raises(GoogleAdsError) as e:
        client(FakeGoogle(400, "invalid_grant")).account_info()
    assert e.value.state == "token_expired" and "refresh-secret" not in e.value.message


@pytest.mark.parametrize(
    ("status", "code", "state"),
    [
        (403, {"authorizationError": "CUSTOMER_NOT_ENABLED"}, "not_enabled"),
        (403, {"authorizationError": "USER_PERMISSION_DENIED"}, "permission"),
        (429, {"quotaError": "RESOURCE_EXHAUSTED"}, "rate_limited"),
        (400, {"queryError": "BAD_FIELD_NAME"}, "bad_request"),
    ],
)
def test_google_errors_become_plain_states(status: int, code: dict[str, str], state: str) -> None:
    def answer(request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "a", "expires_in": 3600})
        return httpx.Response(
            status, json={"error": {"code": status, "details": [{"errors": [{"errorCode": code}]}]}}
        )

    g = GoogleAdsClient(ACC, transport=httpx.MockTransport(answer), sleep=lambda s: None)
    with pytest.raises(GoogleAdsError) as e:
        g.campaigns()
    assert e.value.state == state


# ------------------------------------------------------------------ sync
class SyncFake:
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
        mp.setattr(
            data, "save_g_campaigns", lambda rows, c=None: self.log.append(("campaigns", rows))
        )
        mp.setattr(
            data,
            "g_replace",
            lambda key, kind, a, b, rows, c=None: (
                self.log.append(("rows", (kind, a, b))) or len(rows)
            ),
        )
        mp.setattr(data, "forget", lambda key=None: None)
        mp.setattr(data, "account", lambda key, c=None: {"key": key})
        mp.setattr(
            data, "mark_loaded_from", lambda key, day, c=None: self.log.append(("loaded_from", day))
        )


def test_first_google_sync_loads_90_days_of_every_kind(monkeypatch: pytest.MonkeyPatch) -> None:
    for k, v in GOOGLE_ENV.items():
        monkeypatch.setenv(k, v)
    sf = SyncFake({"got_lock": True, "full_at": None, "loaded_from": None})
    sf.install(monkeypatch)
    now = datetime(2026, 11, 27, 12, tzinfo=UTC)
    out = google_sync.sync_google("ridhi", gads=client(FakeGoogle()), now=now)
    assert out["state"] == "ok" and out["full"] and out["platform"] == "google"
    spans = [x for k, x in sf.log if k == "rows"]
    assert {kind for kind, _a, _b in spans} == {"campaign", "group", "term", "keyword", "product"}
    assert min(a for _k, a, _b in spans) == date(2026, 11, 27) - timedelta(
        days=89
    )  # India: still the 27th
    assert len(spans) == 3 * 5  # 90 days in spans of 30, five kinds each
    account = next(x for k, x in sf.log if k == "account")
    assert (
        account["key"] == "google:ridhi"
        and account["platform"] == "google"
        and account["external_id"] == "1234567890"
    )
    assert next(x for k, x in sf.log if k == "end") == (
        True,
        None,
        True,
        date(2026, 11, 27) - timedelta(days=89),
    )


def test_a_google_failure_is_recorded_not_raised(monkeypatch: pytest.MonkeyPatch) -> None:
    for k, v in GOOGLE_ENV.items():
        monkeypatch.setenv(k, v)
    sf = SyncFake({"got_lock": True, "full_at": None, "loaded_from": None})
    sf.install(monkeypatch)
    out = google_sync.sync_google("ridhi", gads=client(FakeGoogle(400, "invalid_grant")))
    assert out["state"] == "failed" and out["reason"] == "token_expired"
    assert google_sync.sync_google("cpc")["state"] == "not_configured"


# ------------------------------------------------------------------ the page with Google
@pytest.fixture
def gfake(fake: FakeData, monkeypatch: pytest.MonkeyPatch) -> FakeData:
    """The service fake with Ridhi's Google account set and read."""
    for k, v in GOOGLE_ENV.items():
        monkeypatch.setenv(k, v)
    fake.google_row = {
        "key": "google:ridhi",
        "name": "Ridhi Google test",
        "currency": "USD",
        "timezone": "UTC",
        "first_day": iso(Y - timedelta(days=90)),
        "last_run_at": datetime.now(UTC).isoformat(),
        "last_status": "ok",
    }
    return fake


def test_all_adds_google_spend_and_mer_uses_both(gfake: FakeData) -> None:
    o = service.overview("ridhi", "all", None, None, None)
    m = o["metrics"]
    assert m["spend"]["value"] == m["total_spend"]["value"] == 7 * (1000 + 100)
    assert "roas" not in m  # platforms' claimed sales are never added together
    meta, google = o["platforms"]
    assert (
        google["account"] == "Ridhi Google test"
        and google["spend"] == 700
        and google["roas"] == 3.0
    )
    assert google["share_of_spend"] == round(100 / 1100 * 100, 1) and meta[
        "share_of_spend"
    ] == round(1000 / 1100 * 100, 1)
    assert o["trend"][-1]["google_spend"] == 100 and o["trend"][-1]["spend"] == 1100
    assert o["google_saved_to"] == iso(Y) and o["gate"]["state"] != "unknown"
    assert o["goal"]["avg_spend_7d"] == 1100


def test_google_alone_shows_its_roas_but_mer_still_counts_meta(gfake: FakeData) -> None:
    o = service.overview("ridhi", "google", None, None, None)
    m = o["metrics"]
    assert m["spend"]["value"] == 700 and m["total_spend"]["value"] == 7700
    assert m["roas"]["value"] == 3.0 and m["purchases"]["value"] == 21
    all_ = service.overview("ridhi", "all", None, None, None)["metrics"]
    assert m["mer_ex_bulk"]["value"] == all_["mer_ex_bulk"]["value"]


def test_google_not_saved_to_the_end_means_no_spend_call(
    gfake: FakeData, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(data, "g_latest_day", lambda key, c=None: Y - timedelta(days=3))
    o = service.overview("ridhi", "all", None, None, None)
    assert o["gate"]["state"] == "unknown"
    assert o["notes"][0].startswith("Google figures are saved up to")


def test_google_campaigns_with_their_groups(gfake: FakeData) -> None:
    rows = service.campaigns("ridhi", "google", None, None, None)["campaigns"]
    assert [r["id"] for r in rows] == ["g_pmax", "g_brand"]  # by spend
    pmax, brand = rows
    assert (
        pmax["type"] == "pmax"
        and pmax["type_label"] == "Performance Max"
        and pmax["status"] == "ACTIVE"
    )
    assert (
        pmax["spend"] == 490 and pmax["roas"] == round(150 / 70, 2) and pmax["daily_budget"] == 75
    )
    assert pmax["groups"][0]["kind"] == "asset_group" and pmax["groups"][0]["spend"] == 490
    assert brand["is_brand"] and brand["type"] == "search" and not pmax["is_brand"]
    both = service.campaigns("ridhi", "all", None, None, None)["campaigns"]
    assert {r["platform"] for r in both} == {"meta", "google"}


def test_search_terms_keywords_products_and_the_brand_share(gfake: FakeData) -> None:
    d = service.search_terms("ridhi", None, None, None)
    terms = {t["term"].lower(): t for t in d["terms"]}
    assert (
        terms["ridhi block print"]["spend"] == 7 * 25 and terms["ridhi block print"]["is_brand"]
    )  # two spellings, one row
    assert [k["match_type"] for k in d["keywords"]] == ["BROAD", "PHRASE"]
    assert [p["title"] for p in d["products"]] == [
        "Quilt | Sage Queen"
    ]  # no spend, no purchase: left out
    b = d["brand_share"]
    assert (
        b["spend"] == 210
        and b["total_spend"] == 700
        and b["value"] == 1050
        and b["total_value"] == 2100
    )
    assert len({r["id"] for r in d["keywords"]}) == len(d["keywords"])


def test_google_funnel(gfake: FakeData) -> None:
    f = service.funnel("ridhi", "google", None, None, None)
    assert f["meta"] is None
    steps = {s["key"]: s for s in f["google"]["steps"]}
    assert steps["clicks"]["value"] == 7 * 120 and steps["purchases"]["rate"] == round(
        21 / 840 * 100, 1
    )


def test_settings_list_the_google_account(gfake: FakeData) -> None:
    s = service.settings("ridhi")
    assert [a["platform"] for a in s["accounts"]] == ["meta", "google"]
    assert s["google"] == {"connected": True, "note": None}


def test_google_not_set_says_which_key(
    fake: FakeData, app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RIDHI_META_AD_ACCOUNT_ID", "123")  # the app fixture clears Meta's keys
    monkeypatch.setenv("RIDHI_META_ACCESS_TOKEN", "test-token")
    with pytest.raises(service.GoogleNotConnectedError) as e:
        service.overview("ridhi", "google", None, None, None)
    assert "RIDHI_GOOGLE_ADS_CUSTOMER_ID" in e.value.message
    o = service.overview("ridhi", "all", None, None, None)  # All still works, with Meta only
    assert (
        o["platforms"][1]["account"] == "Not connected yet"
        and o["metrics"]["spend"]["value"] == 7000
    )
    r = local_client(app).get("/api/ads/search-terms?brand=ridhi")
    assert r.status_code == 503 and r.json()["code"] == "google_not_connected"


def test_google_not_read_yet_says_so(gfake: FakeData) -> None:
    assert gfake.google_row is not None
    gfake.google_row["first_day"] = None
    gfake.google_row["last_error"] = "This Google login cannot read that Google Ads account."
    with pytest.raises(service.GoogleNotConnectedError) as e:
        service.search_terms("ridhi")
    assert "not finished yet" in e.value.message and "cannot read" in e.value.message
    assert RATE  # the Meta fake's rate stays untouched by Google (USD)


def test_missing_google_tables_wait_instead_of_failing(monkeypatch: pytest.MonkeyPatch) -> None:
    from flowmerce.modules.shipping.supabase import SupabaseError

    for k, v in GOOGLE_ENV.items():
        monkeypatch.setenv(k, v)
    sf = SyncFake({"got_lock": True, "full_at": None, "loaded_from": None})
    sf.install(monkeypatch)

    def missing(rows: Any, c: Any = None) -> None:
        raise SupabaseError("schema_missing", "relation does not exist")

    monkeypatch.setattr(data, "save_g_campaigns", missing)
    out = google_sync.sync_google("ridhi", gads=client(FakeGoogle()))
    assert out["state"] == "waiting" and "117_ads_google.sql" in out["error"]
    ok, err, _full, _first = next(x for k, x in sf.log if k == "end")
    assert not ok and "117_ads_google.sql" in err


def test_only_passing_failures_bring_the_next_round_forward() -> None:
    from flowmerce.modules.ads.scheduler import needs_retry

    ok = {"state": "ok"}
    assert not needs_retry({"ridhi": ok, "ridhi:google": {"state": "waiting"}})
    assert not needs_retry({"cpc:google": {"state": "failed", "reason": "permission"}})
    assert not needs_retry({"ridhi": {"state": "failed", "reason": "token_expired"}})
    assert needs_retry({"ridhi": {"state": "failed", "reason": "connection_failed"}})
    assert needs_retry({"ridhi": {"state": "locked"}})
    assert needs_retry({"ridhi": {"state": "failed", "error": "database down"}})  # no reason given
