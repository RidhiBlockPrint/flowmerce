-- =====================================================================================
-- Flowmerce central database · 010 · set-up tables (shared by SEO and Shipping)
-- stores · people · settings · carriers · carrier_services · shipping_accounts · status_map
-- Safe to run more than once.
-- =====================================================================================

-- ---------------------------------------------------------------- stores
create table if not exists ops.stores (
  id              text primary key,                                   -- RBP or CPC
  name            text not null,
  shopify_domain  text not null unique,
  currency        text not null default 'USD',
  timezone        text not null default 'America/Los_Angeles',
  active          boolean not null default true,
  -- FLOWMERCE ADDITION: the code the SEO module already uses ('ridhi', 'cpc').
  -- Lets seo.* keep its brand_id values unchanged while linking to this table.
  legacy_code     text unique
);
comment on table ops.stores is 'The two Shopify stores. Every other row says which store it belongs to.';
comment on column ops.stores.legacy_code is 'SEO module brand_id (ridhi/cpc). Added so the working SEO code does not have to change its ids.';

-- ---------------------------------------------------------------- people
-- id matches auth.users.id (Supabase Google sign-in) from Phase 5. The foreign key to
-- auth.users is added by 095_optional_supabase_auth.sql so this file also runs on
-- plain PostgreSQL. Until Phase 5 there is no login (owner decision D3).
create table if not exists ops.people (
  id             uuid primary key default gen_random_uuid(),
  email          text not null,
  name           text not null,
  team           text not null check (team in ('production','shipment','orders','care','corporate','admin')),
  title          text,
  is_head        boolean not null default false,
  sections       text[] not null default '{}',
  stores         text[] not null default '{RBP,CPC}',
  can_see_costs  boolean not null default false,
  active         boolean not null default true,
  created_at     timestamptz not null default now()
);
create unique index if not exists people_email_lower on ops.people (lower(email));
comment on table ops.people is 'Everyone who signs in. Team/title/head decide alerts; sections/stores decide visibility.';

-- ---------------------------------------------------------------- settings
create table if not exists ops.settings (
  key         text primary key,
  value       jsonb not null,
  note        text,
  updated_by  text,
  updated_at  timestamptz not null default now()
);
comment on table ops.settings is 'Every shared rule: write switches (off by default), working hours, step limits, escalation, reason lists, GST numbering.';
drop trigger if exists settings_updated_at on ops.settings;
create trigger settings_updated_at before update on ops.settings
  for each row execute function ops.set_updated_at();

-- ---------------------------------------------------------------- carriers
create table if not exists ops.carriers (
  id             text primary key,                                    -- dhl, fedex, amazon_logistics_us ...
  name           text not null,
  kind           text not null check (kind in ('courier','marketplace','platform','unknown')),
  shopify_name   text unique,
  tracking_slug  text,
  track_url      text,
  active         boolean not null default true
);
comment on table ops.carriers is 'Each carrier or shipping platform once. kind=unknown is a FLOWMERCE ADDITION for imported rows whose carrier cannot be identified (never guessed).';

-- ---------------------------------------------------------------- carrier_aliases  (FLOWMERCE ADDITION)
-- The tracker's real data writes one carrier several ways ("Amazon Logistics", "Amazon Logistics US",
-- "Amazon Fulfillment"; blank; "Other"). Each spelling is mapped once, here, to one carrier row.
create table if not exists ops.carrier_aliases (
  alias       text primary key,                                       -- stored lower-case, trimmed
  carrier_id  text not null references ops.carriers(id),
  note        text
);
comment on table ops.carrier_aliases is 'Spelling -> carrier. An unlisted spelling resolves to carrier unknown (never guessed).';

-- ---------------------------------------------------------------- carrier_services
create table if not exists ops.carrier_services (
  id          text primary key,
  carrier_id  text not null references ops.carriers(id),
  code        text not null,
  name        text not null,
  tier        text not null check (tier in ('express','standard','economy')),
  days_min    int check (days_min is null or days_min >= 0),
  days_max    int check (days_max is null or days_max >= 0),
  active      boolean not null default true,
  check (days_min is null or days_max is null or days_min <= days_max)
);
create unique index if not exists carrier_services_code on ops.carrier_services (carrier_id, code);
comment on table ops.carrier_services is 'Service levels with expected delivery days. days_max decides "late".';

-- ---------------------------------------------------------------- shipping_accounts
create table if not exists ops.shipping_accounts (
  id              text primary key,
  store           text references ops.stores(id),                    -- null = shared by both stores
  carrier_id      text references ops.carriers(id),                  -- null for the tracking service
  kind            text not null check (kind in ('amazon_mcf','courier','platform','tracking_service')),
  label           text not null unique,
  account_ref     text,                                               -- partly hidden; not a secret
  marketplace     text,
  credential_ref  text,                                               -- NAME of the secret, never the secret
  status          text not null default 'active' check (status in ('active','expired','off')),
  last_ok_at      timestamptz
);
comment on table ops.shipping_accounts is 'Accounts we ship through. Holds only a pointer to the secret, never the key.';

-- ---------------------------------------------------------------- status_map  (FLOWMERCE ADDITION)
-- The auditable mapping layer between every outside status word and the one internal
-- vocabulary. Kept as data (not code) so the team can see and fix a wrong mapping, and
-- so every scan can say which rule turned its raw status into a Flowmerce status.
create table if not exists ops.status_map (
  source       text not null check (source in ('shopify','amazon','aggregator','carrier_api','manual','tracker_import')),
  carrier_id   text not null default '*',                             -- '*' = any carrier
  raw_status   text not null,                                         -- compared upper-case, trimmed
  status       text not null check (status in ('pending','info_received','in_transit','out_for_delivery','delivered','exception','returned','expired')),
  is_terminal  boolean not null default false,                        -- delivered / returned / expired
  confirms_delivery boolean not null default false,                   -- true ONLY when the source can confirm delivery
  note         text,
  primary key (source, carrier_id, raw_status)
);
comment on table ops.status_map is 'Outside status -> Flowmerce status. Unknown raw statuses are NOT in this table and must map to pending (unverified), never delivered.';
