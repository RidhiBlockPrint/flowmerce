"""What the Ads pages ask for: connection status, and a performance summary per store.

Two sources, never mixed in one answer:
  * demo   fixed sample figures, so the pages can be built and reviewed before the manager hands
           over access. Every answer carries ``"source": "demo"`` and the pages label it.
  * live   the platforms themselves, through meta.py and google.py.

The summary deliberately stays small: spend, impressions, clicks and what each platform claims for
purchases, plus the rates worked out in one place here rather than in SQL or in the browser. The
store-side truth (Shopify orders) is joined in a later task; until then the page says that the
purchase figures are the platforms' own claim.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from .config import STORE_BRAND, ads_config, google_credentials, meta_credentials, store_for
from .google import GoogleAdsClient, GoogleAdsError
from .google import metric_row as google_metric_row
from .meta import MetaClient, MetaError
from .meta import metric_row as meta_metric_row

log = logging.getLogger(__name__)

# Below this a rate is noise rather than a finding. Same idea as CRO's comparison limits and as the
# `sample_ok` flag in creative.insight.
MIN_IMPRESSIONS_FOR_RATES = 1000


class InputError(ValueError):
    """A value the caller sent that cannot be used (becomes HTTP 400)."""


@dataclass(frozen=True)
class Totals:
    """Added-up figures for one platform over one range."""

    spend: float = 0.0
    impressions: int = 0
    clicks: int = 0
    purchases: float = 0.0
    purchase_value: float = 0.0
    currency: str = ""
    days: int = 0

    def as_dict(self) -> dict[str, Any]:
        """The figures plus the rates, with rates left out when there is too little data."""
        enough = self.impressions >= MIN_IMPRESSIONS_FOR_RATES
        return {
            "spend": round(self.spend, 2),
            "impressions": self.impressions,
            "clicks": self.clicks,
            "purchases": round(self.purchases, 2),
            "purchaseValue": round(self.purchase_value, 2),
            "currency": self.currency,
            "days": self.days,
            "ctr": round(self.clicks / self.impressions * 100, 2) if enough else None,
            "cpc": round(self.spend / self.clicks, 2) if self.clicks else None,
            "cpm": round(self.spend / self.impressions * 1000, 2) if enough else None,
            "roas": round(self.purchase_value / self.spend, 2) if self.spend > 0 else None,
            "cpa": round(self.spend / self.purchases, 2) if self.purchases > 0 else None,
            "sampleOk": enough,
        }


def _add(totals: Totals, row: dict[str, Any]) -> Totals:
    """Add one daily row to the running totals."""
    return Totals(
        spend=totals.spend + float(row.get("spend") or 0),
        impressions=totals.impressions + int(row.get("impressions") or 0),
        clicks=totals.clicks + int(row.get("clicks") or 0),
        purchases=totals.purchases + float(row.get("purchases") or 0),
        purchase_value=totals.purchase_value + float(row.get("purchase_value") or 0),
        currency=totals.currency or str(row.get("currency") or ""),
        days=totals.days + 1,
    )


def _range(days: int) -> tuple[date, date]:
    """The last `days` complete days, ending yesterday.

    Today is left out on purpose: a part-day makes every rate look wrong, and both platforms are
    still restating it.
    """
    if days < 1 or days > 400:
        raise InputError("Choose between 1 and 400 days.")
    yesterday = datetime.now(UTC).date() - timedelta(days=1)
    return yesterday - timedelta(days=days - 1), yesterday


# ------------------------------------------------------------------ connection status
def status() -> dict[str, Any]:
    """Which platforms are connected for which store, and what is still missing.

    Safe to call without any credentials: it reads the environment only and never calls a platform,
    so the Settings page can show the gaps before anything is connected.
    """
    cfg = ads_config()
    stores: list[dict[str, Any]] = []
    for store, brand in STORE_BRAND.items():
        meta = meta_credentials(store)
        google = google_credentials(store)
        stores.append(
            {
                "store": store,
                "brand": brand,
                "meta": {
                    "connected": meta.configured,
                    "missing": meta.missing,
                    "apiVersion": meta.api_version,
                    "accountId": meta.account_id,  # an id, not a secret
                },
                "google": {
                    "connected": google.configured,
                    "missing": google.missing,
                    "apiVersion": google.api_version,
                    "customerId": google.customer_id,
                    "managerId": google.login_customer_id,
                },
            }
        )
    return {
        "demo": cfg.demo,
        "syncMinutes": cfg.sync_minutes,
        "stores": stores,
        "note": (
            "Demo figures are shown while no platform is connected. Flowmerce only reads from Meta "
            "and Google Ads: it never creates, pauses or changes an ad or a budget."
        )
        if cfg.demo
        else "Flowmerce reads Meta and Google Ads. It never changes an ad or a budget.",
    }


# ------------------------------------------------------------------ performance summary
def summary(brand: str, days: int = 28) -> dict[str, Any]:
    """Spend and performance per platform for one store over the last `days` complete days."""
    store = store_for(brand)
    since, until = _range(days)
    cfg = ads_config()
    if cfg.demo:
        return _demo_summary(brand, store, since, until)

    platforms: dict[str, Any] = {}
    problems: list[dict[str, str]] = []
    for name, totals_or_error in (
        ("meta", _meta_totals(store, since, until, cfg.timeout)),
        ("google", _google_totals(store, since, until, cfg.timeout)),
    ):
        if isinstance(totals_or_error, Totals):
            platforms[name] = totals_or_error.as_dict()
        else:
            platforms[name] = None
            problems.append({"platform": name, **totals_or_error})
    return {
        "brand": brand,
        "store": store,
        "source": "live",
        "from": since.isoformat(),
        "to": until.isoformat(),
        "platforms": platforms,
        "problems": problems,
        "purchasesAre": (
            "Each platform's own claim. Shopify orders are counted separately and can differ."
        ),
    }


def _meta_totals(
    store: str, since: date, until: date, timeout: float
) -> Totals | dict[str, str]:
    """Meta's figures for one store, or an explained problem the page can show."""
    creds = meta_credentials(store)
    if not creds.configured:
        return {"state": "not_configured", "message": "Meta Ads is not connected for this store."}
    client = MetaClient(creds, timeout=timeout)
    try:
        rows = client.insights(since, until, level="account")
        totals = Totals()
        for row in rows:
            totals = _add(totals, meta_metric_row(row))
        return totals
    except MetaError as exc:
        log.warning("Ads: Meta read failed for %s (%s)", store, exc.state)
        return {"state": exc.state, "message": exc.message}
    finally:
        client.close()


