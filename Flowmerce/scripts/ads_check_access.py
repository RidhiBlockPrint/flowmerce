"""Read-only check of the Meta Ads and Google Ads credentials.

Run this once the manager has filled the values into .env. It proves that the credentials work and
that the accounts can be read, and nothing else: it makes only GET-style reads, writes nothing to
either platform, and writes nothing to the database.

What it prints: which values are missing, which ad accounts the credentials can see, and the spend
and impressions of the last seven complete days. It never prints a token, a secret, a URL or a
customer's personal data.

Usage:  .venv\\Scripts\\python.exe scripts\\ads_check_access.py
        .venv\\Scripts\\python.exe scripts\\ads_check_access.py --days 30

Exit codes: 0 = every configured platform answered, 1 = nothing is configured yet,
            2 = something is configured but a platform refused.
"""
from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from flowmerce.modules.ads.config import (  # noqa: E402
    STORE_BRAND,
    ads_config,
    google_credentials,
    meta_credentials,
)
from flowmerce.modules.ads.google import GoogleAdsClient, GoogleAdsError  # noqa: E402
from flowmerce.modules.ads.google import metric_row as google_metric_row  # noqa: E402
from flowmerce.modules.ads.meta import MetaClient, MetaError  # noqa: E402
from flowmerce.modules.ads.meta import metric_row as meta_metric_row  # noqa: E402


def _totals(rows: list[dict[str, object]], convert) -> tuple[float, int, str]:  # type: ignore[no-untyped-def]
    """Add up spend and impressions across the daily rows."""
    spend = 0.0
    impressions = 0
    currency = ""
    for row in rows:
        values = convert(row)
        spend += float(values.get("spend") or 0)
        impressions += int(values.get("impressions") or 0)
        currency = currency or str(values.get("currency") or "")
    return spend, impressions, currency


def check_meta(store: str, days: int, timeout: float) -> bool:
    """Read Meta for one store. Returns False when it is configured but refused."""
    creds = meta_credentials(store)
    print(f"\n--- {store} · Meta Ads (API {creds.api_version})")
    if not creds.configured:
        print(f"    not configured; missing: {', '.join(creds.missing)}")
        return True
    client = MetaClient(creds, timeout=timeout)
    try:
        accounts = client.accounts()
        print(f"    token can see {len(accounts)} ad account(s):")
        for account in accounts:
            print(
                f"      {account.get('id', '?')}  {account.get('name', '')}  "
                f"{account.get('currency', '')}  status={account.get('account_status', '?')}"
            )
        ids = {str(a.get("id") or "") for a in accounts}
        if accounts and creds.account_id not in ids:
            print(
                f"    WARNING: the configured account {creds.account_id} is not in that list. "
                "The system user may not be assigned to it."
            )
        until = datetime.now(UTC).date() - timedelta(days=1)
        since = until - timedelta(days=days - 1)
        rows = client.insights(since, until, level="account")
        spend, impressions, currency = _totals(rows, meta_metric_row)
        print(
            f"    {since} to {until}: spend {spend:,.2f} {currency}, "
            f"{impressions:,} impressions, {len(rows)} day row(s)"
        )
        if client.throttle.tier:
            print(
                f"    throttle: app {client.throttle.app_pct:.0f}%, "
                f"account {client.throttle.account_pct:.0f}%, tier {client.throttle.tier}"
            )
        return True
    except MetaError as exc:
        print(f"    FAILED ({exc.state}): {exc.message}")
        return False
    finally:
        client.close()


def check_google(store: str, days: int, timeout: float) -> bool:
    """Read Google Ads for one store. Returns False when it is configured but refused."""
    creds = google_credentials(store)
    print(f"\n--- {store} · Google Ads (API {creds.api_version})")
    if not creds.configured:
        print(f"    not configured; missing: {', '.join(creds.missing)}")
        return True
    client = GoogleAdsClient(creds, timeout=timeout)
    try:
        customers = client.accessible_customers()
        print(f"    credentials can reach {len(customers)} customer id(s): {', '.join(customers) or '-'}")
        if customers and creds.customer_id not in customers:
            print(
                f"    NOTE: {creds.customer_id} is not in that list. That is normal when the "
                "account sits under a manager account; GOOGLE_ADS_LOGIN_CUSTOMER_ID must then be set."
            )
        account = client.account()
        customer = account.get("customer") if isinstance(account, dict) else None
        if isinstance(customer, dict):
            print(
                f"    account: {customer.get('descriptiveName', '')}  "
                f"{customer.get('currencyCode', '')}  {customer.get('timeZone', '')}  "
                f"status={customer.get('status', '?')}"
            )
        until = datetime.now(UTC).date() - timedelta(days=1)
        since = until - timedelta(days=days - 1)
        rows = client.daily_metrics(since, until, level="campaign")
        spend, impressions, currency = _totals(rows, google_metric_row)
        print(
            f"    {since} to {until}: spend {spend:,.2f} {currency}, "
            f"{impressions:,} impressions, {len(rows)} campaign-day row(s)"
        )
        return True
    except GoogleAdsError as exc:
        print(f"    FAILED ({exc.state}): {exc.message}")
        return False
    finally:
        client.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only check of the Meta and Google Ads credentials")
    parser.add_argument("--days", type=int, default=7, help="how many complete days to read (default 7)")
    args = parser.parse_args()
    days = max(1, min(90, args.days))

    cfg = ads_config()
    print("Flowmerce · Ads credential check (read-only; nothing is changed or stored)")
    if cfg.demo:
        print("ADS_DEMO is on, so the app itself is showing sample figures. This check still reads live.")

    configured = False
    ok = True
    for store in STORE_BRAND:
        if meta_credentials(store).configured or google_credentials(store).configured:
            configured = True
        ok = check_meta(store, days, cfg.timeout) and ok
        ok = check_google(store, days, cfg.timeout) and ok

    print()
    if not configured:
        print("Nothing is configured yet. Fill the Meta and Google values into .env and run this again.")
        return 1
    if not ok:
        print("At least one platform refused. The message above says what to fix.")
        return 2
    print("Every configured platform answered. The credentials work for reading.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
