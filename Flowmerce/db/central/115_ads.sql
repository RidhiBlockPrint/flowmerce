-- =====================================================================================
-- Flowmerce central database · 115 · Ads (Meta Ads + Google Ads, read-only sync)
-- Safe to run more than once. Creates the schema `ads`; reads ops.stores; never writes ops.*,
-- seo.*, cro.* or public.*.
--
-- What lives here (the smallest set the Marketing Intelligence MVP needs; the fuller design in
-- db/schema.sql keeps breakdowns, keywords, search terms and change history for later):
--   ads.ad_account    one row per ad account per platform, linked to a store
--   ads.campaign      campaigns of both platforms in one table
--   ads.ad_group      Meta ad set / Google ad group or asset group
--   ads.ad            the individual ad, with the creative text Creative Strategist reads
--   ads.daily_metric  one row per day per entity: spend, impressions, clicks, purchases, video
--   ads.sync_state    one row per account: the sync cursor, the last result, the running lock
--   ads.v_ad_daily    view: ad-level metrics with their campaign, account and store
--
-- Naming follows the existing central files (schema `ops`, store ids 'RBP' / 'CPC'), not the
-- uuid/core.store draft in db/schema.sql: ops.stores is the table every other module already uses.
--
-- No personal data: only aggregated platform figures and the ads' own text.
--
-- After running: Project Settings -> Data API -> Exposed schemas -> add "ads" (next to "ops", "cro").
-- =====================================================================================

create schema if not exists ads;
comment on schema ads is 'Flowmerce Ads module: Meta and Google ad accounts, campaigns, ads and their daily metrics. Read-only copies of what the platforms report.';

-- ---------------------------------------------------------------- ad_account
create table if not exists ads.ad_account (
  id            bigint generated always as identity primary key,
  store         text not null references ops.stores(id),
  platform      text not null check (platform in ('meta', 'google')),
  external_id   text not null check (length(btrim(external_id)) between 1 and 100),  -- act_123... / 1234567890
  name          text not null default '',
  currency      text not null default '',
  timezone      text not null default '',
  status        text not null default '',
  is_active     boolean not null default true,          -- false = stop syncing it, keep its history
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  unique (platform, external_id)
);
comment on table ads.ad_account is 'One ad account per platform per store. external_id is the platform id: Meta act_<digits>, Google the 10-digit customer id without dashes.';
comment on column ads.ad_account.is_active is 'false stops the sync for this account without deleting the figures already copied.';
create index if not exists ad_account_store on ads.ad_account (store, platform);

drop trigger if exists ad_account_updated_at on ads.ad_account;
create trigger ad_account_updated_at before update on ads.ad_account
  for each row execute function ops.set_updated_at();

-- ---------------------------------------------------------------- campaign
create table if not exists ads.campaign (
  id               bigint generated always as identity primary key,
  account_id       bigint not null references ads.ad_account(id) on delete cascade,
  platform         text not null check (platform in ('meta', 'google')),
  external_id      text not null check (length(btrim(external_id)) between 1 and 100),
  name             text not null default '',
  objective        text,                                 -- Meta objective / Google advertising channel type
  status           text not null default '',
  daily_budget     numeric(14,2) check (daily_budget is null or daily_budget >= 0),
  lifetime_budget  numeric(14,2) check (lifetime_budget is null or lifetime_budget >= 0),
  campaign_key     text,                                 -- lower(name) or the utm_campaign used to join Shopify orders
  started_at       timestamptz,
  ended_at         timestamptz,
  src_updated_at   timestamptz,                          -- the platform's own "last changed" time
  synced_at        timestamptz not null default now(),
  unique (platform, external_id)
);
comment on table ads.campaign is 'Campaigns of both platforms. campaign_key is the normalised value used to match utm_campaign on Shopify orders.';
create index if not exists campaign_account on ads.campaign (account_id);
create index if not exists campaign_key_idx on ads.campaign (campaign_key);

-- ---------------------------------------------------------------- ad_group
-- Meta calls it an ad set, Google an ad group (or asset group for Performance Max).
create table if not exists ads.ad_group (
  id                 bigint generated always as identity primary key,
  campaign_id        bigint not null references ads.campaign(id) on delete cascade,
  platform           text not null check (platform in ('meta', 'google')),
  external_id        text not null check (length(btrim(external_id)) between 1 and 100),
  kind               text not null default 'ad_group' check (kind in ('ad_set', 'ad_group', 'asset_group')),
  name               text not null default '',
  status             text not null default '',
  daily_budget       numeric(14,2) check (daily_budget is null or daily_budget >= 0),
  optimization_goal  text,
  synced_at          timestamptz not null default now(),
  unique (platform, external_id)
);
comment on table ads.ad_group is 'Meta ad set / Google ad group or asset group. Targeting details are not copied: Flowmerce only reads performance.';
create index if not exists ad_group_campaign on ads.ad_group (campaign_id);