def _google_totals(
    store: str, since: date, until: date, timeout: float
) -> Totals | dict[str, str]:
    """Google's figures for one store, or an explained problem the page can show."""
    creds = google_credentials(store)
    if not creds.configured:
        return {"state": "not_configured", "message": "Google Ads is not connected for this store."}
    client = GoogleAdsClient(creds, timeout=timeout)
    try:
        rows = client.daily_metrics(since, until, level="campaign")
        totals = Totals()
        for row in rows:
            totals = _add(totals, google_metric_row(row))
        return totals
    except GoogleAdsError as exc:
        log.warning("Ads: Google read failed for %s (%s)", store, exc.state)
        return {"state": exc.state, "message": exc.message}
    finally:
        client.close()


# ------------------------------------------------------------------ demo figures
# Fixed numbers, not random: a demo screenshot has to look the same tomorrow, and a test can assert
# on them. In US dollars because both stores sell in USD (ops.stores defaults to USD on America/
# Los_Angeles time, and Ridhi's brand guide sets US customers and prices in dollars); the first
# samples written on 2026-11-25 were in rupees, which would have taught the team the wrong currency.
_DEMO: dict[str, dict[str, Any]] = {
    "RBP": {
        "meta": {"spend": 4235.0, "impressions": 612_400, "clicks": 9_186, "purchases": 128.0,
                 "purchase_value": 19_648.0, "currency": "USD"},
        "google": {"spend": 1890.0, "impressions": 141_300, "clicks": 4_521, "purchases": 61.0,
                   "purchase_value": 9_760.0, "currency": "USD"},
    },
    "CPC": {
        "meta": {"spend": 2310.0, "impressions": 388_900, "clicks": 5_833, "purchases": 74.0,
                 "purchase_value": 10_360.0, "currency": "USD"},
        "google": {"spend": 945.0, "impressions": 78_200, "clicks": 2_190, "purchases": 28.0,
                   "purchase_value": 4_200.0, "currency": "USD"},
    },
}


def _demo_summary(brand: str, store: str, since: date, until: date) -> dict[str, Any]:
    """The demo answer, in exactly the shape a live answer has."""
    days = (until - since).days + 1
    figures = _DEMO.get(store, _DEMO["RBP"])
    platforms = {
        name: Totals(
            spend=values["spend"],
            impressions=values["impressions"],
            clicks=values["clicks"],
            purchases=values["purchases"],
            purchase_value=values["purchase_value"],
            currency=values["currency"],
            days=days,
        ).as_dict()
        for name, values in figures.items()
    }
    return {
        "brand": brand,
        "store": store,
        "source": "demo",
        "from": since.isoformat(),
        "to": until.isoformat(),
        "platforms": platforms,
        "problems": [],
        "purchasesAre": "Sample figures. Nothing here comes from a real ad account.",
    }
