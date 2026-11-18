# Shipping — what we fail to extract, and what the schema needs

**Date:** 2026-11-17 · **Database checked:** the live Supabase project in `Flowmerce/.env` (read-only, counts and key names only, no customer data read)
**Applies to:** the `public` schema (stores, orders, items, shipments, tracking_numbers, …)

---

## 1. The short version

1. **Flowmerce Shipping reads the wrong tables.** `ops.refresh_from_tracker()` expects an older "Delayed Orders Tracker" layout (`public.shipments.carrier_name`, `public.order_checks`, `public.manual_status`). Those don't exist in this database. All 3 refresh runs so far failed with `column s.carrier_name does not exist`, so Flowmerce shows nothing.
2. **Your `shipments`, `tracking_numbers` and `tracking_scans` tables are empty (0 rows).** All shipping facts are still inside `orders.raw → fulfillments` (the Shopify order JSON) and are never copied out.
3. **75% of that fulfillment JSON is incomplete.** 5,051 of 6,741 fulfillments (orders placed Aug–Nov 2026, mostly Sept–Oct) were stored with **only `createdAt`**: no carrier, tracking number, status or line items. Only the 1,690 fulfillments that later arrived by webhook are complete.
4. **No delivery date or scan history is captured anywhere.** Shopify reports `delivered` for 860 fulfillments, but no `orders.stage` is ever `delivered` (5,376 stay `shipped`). There is no delivered time, no estimated delivery date and no scans.
5. **Carrier names don't match the carrier list.** 5 carriers are set up, but the data uses 10 spellings (USPS, UPS, "Amazon Logistics", "DHL eCommerce", …).

To fix this, you need: **a fresh fulfillment pull from Shopify**, **3 more webhook topics**, **a job that writes `shipments` + `tracking_numbers` from Shopify fulfillments**, plus the new columns and tables below.

---

## 2. Evidence (measured 2026-11-17)

| What | Count |
|---|---|
| `orders` | 6,507 (RBP 4,222 · CPC 2,285) |
| `orders.fulfillment_status` | FULFILLED 5,377 · UNFULFILLED 931 · PARTIALLY_FULFILLED 122 · FULFILLMENT_NOT_REQUIRED 61 · IN_PROGRESS 10 · other 6 |
| `orders.stage` | shipped 5,376 · new 1,072 · cancelled 59 · **delivered 0 · transit 0** |
| Fulfillment objects inside `orders.raw` | 6,741 on 5,504 orders |
| …stored with only `createdAt` (stub) | **5,051 (75%)**: Aug 11 · Sep 2,706 · Oct 2,294 · Nov 40 |
| …complete | 1,690 (mostly Oct–Nov, i.e. arrived by webhook) |
| Fulfillments with a tracking number | 1,670 (27 have 2, 9 have 3+) |
| `tracking_company` (complete ones) | DHL Express 740 · Amazon Logistics 417 · USPS 165 · Amazon Logistics US 157 · FedEx 153 · UPS 28 · "Amazon shipping + Amazon MCF" 6 · Other 2 · DHL eCommerce 1 · Amazon Fulfillment 1 |
| Shopify `shipment_status` | delivered 860 · in_transit 192 · confirmed 153 · failure 5 · delayed 2 · out_for_delivery 2 · attempted_delivery 2 · returning_to_sender 1 · **blank 5,524** |
| `shipments` / `tracking_numbers` / `tracking_scans` | **0 / 0 / 0** |
| `shipping_exceptions` / `return_cases` / `shipping_costs` / `rate_cards` | 0 / 0 / 0 / 0 |
| `events` | 26,294: **0 linked to a shipment**. Alert kinds include `delivery` 81, `carrier_problem` 40, `late` 526 |
| `webhook_inbox` topics | only `orders/updated` 17,360 · `orders/create` 1,170 · `orders/paid` 1,164 · `orders/fulfilled` 1,045 · `orders/cancelled` 7 |
| Orders with refunds in raw / with `returns` | 70 / 0 |
| Orders with `total_weight` | 67 |
| `carriers` | dhl, fedex, amazon_logistics_us, shiprocket, delhivery (5) |

---

## 3. What we fail to extract — gap by gap

Priority: **P1** = Shipping screens stay empty or wrong without it · **P2** = accuracy · **P3** = later modules (costs, claims, returns).

