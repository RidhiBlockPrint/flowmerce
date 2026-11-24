"""Ads module: Meta Ads (and later Google Ads) next to the store's own sales
(docs/plans/ads-module.md).

* A background job (`scheduler.py`) reads each brand's Meta ad account, read-only, into schema `ads`
  in the central Supabase database: campaigns, ad sets and ads, and one row per ad per day
  (`sync.py`, `meta.py`).
* The /api/ads routes (`api.py`) answer the Ads page from Supabase, never from Meta directly; the
  totals are added up in the database (`db/central/115_ads.sql`), and the verdicts, budget calls and
  suggestions are worked out in `metrics.py` from the rules on the Rules tab.
* Store sales come from CRO's copy of the Shopify orders (`cro.orders`), read through a database
  function.

Read-only toward the ad accounts: nothing here changes a budget, a status or anything else in Meta
or Google. Independent of SEO, Shipping and CRO: if Meta or Supabase cannot be reached, only the Ads
page says so.
"""
