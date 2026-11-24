# db/central — the Flowmerce central database (Supabase)

**Easiest way:** open Supabase → SQL Editor, paste **`supabase_setup.sql`**, run it. Then add `ops` and `cro` under
Project Settings → Data API → Exposed schemas. Full guide: `docs/operations/shipping-supabase-setup.md`.

`supabase_setup.sql` is files 000–114 below joined in order (except 095 and 110) (generated; edit the numbered files, then rebuild it).
Every file is safe to run more than once, and none of them writes to the hub's `public.*` tables.

| File | What it does |
|---|---|
| `000_extensions_and_schemas.sql` | Schemas `ops` and `seo`, the `updated_at` helper, the migrations log |
| `010_ops_setup.sql` | stores, people, settings, carriers, **carrier_aliases**, carrier_services, shipping_accounts, **status_map** |
| `020_ops_orders_shipments.sql` | orders, items, shipments, stock, events |
| `030_ops_tracking.sql` | tracking_numbers (with team mark + freshness columns), tracking_scans, latest-status function, exceptions, claims, returns |
| `040_ops_costs_and_feeds.sql` | shipping_costs, rate_cards, webhook_inbox, sync_runs (duplicate-run lock) |
| `060_ops_views.sql` | design views + feed_freshness, shipment_diagnostics, diagnostics_list/summary, **shipment_list**, shipping_summary |
| `070_seo_tables.sql` | the 20 SEO tables, ported 1:1 from SQLite (SEO still runs on SQLite until Phase 4) |
| `080_security.sql` | RLS on everywhere; rights for Supabase `service_role` only; none for anon/authenticated |
| `090_seed.sql` | stores, carriers + every spelling seen in the live data, services, settings (write switches OFF), status map |
| `105_refresh_from_shopify_orders.sql` | `ops.refresh_from_shopify_orders()` (repeatable, reads `public.orders` / `public.sync_runs`, never writes `public`) and `ops.set_team_mark()`. Replaces the removed `100_tracker_refresh.sql` |
| `095_optional_supabase_auth.sql` | Phase 5 only (sign-in). Not in `supabase_setup.sql` |
| `110_validate.sql` | Read-only checks: A–C after setup, D–I after the first refresh |
| `112_cro.sql` | CRO module: schema `cro` with store_settings, alarm_rules (editable thresholds), alerts (no duplicate open alerts), change_log, view `daily_sales` from `ops.orders`; default rules for RBP and CPC. Reads `ops` only. Run 2026-11-19 |
| `113_cro_orders.sql` | CRO's own order copy: `cro.orders` (money breakdown), `cro.order_lines`, `cro.sync_state`; functions `save_orders`, `begin_sync`/`end_sync` (per-store lock), `delete_change_log`; drops 112's `daily_sales` view. **Not yet run** |
| `114_cro_tracking.sql` | CRO recommendation status, experiments log, free-shipping amount |
| `115_ads.sql` | Ads module: schema `ads` with accounts (+ sync state), campaigns, ad_sets, ads, daily (one row per ad per account day), fx_rates (INR starts at 88), rules, action_status, action_history; functions begin/end_sync, replace_daily, save_lifetime, reopen_action, account_days, ad_windows, store_days (reads `cro.orders`). Not in `supabase_setup.sql`: run it on its own, then expose `ads`. **Not yet run** |
| `rollback/115_rollback_ads.sql` | Removes `ads` only; refuses while team-recorded Ads data exists (rules, action marks, rates). **Destructive, owner approval** |
| `rollback/999_rollback_central.sql` | Removes `ops` + `seo`; refuses while real data exists. **Destructive, owner approval** |
| `rollback/112_rollback_cro.sql` | Removes `cro` only (112 + 113); refuses while team-recorded CRO data exists. **Destructive, owner approval** |

Checked on 2026-11-17 against the live database: it has no tracker tables (`order_checks`, `manual_status`);
shipping data lives in `public.orders.raw → fulfillments`. `105` was tested on a local PostgreSQL 17 with a copy of
that data (fresh install and upgrade over the earlier setup; second run changes nothing).