| # | Gap | Where the data should come from | Fix | Pri |
|---|---|---|---|---|
| G1 | 5,051 fulfillments are stubs (only `createdAt`). **Last 60 days: solved by Flowmerce reading Shopify directly (2026-11-17)**; older ones still need `read_all_orders` or the hub | Shopify Admin GraphQL `order.fulfillments` | One-time backfill: re-fetch every order with stub fulfillments (or all orders since 2026-08-01) asking for the full fulfillment fields (§5) | P1 |
| G2 | Nothing copies fulfillments into `shipments` / `tracking_numbers` | `orders.raw → fulfillments` | A repeatable job (SQL function or the sync worker) that upserts 1 `shipments` row per Shopify fulfillment and 1 `tracking_numbers` row per tracking number | P1 |
| G3 | Flowmerce refresh reads non-existent tracker tables | n/a | **Done 2026-11-17:** replaced by `ops.refresh_from_shopify_orders()` (`supabase/105_refresh_from_shopify_orders.sql`), which reads `public.orders.raw → fulfillments`. Needs to be run once in the Supabase SQL Editor | P1 |
| G4 | No `fulfillments/*` webhooks, so status changes after shipping are only caught when Shopify also fires `orders/updated` | Shopify webhooks | Subscribe `fulfillments/create`, `fulfillments/update`, `fulfillment_events/create` | P1 |
| G5 | No delivered time, no estimated delivery date | GraphQL `Fulfillment.deliveredAt`, `estimatedDeliveryAt`, `inTransitAt` | New columns on `shipments` / fill `tracking_numbers.delivered_at`, `eta`, `picked_up_at` | P1 |
| G6 | `orders.stage` never reaches `transit` / `delivered` | derived from shipments | Stage rule: all shipments delivered → `delivered`; any in transit / out / exception → `transit`; also set new `orders.delivered_at` | P1 |
| G7 | Carrier spellings don't match `carriers` (USPS, UPS, Amazon Logistics, DHL eCommerce, Amazon MCF, "Other", blank) | `tracking_company` | New `carrier_aliases` table + missing carrier rows; unmatched → `unknown`, never guessed | P1 |
| G8 | Shopify status words have no agreed mapping | `shipment_status` / fulfillment event `status` | New `status_map` table + a defined status list for `tracking_numbers.status` | P1 |
| G9 | No scan history (`tracking_scans` empty) | GraphQL `Fulfillment.events` (happenedAt, status, message, city, province, country) and/or a tracking aggregator | Write one `tracking_scans` row per fulfillment event; `external_id` = Shopify event id | P2 |
| G10 | "Delivered" is only Shopify's word, never carrier-confirmed | carrier / aggregator | `tracking_numbers.delivery_confirmed` + `status_source`; Shopify alone never sets it true | P2 |
| G11 | Multi-parcel and multi-number fulfillments (36 have 2+ numbers) | `tracking_numbers[]`, `tracking_urls[]` | One `tracking_numbers` row each; keep each URL | P2 |
| G12 | Which items went in which parcel | `Fulfillment.fulfillmentLineItems` | Fill `shipments.items` (jsonb `[{item_id, qty}]`); keep `items.fulfilled_qty` in step | P2 |
| G13 | Team marks (lost / delivered / failed) have no home | Flowmerce + hub | `tracking_numbers.team_mark*` columns; lost/failed opens a `shipping_exceptions` row | P2 |
| G14 | Alerts not linked to parcels (0 of 26,294 events have `shipment_id`) | alert writer | Set `events.shipment_id` when an alert is about a parcel (`delivery`, `carrier_problem`, `late` after shipping) | P2 |
| G15 | Tracking freshness unknown (when last checked, did it fail) | sync job | `tracking_numbers.last_checked_at`, `last_check_ok_at`, `last_check_error`, `check_attempts` | P2 |
| G16 | Fulfilled-by-Amazon orders (service `amazon-fulfillment`, 204) not tied to MCF | `Fulfillment.service`, MCF ids | Fill `shipments.kind = 'mcf'` and `shipments.mcf_id`; link `shipping_accounts` | P2 |
| G17 | Returns never captured (`raw.returns` empty; 70 refunded orders) | GraphQL `order.returns` (needs `read_returns` scope) | Fill `return_cases`; return label tracking → `tracking_numbers` | P3 |
| G18 | No weight or cost per parcel (weight on 67 orders only) | label provider / carrier invoices | `shipments.weight_kg`, `shipping_costs`, `rate_cards` | P3 |
| G19 | Shipping method the customer paid for not linked to the service used | `orders.raw → shipping_lines` (Express 1,140 · Standard 777 · …) | New `orders.shipping_method` to compare promise vs actual | P3 |

