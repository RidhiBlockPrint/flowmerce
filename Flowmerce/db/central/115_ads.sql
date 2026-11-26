-- =====================================================================================
-- Flowmerce central database · 115 · Ads module (Meta Ads now; Google Ads later in the same tables)
-- Safe to run more than once. Creates the schema `ads`; reads cro.orders (store sales) and ops.stores; never writes
-- ops.*, cro.*, seo.* or public.*.
--
-- What lives here:
--   ads.accounts        one row per ad account Flowmerce reads ('meta:ridhi', 'meta:cpc'): name, currency, time zone,
--                       and the sync state (lock, last run, last full re-read, sign-in expiry)
--   ads.campaigns       campaigns with their budget (account currency) and when the budget last changed
--   ads.ad_sets         ad sets with their budget
--   ads.ads             ads with their post (to match copies across campaigns), format, video length and lifetime totals
--   ads.daily           one row per ad per account day: spend, impressions, clicks, page views, carts, checkouts,
--                       purchases, purchase value and video views. Amounts in the account's currency.
--   ads.fx_rates        what one US dollar costs in another currency, from a day on (Ridhi's Meta account is in INR)
--   ads.rules           per brand: the thresholds edited on the Rules tab (anything missing uses the app's default)
--   ads.action_status   per brand: suggestions the team marked done or skipped
--   ads.action_history  every time a suggestion was marked, newest first
--
-- Functions (the backend's REST client cannot run SQL, so it calls these):
--   begin_sync / end_sync   per-account lock; a lock older than 45 minutes counts as abandoned
--   replace_daily           replaces an account's daily rows for a span of days in one transaction
--   account_days            per day totals for one account, converted to US dollars at each day's rate
--   ad_windows              per ad totals for the chosen days, the days before, and the last 3, 7 and 14 days
--   store_days              store orders and sales per store-local day from cro.orders, with bulk orders apart
--   reopen_action           marks a suggestion open again
--   save_lifetime           all ads' lifetime totals in one call
--
-- No personal data: ad accounts hold none, and store_days returns daily sums only.
-- Secrets: the Meta and Google keys stay in the server's .env; nothing secret is stored here.
--
-- After running: Project Settings -> Data API -> Exposed schemas -> add "ads" (next to "ops" and "cro").
-- =====================================================================================

create schema if not exists ads;
comment on schema ads is 'Flowmerce Ads module: Meta (and later Google) ad accounts, daily figures, rules and action status.';

-- ---------------------------------------------------------------- accounts (+ sync state)
create table if not exists ads.accounts (
  key               text primary key check (key ~ '^(meta|google):[a-z]+$'),   -- 'meta:ridhi'
  brand             text not null check (brand in ('ridhi', 'cpc')),
  platform          text not null check (platform in ('meta', 'google')),
  external_id       text not null,                                            -- act_123 / 1234567890
  name              text not null default '',
  currency          char(3) not null default 'USD',
  timezone          text not null default 'UTC',
  account_status    int,
  token_expires_at  timestamptz,                                              -- null = never or unknown
  running_since     timestamptz,                                              -- set while a sync runs (the lock)
  last_run_at       timestamptz,
  last_status       text check (last_status in ('ok', 'failed')),
  last_error        text,
  last_full_at      timestamptz,                                              -- last re-read of 28 days + lifetime totals
  first_day         date,                                                     -- oldest day loaded
  updated_at        timestamptz not null default now(),
  unique (brand, platform)
);
comment on table ads.accounts is 'One row per ad account Flowmerce reads, with its sync state. running_since is the lock.';

-- ---------------------------------------------------------------- campaigns / ad sets / ads
create table if not exists ads.campaigns (
  id                 text primary key,
  account_key        text not null references ads.accounts(key) on delete cascade,
  name               text not null,
  objective          text,
  status             text not null,                      -- the effective status: ACTIVE, PAUSED, ...
  daily_budget       numeric(14,2),                      -- account currency, major units; null = budget per ad set
  lifetime_budget    numeric(14,2),
  bid_strategy       text,
  created_time       timestamptz,
  budget_changed_at  timestamptz,                        -- last budget change seen (Meta's activity log or a sync)
  synced_at          timestamptz not null default now()
);
create index if not exists ads_campaigns_account on ads.campaigns (account_key);

create table if not exists ads.ad_sets (
  id                 text primary key,
  account_key        text not null references ads.accounts(key) on delete cascade,
  campaign_id        text not null,
  name               text not null,
  status             text not null,
  daily_budget       numeric(14,2),
  optimization_goal  text,
  synced_at          timestamptz not null default now()
);
create index if not exists ads_ad_sets_account on ads.ad_sets (account_key);

create table if not exists ads.ads (
  id              text primary key,
  account_key     text not null references ads.accounts(key) on delete cascade,
  campaign_id     text not null,
  ad_set_id       text not null,
  name            text not null,
  status          text not null,
  created_time    timestamptz,
  post_id         text,                                  -- the Facebook post: the same post in two campaigns is one creative
  format          text not null default 'image' check (format in ('image', 'video')),
  video_id        text,
  video_length_s  numeric(8,1),                          -- not readable with ads_read only (Meta, 2026-11-24)
  thumbnail_url   text,
  lt_spend        numeric(14,2),                         -- lifetime totals, account currency, refreshed by the full re-read
  lt_purchases    numeric(12,2),
  lt_value        numeric(14,2),
  lt_at           timestamptz,
  synced_at       timestamptz not null default now()
);
create index if not exists ads_ads_account on ads.ads (account_key);
create index if not exists ads_ads_post on ads.ads (post_id);

-- ---------------------------------------------------------------- daily figures
create table if not exists ads.daily (
  ad_id        text not null,
  day          date not null,                            -- the ad account's own day
  account_key  text not null references ads.accounts(key) on delete cascade,
  spend        numeric(14,2) not null default 0,         -- account currency
  impressions  bigint not null default 0,
  clicks       bigint not null default 0,                -- outbound clicks
  link_clicks  bigint not null default 0,
  lpv          bigint not null default 0,                -- landing page views
  atc          bigint not null default 0,                -- add to cart (website + app)
  ic           bigint not null default 0,                -- checkout started (website + app)
  purchases    numeric(12,2) not null default 0,
  value        numeric(14,2) not null default 0,         -- purchase value, account currency
  v3           bigint not null default 0,                -- 3-second video views
  p25          bigint not null default 0,
  p50          bigint not null default 0,
  p75          bigint not null default 0,
  p95          bigint not null default 0,
  plays        bigint not null default 0,
  watch_s      numeric(16,1) not null default 0,         -- average watch time x plays, so days can be added up
  primary key (ad_id, day)
);
comment on table ads.daily is 'One row per ad per account day with delivery. A day an ad did not run has no row.';
create index if not exists ads_daily_account_day on ads.daily (account_key, day);

-- ---------------------------------------------------------------- exchange rates
create table if not exists ads.fx_rates (
  currency    char(3) not null check (currency <> 'USD'),
  valid_from  date not null,
  rate        numeric(12,4) not null check (rate > 0),   -- units of `currency` for one US dollar
  set_by      text,
  set_at      timestamptz not null default now(),
  primary key (currency, valid_from)
);
comment on table ads.fx_rates is 'Rate for one US dollar from valid_from on. Each day uses the newest rate on or before it.';
-- Starting rate: the Daily sheet's assumption (Rs 88). Changed from the Rules tab; earlier days keep their rate.
insert into ads.fx_rates (currency, valid_from, rate, set_by)
values ('INR', date '2000-01-01', 88, 'default (Daily sheet, 24 Oct 2026)')
on conflict (currency, valid_from) do nothing;

-- ---------------------------------------------------------------- rules and actions
create table if not exists ads.rules (
  brand       text primary key check (brand in ('ridhi', 'cpc')),
  rules       jsonb not null default '{}'::jsonb,        -- only the values the team changed
  updated_by  text,
  updated_at  timestamptz not null default now()
);

create table if not exists ads.action_status (
  brand       text not null check (brand in ('ridhi', 'cpc')),
  action_id   text not null check (length(action_id) between 1 and 200),
  status      text not null check (status in ('done', 'skipped')),
  updated_by  text,
  updated_at  timestamptz not null default now(),
  primary key (brand, action_id)
);
comment on table ads.action_status is 'Suggestions the team marked done or skipped. A suggestion without a row is open.';

create table if not exists ads.action_history (
  id         bigint generated always as identity primary key,
  brand      text not null check (brand in ('ridhi', 'cpc')),
  action_id  text not null,
  title      text not null default '',
  grp        text not null default '',
  status     text not null check (status in ('open', 'done', 'skipped')),
  by_user    text,
  at         timestamptz not null default now()
);
create index if not exists ads_action_history_brand on ads.action_history (brand, at desc);

-- ---------------------------------------------------------------- begin_sync / end_sync
create or replace function ads.begin_sync(p_key text)
returns table (got_lock boolean, full_at timestamptz, loaded_from date)
language plpgsql security invoker set search_path = ads, pg_temp as $$
begin
  return query
    with taken as (
      update ads.accounts a set running_since = now()
       where a.key = p_key
         and (a.running_since is null or a.running_since < now() - interval '45 minutes')
      returning a.last_full_at as lf, a.first_day as fd
    )
    select true, taken.lf, taken.fd from taken;
end $$;

create or replace function ads.end_sync(p_key text, p_ok boolean, p_error text, p_full boolean, p_first_day date)
returns void
language plpgsql security invoker set search_path = ads, pg_temp as $$
begin
  update ads.accounts set
    running_since = null,
    last_run_at   = now(),
    last_status   = case when p_ok then 'ok' else 'failed' end,
    last_error    = case when p_ok then null else left(p_error, 1000) end,
    last_full_at  = case when p_ok and p_full then now() else last_full_at end,
    first_day     = case when p_ok and p_first_day is not null then least(coalesce(first_day, p_first_day), p_first_day) else first_day end,
    updated_at    = now()
  where key = p_key;
end $$;

-- ---------------------------------------------------------------- replace_daily
-- Replaces the account's rows for p_from..p_to with p_rows (a JSON array of ads.daily rows without account_key).
-- An ad that stopped running on a day re-read here loses its old row. Returns the number of rows written.
create or replace function ads.replace_daily(p_key text, p_from date, p_to date, p_rows jsonb)
returns int
language plpgsql security invoker set search_path = ads, pg_temp as $$
declare
  n int;
begin
  delete from ads.daily where account_key = p_key and day between p_from and p_to;
  insert into ads.daily (ad_id, day, account_key, spend, impressions, clicks, link_clicks, lpv, atc, ic, purchases,
                         value, v3, p25, p50, p75, p95, plays, watch_s)
  select x.ad_id, x.day, p_key, coalesce(x.spend, 0), coalesce(x.impressions, 0), coalesce(x.clicks, 0),
         coalesce(x.link_clicks, 0), coalesce(x.lpv, 0), coalesce(x.atc, 0), coalesce(x.ic, 0),
         coalesce(x.purchases, 0), coalesce(x.value, 0), coalesce(x.v3, 0), coalesce(x.p25, 0), coalesce(x.p50, 0),
         coalesce(x.p75, 0), coalesce(x.p95, 0), coalesce(x.plays, 0), coalesce(x.watch_s, 0)
  from jsonb_to_recordset(p_rows) as x(
    ad_id text, day date, spend numeric, impressions bigint, clicks bigint, link_clicks bigint, lpv bigint, atc bigint,
    ic bigint, purchases numeric, value numeric, v3 bigint, p25 bigint, p50 bigint, p75 bigint, p95 bigint,
    plays bigint, watch_s numeric)
  where x.day between p_from and p_to;
  get diagnostics n = row_count;
  return n;
end $$;

-- ---------------------------------------------------------------- save_lifetime
-- One call instead of one request per ad. Ads that are not in ads.ads (deleted ones) are skipped.
create or replace function ads.save_lifetime(p_key text, p_at timestamptz, p_rows jsonb)
returns int
language plpgsql security invoker set search_path = ads, pg_temp as $$
declare
  n int;
begin
  update ads.ads a set lt_spend = x.spend, lt_purchases = x.purchases, lt_value = x.value, lt_at = p_at
  from jsonb_to_recordset(p_rows) as x(ad_id text, spend numeric, purchases numeric, value numeric)
  where a.id = x.ad_id and a.account_key = p_key;
  get diagnostics n = row_count;
  return n;
end $$;

-- ---------------------------------------------------------------- reopen_action
-- The backend's REST client only inserts, updates and calls functions, so marking a suggestion open again (removing
-- its done / skipped row) goes through this function. Returns true when a row was removed.
create or replace function ads.reopen_action(p_brand text, p_action_id text)
returns boolean
language plpgsql security invoker set search_path = ads, pg_temp as $$
begin
  delete from ads.action_status where brand = p_brand and action_id = p_action_id;
  return found;
end $$;

-- ---------------------------------------------------------------- rate of a day
-- Units of the account's currency per US dollar on a day: 1 for USD, else the newest ads.fx_rates row on or before it.
create or replace function ads.rate_on(p_currency text, p_day date)
returns numeric
language sql stable security invoker set search_path = ads, pg_temp as $$
  select case when p_currency = 'USD' then 1::numeric
              else (select r.rate from ads.fx_rates r where r.currency = p_currency and r.valid_from <= p_day
                    order by r.valid_from desc limit 1) end
$$;

-- ---------------------------------------------------------------- account_days
create or replace function ads.account_days(p_key text, p_from date, p_to date)
returns table (day date, spend numeric, value numeric, impressions bigint, vimp bigint, clicks bigint,
               link_clicks bigint, lpv bigint, atc bigint, ic bigint, purchases numeric, v3 bigint, rate numeric)
language sql stable security invoker set search_path = ads, pg_temp as $$
  with acc as (select currency from ads.accounts where key = p_key)
  select d.day,
         round(sum(d.spend) / ads.rate_on((select currency from acc), d.day), 2),
         round(sum(d.value) / ads.rate_on((select currency from acc), d.day), 2),
         sum(d.impressions)::bigint,
         coalesce(sum(d.impressions) filter (where a.format = 'video'), 0)::bigint,
         sum(d.clicks)::bigint, sum(d.link_clicks)::bigint, sum(d.lpv)::bigint, sum(d.atc)::bigint, sum(d.ic)::bigint,
         sum(d.purchases), sum(d.v3)::bigint, ads.rate_on((select currency from acc), d.day)
  from ads.daily d
  left join ads.ads a on a.id = d.ad_id
  where d.account_key = p_key and d.day between p_from and p_to
  group by d.day
  order by d.day
$$;

-- ---------------------------------------------------------------- ad_windows
-- Per ad and window: 'cur' (p_from..p_to), 'prev' (p_prev_from..p_prev_to), 'd3', 'd7', 'd14' (the last 3, 7, 14
-- days ending p_to). Money in US dollars at each day's rate. Only ads with a row in a window appear in it.
create or replace function ads.ad_windows(p_key text, p_from date, p_to date, p_prev_from date, p_prev_to date)
returns table (ad_id text, w text, spend numeric, value numeric, impressions bigint, clicks bigint, lpv bigint,
               atc bigint, ic bigint, purchases numeric, v3 bigint, p25 bigint, p50 bigint, p75 bigint, p95 bigint,
               plays bigint, watch_s numeric)
language sql stable security invoker set search_path = ads, pg_temp as $$
  with acc as (select currency from ads.accounts where key = p_key),
  win(w, f, t) as (values ('cur', p_from, p_to), ('prev', p_prev_from, p_prev_to), ('d3', p_to - 2, p_to),
                          ('d7', p_to - 6, p_to), ('d14', p_to - 13, p_to)),
  src as (
    select d.*, ads.rate_on((select currency from acc), d.day) as r
    from ads.daily d
    where d.account_key = p_key and d.day between least(p_from, p_prev_from, p_to - 13) and p_to
  )
  select x.ad_id, win.w, round(sum(x.spend / x.r), 2), round(sum(x.value / x.r), 2), sum(x.impressions)::bigint,
         sum(x.clicks)::bigint, sum(x.lpv)::bigint, sum(x.atc)::bigint, sum(x.ic)::bigint, sum(x.purchases),
         sum(x.v3)::bigint, sum(x.p25)::bigint, sum(x.p50)::bigint, sum(x.p75)::bigint, sum(x.p95)::bigint,
         sum(x.plays)::bigint, sum(x.watch_s)
  from win
  join src x on x.day between win.f and win.t
  group by x.ad_id, win.w
$$;

-- ---------------------------------------------------------------- store_days
-- Orders and sales per store-local day (p_tz: the time zone Shopify reports for the store; ops.stores.timezone is
-- not used because it is not kept up to date). Sales = the order total as placed (current total + refunded), so a
-- refund made later does not change an earlier day. Cancelled and test orders are left out. An order of p_bulk_min
-- or more is a bulk order and is also counted apart.
create or replace function ads.store_days(p_store text, p_tz text, p_from date, p_to date, p_bulk_min numeric)
returns table (day date, orders bigint, sales numeric, bulk_orders bigint, bulk_amount numeric)
language sql stable security invoker set search_path = ads, pg_temp as $$
  select (o.placed_at at time zone p_tz)::date as day,
         count(*),
         round(sum(o.total + o.refunded), 2),
         count(*) filter (where o.total + o.refunded >= p_bulk_min),
         round(coalesce(sum(o.total + o.refunded) filter (where o.total + o.refunded >= p_bulk_min), 0), 2)
  from cro.orders o
  where o.store = p_store
    and o.cancelled_at is null
    and o.placed_at >= (p_from::timestamp at time zone p_tz)
    and o.placed_at <  ((p_to + 1)::timestamp at time zone p_tz)
  group by 1
  order by 1
$$;

-- ---------------------------------------------------------------- security (same rules as 080 / 112)
-- RLS on, no policies: the browser keys (anon, authenticated) can read nothing. Only the backend's service_role
-- (and flowmerce_app, for a direct connection later) may read and write.
alter table ads.accounts       enable row level security;
alter table ads.campaigns      enable row level security;
alter table ads.ad_sets        enable row level security;
alter table ads.ads            enable row level security;
alter table ads.daily          enable row level security;
alter table ads.fx_rates       enable row level security;
alter table ads.rules          enable row level security;
alter table ads.action_status  enable row level security;
alter table ads.action_history enable row level security;

revoke all on all tables in schema ads from public;
revoke execute on all functions in schema ads from public;

do $$
begin
  if exists (select 1 from pg_roles where rolname = 'service_role') then
    execute 'grant usage on schema ads to service_role';
    execute 'grant select, insert, update, delete on all tables in schema ads to service_role';
    execute 'grant usage, select on all sequences in schema ads to service_role';
    execute 'grant execute on all functions in schema ads to service_role';
  end if;
  if exists (select 1 from pg_roles where rolname = 'anon') then
    execute 'revoke all on all tables in schema ads from anon, authenticated';
    execute 'revoke execute on all functions in schema ads from anon, authenticated';
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
values ('115_ads.sql', 'schema ads: accounts, campaigns, ad_sets, ads, daily, fx_rates, rules, action_status/history; sync and report functions')
on conflict (file) do update set applied_at = now();

notify pgrst, 'reload schema';
