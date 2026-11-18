# Shipping on Supabase — setup in 4 steps

Flowmerce's Shipping tab reads the hub's Shopify orders in your Supabase project (`public.orders`, whose `raw`
column holds each order's Shopify fulfillments) and keeps its own shipping tables in schema `ops` up to date from
them. Nothing in `public.*` is ever changed.

> **Already ran the setup earlier?** Run only
> [`db/central/105_refresh_from_shopify_orders.sql`](../supabase/105_refresh_from_shopify_orders.sql) in the
> SQL Editor (again, if you ran an earlier version of it: it is safe to re-run and adds `ops.shopify_orders`).
> It replaces the old tracker refresh, which failed with `column s.carrier_name does not exist`
> because the tracker tables it expected (`order_checks`, `manual_status`, a different `shipments`) are not in this
> database.

## 1. Run the SQL (once)

1. Open Supabase → your project → **SQL Editor** → **New query**.
2. Paste the whole of [`db/central/supabase_setup.sql`](../supabase/supabase_setup.sql) and press **Run**.
   It creates schemas `ops` and `seo`, all tables, views, starting data, security, and the refresh
   function. It is safe to run again later (nothing is duplicated or overwritten).
3. Optional check: paste and run [`db/central/110_validate.sql`](../supabase/110_validate.sql) sections A–C.

## 2. Expose the `ops` schema to the API (once)

Supabase → **Project Settings → Data API → Exposed schemas** → add **`ops`** → Save.
(The browser key still cannot read anything: every `ops` table has row-level security with no public policy,
and the anon/authenticated roles have no rights on the schema. Only the server-side service-role key can.)

## 3. Give Flowmerce the keys (server only)

In `.env` (or `.env.shipping`, both git-ignored) on this computer:

```
SUPABASE_URL=https://<your-project>.supabase.co
SUPABASE_SERVICE_ROLE_KEY=<service role key>
# optional
SHIPPING_REFRESH_MINUTES=15
```

The key is read by the Python backend only. It is never sent to the browser or written to a log.

## 3b. Shopify keys (for reading Shopify directly)

Flowmerce reads each store's orders, tracking and carrier events straight from Shopify with the keys in `.env`
(`RIDHI_SHOPIFY_SHOP`, `RIDHI_SHOPIFY_CLIENT_ID`, `RIDHI_SHOPIFY_CLIENT_SECRET`, and the same for `CPC_`).
The keys stay on this computer and are never written to Supabase. Required app scopes: `read_orders`,
`read_merchant_managed_fulfillment_orders`, `read_third_party_fulfillment_orders`, `read_assigned_fulfillment_orders`,
`read_returns`, `read_locations`, `read_shipping`, `read_inventory` (plus `read_content`, `write_content`,
`read_products` for SEO). A store without keys is skipped; a store whose keys are refused shows a red
"Shopify direct" pill and does not stop the other store.

Without `read_all_orders`, Shopify only lets the app read the last 60 days.

## 4. Start Flowmerce and fill the data

```powershell
python scripts\run_flowmerce.py
```

Open **Shipping** and press **Refresh now** (or wait: the backend refreshes every 15 minutes).
The first time per store, reading Shopify exports the last 60 days in one go and can take a few minutes; it is
easiest to run it once from a terminal: `.venv\Scripts\python.exe scripts\shipping_refresh.py`.
The first refresh reads all orders (6,507 on 2026-11-17) and builds about 1,690 shipments and 1,695 tracking
numbers in under a second; later ones only apply changes and add new status rows.

**Known gap:** 5,051 of the 6,741 Shopify fulfillments in `public.orders.raw` (mostly September–October) were
stored with only `createdAt`: no carrier, number or status. They are skipped and counted as
`fulfillments_incomplete` in each refresh result until the hub re-fetches them from Shopify. See
[`docs/shipping-schema-needs.md`](shipping-schema-needs.md) (gap G1).

## Checks

```powershell
.venv\Scripts\python.exe scripts\shipping_inspect_supabase.py      # tables reachable, row counts, column names
.venv\Scripts\python.exe scripts\shipping_smoke.py                 # SEO + Shipping API answer
.venv\Scripts\python.exe -m unittest discover -s tests\unit\shipping -v
```

In Supabase, after the first refresh: `db/central/110_validate.sql` sections D–I compare `public.orders` with
Flowmerce (counts incl. incomplete fulfillments, Shopify word vs Flowmerce status, carrier spellings that fell to
"unknown", delivered-without-time check, a random sample of 20 to check against Shopify admin).

## What the screens mean

| Badge | Meaning |
|---|---|
| **Delivered · not carrier-confirmed** | Shopify reported delivery; no carrier feed has confirmed it. The time shown is when Shopify last updated the fulfillment |
| **Unverified** | No carrier evidence yet (label only, or a status word not in the map) |
| **Delivery problem** | Shopify reports failure, delayed, attempted_delivery or returning_to_sender |
| **No movement** | Open parcel whose Shopify status has not changed for 72 h (`ops.settings.step_limits.no_scan_h`) |
| **Team: lost / failed / delivered** | A person's check; stored apart from the carrier status |
| **mcf? / india? / unknown?** | The type was guessed from the carrier name; please confirm (Amazon's own fulfillment service counts as MCF for sure) |
| Freshness pills | When Flowmerce last read each store from Shopify ("Shopify direct"), last refreshed, and the hub's nightly Shopify check per store |