---

## 4. Schema additions (to `public`)

### 4.1 New columns on existing tables

| Table | Column | Type | Why |
|---|---|---|---|
| `orders` | `delivered_at` | timestamptz | When the last shipment was delivered (G6) |
| `orders` | `shipping_method` | text | Customer-chosen shipping line title, e.g. Express (G19) |
| `shipments` | `shopify_status` | text | Fulfillment status as Shopify gives it: `success` / `cancelled` / `pending` |
| `shipments` | `shopify_shipment_status` | text | Raw Shopify carrier word (`in_transit`, `delivered`, …), stored as-is (G8) |
| `shipments` | `carrier_raw` | text | Exact `tracking_company` text before mapping (G7) |
| `shipments` | `service_raw` | text | Shopify `service` (`manual`, `amazon-fulfillment`) (G16) |
| `shipments` | `shipped_at` | timestamptz | Fulfillment created time |
| `shipments` | `in_transit_at` | timestamptz | `Fulfillment.inTransitAt` (G5) |
| `shipments` | `eta` | timestamptz | `Fulfillment.estimatedDeliveryAt` (G5) |
| `shipments` | `delivered_at` | timestamptz | `Fulfillment.deliveredAt` (G5) |
| `shipments` | `last_scan_at` / `last_scan_place` / `last_scan_text` | timestamptz / text / text | Latest event, for the board without joining scans |
| `shipments` | `source` | text | `shopify_webhook` / `shopify_backfill` / `manual`, so you can tell where each row came from |
| `tracking_numbers` | `tracking_url` | text | Shopify tracking URL (G11) |
| `tracking_numbers` | `raw_status` | text | Last raw status word (G8) |
| `tracking_numbers` | `status_source` | text | `shopify` / `carrier` / `aggregator` / `person` (G10) |
| `tracking_numbers` | `delivery_confirmed` | boolean, default false | True only from a carrier or aggregator (G10) |
| `tracking_numbers` | `last_checked_at` / `last_check_ok_at` / `last_check_error` / `check_attempts` | timestamptz / timestamptz / text / int default 0 | Freshness (G15) |
| `tracking_numbers` | `team_mark` / `team_mark_by` / `team_mark_at` / `team_note` | text / text / timestamptz / text | Team marks, kept apart from the carrier status (G13) |
| `tracking_scans` | `mapped_rule` | text | Which `status_map` row produced `status` |
| `stores` | `legacy_code` | text | `hub_docs` uses `Ridhi_…` where the store id is `RBP` |
| `sync_runs` | `lock_key` | text, unique while running | Stops two refreshes running at once |

### 4.2 New tables

**`carrier_aliases`**: maps any spelling to one carrier.
`alias text primary key` (lower-cased), `carrier_id text not null references carriers(id)`, `note text`.

**`status_map`**: maps a raw status word to the one status list.
`source text`, `carrier_id text` (`'*'` = any), `raw_status text` (lower-case), `status text`, `is_terminal boolean`, `confirms_delivery boolean`, `note text`; primary key `(source, carrier_id, raw_status)`.

### 4.3 Allowed words (add as CHECK constraints)

- `tracking_numbers.status`: `pending`, `info_received`, `in_transit`, `out_for_delivery`, `delivered`, `exception`, `returned`, `expired`
- `shipments.step`: agree one list with the hub (the hub already uses `step`, `step_times`, `step_limits`). Proposed list: `requested`, `packed`, `label`, `shipped`, `transit`, `out`, `delivered`, `exception`, `returned`, `cancelled`

### 4.4 Reference rows to add

**Carriers** (missing): `usps`, `ups`, `dhl_ecommerce`, `amazon_mcf`, `unknown`.

**Carrier aliases**, from the spellings found in the data:

| alias (lower-case) | carrier_id |
|---|---|
| dhl express | dhl |
| fedex | fedex |
| usps | usps |
| ups | ups |
| dhl ecommerce | dhl_ecommerce |
| amazon logistics | amazon_logistics_us |
| amazon logistics us | amazon_logistics_us |
| amazon shipping + amazon mcf | amazon_mcf |
| amazon fulfillment | amazon_mcf |
| other | unknown |
| (blank) | unknown |

**Status map** (`source = 'shopify'`, `carrier_id = '*'`), covering every word found in the data plus Shopify's other documented ones:

