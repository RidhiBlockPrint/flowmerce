-- 111: the team's Amazon MCF tracking sheet, copied into Supabase once a day by Flowmerce.
-- Safe to run more than once. Adds one table and widens the view ops.amazon_mcf_packages (109); changes no data.
--
-- The sheet ("Sellora MCF Tracking", tab Tracking) is refreshed from Amazon every morning around 04:30-05:00 IST.
-- Flowmerce reads it at 09:00 IST through its Google service account and upserts every row here (key: MCF id +
-- parcel). Rows are never deleted: an MCF order that later leaves the sheet keeps its last known state, and
-- synced_at says when the sheet last showed it. Each sync is logged in ops.sync_runs (source 'amazon', kind 'import').
--
-- No personal data: no customer name (the sheet's Order column sometimes holds one; only an order number is kept),
-- no street address, no link. last_event_city / _state are the city and state of Amazon's last scan.

create table if not exists ops.amazon_mcf_sheet (
  sfo_id               text not null,                     -- MCF id (seller fulfillment order id)
  package_key          text not null default '',          -- Parcel (Amazon package number), '' until Amazon packs it
  store                text references ops.stores(id),    -- RBP (Ridhi) or CPC
  order_number         text,                               -- Shopify order number digits; null when the sheet has none
  order_status         text,                               -- Amazon order status: Complete, Processing, Planning, ...
  received_on          date,
  speed                text,                               -- Standard / Expedited / Priority
  tracking_number      text,
  carrier              text,
  shipped_on           date,
  arrives_by           date,
  tracking_status      text,                               -- DELIVERED, IN_TRANSIT, OUT_FOR_DELIVERY, DELAYED, ...
  tracking_status_text text,                               -- Amazon's last scan text
  delivered_at         timestamptz,
  last_event_at        timestamptz,
  last_event_city      text,
  last_event_state     text,
  sheet_flag           text,                               -- the sheet's own Flag column
  checked_at           timestamptz,                        -- when the team's tool last asked Amazon
  first_synced_at      timestamptz not null default now(),
  synced_at            timestamptz not null default now(), -- the last sync that saw this row in the sheet
  primary key (sfo_id, package_key)
);

create index if not exists amazon_mcf_sheet_tracking on ops.amazon_mcf_sheet (upper(tracking_number));
create index if not exists amazon_mcf_sheet_order on ops.amazon_mcf_sheet (store, order_number);

alter table ops.amazon_mcf_sheet enable row level security;
revoke all on ops.amazon_mcf_sheet from public, anon, authenticated;
grant select, insert, update, delete on ops.amazon_mcf_sheet to service_role;

-- 109's view, plus the sheet's rows (an MCF order loaded from Amazon's API, in 109's tables, wins over the sheet).
-- Two columns are added at the end: source ('amazon_api' / 'sheet') and synced_at.
drop view if exists ops.amazon_mcf_packages;   -- recreated below (109 and 111 may be re-run in any order)
create view ops.amazon_mcf_packages with (security_invoker = true) as
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
       greatest(o.fetched_at, t.fetched_at)                                as fetched_at,
       'amazon_api'::text                                                  as source,
       greatest(o.fetched_at, t.fetched_at)                                as synced_at
from o
left join pk on pk.sfo_id = o.sfo_id
left join ops.amazon_mcf_tracking t on t.package_number = pk.pkg->>'packageNumber'
left join lateral (
  select nullif(e->>'eventDate', '')::timestamptz as last_event_at, e->>'eventDescription' as last_event_text,
         e->'eventAddress'->>'city' as last_event_city, e->'eventAddress'->>'state' as last_event_state
  from jsonb_array_elements(case when jsonb_typeof(t.payload->'trackingEvents') = 'array' then t.payload->'trackingEvents' else '[]'::jsonb end) e
  order by nullif(e->>'eventDate', '')::timestamptz desc nulls last limit 1
) ev on true

union all

select s.sfo_id,
       s.store,
       s.order_number                                                      as displayable_order_id,
       s.order_status,
       (s.received_on::timestamp at time zone 'UTC') as received_at,
       null::timestamptz                                                   as order_status_at,
       '[]'::jsonb                                                         as items,
       null::text                                                          as amazon_shipment_id,
       case when s.tracking_number is not null or s.shipped_on is not null then 'SHIPPED' end as shipment_status,
       (s.shipped_on::timestamp at time zone 'UTC') as shipped_at,
       nullif(s.package_key, '')                                           as package_number,
       s.tracking_number,
       s.carrier                                                           as carrier_code,
       (s.arrives_by::timestamp at time zone 'UTC') as estimated_arrival,
       s.tracking_status,
       s.tracking_status_text,
       s.delivered_at,
       s.last_event_at,
       s.tracking_status_text                                              as last_event_text,
       s.last_event_city,
       s.last_event_state,
       '[]'::jsonb                                                         as events,
       s.checked_at                                                        as fetched_at,
       'sheet'::text                                                       as source,
       s.synced_at
from ops.amazon_mcf_sheet s
where not exists (select 1 from ops.amazon_mcf_orders m where m.seller_fulfillment_order_id = s.sfo_id)
  -- the "not packed yet" row of an MCF order that has since got its parcel(s) is history, not a parcel
  and not (s.package_key = '' and exists (select 1 from ops.amazon_mcf_sheet x where x.sfo_id = s.sfo_id and x.package_key <> ''));

revoke all on ops.amazon_mcf_packages from public, anon, authenticated;
grant select on ops.amazon_mcf_packages to service_role;
do $$ begin
  if exists (select 1 from pg_roles where rolname = 'flowmerce_app') then
    execute 'grant select on ops.amazon_mcf_packages to flowmerce_app';
    execute 'grant select on ops.amazon_mcf_sheet to flowmerce_app';
  end if;
end $$;

notify pgrst, 'reload schema';
