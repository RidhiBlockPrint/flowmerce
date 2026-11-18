-- =====================================================================================
-- Flowmerce central database · 060 · views (worked out live, never stored)
-- From the v2 design: stock_free · alert_board · daily · order_shipping_cost · carrier_performance
-- FLOWMERCE ADDITIONS: feed_freshness · shipment_diagnostics · shipping_summary
-- Safe to run more than once (create or replace).
-- =====================================================================================

-- ---------------------------------------------------------------- stock_free
create or replace view ops.stock_free as
select s.store, s.sku, s.fba, s.india,
  s.fba   - coalesce(r.fba, 0)   as fba_free,
  s.india - coalesce(r.india, 0) as india_free,
  s.as_of
from ops.stock s
left join (
  select sh.store, it.sku,
    sum(case when sh.kind = 'mcf'   then (x->>'qty')::int else 0 end) as fba,
    sum(case when sh.kind = 'india' then (x->>'qty')::int else 0 end) as india
  from ops.shipments sh
  cross join lateral jsonb_array_elements(sh.items) x
  join ops.items it on it.id = (x->>'item_id')::bigint
  where sh.step in ('requested','packed','label')
  group by sh.store, it.sku
) r using (store, sku);

-- ---------------------------------------------------------------- alert_board
create or replace view ops.alert_board as
select e.id, e.at as opened_at, e.alert_kind, e.severity, e.level, e.owner_team, e.assigned_to,
  e.reason, e.action, e.due_at, e.seen_at, o.store, o.name as order_name, sh.kind, sh.step, sh.responsible
from ops.events e
join ops.orders o on o.id = e.order_id
left join ops.shipments sh on sh.id = e.shipment_id
where e.type = 'alert' and e.closed_at is null;

-- ---------------------------------------------------------------- daily
create or replace view ops.daily as
select o.store, o.day,
  count(*) filter (where o.cancelled_at is null) as orders,
  sum(o.total - o.refunded_amount) filter (where o.cancelled_at is null) as sales,
  (select count(*) from ops.shipments sh
    where sh.store = o.store
      and ((sh.step_times->>'shipped')::timestamptz at time zone o.tz)::date = o.day) as shipped,
  count(*) filter (where o.late) as late_now
from (
  select x.*, st.timezone as tz, (x.placed_at at time zone st.timezone)::date as day
  from ops.orders x join ops.stores st on st.id = x.store
) o
group by o.store, o.tz, o.day;

-- ---------------------------------------------------------------- order_shipping_cost
create or replace view ops.order_shipping_cost as
select o.id as order_id, o.store, o.name as order_name, o.shipping_charged,
  coalesce(sum(c.amount_usd), 0) as cost_usd,
  coalesce(bool_or(c.is_estimate), false) as has_estimate,
  o.shipping_charged - coalesce(sum(c.amount_usd), 0) as margin_usd
from ops.orders o
left join ops.shipments sh on sh.order_id = o.id
left join ops.shipping_costs c on c.shipment_id = sh.id
group by o.id, o.store, o.name, o.shipping_charged;

-- ---------------------------------------------------------------- carrier_performance
create or replace view ops.carrier_performance as
select t.carrier_id, t.service_id, t.dest_country,
  -- picked_up_at is only known from a carrier feed; until then the dispatch (registration) time is used
  date_trunc('month', coalesce(t.picked_up_at, t.registered_at))::date as month,
  count(*) as shipments,
  count(*) filter (where t.status = 'delivered') as delivered,
  count(*) filter (where t.status = 'delivered' and t.delivery_confirmed) as delivered_confirmed,
  round(avg(extract(epoch from (t.delivered_at - coalesce(t.picked_up_at, t.registered_at))) / 86400)::numeric, 1) as avg_transit_days,
  round(100.0 * count(*) filter (where t.delivered_at::date <= t.promised_by)
        / nullif(count(*) filter (where t.status = 'delivered' and t.promised_by is not null), 0), 1) as on_time_pct,
  count(x.tracking_id) as with_problem
from ops.tracking_numbers t
left join (select tracking_id from ops.shipping_exceptions where tracking_id is not null group by tracking_id) x
  on x.tracking_id = t.id
group by t.carrier_id, t.service_id, t.dest_country, date_trunc('month', coalesce(t.picked_up_at, t.registered_at));

