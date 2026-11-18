-- =====================================================================================
-- Flowmerce central database · 105 · refresh ops.* from the hub's public tables
--
-- Replaces 100_tracker_refresh.sql (removed). That version read the old "Delayed Orders Tracker" tables
-- (public.shipments with carrier_name, public.order_checks, public.manual_status), which do not
-- exist in this database, so every refresh failed. This version reads what the database really
-- has (checked 2026-11-17):
--   * public.stores                      -> ops.stores (missing rows only)
--   * public.orders                      -> ops.orders
--   * public.orders.raw -> fulfillments  -> ops.shipments (1 per Shopify fulfillment)
--                                           ops.tracking_numbers (1 per tracking number)
--                                           ops.tracking_scans (1 per Shopify shipment_status seen)
--   * public.sync_runs                   -> ops.sync_runs (the hub's Shopify runs, for freshness)
--   * ops.shopify_orders                 -> preferred over public.orders.raw for the same order: what
--                                           Flowmerce read straight from Shopify (carrier events, real
--                                           delivery time, ETA). Filled by the backend, keys stay in .env.
--
-- ops.refresh_from_shopify_orders() is REPEATABLE (the Flowmerce backend calls it every
-- 15 minutes and from "Refresh now"). It NEVER writes, updates or deletes anything in public.*.
--
-- Honesty rules:
--   * Shopify's word never confirms a delivery (delivery_confirmed stays false).
--   * Shopify fulfillments have no delivered time. When Shopify says "delivered", the time Shopify
--     last updated that fulfillment is used, and status_detail says so. With no such time the
--     parcel stays "pending"; it is never shown as delivered without a time.
--   * A fulfillment stored with only "createdAt" (no carrier, number or status: 5,051 such rows on
--     2026-11-17) is NOT turned into a shipment. It is counted as "incomplete" in the run result
--     until the hub re-fetches it from Shopify (see docs/shipping-schema-needs.md, G1).
--   * Unknown carrier names map to carrier "unknown", never guessed.
-- Safe to run more than once.
-- =====================================================================================

-- ---------------------------------------------------------------- reference words found in the live data
insert into ops.status_map (source, carrier_id, raw_status, status, is_terminal, confirms_delivery, note) values
  ('shopify','*','RETURNING_TO_SENDER', 'returned',   true,  false, 'Shopify shipment_status'),
  ('shopify','*','CARRIER_PICKED_UP',   'in_transit', false, false, null)
on conflict (source, carrier_id, raw_status) do nothing;

insert into ops.carrier_aliases (alias, carrier_id, note) values
  ('amazon shipping + amazon mcf', 'amazon_logistics_us', 'Shopify data (6)')
on conflict (alias) do nothing;

-- ---------------------------------------------------------------- what Flowmerce reads straight from Shopify
-- Written by the Flowmerce backend (modules/shipping/shopify_source.py) with the store keys from its own .env.
-- No Shopify keys or tokens are ever stored in Supabase. No customer details either: only the order
-- number, dates, statuses, carrier, tracking numbers and carrier events (time, status, city/country).
create table if not exists ops.shopify_orders (
  id                  bigint primary key,                   -- Shopify order id (legacy number)
  store               text not null references ops.stores(id),
  name                text not null,                        -- #RBP1234
  created_at          timestamptz not null,
  updated_at          timestamptz not null,                 -- Shopify's updatedAt (sync cursor)
  cancelled_at        timestamptz,
  fulfillment_status  text,                                 -- Shopify displayFulfillmentStatus
  fulfillments        jsonb not null default '[]',          -- normalised, see shopify_source.py
  fetched_at          timestamptz not null default now()
);
create index if not exists shopify_orders_store_updated on ops.shopify_orders (store, updated_at desc);
alter table ops.shopify_orders enable row level security;
comment on table ops.shopify_orders is 'Orders and fulfillments as Flowmerce last read them from the Shopify Admin API. Preferred over public.orders.raw by ops.refresh_from_shopify_orders().';
do $$
begin
  if exists (select 1 from pg_roles where rolname = 'service_role') then
    execute 'grant select, insert, update, delete on ops.shopify_orders to service_role';
  end if;
  if exists (select 1 from pg_roles where rolname = 'flowmerce_app') then
    execute 'grant select, insert, update, delete on ops.shopify_orders to flowmerce_app';
  end if;
end $$;

-- The old tracker refresh cannot work against this database; remove it so nothing calls it by mistake.
drop function if exists ops.refresh_from_tracker(text);

create or replace function ops.refresh_from_shopify_orders(p_store text default null)
returns jsonb
language plpgsql
security invoker
set search_path = ops, pg_temp
as $$
declare
  v_run        bigint;
  n_orders     int := 0;
  n_fulfil     int := 0;
  n_direct     int := 0;
  n_incomplete int := 0;
  n_no_number  int := 0;
  n_new_ship   int := 0;
  n_upd_ship   int := 0;
  n_tracking   int := 0;
  n_scans      int := 0;
  n_exc        int := 0;
  n_hub_runs   int := 0;
  v_n          int;
begin
  -- Logged as source shopify / kind import. One running refresh at a time (unique lock_key on running
  -- rows): a second caller fails at once.
  insert into ops.sync_runs (source, kind, store, triggered_by)
  values ('shopify', 'import', p_store,
          coalesce(nullif(current_setting('request.jwt.claim.role', true), ''), current_user))
  returning id into v_run;

  -- ------------------------------------------------------------ 0. stores (add missing ones only)
  insert into ops.stores (id, name, shopify_domain, currency, timezone, active)
  select s.id, s.name, s.shopify_domain, s.currency, s.timezone, s.active
  from public.stores s
  where p_store is null or s.id = p_store
  on conflict do nothing;

  -- ------------------------------------------------------------ 1. orders
  -- a) from the hub (public.orders); never overwrites newer facts Flowmerce read from Shopify itself
  insert into ops.orders as o (id, store, name, placed_at, shop_updated_at, synced_at, origin,
                               cancelled_at, cancel_reason, financial_status, fulfillment_status,
                               currency, total, ship_country, stage, stage_at)
  --    When Flowmerce's own Shopify copy is at least as new, its cancelled/fulfillment status is used, so
  --    steps a) and b) never overwrite each other on every run.
  select p.id, p.store, p.name, p.placed_at, greatest(p.shop_updated_at, so.updated_at), now(), 'shopify_sync',
         case when so.id is not null then so.cancelled_at else p.cancelled_at end,
         p.cancel_reason, p.financial_status,
         case when so.id is not null then so.fulfillment_status else p.fulfillment_status end,
         coalesce(p.currency, 'USD'), p.total, p.ship_country,
         case when (case when so.id is not null then so.cancelled_at else p.cancelled_at end) is not null
              then 'cancelled' else p.stage end, p.stage_at
  from public.orders p
  join ops.stores s on s.id = p.store
  left join ops.shopify_orders so on so.id = p.id and so.updated_at >= p.shop_updated_at
  where p_store is null or p.store = p_store
  on conflict (id) do update set
    name               = excluded.name,
    shop_updated_at    = excluded.shop_updated_at,
    cancelled_at       = excluded.cancelled_at,
    cancel_reason      = excluded.cancel_reason,
    financial_status   = excluded.financial_status,
    fulfillment_status = excluded.fulfillment_status,
    currency           = excluded.currency,
    total              = excluded.total,
    ship_country       = excluded.ship_country,
    origin             = 'shopify_sync',
    synced_at          = now()
  where excluded.shop_updated_at >= o.shop_updated_at
    and (o.name, o.shop_updated_at, o.cancelled_at, o.financial_status, o.fulfillment_status, o.total,
         o.ship_country, o.origin)
        is distinct from
        (excluded.name, excluded.shop_updated_at, excluded.cancelled_at, excluded.financial_status,
         excluded.fulfillment_status, excluded.total, excluded.ship_country, excluded.origin);
  get diagnostics v_n = row_count;
  n_orders := v_n;

  -- b) read by Flowmerce straight from Shopify (ops.shopify_orders): newer facts win; orders the hub lacks are added
  insert into ops.orders as o (id, store, name, placed_at, shop_updated_at, synced_at, origin,
                               cancelled_at, fulfillment_status)
  select s.id, s.store, s.name, s.created_at, s.updated_at, now(), 'shopify_sync', s.cancelled_at, s.fulfillment_status
  from ops.shopify_orders s
  join ops.stores st on st.id = s.store
  where p_store is null or s.store = p_store
  on conflict (id) do update set
    shop_updated_at    = excluded.shop_updated_at,
    cancelled_at       = excluded.cancelled_at,
    fulfillment_status = excluded.fulfillment_status,
    synced_at          = now()
  where excluded.shop_updated_at > o.shop_updated_at
     or (excluded.shop_updated_at = o.shop_updated_at
         and (o.cancelled_at, o.fulfillment_status) is distinct from (excluded.cancelled_at, excluded.fulfillment_status));
  get diagnostics v_n = row_count;
  n_orders := n_orders + v_n;

  -- ------------------------------------------------------------ 2. staging: one row per Shopify fulfillment
  -- Orders Flowmerce read from Shopify itself use that data (carrier events, real delivery time, ETA);
  -- all other orders use the copy in the hub's public.orders.raw.
  create temp table _f on commit drop as
  select
    p.id                                                                          as order_id,
    p.store,
    p.synced_at                                                                   as order_synced_at,
    nullif(regexp_replace(coalesce(f.value->>'id', ''), '\D', '', 'g'), '')::bigint as fulfillment_id,
    (f.value ? 'status')                                                          as complete,
    lower(nullif(btrim(f.value->>'status'), ''))                                  as f_status,
    nullif(btrim(f.value->>'tracking_company'), '')                               as carrier_name,
    nullif(btrim(f.value->>'shipment_status'), '')                                as raw_status,
    upper(nullif(btrim(f.value->>'shipment_status'), ''))                         as raw_up,
    nullif(f.value->>'created_at', '')::timestamptz                               as created_at,
    nullif(f.value->>'updated_at', '')::timestamptz                               as updated_at,
    nullif(btrim(f.value->>'service'), '')                                        as service,
    coalesce((select jsonb_agg(jsonb_build_object('item_id', (li->>'id')::bigint, 'qty', (li->>'quantity')::int))
                from jsonb_array_elements(case when jsonb_typeof(f.value->'line_items') = 'array'
                                               then f.value->'line_items' else '[]'::jsonb end) li
               where li->>'id' ~ '^\d+$' and li->>'quantity' ~ '^\d+$'), '[]'::jsonb) as items,
    array(select distinct btrim(n)
            from jsonb_array_elements_text(
                   case when jsonb_typeof(f.value->'tracking_numbers') = 'array' then f.value->'tracking_numbers'
                        when nullif(btrim(f.value->>'tracking_number'), '') is not null
                          then jsonb_build_array(f.value->>'tracking_number')
                        else '[]'::jsonb end) n
           where nullif(btrim(n), '') is not null)                                as numbers,
    'hub'::text           as src,
    null::timestamptz     as eta,
    null::timestamptz     as delivered_src,
    null::timestamptz     as in_transit_at,
    '[]'::jsonb           as events,
    null::text    as carrier_id,
    null::text    as status,
    null::text    as mapped_rule,
    null::timestamptz as delivered_at,
    null::text    as note
  from public.orders p
  join ops.orders o on o.id = p.id
  cross join lateral jsonb_array_elements(
    case when jsonb_typeof(p.raw->'fulfillments') = 'array' then p.raw->'fulfillments' else '[]'::jsonb end) f(value)
  where (p_store is null or p.store = p_store)
    and not exists (select 1 from ops.shopify_orders s where s.id = p.id)
  union all
  select
    s.id, s.store, s.fetched_at,
    nullif(f.value->>'id', '')::bigint,
    true,
    lower(nullif(btrim(f.value->>'status'), '')),
    nullif(btrim(f.value->'tracking'->0->>'company'), ''),
    coalesce(le.status, nullif(btrim(f.value->>'display_status'), '')),
    upper(coalesce(le.status, nullif(btrim(f.value->>'display_status'), ''))),
    nullif(f.value->>'created_at', '')::timestamptz,
    nullif(f.value->>'updated_at', '')::timestamptz,
    nullif(btrim(f.value->>'service'), ''),
    case when jsonb_typeof(f.value->'items') = 'array' then f.value->'items' else '[]'::jsonb end,
    array(select distinct btrim(t->>'number')
            from jsonb_array_elements(case when jsonb_typeof(f.value->'tracking') = 'array'
                                           then f.value->'tracking' else '[]'::jsonb end) t
           where nullif(btrim(t->>'number'), '') is not null),
    'shopify',
    nullif(f.value->>'eta', '')::timestamptz,
    nullif(f.value->>'delivered_at', '')::timestamptz,
    nullif(f.value->>'in_transit_at', '')::timestamptz,
    case when jsonb_typeof(f.value->'events') = 'array' then f.value->'events' else '[]'::jsonb end,
    null, null, null, null, null
  from ops.shopify_orders s
  join ops.orders o on o.id = s.id
  cross join lateral jsonb_array_elements(
    case when jsonb_typeof(s.fulfillments) = 'array' then s.fulfillments else '[]'::jsonb end) f(value)
  -- the newest carrier event decides the status; without events, Shopify's display status does.
  -- Exception: once the carrier has scanned the parcel DELIVERED it stays delivered. Carriers (DHL above all) sometimes
  -- add a stray event days later, e.g. "FAILURE" with no text 18 days after delivery; Shopify keeps its delivery time
  -- and "marked as delivered" for such parcels, and so does Flowmerce.
  left join lateral (select e->>'status' as status
                       from jsonb_array_elements(case when jsonb_typeof(f.value->'events') = 'array'
                                                      then f.value->'events' else '[]'::jsonb end) e
                      where nullif(e->>'at', '') is not null and nullif(e->>'status', '') is not null
                      order by (upper(e->>'status') = 'DELIVERED') desc, (e->>'at')::timestamptz desc, e->>'id' desc
                      limit 1) le on true
  where p_store is null or s.store = p_store;

  select count(*) filter (where not complete or fulfillment_id is null) into n_incomplete from _f;
  delete from _f where not complete or fulfillment_id is null;
  select count(*), count(*) filter (where src = 'shopify') into n_fulfil, n_direct from _f;

  -- carrier: through the alias list; unmatched (blank, "Other", new names) -> unknown
  update _f t set carrier_id = a.carrier_id
    from ops.carrier_aliases a
   where a.alias = lower(coalesce(t.carrier_name, ''));
  update _f set carrier_id = 'unknown' where carrier_id is null;

  -- status: through the status map; no word = no carrier evidence yet = pending
  update _f t set status = m.status, mapped_rule = 'shopify/*/' || m.raw_status
    from ops.status_map m
   where m.source = 'shopify' and m.carrier_id = '*' and m.raw_status = t.raw_up;
  update _f set status = 'pending',
                note = 'Shopify status word not in the status map: ' || raw_status
   where status is null and raw_status is not null;
  update _f set status = 'pending' where status is null;

  -- delivered time: Shopify's own delivery time, else the newest "delivered" carrier event,
  -- else (hub data only) Shopify's last update of the fulfillment. Never carrier-confirmed.
  update _f set delivered_at = coalesce(delivered_src,
                  (select max((e->>'at')::timestamptz) from jsonb_array_elements(events) e
                    where upper(e->>'status') = 'DELIVERED' and nullif(e->>'at', '') is not null)),
                note = 'Delivered per Shopify carrier tracking (not carrier-confirmed)'
   where status = 'delivered' and src = 'shopify';
  update _f set delivered_at = updated_at,
                note = 'Delivered per Shopify; time is when Shopify last updated the fulfillment (not carrier-confirmed)'
   where status = 'delivered' and src = 'hub' and updated_at is not null;
  update _f set status = 'pending', note = 'Shopify said delivered but gave no time'
   where status = 'delivered' and delivered_at is null;

  -- ------------------------------------------------------------ 3. shipments (one per Shopify fulfillment)
  create temp table _s on commit drop as
  select f.*,
    case
      when f.f_status in ('cancelled', 'error', 'failure') then 'cancelled'
      when f.status = 'delivered'                         then 'delivered'
      when f.status in ('exception', 'returned')          then 'exception'
      when f.status = 'out_for_delivery'                  then 'out'
      when f.status = 'in_transit'                        then 'transit'
      else 'shipped'
    end as step
  from _f f;

  create temp table _chg on commit drop as
  select sh.id as shipment_id, sh.order_id, sh.seq, sh.step as old_step, s.step as new_step,
         coalesce(s.delivered_at, s.updated_at, now()) as at
  from ops.shipments sh join _s s on s.fulfillment_id = sh.shopify_fulfillment_id
  where sh.origin = 'shopify_sync' and sh.step <> s.step;

  update ops.shipments sh set
    step         = s.step,
    step_at      = case when sh.step <> s.step then coalesce(s.delivered_at, s.updated_at, now()) else sh.step_at end,
    step_times   = sh.step_times || jsonb_strip_nulls(jsonb_build_object('shipped', s.created_at,
                                                                         'transit', s.in_transit_at,
                                                                         'delivered', s.delivered_at)),
    carrier      = s.carrier_name,
    carrier_id   = s.carrier_id,
    service      = s.service,
    eta          = s.eta::date,
    delivered_at = s.delivered_at,
    tracking     = s.numbers,
    items        = case when s.items <> '[]'::jsonb then s.items else sh.items end
  from _s s
  where sh.shopify_fulfillment_id = s.fulfillment_id
    and sh.origin = 'shopify_sync'
    and (sh.step, sh.carrier, sh.carrier_id, sh.service, sh.eta, sh.delivered_at, sh.tracking,
         case when s.items <> '[]'::jsonb then s.items else sh.items end)
        is distinct from
        (s.step, s.carrier_name, s.carrier_id, s.service, s.eta::date, s.delivered_at, s.numbers, sh.items);
  get diagnostics n_upd_ship = row_count;

  insert into ops.shipments (order_id, store, seq, kind, kind_inferred, items, step, step_at, step_times,
                             carrier, service, carrier_id, shopify_fulfillment_id, eta, delivered_at, tracking,
                             origin, created_by)
  select s.order_id, s.store,
    coalesce((select max(x.seq) from ops.shipments x where x.order_id = s.order_id), 0)
      + row_number() over (partition by s.order_id order by s.created_at nulls last, s.fulfillment_id),
    case when s.service = 'amazon-fulfillment'                   then 'mcf'
         when s.carrier_id = 'amazon_logistics_us'               then 'mcf'
         when s.carrier_id in ('dhl', 'fedex', 'dhl_ecommerce')  then 'india'
         else 'unknown' end,
    s.service is distinct from 'amazon-fulfillment',   -- only Amazon's own fulfillment service says MCF for sure
    s.items, s.step,
    coalesce(s.delivered_at, s.updated_at, s.created_at, now()),
    jsonb_strip_nulls(jsonb_build_object('shipped', s.created_at, 'transit', s.in_transit_at,
                                         'delivered', s.delivered_at)),
    s.carrier_name, s.service, s.carrier_id, s.fulfillment_id, s.eta::date, s.delivered_at, s.numbers,
    'shopify_sync', 'job:shopify_orders_refresh'
  from _s s
  where not exists (select 1 from ops.shipments x where x.shopify_fulfillment_id = s.fulfillment_id);
  get diagnostics n_new_ship = row_count;

  insert into ops.events (at, store, order_id, shipment_id, type, by, title, data, external_id)
  select c.at, sh.store, c.order_id, c.shipment_id, 'step', 'job:shopify_orders_refresh',
         'P' || c.seq || ': ' || c.old_step || ' → ' || c.new_step,
         jsonb_build_object('before', c.old_step, 'after', c.new_step),
         'step:' || c.shipment_id || ':' || c.new_step || ':' || extract(epoch from c.at)::bigint
  from _chg c join ops.shipments sh on sh.id = c.shipment_id
  on conflict (external_id) do nothing;

  -- ------------------------------------------------------------ 4. tracking numbers
  select count(*) into n_no_number from _s where step <> 'cancelled' and cardinality(numbers) = 0;

  -- one row per (carrier, number): a number on several fulfillments belongs to the newest live one
  create temp table _n on commit drop as
  select distinct on (s.carrier_id, n.num) s.*, n.num as tracking_number, sh.id as shipment_id
  from _s s
  cross join lateral unnest(s.numbers) n(num)
  join ops.shipments sh on sh.shopify_fulfillment_id = s.fulfillment_id
  where s.step <> 'cancelled'
  order by s.carrier_id, n.num, s.created_at desc nulls last, s.fulfillment_id desc;

  insert into ops.tracking_numbers as tn (
    shipment_id, store, carrier_id, tracking_number, source, status, status_detail, raw_status,
    registered_at, picked_up_at, eta, delivered_at, delivery_confirmed, dest_country,
    last_checked_at, last_check_ok_at, check_attempts, active, stopped_at)
  select n.shipment_id, n.store, n.carrier_id, n.tracking_number, 'shopify', n.status, n.note, n.raw_status,
    coalesce(n.created_at, now()), n.in_transit_at, n.eta::date, n.delivered_at,
    false,                                            -- Shopify's word never confirms a delivery
    o.ship_country,
    n.order_synced_at, n.order_synced_at, 0,
    n.status not in ('delivered', 'returned', 'expired'),
    case when n.status in ('delivered', 'returned', 'expired') then now() end
  from _n n join ops.orders o on o.id = n.order_id
  on conflict (carrier_id, tracking_number) do update set
    shipment_id      = excluded.shipment_id,
    status           = excluded.status,
    status_detail    = excluded.status_detail,
    raw_status       = excluded.raw_status,
    picked_up_at     = coalesce(excluded.picked_up_at, tn.picked_up_at),
    eta              = excluded.eta,
    delivered_at     = excluded.delivered_at,
    dest_country     = excluded.dest_country,
    last_checked_at  = excluded.last_checked_at,
    last_check_ok_at = excluded.last_check_ok_at,
    active           = excluded.active,
    stopped_at       = case when not excluded.active then coalesce(tn.stopped_at, now()) end
  where tn.source = 'shopify'
    and (tn.shipment_id, tn.status, tn.raw_status, tn.delivered_at, tn.status_detail, tn.dest_country,
         tn.last_checked_at, tn.active, tn.eta, coalesce(excluded.picked_up_at, tn.picked_up_at))
        is distinct from
        (excluded.shipment_id, excluded.status, excluded.raw_status, excluded.delivered_at, excluded.status_detail,
         excluded.dest_country, excluded.last_checked_at, excluded.active, excluded.eta, tn.picked_up_at);
  get diagnostics n_tracking = row_count;

  -- numbers whose fulfillment was cancelled stop being tracked
  update ops.tracking_numbers tn set active = false, stopped_at = coalesce(tn.stopped_at, now())
    from ops.shipments sh
   where sh.id = tn.shipment_id and sh.step = 'cancelled' and tn.active and tn.source = 'shopify';

  -- ------------------------------------------------------------ 5. scans
  -- Direct Shopify data: one scan per real carrier event (time, place, message), per tracking number.
  -- Hub data: Shopify keeps only the current status word, so each new word becomes one scan row timed by
  -- Shopify's update of the fulfillment. Once a number has real events, those placeholder rows are removed
  -- so the newest scan is always a real carrier event.
  with gone as (
    delete from ops.tracking_scans sc
     using _n n, ops.tracking_numbers tn
     where n.src = 'shopify' and jsonb_array_length(n.events) > 0
       and tn.carrier_id = n.carrier_id and tn.tracking_number = n.tracking_number
       and sc.tracking_id = tn.id and sc.external_id like 'shopify:%'
    returning sc.external_id
  )
  delete from ops.events e using gone where e.external_id = gone.external_id;   -- and their timeline lines

  create temp table _ins (id bigint, tracking_id uuid, shipment_id uuid, external_id text,
                          scanned_at timestamptz, status text, raw_status text, city text) on commit drop;
  with ins as (
    insert into ops.tracking_scans (tracking_id, shipment_id, external_id, scanned_at, status, raw_status,
                                    message, city, province, country, source, mapped_rule)
    select tn.id, tn.shipment_id,
      'shopify_event:' || (e->>'id') || ':' || n.tracking_number,
      (e->>'at')::timestamptz, coalesce(m.status, 'pending'), e->>'status',
      coalesce(nullif(btrim(e->>'message'), ''), 'Carrier event: ' || (e->>'status')),
      nullif(btrim(e->>'city'), ''), nullif(btrim(e->>'province'), ''), nullif(btrim(e->>'country'), ''),
      'shopify', case when m.status is not null then 'shopify/*/' || m.raw_status end
    from _n n
    join ops.tracking_numbers tn on tn.carrier_id = n.carrier_id and tn.tracking_number = n.tracking_number
    cross join lateral jsonb_array_elements(n.events) e
    left join ops.status_map m on m.source = 'shopify' and m.carrier_id = '*' and m.raw_status = upper(e->>'status')
    where n.src = 'shopify' and tn.source = 'shopify'
      and nullif(e->>'id', '') is not null and nullif(e->>'at', '') is not null and nullif(e->>'status', '') is not null
    union all
    select tn.id, tn.shipment_id,
      'shopify:' || n.carrier_id || ':' || n.tracking_number || ':' || n.raw_up,
      n.updated_at, n.status, n.raw_status, 'Shopify shipment status: ' || n.raw_status,
      null, null, null, 'shopify', n.mapped_rule
    from _n n
    join ops.tracking_numbers tn on tn.carrier_id = n.carrier_id and tn.tracking_number = n.tracking_number
    where n.src = 'hub' and n.raw_status is not null and n.updated_at is not null and tn.source = 'shopify'
      and n.status = tn.status                    -- never a scan that disagrees with the stored status
    on conflict (external_id) do nothing
    returning id, tracking_id, shipment_id, external_id, scanned_at, status, raw_status, city
  )
  insert into _ins select * from ins;
  get diagnostics n_scans = row_count;

  -- timeline: every status change, but only the first of a run of "in transit" hops
  insert into ops.events (at, store, order_id, shipment_id, type, by, title, data, external_id)
  select i.scanned_at, sh.store, sh.order_id, i.shipment_id, 'scan', 'shopify',
         initcap(replace(i.status, '_', ' ')) || coalesce(' · ' || i.city, '') || ' (Shopify)',
         jsonb_build_object('raw_status', i.raw_status, 'tracking_id', i.tracking_id),
         i.external_id
  from _ins i join ops.shipments sh on sh.id = i.shipment_id
  where i.status <> 'in_transit'
     or not exists (select 1 from ops.tracking_scans p
                     where p.tracking_id = i.tracking_id and p.status = 'in_transit' and p.scanned_at < i.scanned_at)
  on conflict (external_id) do nothing;

  update ops.tracking_scans s set event_id = e.id
    from _ins i join ops.events e on e.external_id = i.external_id
   where s.id = i.id and s.event_id is null;

  update ops.tracking_numbers tn set
    scan_count   = c.n,
    last_scan_at = c.last_at,
    picked_up_at = coalesce(tn.picked_up_at, c.first_move)
  from (select tracking_id, count(*)::int as n, max(scanned_at) as last_at,
               min(scanned_at) filter (where status in ('in_transit', 'out_for_delivery', 'delivered')) as first_move
          from ops.tracking_scans group by tracking_id) c
  where c.tracking_id = tn.id
    and (tn.scan_count, tn.last_scan_at, tn.picked_up_at)
        is distinct from (c.n, c.last_at, coalesce(tn.picked_up_at, c.first_move));

  update ops.shipments sh set last_scan_at = x.last_at, last_scan_place = x.place, last_scan_text = x.msg
  from (select distinct on (s.shipment_id) s.shipment_id, s.scanned_at as last_at, s.message as msg,
               nullif(concat_ws(', ', s.city, s.province, s.country), '') as place
          from ops.tracking_scans s order by s.shipment_id, s.scanned_at desc, s.id desc) x
  where x.shipment_id = sh.id
    and (sh.last_scan_at, sh.last_scan_place, sh.last_scan_text) is distinct from (x.last_at, x.place, x.msg);

  -- ------------------------------------------------------------ 6. exceptions from Shopify's carrier status
  insert into ops.shipping_exceptions (order_id, shipment_id, tracking_id, store, kind, severity, source,
                                       detected_at, description, status)
  select sh.order_id, tn.shipment_id, tn.id, tn.store, k.kind, k.severity, 'carrier',
         coalesce(tn.last_scan_at, now()), 'Shopify reports ' || coalesce(tn.raw_status, 'a delivery problem'), 'open'
  from ops.tracking_numbers tn
  join ops.shipments sh on sh.id = tn.shipment_id
  cross join lateral (select
      case upper(coalesce(tn.raw_status, ''))
        when 'DELAYED'             then 'delay'
        when 'RETURNED'            then 'returned_to_sender'
        when 'RETURN_TO_SENDER'    then 'returned_to_sender'
        when 'RETURNING_TO_SENDER' then 'returned_to_sender'
        else 'failed_delivery' end as kind,
      case upper(coalesce(tn.raw_status, ''))
        when 'DELAYED'             then 'amber'
        when 'ATTEMPTED_DELIVERY'  then 'amber'
        else 'red' end as severity) k
  where tn.source = 'shopify' and tn.status in ('exception', 'returned')
    and not exists (select 1 from ops.shipping_exceptions e
                     where e.tracking_id = tn.id and e.kind = k.kind and e.closed_at is null);
  get diagnostics n_exc = row_count;

  -- carrier-raised problems close themselves once the parcel moves on (in transit again, out, delivered)
  update ops.shipping_exceptions e set
    status = 'resolved', resolved_at = now(), closed_at = now(),
    resolution = case when tn.status = 'delivered' then 'Shopify later reported delivered'
                      else 'Carrier tracking moved on: ' || tn.status end
  from ops.tracking_numbers tn
  where e.tracking_id = tn.id and e.source = 'carrier' and e.closed_at is null
    and tn.status in ('delivered', 'in_transit', 'out_for_delivery');

  -- ------------------------------------------------------------ 7. order stage from its shipments
  -- No shipments yet: keep the hub's own stage (checked, routed, in_production, packed, on_hold ...).
  update ops.orders o set
    stage     = x.stage,
    stage_at  = now(),
    closed_at = case when x.stage = 'delivered' then coalesce(o.closed_at, x.last_delivered, now()) end
  from (
    select o2.id,
      max(sh.delivered_at) as last_delivered,
      case
        when o2.cancelled_at is not null then 'cancelled'
        when count(sh.id) filter (where sh.step <> 'cancelled') = 0 then
          coalesce((select p.stage from public.orders p where p.id = o2.id), o2.stage, 'new')
        when bool_and(sh.step = 'delivered') filter (where sh.step <> 'cancelled')
             and upper(coalesce(o2.fulfillment_status, '')) <> 'PARTIALLY_FULFILLED' then 'delivered'
        when bool_or(sh.step in ('transit', 'out', 'exception')) then 'transit'
        else 'shipped'
      end as stage
    from ops.orders o2
    left join ops.shipments sh on sh.order_id = o2.id
    where o2.origin = 'shopify_sync' and (p_store is null or o2.store = p_store)
    group by o2.id
  ) x
  where o.id = x.id and o.stage is distinct from x.stage;

  -- ------------------------------------------------------------ 8. mirror the hub's sync runs (freshness)
  insert into ops.sync_runs (source, kind, store, started_at, finished_at, status, rows_read, rows_written,
                             rows_failed, error, triggered_by, cursor)
  select r.source, r.kind, r.store, r.started_at, r.finished_at, r.status,
         coalesce(r.rows_read, 0), coalesce(r.rows_written, 0), coalesce(r.rows_failed, 0),
         nullif(left(r.error, 1000), ''), 'hub:' || coalesce(r.triggered_by, '?'), 'hub_run:' || r.id
  from public.sync_runs r
  where r.status in ('ok', 'partial', 'failed')
    and r.source in ('shopify','amazon','aftership','17track','shiprocket','delhivery','dhl','fedex','erp')
    and r.kind in ('backfill','nightly_check','webhook_replay')
    and r.started_at > now() - interval '30 days'
    and (p_store is null or r.store = p_store or r.store is null)
    and (r.store is null or exists (select 1 from ops.stores s where s.id = r.store))
    and not exists (select 1 from ops.sync_runs x where x.cursor = 'hub_run:' || r.id);
  get diagnostics n_hub_runs = row_count;

  -- ------------------------------------------------------------ 9. close the run log
  update ops.sync_runs set
    finished_at  = clock_timestamp(),
    status       = 'ok',
    rows_read    = n_fulfil + n_incomplete,
    rows_written = n_new_ship + n_upd_ship + n_tracking + n_scans,
    rows_failed  = n_incomplete
  where id = v_run;

  return jsonb_build_object(
    'run_id', v_run, 'orders_changed', n_orders, 'fulfillments', n_fulfil,
    'fulfillments_from_shopify', n_direct,
    'fulfillments_incomplete', n_incomplete, 'shipped_without_number', n_no_number,
    'shipments_new', n_new_ship, 'shipments_updated', n_upd_ship, 'tracking_changed', n_tracking,
    'new_scans', n_scans, 'exceptions_opened', n_exc, 'hub_runs_copied', n_hub_runs);
