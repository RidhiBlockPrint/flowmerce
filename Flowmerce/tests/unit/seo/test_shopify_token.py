import dataclasses

import pytest

from flowmerce.modules.seo.config import config
from flowmerce.modules.seo.integrations import shopify


class _Res:
    def __init__(self, status, data):
        self.status_code, self._d = status, data

    def json(self):
        return self._d


@pytest.fixture
def brand(monkeypatch):
    monkeypatch.setattr(shopify, "_tokens", {})
    return dataclasses.replace(config.brands["ridhi"], admin_token="", client_id="id", client_secret="sec")


def test_configured_by_token_or_client_credentials(brand):
    assert shopify.configured(brand)
    assert not shopify.configured(dataclasses.replace(brand, client_secret=""))
    assert shopify.configured(dataclasses.replace(brand, client_id="", client_secret="", admin_token="shpat_x"))


def test_token_is_exchanged_once_and_cached(brand, monkeypatch):
    calls = []
    monkeypatch.setattr(shopify.httpx, "post", lambda *a, **k: calls.append(k) or _Res(200, {"access_token": "t1", "expires_in": 86399}))
    assert shopify._access_token(brand) == "t1" and shopify._access_token(brand) == "t1"
    assert len(calls) == 1 and calls[0]["data"]["grant_type"] == "client_credentials"


def test_static_token_wins_and_a_refused_exchange_is_clear(brand, monkeypatch):
    assert shopify._access_token(dataclasses.replace(brand, admin_token="shpat_x")) == "shpat_x"
    monkeypatch.setattr(shopify.httpx, "post", lambda *a, **k: _Res(400, {}))
    with pytest.raises(RuntimeError, match="refused the client id/secret"):
        shopify._access_token(brand)
