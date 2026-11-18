-- 107: one row per parcel (or open order) for the Shipping page.  Read-only view; safe to run more than once.
--
-- Three kinds of row:
--   tracking  every tracking number Flowmerce knows (ops.shipment_list), delivered ones included
--   shipment  a fulfilment that has no tracking number yet (dispatched without a number)
--   order     an order placed in the last 60 days that is not cancelled and has no fulfilment yet (not dispatched)
--
-- Each row carries the order's value, payment state and cancel time (ops.orders), and from the hub's order copy
-- (public.orders.raw) only the destination CITY and STATE and a yes/no "the order note says DONE".
-- The note text, names, street addresses, e-mails and phone numbers are never selected.

create or replace view ops.flow_board with (security_invoker = true) as
with hub as (
  select p.id,
         nullif(coalesce(p.raw->'shippingAddress'->>'city', p.raw->'shipping_address'->>'city'), '')               as ship_city,
         nullif(coalesce(p.raw->'shippingAddress'->>'provinceCode', p.raw->'shipping_address'->>'province_code'), '') as ship_state,
         coalesce(p.raw->>'note', '') ~* '\mdone\M'                                                                   as note_done
  from public.orders p
)
select 'tracking'::text                 as row_kind,
       t.tracking_id::text              as row_id,
       t.tracking_id,
       t.store, t.order_id, t.order_name, t.placed_at,
       t.shipment_id, t.kind,
       t.carrier_name, t.tracking_number, t.track_url,
       t.status, t.raw_status, t.source,
       t.shipped_at, t.last_scan_at, t.last_scan_place, sh.last_scan_text,
       t.delivered_at, t.eta, t.last_check_ok_at,
       t.team_mark, t.team_mark_at,
       t.open_exceptions,
       o.total, o.currency, o.financial_status, o.fulfillment_status, o.cancelled_at,
       h.ship_city, h.ship_state, coalesce(h.note_done, false) as note_done
from ops.shipment_list t
join ops.shipments sh on sh.id = t.shipment_id
join ops.orders o     on o.id  = t.order_id
left join hub h       on h.id  = t.order_id

union all

select 'shipment', sh.id::text, null::uuid,
       sh.store, o.id, o.name, o.placed_at,
       sh.id, sh.kind,
       coalesce(c.name, nullif(sh.carrier, '')), null::text, null::text,
       'pending'::text, null::text, 'shopify'::text,
       sh.created_at, null::timestamptz, sh.last_scan_place, sh.last_scan_text,
       sh.delivered_at, sh.eta, null::timestamptz,
       null::text, null::timestamptz,
       0,
       o.total, o.currency, o.financial_status, o.fulfillment_status, o.cancelled_at,
       h.ship_city, h.ship_state, coalesce(h.note_done, false)
from ops.shipments sh
join ops.orders o on o.id = sh.order_id
left join ops.carriers c on c.id = sh.carrier_id
left join hub h on h.id = o.id
where sh.step not in ('cancelled')
  and not exists (select 1 from ops.tracking_numbers t where t.shipment_id = sh.id)

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
       h.ship_city, h.ship_state, coalesce(h.note_done, false)
from ops.orders o
left join hub h on h.id = o.id
where o.placed_at > now() - interval '60 days'
  and o.cancelled_at is null
  and coalesce(o.fulfillment_status, '') not in ('FULFILLED', 'FULFILLMENT_NOT_REQUIRED')
  and not exists (select 1 from ops.shipments sh where sh.order_id = o.id);

revoke all on ops.flow_board from public, anon, authenticated;
grant select on ops.flow_board to service_role;
do $$ begin
  if exists (select 1 from pg_roles where rolname = 'flowmerce_app') then
    execute 'grant select on ops.flow_board to flowmerce_app';
  end if;
end $$;

notify pgrst, 'reload schema';