end $$;

comment on function ops.refresh_from_shopify_orders(text) is
  'Repeatable refresh of ops.* from public.orders (Shopify fulfillments in raw) and public.sync_runs. Never writes to public.*.';

-- ---------------------------------------------------------------- team marks made in Flowmerce
create or replace function ops.set_team_mark(p_tracking_id uuid, p_mark text, p_note text, p_by text)
returns jsonb
language plpgsql
security invoker
set search_path = ops, pg_temp
as $$
declare
  v_ship uuid;
  v_order bigint;
  v_store text;
  v_kind text;
begin
  if p_mark is not null and p_mark not in ('delivered', 'lost', 'failed', 'in_transit', 'checked') then
    raise exception 'Unknown team mark %', p_mark using errcode = '22023';
  end if;
  if p_mark is null and nullif(btrim(coalesce(p_note, '')), '') is null then
    raise exception 'A mark or a note is required' using errcode = '22023';
  end if;
  if nullif(btrim(coalesce(p_by, '')), '') is null then
    raise exception 'Who made the mark is required' using errcode = '22023';
  end if;

  update ops.tracking_numbers set
    team_mark    = coalesce(p_mark, team_mark),
    team_mark_by = p_by,
    team_mark_at = now(),
    team_note    = coalesce(nullif(btrim(coalesce(p_note, '')), ''), team_note)
  where id = p_tracking_id
  returning shipment_id, store into v_ship, v_store;
  if not found then
    raise exception 'Tracking number not found' using errcode = 'P0002';
  end if;
  select order_id into v_order from ops.shipments where id = v_ship;

  insert into ops.events (store, order_id, shipment_id, type, by, title, data)
  values (v_store, v_order, v_ship, 'note', p_by,
          case when p_mark is not null then 'Team marked ' || p_mark else 'Team note' end,
          jsonb_strip_nulls(jsonb_build_object('mark', p_mark, 'note', nullif(btrim(coalesce(p_note, '')), ''),
                                               'tracking_id', p_tracking_id)));

  if p_mark in ('lost', 'failed') then
    v_kind := case p_mark when 'lost' then 'lost' else 'failed_delivery' end;
    insert into ops.shipping_exceptions (order_id, shipment_id, tracking_id, store, kind, severity, source,
                                         description, status, owner)
    select v_order, v_ship, p_tracking_id, v_store, v_kind, 'red', 'person',
           coalesce(nullif(btrim(coalesce(p_note, '')), ''), 'Team marked ' || p_mark), 'open', p_by
    where not exists (select 1 from ops.shipping_exceptions e
                       where e.tracking_id = p_tracking_id and e.kind = v_kind and e.closed_at is null);
  end if;

  return jsonb_build_object('ok', true, 'tracking_id', p_tracking_id, 'mark', p_mark);
