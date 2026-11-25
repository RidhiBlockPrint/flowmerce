"""Ads configuration and the connection status route's data. No network, no credentials."""

from __future__ import annotations

import pytest

from flowmerce.modules.ads import service
from flowmerce.modules.ads.config import ads_config, google_credentials, meta_credentials, store_for

ENV_KEYS = (
    "META_SYSTEM_USER_TOKEN",
    "META_API_VERSION",
    "RIDHI_META_AD_ACCOUNT_ID",
    "CPC_META_AD_ACCOUNT_ID",
    "GOOGLE_ADS_CLIENT_ID",
    "GOOGLE_ADS_CLIENT_SECRET",
    "GOOGLE_ADS_REFRESH_TOKEN",
    "GOOGLE_ADS_LOGIN_CUSTOMER_ID",
    "GOOGLE_ADS_API_VERSION",
    "RIDHI_GOOGLE_ADS_CUSTOMER_ID",
    "CPC_GOOGLE_ADS_CUSTOMER_ID",
    "ADS_DEMO",
    "ADS_SYNC_MINUTES",
    "ADS_TIMEOUT_SECONDS",
    "DEMO_MODE",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start every test from an empty Ads configuration, whatever the developer's .env holds."""
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_store_for_maps_brands_and_rejects_unknown() -> None:
    assert store_for("ridhi") == "RBP"
    assert store_for("cpc") == "CPC"
    with pytest.raises(ValueError, match="Unknown brand"):
        store_for("nope")


def test_credentials_are_not_configured_and_list_what_is_missing() -> None:
    meta = meta_credentials("RBP")
    assert not meta.configured
    assert "META_SYSTEM_USER_TOKEN" in meta.missing
    google = google_credentials("RBP")
    assert not google.configured
    assert "GOOGLE_ADS_CLIENT_ID" in google.missing
    assert "<BRAND>_GOOGLE_ADS_CUSTOMER_ID" in google.missing


def test_meta_account_id_gets_the_act_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    """The manager may hand over a bare number; the API needs act_<digits>."""
    monkeypatch.setenv("META_SYSTEM_USER_TOKEN", "token-value")
    monkeypatch.setenv("RIDHI_META_AD_ACCOUNT_ID", "1234567890")
    creds = meta_credentials("RBP")
    assert creds.account_id == "act_1234567890"
    assert creds.configured
    assert creds.missing == []


def test_google_customer_id_keeps_digits_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """Google writes ids as 123-456-7890 in the UI but the API wants digits."""
    monkeypatch.setenv("CPC_GOOGLE_ADS_CUSTOMER_ID", "123-456-7890")
    monkeypatch.setenv("GOOGLE_ADS_LOGIN_CUSTOMER_ID", "999-888-7777")
    creds = google_credentials("CPC")
    assert creds.customer_id == "1234567890"
    assert creds.login_customer_id == "9998887777"


def test_demo_is_on_while_nothing_is_connected() -> None:
    assert ads_config().demo is True


def test_demo_mode_overrides_ads_demo_false(monkeypatch: pytest.MonkeyPatch) -> None:
    """DEMO_MODE must never be defeated by ADS_DEMO=false: it may not show real figures."""
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("ADS_DEMO", "false")
    assert ads_config().demo is True


def test_demo_turns_off_once_a_platform_is_connected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("META_SYSTEM_USER_TOKEN", "token-value")
    monkeypatch.setenv("RIDHI_META_AD_ACCOUNT_ID", "act_1")
    assert ads_config().demo is False


def test_status_reports_both_stores_and_never_leaks_the_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("META_SYSTEM_USER_TOKEN", "super-secret-token")
    monkeypatch.setenv("RIDHI_META_AD_ACCOUNT_ID", "act_1")
    out = service.status()
    stores = {row["store"]: row for row in out["stores"]}
    assert set(stores) == {"RBP", "CPC"}
    assert stores["RBP"]["meta"]["connected"] is True
    assert stores["CPC"]["meta"]["connected"] is False
    assert "super-secret-token" not in str(out)


def test_summary_in_demo_mode_is_labelled_and_has_both_platforms() -> None:
    out = service.summary("ridhi", days=28)
    assert out["source"] == "demo"
    assert set(out["platforms"]) == {"meta", "google"}
    meta = out["platforms"]["meta"]
    # 9,186 clicks on 612,400 impressions is 1.5%; 196,480 value on 42,350 spend is 4.64 ROAS.
    assert meta["ctr"] == 1.5
    assert meta["roas"] == 4.64
    assert meta["sampleOk"] is True


def test_summary_rejects_an_impossible_range() -> None:
    with pytest.raises(service.InputError):
        service.summary("ridhi", days=0)


def test_rates_are_withheld_when_there_is_too_little_data() -> None:
    """A rate on 40 impressions is noise, so the page gets null and sampleOk = false."""
    small = service.Totals(spend=10.0, impressions=40, clicks=2, days=1)
    out = small.as_dict()
    assert out["ctr"] is None
    assert out["cpm"] is None
    assert out["sampleOk"] is False
    assert out["cpc"] == 5.0  # cost per click needs no impression threshold