-- ---------------------------------------------------------------- ad
-- The creative text lives here because Creative Strategist reads it to tell hooks and angles apart.
create table if not exists ads.ad (
  id               bigint generated always as identity primary key,
  ad_group_id      bigint not null references ads.ad_group(id) on delete cascade,
  platform         text not null check (platform in ('meta', 'google')),
  external_id      text not null check (length(btrim(external_id)) between 1 and 100),
  name             text not null default '',
  status           text not null default '',
  ad_format        text,                                  -- image, video, carousel, rsa, pmax_asset
  headline         text,
  primary_text     text,
  call_to_action   text,
  destination_url  text,
  url_tags         text,                                  -- the UTM template set on the ad
  thumbnail_url    text,
  src_created_at   timestamptz,
  synced_at        timestamptz not null default now(),
  unique (platform, external_id)
);
comment on table ads.ad is 'One row per ad. headline / primary_text are the ad''s own copy, which Creative Strategist groups into hooks and angles.';
comment on column ads.ad.url_tags is 'The ad''s UTM template. Without utm_content={{ad.id}} (Meta) or {creative} (Google) an order cannot be traced back to this ad.';
create index if not exists ad_group_idx on ads.ad (ad_group_id);

-- ---------------------------------------------------------------- daily_metric
-- One row per day per entity, exactly as the platform reported it. level says which table entity_id
-- points at, so a foreign key is not possible; the sync only ever writes ids it has just stored.
create table if not exists ads.daily_metric (
  metric_date         date not null,
  level               text not null check (level in ('account', 'campaign', 'ad_group', 'ad')),
  entity_id           bigint not null,
  platform            text not null check (platform in ('meta', 'google')),
  spend               numeric(14,2) not null default 0 check (spend >= 0),
  impressions         bigint not null default 0 check (impressions >= 0),
  reach               bigint check (reach is null or reach >= 0),
  frequency           numeric(8,3) check (frequency is null or frequency >= 0),
  clicks              bigint not null default 0 check (clicks >= 0),
  link_clicks         bigint check (link_clicks is null or link_clicks >= 0),
  landing_page_views  bigint check (landing_page_views is null or landing_page_views >= 0),
  add_to_cart         numeric(14,2) check (add_to_cart is null or add_to_cart >= 0),
  initiate_checkout   numeric(14,2) check (initiate_checkout is null or initiate_checkout >= 0),
  purchases           numeric(14,2) check (purchases is null or purchases >= 0),   -- fractional on Google
  purchase_value      numeric(14,2) check (purchase_value is null or purchase_value >= 0),
  video_3s_views      bigint check (video_3s_views is null or video_3s_views >= 0),
  video_thruplays     bigint check (video_thruplays is null or video_thruplays >= 0),
  currency            text not null default '',
  pulled_at           timestamptz not null default now(),
  primary key (metric_date, level, entity_id)
);
comment on table ads.daily_metric is 'Platform-reported figures, one row per day per entity. purchases/purchase_value are what the platform claims; Shopify orders are the store-side truth.';
comment on column ads.daily_metric.entity_id is 'Points at ads.ad_account / campaign / ad_group / ad depending on level. No foreign key: one table holds all four levels.';
create index if not exists daily_metric_recent on ads.daily_metric (level, metric_date desc);
create index if not exists daily_metric_entity on ads.daily_metric (entity_id, metric_date desc);

-- ---------------------------------------------------------------- sync_state
-- One row per account: how far the sync has read, what happened last time, and a lock so two
-- processes never sync the same account at once (the hosted copy and a laptop can both be running).
create table if not exists ads.sync_state (
  account_id      bigint primary key references ads.ad_account(id) on delete cascade,
  since_date      date,                                  -- the first day still to re-read (platforms restate recent days)
  last_run_at     timestamptz,
  last_state      text not null default 'not_run_yet'
                  check (last_state in ('not_run_yet', 'ok', 'failed', 'skipped')),
  last_error      text check (last_error is null or length(last_error) <= 500),
  rows_written    integer not null default 0 check (rows_written >= 0),
  running_since   timestamptz,                           -- not null = a sync is in progress
  updated_at      timestamptz not null default now()
);
comment on table ads.sync_state is 'Per-account sync cursor, last result and lock. last_error never contains a token or a URL.';

drop trigger if exists sync_state_updated_at on ads.sync_state;
create trigger sync_state_updated_at before update on ads.sync_state
  for each row execute function ops.set_updated_at();

-- ---------------------------------------------------------------- begin_sync / end_sync
-- Same shape as the CRO sync lock: take the lock and read the cursor in one call, so two processes
-- cannot both start. A lock older than p_stale_minutes is treated as a crashed run and taken over.
create or replace function ads.begin_sync(p_account_id bigint, p_stale_minutes integer default 30)
returns table (got_lock boolean, since_date date)
language plpgsql security invoker set search_path = ads, pg_temp as $$
declare
  v_since date;