-- ---------------------------------------------------------------- feed_freshness  (ADDITION)
-- Latest attempt and latest success per feed. The UI shows "synced 12 min ago" from this,
-- and must show a warning when last_ok_at is old or last_status is failed.
create or replace view ops.feed_freshness as
select r.source, r.kind, r.store,
  max(r.started_at)                                   as last_attempt_at,
  max(r.finished_at) filter (where r.status = 'ok')   as last_ok_at,
  (array_agg(r.status order by r.started_at desc))[1] as last_status,
  (array_agg(r.error  order by r.started_at desc))[1] as last_error,
  count(*) filter (where r.status = 'failed' and r.started_at > now() - interval '24 hours') as failures_24h
from ops.sync_runs r
group by r.source, r.kind, r.store;

-- ---------------------------------------------------------------- shipment_diagnostics  (ADDITION)
-- One row per problem found. Thresholds come from ops.settings (step_limits.no_scan_h, default 72).
-- Never invents data: it only reports what is missing or contradictory.
create or replace view ops.shipment_diagnostics as
with lim as (
  select coalesce((select (value->>'no_scan_h')::int from ops.settings where key = 'step_limits'), 72) as no_scan_h
),
latest_scan as (
  select distinct on (s.tracking_id) s.tracking_id, s.status, s.scanned_at
  from ops.tracking_scans s
  order by s.tracking_id, s.scanned_at desc, s.received_at desc, s.id desc
)
-- 1. tracking number exists but no scan ever arrived
select t.store, t.shipment_id, t.id as tracking_id, t.tracking_number, 'no_scans'::text as problem, 'amber'::text as severity,
       'Tracking number registered ' || to_char(t.registered_at, 'YYYY-MM-DD') || ' but no scan received' as detail
from ops.tracking_numbers t, lim
where t.active and t.scan_count = 0 and t.registered_at < now() - make_interval(hours => lim.no_scan_h)
union all
-- 2. no movement for longer than the limit
select t.store, t.shipment_id, t.id, t.tracking_number, 'no_movement', 'red',
       'Last scan ' || to_char(t.last_scan_at, 'YYYY-MM-DD HH24:MI') || ' UTC'
from ops.tracking_numbers t, lim
where t.active and t.status not in ('delivered','returned','expired')
  and t.last_scan_at < now() - make_interval(hours => lim.no_scan_h)
union all
-- 3. shipment has no identified carrier
select sh.store, sh.id, null, null, 'missing_carrier', 'amber', coalesce('Carrier text: ' || sh.carrier, 'No carrier at all')
from ops.shipments sh
where sh.step in ('shipped','transit','out') and (sh.carrier_id is null or sh.carrier_id = 'unknown')
union all
-- 4. shown as delivered but no source that can confirm delivery has said so
select t.store, t.shipment_id, t.id, t.tracking_number, 'delivery_unconfirmed', 'amber',
       'Status delivered from source ' || t.source || ' (not carrier-confirmed)'
from ops.tracking_numbers t
where t.status = 'delivered' and not t.delivery_confirmed and t.delivered_at > now() - interval '30 days'
union all
-- 5. stored status disagrees with the newest scan
select t.store, t.shipment_id, t.id, t.tracking_number, 'status_mismatch', 'red',
       'Stored ' || t.status || ' but newest scan says ' || ls.status
from ops.tracking_numbers t join latest_scan ls on ls.tracking_id = t.id
where ls.status <> t.status
union all
-- 6. the source keeps failing for this number
select t.store, t.shipment_id, t.id, t.tracking_number, 'sync_failing', 'amber',
       t.check_attempts || ' failed checks; last error: ' || coalesce(t.last_check_error, '?')
from ops.tracking_numbers t
where t.active and t.check_attempts >= 3
union all
-- 7. the same tracking number is attached to more than one shipment
select min(t.store), null, null, t.tracking_number, 'duplicate_tracking', 'red',
       count(distinct t.shipment_id) || ' shipments share this number'
from ops.tracking_numbers t
group by t.tracking_number
having count(distinct t.shipment_id) > 1
union all
-- 8. shipped but no tracking number
select sh.store, sh.id, null, null, 'shipped_without_tracking', 'red', 'Step ' || sh.step || ' with no tracking number'
from ops.shipments sh
where sh.step in ('shipped','transit','out')
  and not exists (select 1 from ops.tracking_numbers t where t.shipment_id = sh.id)
union all
-- 9. delivery exception still open
select e.store, e.shipment_id, e.tracking_id, null, 'open_exception', e.severity,
       e.kind || ' since ' || to_char(e.detected_at, 'YYYY-MM-DD')
