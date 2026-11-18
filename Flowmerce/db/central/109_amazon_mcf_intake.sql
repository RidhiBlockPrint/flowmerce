-- 109: where the Amazon Multi-Channel Fulfillment (MCF) data goes, and the read-only view Flowmerce reads.
-- Safe to run more than once. Changes no existing table.
--
-- Amazon does not tell Shopify when it ships or delivers an MCF order. The team loads Amazon's own API answers here
-- (Selling Partner API, Fulfillment Outbound v2020-07-01), unchanged, as JSON:
--
--   ops.amazon_mcf_orders    one row per MCF order:   the `payload` of getFulfillmentOrder
--                            ({ fulfillmentOrder, fulfillmentOrderItems, fulfillmentShipments, ... })
--   ops.amazon_mcf_tracking  one row per package:     the `payload` of getPackageTrackingDetails
--                            ({ packageNumber, trackingNumber, carrierCode, currentStatus, trackingEvents, ... })
--
-- Load again whenever Amazon has news: insert ... on conflict (key) do update set payload = excluded.payload.
-- Flowmerce only reads ops.amazon_mcf_packages (below), which keeps NO name, street address, phone or e-mail.

create table if not exists ops.amazon_mcf_orders (
  seller_fulfillment_order_id text primary key,       -- fulfillmentOrder.sellerFulfillmentOrderId
  store        text references ops.stores(id),        -- RBP or CPC (optional; leave empty if not known)
  payload      jsonb not null,                         -- getFulfillmentOrder payload, unchanged
  fetched_at   timestamptz not null default now()
);

create table if not exists ops.amazon_mcf_tracking (
  package_number text primary key,                     -- packageNumber (as text)
  payload      jsonb not null,                         -- getPackageTrackingDetails payload, unchanged
  fetched_at   timestamptz not null default now()
);

create index if not exists amazon_mcf_tracking_number on ops.amazon_mcf_tracking ((upper(payload->>'trackingNumber')));

alter table ops.amazon_mcf_orders   enable row level security;
alter table ops.amazon_mcf_tracking enable row level security;
revoke all on ops.amazon_mcf_orders, ops.amazon_mcf_tracking from public, anon, authenticated;
grant select, insert, update, delete on ops.amazon_mcf_orders, ops.amazon_mcf_tracking to service_role;

-- One row per Amazon package (or per MCF order that has no package yet). No personal data.
-- When 111 (the MCF sheet table) exists, 111 owns this view (it adds the sheet's rows): 109 leaves it alone.
do $v$ begin
  if to_regclass('ops.amazon_mcf_sheet') is null then
    execute 'drop view if exists ops.amazon_mcf_packages';
    execute $q$create view ops.amazon_mcf_packages with (security_invoker = true) as
with o as (
  select m.seller_fulfillment_order_id                                   as sfo_id,
         m.store,
         m.payload->'fulfillmentOrder'                                   as fo,
         m.payload->'fulfillmentShipments'                               as shipments,
         m.payload->'fulfillmentOrderItems'                              as items,
         m.fetched_at
  from ops.amazon_mcf_orders m
),
pk as (   -- packages inside the order's shipments
  select o.sfo_id, s.shp, p.pkg
  from o
  cross join lateral jsonb_array_elements(case when jsonb_typeof(o.shipments) = 'array' then o.shipments else '[]'::jsonb end) s(shp)
  cross join lateral jsonb_array_elements(case when jsonb_typeof(s.shp->'fulfillmentShipmentPackage') = 'array'
                                               then s.shp->'fulfillmentShipmentPackage' else '[]'::jsonb end) p(pkg)
)
select o.sfo_id,
       o.store,
       o.fo->>'displayableOrderId'                                         as displayable_order_id,
       o.fo->>'fulfillmentOrderStatus'                                     as order_status,
       nullif(o.fo->>'receivedDate', '')::timestamptz                       as received_at,
       nullif(o.fo->>'statusUpdatedDate', '')::timestamptz                  as order_status_at,
       (select coalesce(jsonb_agg(jsonb_build_object('sku', i->>'sellerSku', 'qty', (i->>'quantity')::int)), '[]'::jsonb)
          from jsonb_array_elements(case when jsonb_typeof(o.items) = 'array' then o.items else '[]'::jsonb end) i) as items,
       pk.shp->>'amazonShipmentId'                                         as amazon_shipment_id,
       pk.shp->>'fulfillmentShipmentStatus'                                as shipment_status,
       nullif(pk.shp->>'shippingDate', '')::timestamptz                     as shipped_at,
       pk.pkg->>'packageNumber'                                            as package_number,
       coalesce(nullif(t.payload->>'trackingNumber', ''), nullif(pk.pkg->>'trackingNumber', '')) as tracking_number,
       coalesce(nullif(t.payload->>'carrierCode', ''), nullif(pk.pkg->>'carrierCode', ''))       as carrier_code,
       coalesce(nullif(t.payload->>'estimatedArrivalDate', ''), nullif(pk.pkg->>'estimatedArrivalDate', ''),
                nullif(pk.shp->>'estimatedArrivalDate', ''))::timestamptz   as estimated_arrival,
       t.payload->>'currentStatus'                                         as tracking_status,
       t.payload->>'currentStatusDescription'                              as tracking_status_text,
       case when t.payload->>'currentStatus' = 'DELIVERED'                -- delivered: the time of Amazon's latest event
            then coalesce(ev.last_event_at, t.fetched_at) end               as delivered_at,
       ev.last_event_at, ev.last_event_text, ev.last_event_city, ev.last_event_state,
       (select coalesce(jsonb_agg(jsonb_build_object('at', e->>'eventDate', 'code', e->>'eventCode',
                                                     'text', e->>'eventDescription',
                                                     'city', e->'eventAddress'->>'city', 'state', e->'eventAddress'->>'state',
                                                     'country', e->'eventAddress'->>'country')
                                  order by e->>'eventDate'), '[]'::jsonb)
          from jsonb_array_elements(case when jsonb_typeof(t.payload->'trackingEvents') = 'array' then t.payload->'trackingEvents' else '[]'::jsonb end) e) as events,
       greatest(o.fetched_at, t.fetched_at)                                as fetched_at
from o
left join pk on pk.sfo_id = o.sfo_id
left join ops.amazon_mcf_tracking t on t.package_number = pk.pkg->>'packageNumber'
left join lateral (
  select nullif(e->>'eventDate', '')::timestamptz as last_event_at, e->>'eventDescription' as last_event_text,
         e->'eventAddress'->>'city' as last_event_city, e->'eventAddress'->>'state' as last_event_state
  from jsonb_array_elements(case when jsonb_typeof(t.payload->'trackingEvents') = 'array' then t.payload->'trackingEvents' else '[]'::jsonb end) e
  order by nullif(e->>'eventDate', '')::timestamptz desc nulls last limit 1
) ev on true$q$;
  end if;
end $v$;

revoke all on ops.amazon_mcf_packages from public, anon, authenticated;
grant select on ops.amazon_mcf_packages to service_role;
do $$ begin
  if exists (select 1 from pg_roles where rolname = 'flowmerce_app') then
    execute 'grant select on ops.amazon_mcf_packages to flowmerce_app';
  end if;
end $$;

notify pgrst, 'reload schema';
