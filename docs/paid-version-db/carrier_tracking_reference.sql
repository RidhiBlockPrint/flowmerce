-- =====================================================================================
-- Flowmerce central database · 116 · DHL and FedEx tracking straight from the carriers
-- Safe to run more than once. Needs 010-040 (carriers, tracking_numbers, tracking_scans, sync_runs).
-- Adds tables, starting rows and one view; changes no existing data and never writes public.*.
--
-- Shopify's "delivered" is only Shopify's word (delivery_confirmed stays false). Asking DHL and FedEx
-- directly gives the real scan history, delivery time, signature and estimated delivery date:
--
--   DHL   Shipment Tracking - Unified API (api-eu.dhl.com/track/shipments). Covers DHL Express and DHL eCommerce.
--         Status codes: pre-transit, transit, delivered, failure, unknown.
--   FedEx Track API (apis.fedex.com/track/v1/trackingnumbers). Status codes like PU, IT, OD, DL, DE.
--
-- Where things go:
--   ops.tracking_numbers       status, eta, delivered_at, signed_by, pod_url (existing columns; source 'carrier_api')
--   ops.tracking_scans         one row per carrier scan (existing table; source 'carrier_api', external_id unique)
--   ops.carrier_tracking       NEW: one row per tracking number with carrier-only facts (service, weight, ETA window,
--                              customs, exception code) and the latest answer, cleaned
--   ops.carrier_api_checks     NEW: every call we made (ok or not), for freshness and debugging; pruned after 90 days
--   ops.carrier_api_usage      NEW: calls per account per day, so Flowmerce stays under the carrier's daily limit
--   ops.carrier_tracking_due   NEW view: which DHL / FedEx numbers to check next
--
-- Personal data: carrier answers can hold the receiver's name and address. The backend keeps only city,
-- state and country, and the "signed by" name (already a column on ops.tracking_numbers). Never streets,
-- phone numbers or e-mails.
-- Secrets: shipping_accounts.credential_ref holds the NAME of the env var, never the key.
-- =====================================================================================

-- ---------------------------------------------------------------- carrier_tracking (one row per tracking number)
create table if not exists ops.carrier_tracking (
  tracking_id        uuid primary key references ops.tracking_numbers(id),
  carrier_id         text not null references ops.carriers(id),
  tracking_number    text not null,
  carrier_ref        text,                                            -- DHL shipment id / FedEx tracking number unique id
  service_code       text,                                            -- DHL product code / FedEx service type
  service_name       text,                                            -- e.g. EXPRESS WORLDWIDE, INTERNATIONAL_PRIORITY
  status_code        text,                                            -- carrier's latest code, unchanged
  status_text        text,                                            -- carrier's latest description
  exception_code     text,
  exception_text     text,
  origin_city        text,
  origin_country     text,
  dest_city          text,
  dest_state         text,
  dest_country       text,
  pieces             int,
  weight_kg          numeric(10,3),
  shipped_at         timestamptz,                                     -- carrier's ship / pickup date
  eta_from           timestamptz,                                     -- estimated delivery window
  eta_to             timestamptz,
  delivered_at       timestamptz,
  signed_by          text,                                            -- receiver's signature name, as the carrier shows it
  pod_available      boolean,                                         -- proof of delivery exists
  customs_status     text,
  returned           boolean not null default false,
  last_scan_at       timestamptz,
  last_scan_place    text,
  payload            jsonb,                                           -- latest answer, cleaned of personal fields
  fetched_at         timestamptz not null default now(),
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now(),
  check (carrier_id in ('dhl','dhl_ecommerce','fedex'))
);
create index if not exists carrier_tracking_number on ops.carrier_tracking (carrier_id, tracking_number);
drop trigger if exists carrier_tracking_updated_at on ops.carrier_tracking;
create trigger carrier_tracking_updated_at before update on ops.carrier_tracking
  for each row execute function ops.set_updated_at();
comment on table ops.carrier_tracking is 'DHL / FedEx facts per tracking number. Shared facts (status, eta, delivered_at) are also written to ops.tracking_numbers.';

-- ---------------------------------------------------------------- carrier_api_checks (every call)
create table if not exists ops.carrier_api_checks (
  id            bigserial primary key,
  tracking_id   uuid references ops.tracking_numbers(id),             -- null for a batch call
  carrier_id    text not null references ops.carriers(id),
  account_id    text references ops.shipping_accounts(id),
  sync_run_id   bigint references ops.sync_runs(id),
  checked_at    timestamptz not null default now(),
  ok            boolean not null,
  http_status   int,
  error         text,                                                 -- no secrets
  numbers_asked int not null default 1,                               -- FedEx accepts up to 30 numbers per call
  status_code   text,
  scans_new     int not null default 0,
  duration_ms   int
);
create index if not exists carrier_api_checks_tracking on ops.carrier_api_checks (tracking_id, checked_at desc);
create index if not exists carrier_api_checks_time on ops.carrier_api_checks (checked_at);