| raw_status | status | terminal | confirms delivery | note |
|---|---|---|---|---|
| label_printed, label_purchased | pending | no | no | Label only |
| confirmed | info_received | no | no | 153 parcels: do **not** show as in transit |
| picked_up, carrier_picked_up, in_transit | in_transit | no | no | |
| out_for_delivery, ready_for_pickup | out_for_delivery | no | no | |
| attempted_delivery | exception | no | no | Opens amber exception |
| delayed | exception | no | no | Opens amber exception |
| failure | exception | no | no | Opens red exception |
| returning_to_sender, returned | returned | yes | no | |
| delivered | delivered | yes | **no** | Shopify's word only; not carrier-confirmed |
| (blank) | pending | no | no | No carrier evidence yet |

---

## 5. Shopify data to request (fixes G1, G5, G9, G11, G12)

GraphQL fields per order, for both the backfill and the regular sync:

```graphql
fulfillments(first: 20) {
  id legacyResourceId name status displayStatus createdAt updatedAt
  inTransitAt estimatedDeliveryAt deliveredAt
  service { serviceName handle }
  location { id name }
  trackingInfo(first: 10) { company number url }
  fulfillmentLineItems(first: 50) { nodes { quantity lineItem { id sku } } }
  events(first: 50, sortKey: HAPPENED_AT) {
    nodes { id status message happenedAt city province country zip estimatedDeliveryAt }
  }
}
```

Plus `shippingLines(first: 5) { nodes { title code source } }` for G19, and later `returns` (needs the `read_returns` scope) for G17.

**Webhooks to add:** `fulfillments/create`, `fulfillments/update`, `fulfillment_events/create`, both stores. They land in `webhook_inbox` like the existing topics.

**Backfill scope:** the 5,051 stub fulfillments. Pick them with: orders where `raw → fulfillments` has an element with no `status` key.

---

## 6. Extraction rules (the job behind G2 / G6)

1. **One `shipments` row per Shopify fulfillment.** `id = 'SF-' || fulfillment legacy id` (or your existing id scheme), `shopify_fulfillment_id` = Shopify id, `seq` = order of creation within the order.
2. **One `tracking_numbers` row per tracking number** on that fulfillment. Carrier through `carrier_aliases`; unmatched → `unknown`.
3. **Status** through `status_map`. Keep the raw word in `raw_status` / `shopify_shipment_status`. A `delivered` with no `deliveredAt` stays `out_for_delivery`/`in_transit`, never invented.
4. **Scans:** one `tracking_scans` row per Shopify fulfillment event (`external_id = 'shopify:' || event id`), so re-runs never duplicate.
5. **Cancelled fulfillments** (`status = cancelled`, 34 found): keep the row, set `step = 'cancelled'`, `tracking_numbers.active = false`.
6. **Order stage:** derived from its shipments (G6). Never overwrite a person's `on_hold`.
7. **Exceptions:** `exception`/`returned` statuses and team marks `lost`/`failed` open one `shipping_exceptions` row each (no duplicates while open). A later carrier-confirmed delivery closes carrier-raised ones.
8. **Never write `delivery_confirmed = true` from Shopify data alone.**

---

## 7. Decisions needed

1. **Which schema Flowmerce uses.** For now Flowmerce *reads* `public` and keeps its derived copy in `ops` (G3 done), so nothing in the hub's tables is touched. Once the hub fills `public.shipments` / `tracking_numbers` itself (G2), the refresh can copy from those instead, or Flowmerce can read them directly and `ops` can be retired.
2. **Who runs the extraction.** It can run as a SQL function inside Supabase (like the current refresh, on a schedule) or in the same worker that already writes `orders` and `webhook_inbox`. The worker is the better home for the Shopify backfill and webhooks; a SQL function is fine for `raw → shipments`.
3. **Carrier-confirmed delivery.** Shopify alone can't confirm delivery. Decide whether to add a tracking aggregator (the schema already has `tracking_numbers.aggregator_id` and `shipping_accounts`) or accept "Shopify-reported" as final.
4. **`shipments.step` word list.** Agree it with the hub before adding the CHECK.

---

## Appendix A — draft SQL for §4 (not run; review first)

