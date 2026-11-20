"""Featured images from the person's computer (services/images.py, POST /api/images/upload). No network: the Shopify upload
is replaced by a stand-in."""
import pytest

from flowmerce.modules.seo.integrations import shopify
from flowmerce.modules.seo.services import images
from flowmerce.modules.seo.util import HttpError
from tests.fixtures.seo import local_client

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 64


@pytest.fixture
def stored(monkeypatch):
    seen = {}

    def fake(b, data, filename, mime, alt=""):
        seen.update(brand=b.id, size=len(data), filename=filename, mime=mime, alt=alt)
        return "https://cdn.shopify.com/s/files/1/uploaded.png"

    monkeypatch.setattr(shopify, "configured", lambda b: True)
    monkeypatch.setattr(shopify, "upload_image", fake)
    return seen


def test_the_real_image_type_is_read_from_the_file_not_its_name():
    assert images.sniff(PNG) == "image/png" and images.sniff(JPG) == "image/jpeg"
    assert images.sniff(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == "image/webp"
    assert images.sniff(b"<svg onload=alert(1)>") is None
    assert images.clean_name("My photo (1).JPEG", "image/png") == "My-photo-1.png"


def test_an_upload_returns_the_shopify_url(stored, users):
    r = images.upload(users["admin"], "ridhi", PNG, "quilt.png", "Pink quilt")
    assert r["url"].startswith("https://cdn.shopify.com/") and stored["mime"] == "image/png" and stored["alt"] == "Pink quilt"


def test_bad_files_are_refused_before_anything_is_sent(stored, users, monkeypatch):
    for data, code in ((b"", 400), (b"not an image", 415)):
        with pytest.raises(HttpError) as e:
            images.upload(users["admin"], "ridhi", data, "x.png")
        assert e.value.status == code
    monkeypatch.setattr(images, "MAX_BYTES", 10)
    with pytest.raises(HttpError) as e:
        images.upload(users["admin"], "ridhi", PNG, "x.png")
    assert e.value.status == 413 and not stored


def test_a_missing_shopify_permission_says_how_to_add_it(users, monkeypatch):
    monkeypatch.setattr(shopify, "configured", lambda b: True)

    def denied(*_a, **_k):
        raise shopify.MissingScope("Access denied for stagedUploadsCreate field. Required access: write_files")

    monkeypatch.setattr(shopify, "upload_image", denied)
    with pytest.raises(HttpError) as e:
        images.upload(users["admin"], "ridhi", PNG, "x.png")
    assert e.value.code == "missing_scope" and "write_files" in e.value.message and "image link" in e.value.message


def test_the_route_takes_the_raw_file(stored):
    from flowmerce.modules.seo.app import create_app
    r = local_client(create_app()).post("/api/images/upload?brand=cpc&filename=a.jpg&alt=Runner", content=JPG,
                                        headers={"Content-Type": "image/jpeg", "X-Requested-With": "blog-ops"})
    assert r.status_code == 200, r.text
    assert r.json()["url"].endswith("uploaded.png") and stored["brand"] == "cpc" and stored["filename"] == "a.jpg"
