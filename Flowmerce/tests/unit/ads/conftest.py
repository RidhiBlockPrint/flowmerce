"""Fixtures shared by the Ads tests: the in-memory fake of schema `ads`, the app, and an empty
answer cache before each test (all defined in test_sync_service.py)."""

from tests.unit.ads.test_sync_service import _nothing_kept, app, fake  # noqa: F401