```sql
-- 4.1 columns
alter table public.orders           add column if not exists delivered_at timestamptz,
                                    add column if not exists shipping_method text;
alter table public.shipments        add column if not exists shopify_status text,
                                    add column if not exists shopify_shipment_status text,
                                    add column if not exists carrier_raw text,
                                    add column if not exists service_raw text,
                                    add column if not exists shipped_at timestamptz,
                                    add column if not exists in_transit_at timestamptz,
                                    add column if not exists eta timestamptz,
                                    add column if not exists delivered_at timestamptz,
                                    add column if not exists last_scan_at timestamptz,
                                    add column if not exists last_scan_place text,
                                    add column if not exists last_scan_text text,
                                    add column if not exists source text;
alter table public.tracking_numbers add column if not exists tracking_url text,
                                    add column if not exists raw_status text,
                                    add column if not exists status_source text,
                                    add column if not exists delivery_confirmed boolean not null default false,
                                    add column if not exists last_checked_at timestamptz,
                                    add column if not exists last_check_ok_at timestamptz,
                                    add column if not exists last_check_error text,
                                    add column if not exists check_attempts integer not null default 0,
                                    add column if not exists team_mark text
                                      check (team_mark in ('delivered','lost','failed','in_transit')),
                                    add column if not exists team_mark_by text,
                                    add column if not exists team_mark_at timestamptz,
                                    add column if not exists team_note text;
alter table public.tracking_scans   add column if not exists mapped_rule text;
alter table public.stores           add column if not exists legacy_code text;
alter table public.sync_runs        add column if not exists lock_key text;
create unique index if not exists sync_runs_one_running
  on public.sync_runs (lock_key) where status = 'running' and lock_key is not null;

-- 4.2 tables
create table if not exists public.carrier_aliases (
  alias      text primary key check (alias = lower(btrim(alias))),
  carrier_id text not null references public.carriers(id),
  note       text
);
create table if not exists public.status_map (
  source            text not null,
  carrier_id        text not null default '*',
  raw_status        text not null check (raw_status = lower(raw_status)),
  status            text not null check (status in ('pending','info_received','in_transit','out_for_delivery',
                                                     'delivered','exception','returned','expired')),
  is_terminal       boolean not null default false,
  confirms_delivery boolean not null default false,
  note              text,
  primary key (source, carrier_id, raw_status)
);

-- 4.3 allowed tracking statuses (table is empty, so this is safe now)
alter table public.tracking_numbers drop constraint if exists tracking_numbers_status_check;
alter table public.tracking_numbers add constraint tracking_numbers_status_check
  check (status in ('pending','info_received','in_transit','out_for_delivery','delivered','exception','returned','expired'));

-- 4.4 reference rows
insert into public.carriers (id, name, kind, shopify_name, tracking_slug) values
  ('usps','USPS','courier','USPS','usps'),
  ('ups','UPS','courier','UPS','ups'),
  ('dhl_ecommerce','DHL eCommerce','courier','DHL eCommerce','dhl-ecommerce'),
  ('amazon_mcf','Amazon MCF','marketplace',null,'amazon'),
  ('unknown','Unknown carrier','courier',null,null)
on conflict (id) do nothing;

insert into public.carrier_aliases (alias, carrier_id) values
  ('dhl express','dhl'), ('fedex','fedex'), ('usps','usps'), ('ups','ups'),
  ('dhl ecommerce','dhl_ecommerce'),
  ('amazon logistics','amazon_logistics_us'), ('amazon logistics us','amazon_logistics_us'),
  ('amazon shipping + amazon mcf','amazon_mcf'), ('amazon fulfillment','amazon_mcf'),
  ('other','unknown'), ('','unknown')
on conflict (alias) do nothing;

insert into public.status_map (source, carrier_id, raw_status, status, is_terminal, confirms_delivery, note) values
  ('shopify','*','label_printed','pending',false,false,'Label only'),
  ('shopify','*','label_purchased','pending',false,false,'Label only'),
  ('shopify','*','confirmed','info_received',false,false,'Carrier has the data, not the parcel'),
  ('shopify','*','picked_up','in_transit',false,false,null),
  ('shopify','*','carrier_picked_up','in_transit',false,false,null),
  ('shopify','*','in_transit','in_transit',false,false,null),
  ('shopify','*','out_for_delivery','out_for_delivery',false,false,null),
  ('shopify','*','ready_for_pickup','out_for_delivery',false,false,'Waiting at pickup point'),
  ('shopify','*','attempted_delivery','exception',false,false,'Delivery attempt failed'),
  ('shopify','*','delayed','exception',false,false,null),
  ('shopify','*','failure','exception',false,false,null),
  ('shopify','*','returning_to_sender','returned',true,false,null),
  ('shopify','*','returned','returned',true,false,null),
  ('shopify','*','delivered','delivered',true,false,'Shopify says delivered; not carrier-confirmed')
on conflict do nothing;

-- RLS: new tables follow the same policy as the other public tables (add before exposing them).
```