end $$;

comment on function ops.set_team_mark(uuid, text, text, text) is
  'A person''s check on a parcel. Kept apart from the carrier status; lost/failed opens an exception.';

-- ---------------------------------------------------------------- who may call these
revoke execute on function ops.refresh_from_shopify_orders(text) from public;
revoke execute on function ops.set_team_mark(uuid, text, text, text) from public;
do $$
begin
  if exists (select 1 from pg_roles where rolname = 'anon') then
    execute 'revoke execute on function ops.refresh_from_shopify_orders(text) from anon, authenticated';
    execute 'revoke execute on function ops.set_team_mark(uuid, text, text, text) from anon, authenticated';
  end if;
  if exists (select 1 from pg_roles where rolname = 'service_role') then
    execute 'grant execute on function ops.refresh_from_shopify_orders(text) to service_role';
    execute 'grant execute on function ops.set_team_mark(uuid, text, text, text) to service_role';
  end if;
  if exists (select 1 from pg_roles where rolname = 'flowmerce_app') then
    execute 'grant execute on function ops.refresh_from_shopify_orders(text) to flowmerce_app';
    execute 'grant execute on function ops.set_team_mark(uuid, text, text, text) to flowmerce_app';
    execute 'grant usage on schema public to flowmerce_app';
    execute 'grant select on public.orders, public.stores, public.sync_runs to flowmerce_app';
  end if;
end $$;

-- Tell the Supabase API about the new function right away.
notify pgrst, 'reload schema';