-- ---------------------------------------------------------------- carrier_api_usage (daily limit)
create table if not exists ops.carrier_api_usage (
  account_id   text not null references ops.shipping_accounts(id),
  day          date not null,                                         -- UTC day, as the carriers count
  calls        int not null default 0,
  failures     int not null default 0,
  primary key (account_id, day)
);

-- Count one call and return today's total. The backend calls this before each request and stops when the
-- total passes the account's limit in ops.settings -> carrier_tracking.
create or replace function ops.bump_carrier_api_usage(p_account text, p_ok boolean default true) returns int
language sql security invoker set search_path = ops, pg_temp as $$
  insert into ops.carrier_api_usage as u (account_id, day, calls, failures)
  values (p_account, (now() at time zone 'utc')::date, 1, case when p_ok then 0 else 1 end)
  on conflict (account_id, day) do update
    set calls = u.calls + 1, failures = u.failures + case when p_ok then 0 else 1 end
  returning calls;
$$;

-- Keep the call log small (Render / Supabase free tier): delete checks older than p_days.
create or replace function ops.prune_carrier_api_checks(p_days int default 90) returns int
language sql security invoker set search_path = ops, pg_temp as $$
  with d as (delete from ops.carrier_api_checks where checked_at < now() - make_interval(days => p_days) returning 1)
  select count(*)::int from d;
$$;

-- ---------------------------------------------------------------- accounts and settings (switched OFF)
insert into ops.shipping_accounts (id, store, carrier_id, kind, label, account_ref, credential_ref, status) values
  ('dhl-tracking-api',   null, 'dhl',   'courier', 'DHL Shipment Tracking API', null, 'DHL_API_KEY',                        'off'),
  ('fedex-tracking-api', null, 'fedex', 'courier', 'FedEx Track API',           null, 'FEDEX_CLIENT_ID / FEDEX_CLIENT_SECRET', 'off')
on conflict (id) do nothing;

insert into ops.settings (key, value, note, updated_by) values
  ('carrier_tracking',
   '{"dhl":{"enabled":false,"account":"dhl-tracking-api","every_hours":6,"daily_limit":250,"carriers":["dhl","dhl_ecommerce"]},
     "fedex":{"enabled":false,"account":"fedex-tracking-api","every_hours":6,"daily_limit":null,"batch_size":30,"carriers":["fedex"]},
     "stop_after_days":60,"keep_checks_days":90}',
   'Ask DHL / FedEx for tracking. Off until the API keys are in Flowmerce/.env. daily_limit: check your carrier plan (DHL default 250/day).',
   'seed')
on conflict (key) do nothing;

-- ---------------------------------------------------------------- status words (source carrier_api)
-- DHL Unified API status.statusCode (lower-case in the answer; compared upper-case).
insert into ops.status_map (source, carrier_id, raw_status, status, is_terminal, confirms_delivery, note)
select 'carrier_api', c.id, v.raw, v.status, v.term, v.conf, v.note
from (values ('dhl'), ('dhl_ecommerce')) c(id)
cross join (values
  ('PRE-TRANSIT', 'info_received', false, false, 'Label made; DHL has not picked up'),
  ('TRANSIT',     'in_transit',    false, false, 'Includes "with delivery courier"; see status_text for out-for-delivery'),
  ('DELIVERED',   'delivered',     true,  true,  'Carrier-confirmed delivery'),
  ('FAILURE',     'exception',     false, false, 'Delivery failed or shipment problem'),
  ('UNKNOWN',     'pending',       false, false, 'DHL has no status yet')
) v(raw, status, term, conf, note)
on conflict (source, carrier_id, raw_status) do nothing;