begin
  insert into ads.sync_state (account_id) values (p_account_id)
  on conflict (account_id) do nothing;

  update ads.sync_state s
     set running_since = now()
   where s.account_id = p_account_id
     and (s.running_since is null
          or s.running_since < now() - make_interval(mins => greatest(p_stale_minutes, 1)))
  returning s.since_date into v_since;

  if not found then
    return query select false, null::date;
  else
    return query select true, v_since;
  end if;
end $$;
comment on function ads.begin_sync(bigint, integer) is 'Takes the per-account sync lock and returns the cursor. got_lock = false means another process is already syncing this account.';

create or replace function ads.end_sync(
  p_account_id bigint,
  p_state text,
  p_since_date date default null,
  p_rows integer default 0,
  p_error text default null
) returns void
language plpgsql security invoker set search_path = ads, pg_temp as $$
begin
  if p_state not in ('ok', 'failed', 'skipped') then
    raise exception 'end_sync: unknown state %', p_state using errcode = '22023';
  end if;
  update ads.sync_state
     set running_since = null,
         last_run_at   = now(),
         last_state    = p_state,
         last_error    = left(p_error, 500),
         rows_written  = greatest(coalesce(p_rows, 0), 0),
         -- the cursor only moves forward, and only on a successful run
         since_date    = case when p_state = 'ok' and p_since_date is not null
                              then p_since_date else since_date end
   where account_id = p_account_id;
end $$;
comment on function ads.end_sync(bigint, text, date, integer, text) is 'Releases the sync lock and records the result. The cursor moves only after a successful run.';

-- ---------------------------------------------------------------- v_ad_daily (view)
-- What the Ads page and Creative Strategist read: one row per ad per day with its names and store.
-- Derived rates are left to the backend so the definitions live in one place (Python).
create or replace view ads.v_ad_daily with (security_invoker = true) as
select m.metric_date,
       a.id                as ad_id,
       a.platform,
       acc.store,
       acc.id              as account_id,
       c.id                as campaign_id,
       c.name              as campaign_name,
       g.id                as ad_group_id,
       g.name              as ad_group_name,
       a.name              as ad_name,
       a.headline,
       a.primary_text,
       a.ad_format,
       a.status            as ad_status,
       m.spend,
       m.impressions,
       m.clicks,
       m.link_clicks,
       m.purchases,
       m.purchase_value,
       m.video_3s_views,
       m.video_thruplays,
       m.currency
from ads.daily_metric m
join ads.ad a          on a.id = m.entity_id and m.level = 'ad'
join ads.ad_group g    on g.id = a.ad_group_id
join ads.campaign c    on c.id = g.campaign_id
join ads.ad_account acc on acc.id = c.account_id;
comment on view ads.v_ad_daily is 'Ad-level daily figures with campaign, account and store names. Rates (CTR, ROAS, hook rate) are worked out in the backend.';

-- ---------------------------------------------------------------- security (same rules as 080 / 112)
-- RLS on, no policies: the browser keys (anon, authenticated) can read nothing. Only the backend's
-- service_role (and flowmerce_app, for a direct connection later) may read and write.
alter table ads.ad_account   enable row level security;
alter table ads.campaign     enable row level security;
alter table ads.ad_group     enable row level security;
alter table ads.ad           enable row level security;
alter table ads.daily_metric enable row level security;
alter table ads.sync_state   enable row level security;

revoke all on all tables in schema ads from public;

do $$
begin
  if exists (select 1 from pg_roles where rolname = 'service_role') then
    execute 'grant usage on schema ads to service_role';
    execute 'grant select, insert, update, delete on all tables in schema ads to service_role';
    execute 'grant usage, select on all sequences in schema ads to service_role';
    execute 'grant execute on all functions in schema ads to service_role';
    execute 'alter default privileges in schema ads grant select, insert, update, delete on tables to service_role';
    execute 'alter default privileges in schema ads grant usage, select on sequences to service_role';
  end if;
  if exists (select 1 from pg_roles where rolname = 'anon') then
    execute 'revoke all on all tables in schema ads from anon, authenticated';
    execute 'revoke all on schema ads from anon, authenticated';
  end if;
  if exists (select 1 from pg_roles where rolname = 'flowmerce_app') then
    execute 'grant usage on schema ads to flowmerce_app';
    execute 'grant select, insert, update, delete on all tables in schema ads to flowmerce_app';
    execute 'grant usage, select on all sequences in schema ads to flowmerce_app';
    execute 'grant execute on all functions in schema ads to flowmerce_app';
  end if;
end $$;

-- ---------------------------------------------------------------- bookkeeping
insert into ops.schema_migrations (file, note)
values ('115_ads.sql', 'schema ads: ad_account, campaign, ad_group, ad, daily_metric, sync_state, v_ad_daily view')
on conflict (file) do update set applied_at = now();

notify pgrst, 'reload schema';
