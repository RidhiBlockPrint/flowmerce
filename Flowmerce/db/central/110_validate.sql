-- =====================================================================================
-- Flowmerce central database · 110 · validation (READ-ONLY; changes nothing)
-- Run after 000-090 to check structure, and after 105 to check the refresh from public.orders.
-- Every query returns rows to read; none of them writes.
-- =====================================================================================

-- A. Every expected table exists
select s.schema, s.tbl,
       to_regclass(s.schema || '.' || s.tbl) is not null as exists
from (values
  ('ops','stores'),('ops','people'),('ops','settings'),('ops','carriers'),('ops','carrier_aliases'),('ops','carrier_services'),
  ('ops','shipping_accounts'),('ops','status_map'),('ops','orders'),('ops','items'),('ops','shipments'),
  ('ops','stock'),('ops','events'),('ops','tracking_numbers'),('ops','tracking_scans'),
  ('ops','shipping_exceptions'),('ops','shipping_claims'),('ops','return_cases'),('ops','shipping_costs'),
  ('ops','rate_cards'),('ops','webhook_inbox'),('ops','sync_runs'),('ops','schema_migrations'),
  ('seo','users'),('seo','sessions'),('seo','brand_settings'),('seo','topics'),('seo','keywords'),
  ('seo','articles'),('seo','article_revisions'),('seo','review_notes'),('seo','publish_requests'),
  ('seo','workflow_runs'),('seo','automation_state'),('seo','integration_status'),('seo','gsc_page_daily'),
  ('seo','gsc_query_period'),('seo','ga4_page_daily'),('seo','products'),('seo','audit_log'),
  ('seo','imports'),('seo','ai_jobs'),('seo','ai_job_events')
) as s(schema, tbl)
order by exists, s.schema, s.tbl;

-- B. RLS is on for every table in ops and seo (expect zero rows)
select n.nspname, c.relname
from pg_class c join pg_namespace n on n.oid = c.relnamespace
where n.nspname in ('ops','seo') and c.relkind = 'r' and not c.relrowsecurity;

-- C. Write switches are OFF (expect all false)
select key, value from ops.settings where key in ('shopify_writes','amazon_writes','auto_mcf');

-- D. Refresh from public.orders: counts side by side
with f as (
  select f.value as f
  from public.orders p
  cross join lateral jsonb_array_elements(
    case when jsonb_typeof(p.raw->'fulfillments') = 'array' then p.raw->'fulfillments' else '[]'::jsonb end) f(value)
)
select 'Shopify fulfillments in public.orders.raw'          as what, count(*) from f
union all select '…complete (have a status)',                 count(*) from f where f ? 'status'
union all select '…incomplete (createdAt only; need re-fetch)', count(*) from f where not (f ? 'status')
union all select 'ops.orders',                                 count(*) from ops.orders where origin = 'shopify_sync'
union all select 'ops.shipments',                              count(*) from ops.shipments where origin = 'shopify_sync'
union all select 'ops.tracking_numbers',                       count(*) from ops.tracking_numbers where source = 'shopify'
union all select 'ops.tracking_scans (Shopify status words)',  count(*) from ops.tracking_scans where source = 'shopify'
union all select 'refresh runs',                               count(*) from ops.sync_runs where source = 'shopify' and kind = 'import';

-- E. Shopify's raw word vs Flowmerce's status (spot-check the mapping)
select upper(coalesce(tn.raw_status, '(none)')) as shopify_raw, tn.status as flowmerce_says, count(*)
from ops.tracking_numbers tn
where tn.source = 'shopify'
group by 1, 2 order by 3 desc;

-- F. Carrier spellings that fell through to "unknown" (add them to ops.carrier_aliases)
select coalesce(sh.carrier, '(blank)') as shopify_carrier_text, count(*)
from ops.shipments sh
where sh.origin = 'shopify_sync' and sh.carrier_id = 'unknown'
group by 1 order by 2 desc;

-- G. Delivered must always have a time; Shopify data must never confirm a delivery
select count(*) filter (where status = 'delivered' and delivered_at is null) as delivered_without_time,
       count(*) filter (where source = 'shopify' and delivery_confirmed)       as shopify_marked_confirmed
from ops.tracking_numbers;

-- H. Problem list after the refresh (diagnostics view)
select problem, severity, count(*) from ops.shipment_diagnostics group by 1, 2 order by 3 desc;

-- I. Random sample of 20 for the manual discrepancy report (compare against Shopify admin)
select o.name as order_name, sh.shopify_fulfillment_id, tn.tracking_number, tn.carrier_id,
       tn.status, tn.raw_status, tn.last_scan_at, tn.delivered_at, tn.source, tn.last_check_ok_at
from ops.tracking_numbers tn
join ops.shipments sh on sh.id = tn.shipment_id
join ops.orders o on o.id = sh.order_id
order by random() limit 20;