from ops.shipping_exceptions e
where e.closed_at is null
union all
-- 10. kind of an imported shipment was guessed and not yet confirmed
select sh.store, sh.id, null, null, 'kind_unconfirmed', 'amber', 'Imported; kind ' || sh.kind || ' inferred from carrier name'
from ops.shipments sh
where sh.kind_inferred;

-- ---------------------------------------------------------------- diagnostics_list / diagnostics_summary  (ADDITION)
create or replace view ops.diagnostics_list as
select d.*, o.id as order_id, o.name as order_name, sh.seq, sh.carrier_id
from ops.shipment_diagnostics d
left join ops.shipments sh on sh.id = d.shipment_id
left join ops.orders o on o.id = sh.order_id;

create or replace view ops.diagnostics_summary as
select store, problem, severity, count(*)::int as n
from ops.shipment_diagnostics
group by store, problem, severity;

-- ---------------------------------------------------------------- shipment_list  (ADDITION)
-- One row per tracking number with everything the Shipments screen shows. Filtered, sorted and
-- paged by the database (never loaded whole into the app). Age bands follow the tracker's rules:
-- days since dispatch, yellow 4 / orange 6 / red 9 (ops.settings.age_bands overrides).
create or replace view ops.shipment_list as
with bands as (
  select coalesce((select (value->>'yellow')::int from ops.settings where key = 'age_bands'), 4) as y,
         coalesce((select (value->>'orange')::int from ops.settings where key = 'age_bands'), 6) as o,
         coalesce((select (value->>'red')::int    from ops.settings where key = 'age_bands'), 9) as r,
         coalesce((select (value->>'no_scan_h')::int from ops.settings where key = 'step_limits'), 72) as no_scan_h
),
base as (
  select
    t.id as tracking_id, t.store, o.id as order_id, o.name as order_name, o.placed_at,
    sh.id as shipment_id, sh.seq, sh.kind, sh.kind_inferred, sh.step,
    t.carrier_id, c.name as carrier_name, t.tracking_number,
    replace(c.track_url, '{tracking}', t.tracking_number) as track_url,
    t.status, t.raw_status, t.status_detail, t.source, t.delivery_confirmed,
    t.registered_at as shipped_at, t.last_scan_at, sh.last_scan_place, t.delivered_at, t.eta,
    t.last_checked_at, t.last_check_ok_at, t.last_check_error, t.active,
    t.team_mark, t.team_mark_by, t.team_mark_at, t.team_note,
    floor(extract(epoch from (coalesce(t.delivered_at, now()) - t.registered_at)) / 86400)::int as days_since_dispatch,
    case when t.last_scan_at is not null
         then floor(extract(epoch from (now() - t.last_scan_at)) / 3600)::int end as hours_since_scan,
    (select count(*)::int from ops.shipping_exceptions e where e.tracking_id = t.id and e.closed_at is null) as open_exceptions
  from ops.tracking_numbers t
  join ops.shipments sh on sh.id = t.shipment_id
  join ops.orders o on o.id = sh.order_id
  left join ops.carriers c on c.id = t.carrier_id
)
select b.*,
  case
    when b.status = 'delivered' then 'delivered'
    when b.status in ('returned', 'expired') then 'closed'
    when b.days_since_dispatch >= bands.r then 'red'
    when b.days_since_dispatch >= bands.o then 'orange'
    when b.days_since_dispatch >= bands.y then 'yellow'
    else 'green'
  end as age_band,
  (b.active and b.last_scan_at is not null and b.hours_since_scan >= bands.no_scan_h) as no_movement,
  (b.status = 'pending' and b.active) as unverified
from base b cross join bands;

-- ---------------------------------------------------------------- shipping_summary  (ADDITION)
-- Small, fast numbers for the Home page. Never loads whole tables into the app.
create or replace view ops.shipping_summary as
select t.store,
  count(*) filter (where t.active)                                              as open_tracking,
  count(*) filter (where t.status = 'in_transit')                               as in_transit,
  count(*) filter (where t.status = 'out_for_delivery')                         as out_for_delivery,
  count(*) filter (where t.status = 'delivered' and t.delivered_at > now() - interval '30 days') as delivered_30d,
  count(*) filter (where t.status = 'delivered' and t.delivery_confirmed and t.delivered_at > now() - interval '30 days') as delivered_confirmed_30d,
  count(*) filter (where t.status = 'exception')                                as exceptions,
  count(*) filter (where t.status = 'pending' and t.active)                     as unverified,
  max(t.last_check_ok_at)                                                        as last_check_ok_at
from ops.tracking_numbers t
group by t.store;
