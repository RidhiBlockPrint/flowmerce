"""Ads module: read-only copies of what Meta Ads and Google Ads report.

Flowmerce only reads here. Nothing in this module creates, pauses or changes an ad, a budget or a
campaign; the write scopes (`ads_management` on Meta) are deliberately not asked for.

Layout:
    config.py   credentials and tunables from the environment
    meta.py     Meta Marketing API client (Graph, httpx)
    google.py   Google Ads API client (REST, httpx)
    service.py  connection status and the demo figures the pages show without credentials
    api.py      the /api/ads routes
"""
