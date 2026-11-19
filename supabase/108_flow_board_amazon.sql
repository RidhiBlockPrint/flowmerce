-- 108: the Shipping board learns what Amazon (MCF) says.  Read-only view; safe to run more than once. Needs 107.
--
-- Amazon does not tell Shopify when it ships or delivers an MCF order, so many orders sent through Amazon still show
-- "unfulfilled" in Shopify. The hub keeps its own Amazon check per order in public.hub_orders (o->'pkgs', packages
-- with route 'mcf': Amazon's latest status, when, the tracking number Amazon gave, the MCF order id).
-- This view adds that to every row, and an order that Shopify shows as unfulfilled but Amazon has a package for
-- becomes one 'amazon' row per Amazon package instead of a 'not dispatched' order.
--
-- Columns are only ADDED at the end (amazon_*), so 107's columns keep their positions.
-- Coverage: hub_orders holds the hub's recent orders only (from about 12 Oct 2026); older orders have no Amazon data.

create or replace view ops.flow_board with (security_invoker = true) as
with hub as (
  select p.id,
         nullif(coalesce(p.raw->'shippingAddress'->>'city', p.raw->'shipping_address'->>'city'), '')               as ship_city,
         nullif(coalesce(p.raw->'shippingAddress'->>'provinceCode', p.raw->'shipping_address'->>'province_code'), '') as ship_state,
         coalesce(p.raw->>'note', '') ~* '\mdone\M'                                                                   as note_done
  from public.orders p
),
amz as (   -- one row per Amazon (MCF) package the hub knows
  select h.order_id::bigint                                                          as order_id,
         p.n                                                                         as pkg_no,
         nullif(p.pkg->'last'->>'text', '')                                          as amazon_status,
         case when (p.pkg->'last'->>'at') ~ '^\d+$'
              then to_timestamp((p.pkg->'last'->>'at')::bigint / 1000.0) end         as amazon_at,
         nullif(p.pkg->>'mcfId', '')                                                 as amazon_ref,
         nullif(p.pkg->'trk'->>0, '')                                                as amazon_tracking,
         case when (p.pkg->>'checkedAt') ~ '^\d+$'
              then to_timestamp((p.pkg->>'checkedAt')::bigint / 1000.0) end          as amazon_checked_at
  from public.hub_orders h
  cross join lateral jsonb_array_elements(case when jsonb_typeof(h.o->'pkgs') = 'array' then h.o->'pkgs' else '[]'::jsonb end)
             with ordinality as p(pkg, n)
  where p.pkg->>'route' = 'mcf'
    and h.order_id::text ~ '^\d+$'
),
amz_order as (   -- per order: the latest Amazon word, for rows that already have a Shopify fulfilment
  select distinct on (order_id) order_id, amazon_status, amazon_at, amazon_ref, amazon_tracking, amazon_checked_at
  from amz order by order_id, amazon_at desc nulls last
)
select 'tracking'::text                 as row_kind,
       t.tracking_id::text              as row_id,
       t.tracking_id,
       t.store, t.order_id, t.order_name, t.placed_at,
       t.shipment_id, t.kind,
       t.carrier_name, t.tracking_number, t.track_url,
       t.status, t.raw_status, t.source,
       -- dispatched = the earlier of Shopify's fulfilment and the carrier's first movement: a parcel Amazon sent on
       -- 5 Nov but entered in Shopify on 19 Nov (# RBP8183) is 14 days old, not 0
       least(t.shipped_at, tk.picked_up_at) as shipped_at, t.last_scan_at, t.last_scan_place, sh.last_scan_text,
       t.delivered_at, t.eta, t.last_check_ok_at,
       t.team_mark, t.team_mark_at,
       t.open_exceptions,
       o.total, o.currency, o.financial_status, o.fulfillment_status, o.cancelled_at,
       h.ship_city, h.ship_state, coalesce(h.note_done, false) as note_done,
       a.amazon_status, a.amazon_at, a.amazon_ref, a.amazon_tracking, a.amazon_checked_at
from ops.shipment_list t
join ops.shipments sh on sh.id = t.shipment_id
join ops.orders o     on o.id  = t.order_id
left join ops.tracking_numbers tk on tk.id = t.tracking_id
left join hub h       on h.id  = t.order_id
left join amz_order a on a.order_id = t.order_id

union all

-- A fulfilment with no tracking row of its own. Usually Shopify has no number for it. But two orders sent in ONE
-- parcel share one number, and the number's tracking row belongs to only one of them (e.g. CPC #6948 and #6949,
-- DHL 4503128464): the other order then reads that shared parcel's number, status and last scan, so it is neither
-- "no tracking number" nor stuck once the parcel is delivered. Dispatch time is the fulfilment's own time, not
-- when Flowmerce first stored the row.
select 'shipment', sh.id::text, null::uuid,
       sh.store, o.id, o.name, o.placed_at,
       sh.id, sh.kind,
       coalesce(c.name, nullif(sh.carrier, '')), tn.tracking_number, null::text,
       coalesce(tn.status, 'pending'), tn.raw_status, 'shopify'::text,
       least(coalesce(case when (sh.step_times->>'shipped') ~ '^\d{4}-' then (sh.step_times->>'shipped')::timestamptz end,
                      sh.created_at),
             case when (sh.step_times->>'transit') ~ '^\d{4}-' then (sh.step_times->>'transit')::timestamptz end),
       tn.last_scan_at, coalesce(sh.last_scan_place, tn.last_scan_place), coalesce(sh.last_scan_text, tn.last_scan_text),
       coalesce(sh.delivered_at, tn.delivered_at), coalesce(sh.eta, tn.eta), tn.last_check_ok_at,
       null::text, null::timestamptz,
       0,
       o.total, o.currency, o.financial_status, o.fulfillment_status, o.cancelled_at,
       h.ship_city, h.ship_state, coalesce(h.note_done, false),
       a.amazon_status, a.amazon_at, a.amazon_ref, a.amazon_tracking, a.amazon_checked_at
from ops.shipments sh
join ops.orders o on o.id = sh.order_id
left join ops.carriers c on c.id = sh.carrier_id
left join hub h on h.id = o.id
left join amz_order a on a.order_id = o.id
left join lateral (select t.tracking_number, t.status, t.raw_status, t.last_scan_at, t.delivered_at, t.eta,
                          t.last_check_ok_at, s2.last_scan_place, s2.last_scan_text
                     from ops.tracking_numbers t
                     join ops.shipments s2 on s2.id = t.shipment_id
                    where t.carrier_id = sh.carrier_id and t.store = sh.store
                      and t.tracking_number = any(sh.tracking)
                    order by (t.status = 'delivered') desc, t.updated_at desc
                    limit 1) tn on true
where sh.step not in ('cancelled')
  and not exists (select 1 from ops.tracking_numbers t where t.shipment_id = sh.id)

union all

-- Shopify: unfulfilled, no fulfilment. Amazon: has a package for it -> one row per Amazon package.
select 'amazon', o.id::text || ':' || az.pkg_no::text, null::uuid,
       o.store, o.id, o.name, o.placed_at,
       null::uuid, 'mcf'::text,
       case when az.amazon_tracking ~* '^TBA'                     then 'Amazon Logistics US'
            when az.amazon_tracking ~ '^(9[2-5]\d{18,24})$'       then 'USPS'
            when az.amazon_tracking ~* '^1Z'                      then 'UPS'
            when az.amazon_tracking is not null                   then 'Amazon (carrier not named)'
            else 'Amazon Logistics US' end,
       az.amazon_tracking,
       case when az.amazon_tracking ~* '^TBA'               then 'https://track.amazon.com/tracking/' || az.amazon_tracking
            when az.amazon_tracking ~ '^(9[2-5]\d{18,24})$' then 'https://tools.usps.com/go/TrackConfirmAction?tLabels=' || az.amazon_tracking
            when az.amazon_tracking ~* '^1Z'                then 'https://www.ups.com/track?tracknum=' || az.amazon_tracking end,
       'pending'::text, az.amazon_status, 'amazon'::text,
       case when az.amazon_status ~* 'shipped' then az.amazon_at end, null::timestamptz, null::text,
       'Amazon: ' || coalesce(az.amazon_status, 'request sent, no answer yet'),
       null::timestamptz, null::date, az.amazon_checked_at,
       null::text, null::timestamptz,
       0,
       o.total, o.currency, o.financial_status, o.fulfillment_status, o.cancelled_at,
       h.ship_city, h.ship_state, coalesce(h.note_done, false),
       az.amazon_status, az.amazon_at, az.amazon_ref, az.amazon_tracking, az.amazon_checked_at
from ops.orders o
join amz az on az.order_id = o.id
left join hub h on h.id = o.id
where o.placed_at > now() - interval '60 days'
  and o.cancelled_at is null
  and coalesce(o.fulfillment_status, '') not in ('FULFILLED', 'FULFILLMENT_NOT_REQUIRED')
  and not exists (select 1 from ops.shipments sh where sh.order_id = o.id)

union all

select 'order', o.id::text, null::uuid,
       o.store, o.id, o.name, o.placed_at,
       null::uuid, null::text,
       null::text, null::text, null::text,
       null::text, null::text, null::text,
       null::timestamptz, null::timestamptz, null::text, null::text,
       null::timestamptz, null::date, null::timestamptz,
       null::text, null::timestamptz,
       0,
       o.total, o.currency, o.financial_status, o.fulfillment_status, o.cancelled_at,
       h.ship_city, h.ship_state, coalesce(h.note_done, false),
       null::text, null::timestamptz, null::text, null::text, null::timestamptz
from ops.orders o
left join hub h on h.id = o.id
where o.placed_at > now() - interval '60 days'
  and o.cancelled_at is null
  and coalesce(o.fulfillment_status, '') not in ('FULFILLED', 'FULFILLMENT_NOT_REQUIRED')
  and not exists (select 1 from ops.shipments sh where sh.order_id = o.id)
  and not exists (select 1 from amz where amz.order_id = o.id);

revoke all on ops.flow_board from public, anon, authenticated;
grant select on ops.flow_board to service_role;
do $$ begin
  if exists (select 1 from pg_roles where rolname = 'flowmerce_app') then
    execute 'grant select on ops.flow_board to flowmerce_app';
  end if;
end $$;

notify pgrst, 'reload schema';