-- FedEx Track API latestStatusDetail.code. Confirm against the first live answers and add any new code here.
insert into ops.status_map (source, carrier_id, raw_status, status, is_terminal, confirms_delivery, note) values
  ('carrier_api','fedex','OC', 'info_received',    false, false, 'Label created'),
  ('carrier_api','fedex','IN', 'info_received',    false, false, 'Shipment information sent to FedEx'),
  ('carrier_api','fedex','PU', 'in_transit',       false, false, 'Picked up'),
  ('carrier_api','fedex','IT', 'in_transit',       false, false, 'In transit'),
  ('carrier_api','fedex','AR', 'in_transit',       false, false, 'Arrived at FedEx location'),
  ('carrier_api','fedex','DP', 'in_transit',       false, false, 'Left FedEx location'),
  ('carrier_api','fedex','AF', 'in_transit',       false, false, 'At FedEx facility'),
  ('carrier_api','fedex','CC', 'in_transit',       false, false, 'Cleared customs'),
  ('carrier_api','fedex','OD', 'out_for_delivery', false, false, 'On FedEx vehicle for delivery'),
  ('carrier_api','fedex','HL', 'out_for_delivery', false, false, 'Held at location for pickup'),
  ('carrier_api','fedex','DL', 'delivered',        true,  true,  'Carrier-confirmed delivery'),
  ('carrier_api','fedex','DE', 'exception',        false, false, 'Delivery exception'),
  ('carrier_api','fedex','SE', 'exception',        false, false, 'Shipment exception'),
  ('carrier_api','fedex','CD', 'exception',        false, false, 'Clearance delay'),
  ('carrier_api','fedex','DY', 'exception',        false, false, 'Delay'),
  ('carrier_api','fedex','CA', 'exception',        false, false, 'Shipment cancelled'),
  ('carrier_api','fedex','RS', 'returned',         true,  false, 'Returned to shipper')
on conflict (source, carrier_id, raw_status) do nothing;

-- ---------------------------------------------------------------- view: what to check next
create or replace view ops.carrier_tracking_due with (security_invoker = true) as
select t.id as tracking_id, t.carrier_id, t.tracking_number, t.store, t.status,
       t.last_checked_at, t.last_check_ok_at, t.check_attempts, t.registered_at
from ops.tracking_numbers t
where t.active
  and t.carrier_id in ('dhl','dhl_ecommerce','fedex')
  and t.status not in ('delivered','returned','expired')
  and t.registered_at > now() - interval '60 days'
  and (t.last_checked_at is null or t.last_checked_at < now() - interval '6 hours')
order by t.last_checked_at nulls first, t.registered_at;
comment on view ops.carrier_tracking_due is 'Open DHL / FedEx numbers not checked in 6 hours, oldest check first. The job also reads settings.carrier_tracking.';

-- ---------------------------------------------------------------- security (same rules as 080)
alter table ops.carrier_tracking   enable row level security;
alter table ops.carrier_api_checks enable row level security;
alter table ops.carrier_api_usage  enable row level security;
revoke all on ops.carrier_tracking, ops.carrier_api_checks, ops.carrier_api_usage, ops.carrier_tracking_due from public;
revoke execute on function ops.bump_carrier_api_usage(text, boolean), ops.prune_carrier_api_checks(int) from public;

do $$
begin
  if exists (select 1 from pg_roles where rolname = 'service_role') then
    execute 'grant select, insert, update, delete on ops.carrier_tracking, ops.carrier_api_checks, ops.carrier_api_usage to service_role';
    execute 'grant select on ops.carrier_tracking_due to service_role';
    execute 'grant usage, select on all sequences in schema ops to service_role';
    execute 'grant execute on function ops.bump_carrier_api_usage(text, boolean), ops.prune_carrier_api_checks(int) to service_role';
  end if;
  if exists (select 1 from pg_roles where rolname = 'anon') then
    execute 'revoke all on ops.carrier_tracking, ops.carrier_api_checks, ops.carrier_api_usage, ops.carrier_tracking_due from anon, authenticated';
    execute 'revoke execute on function ops.bump_carrier_api_usage(text, boolean), ops.prune_carrier_api_checks(int) from anon, authenticated';
  end if;
  if exists (select 1 from pg_roles where rolname = 'flowmerce_app') then
    execute 'grant select, insert, update, delete on ops.carrier_tracking, ops.carrier_api_checks, ops.carrier_api_usage to flowmerce_app';
    execute 'grant select on ops.carrier_tracking_due to flowmerce_app';
    execute 'grant usage, select on all sequences in schema ops to flowmerce_app';
    execute 'grant execute on function ops.bump_carrier_api_usage(text, boolean), ops.prune_carrier_api_checks(int) to flowmerce_app';
  end if;
end $$;

-- ---------------------------------------------------------------- bookkeeping
insert into ops.schema_migrations (file, note)
values ('116_carrier_tracking.sql', 'DHL + FedEx tracking: carrier_tracking, carrier_api_checks, carrier_api_usage, status words, due view')
on conflict (file) do update set applied_at = now();

notify pgrst, 'reload schema';
