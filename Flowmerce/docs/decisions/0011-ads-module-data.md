# ADR 0011: How the Ads module reads and keeps ad data

- Status: accepted (owner approved the Ads plan and its phase 2, 2026-11-24)
- Date: 2026-11-24

## Decision

1. **One Ads module** (`src/flowmerce/modules/ads/`, page `/ads`) for Meta Ads and Google Ads, both brands, with a
   platform switch (owner, 2026-11-24). Phase 2 reads Meta; Google is phase 3.
2. **Meta is read directly with `httpx`** (already a dependency), read-only, Graph API version pinned in
   `ads/config.py` (v27.0). No Meta SDK.
3. **The figures are copied into schema `ads` in the central Supabase database** by a background job (hourly by
   default), and the page reads Supabase, never Meta. The job keeps one row per ad per account day; the first run
   loads 90 days, a nightly run re-reads 28 days and each ad's lifetime totals, other runs re-read 3 days.
4. **Totals are added up in the database** (functions in `db/central/115_ads.sql`: `account_days`, `ad_windows`,
   `store_days`), so the server never holds months of daily rows in memory.
5. **Money is reported in US dollars.** An account billed in another currency (Ridhi's Meta account, INR) is
   converted with a rate the owner sets on the Rules tab, stored with the day it starts (`ads.fx_rates`); earlier
   days keep their rate. Starting rate: Rs 88 (the Daily sheet's assumption).
6. **Store sales come from CRO's copy of the Shopify orders** (`cro.orders`, through `ads.store_days`), counted as
   placed (current total + refunded), by the store's own day in the time zone Shopify reports (not
   `ops.stores.timezone`, which says Los Angeles for both stores).
7. **The rules** (verdicts, budget calls, scaling gate, ABO to CBO gap) are pure Python (`ads/metrics.py`), with
   the Daily sheet's Rules tab as the starting values, editable per brand (`ads.rules`).

## Rationale

- Meta answers slowly (25 to 50 seconds for an account's campaigns, ad sets and ads; about 25 seconds per 7 days of
  ad-level figures, measured 2026-11-24), so the page cannot ask Meta on every visit.
- The hosted copy has 512 MB of memory and crashed before from in-memory caches (CRO, 2026-11-23); adding up in the
  database keeps the Ads answers small.
- Checked against the 24 Oct Daily sheet: Meta's `purchase` action, the `omni_` add-to-cart and checkout counts and
  ad-level spend added up reproduce the sheet exactly; the orders in `cro.orders`, counted as placed, reproduce its
  Shopify sales for days without later refunds.

## Alternatives considered

- **Ask Meta on every page visit** (as CRO asks Shopify's ShopifyQL): too slow, and Meta's request limits would be
  reached quickly.
- **Meta's Python SDK** (`facebook-business`): a large dependency for a few GET requests.
- **Keep the figures in the local SQLite file**: the hosted copy and the other modules use Supabase; SQLite holds
  only the SEO module (ADR 0003).
- **Add up in Python**: simpler SQL, but months of ad-level rows in memory on every visit.

## Advantages

- Fast pages and few Meta requests; a Meta outage leaves the last figures readable.
- The same tables take Google Ads in phase 3 (`platform`, account key `google:<brand>`).
- Rates, rules and action marks are the team's own records, kept apart from what is copied from Meta.

## Disadvantages

- Figures are up to an hour old (`ADS_SYNC_MINUTES`), plus Meta's own delay.
- Another schema to run and expose in Supabase (`115_ads.sql`, Exposed schemas: `ads`).
- The SQL functions could not be run before the owner runs them in Supabase (no local PostgreSQL); the Python
  side was tested with unit tests and against both real Meta accounts with the database stood in.
- Video length is not available: Meta refuses video objects to a token with `ads_read` only.

## Consequences and dependencies

- Needs `RIDHI_/CPC_META_AD_ACCOUNT_ID` and `RIDHI_/CPC_META_ACCESS_TOKEN` in the server's environment (also on
  Render). The current tokens are personal user tokens that expire on 2027-01-20; a system-user token does not
  expire. The page shows the days left.
- Depends on CRO's order copy (`cro.orders`) for store sales and on Shipping's Supabase settings.
- Phase 3 adds a Google Ads client and the Search terms tab; until then Google requests answer
  `google_not_connected` and "All" uses Meta spend only (the page says so).
