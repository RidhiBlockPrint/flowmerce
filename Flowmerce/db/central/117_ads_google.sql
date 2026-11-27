-- =====================================================================================
-- Flowmerce central database · 117 · Ads module: Google Ads (phase 3)
-- Safe to run more than once. Needs 115 (schema ads). Adds two tables and three functions to schema `ads`;
-- never writes ops.*, cro.*, seo.*, creative.* or public.*.
--
-- Google accounts use the existing ads.accounts rows ('google:ridhi', 'google:cpc') and the same sync lock
-- (begin_sync / end_sync), rules, action status and rupee rates as Meta.
--
-- What lives here:
--   ads.g_campaigns  Google campaigns: type (Search, Performance Max, Display, Shopping, Video, Demand Gen),
--                    status, daily budget (account currency), bid strategy
--   ads.g_daily      one row per item per account day, for five kinds of item:
--                      campaign  a campaign's day (the account totals add these up)
--                      group     an ad group (Search, Display) or asset group (Performance Max); extra = which
--                      term      a search term (Search campaigns)
--                      keyword   a keyword; label = its text, extra = match type
--                      product   a product (Performance Max and Shopping); label = its title
--                    spend, impressions, clicks, purchases and purchase value. Purchases are Google's primary
--                    purchase conversions only, without click actions (decided in the backend, see
--                    src/flowmerce/modules/ads/google_ads.py).
--
-- Functions (the backend's REST client cannot run SQL, so it calls these):
--   g_replace  replaces one kind's rows of an account for a span of days in one transaction
--   g_days     per day totals of an account's campaigns, in US dollars at each day's rate
--   g_sum      per item totals of one kind for a span of days, in US dollars
--
-- No personal data: search terms are what people typed into Google, without who typed them.
-- Secrets: the Google keys stay in the server's .env; nothing secret is stored here.
-- =====================================================================================

-- ---------------------------------------------------------------- campaigns
create table if not exists ads.g_campaigns (
  id            text primary key,
  account_key   text not null references ads.accounts(key) on delete cascade,
  name          text not null,
  channel       text not null default '',          -- SEARCH, PERFORMANCE_MAX, DISPLAY, SHOPPING, VIDEO, DEMAND_GEN
  status        text not null default '',          -- ENABLED, PAUSED, REMOVED
  daily_budget  numeric(14,2),
  bid_strategy  text,
  synced_at     timestamptz not null default now()
);
create index if not exists g_campaigns_account on ads.g_campaigns (account_key);
comment on table ads.g_campaigns is 'Google Ads campaigns with type, status and daily budget (account currency).';

-- ---------------------------------------------------------------- daily figures per item
create table if not exists ads.g_daily (
  account_key  text not null references ads.accounts(key) on delete cascade,
  kind         text not null check (kind in ('campaign', 'group', 'term', 'keyword', 'product')),
  item         text not null check (length(item) between 1 and 400),
  campaign_id  text not null default '',
  day          date not null,
  label        text not null default '',
  extra        text not null default '',
  spend        numeric(14,4) not null default 0,
  impressions  bigint not null default 0,
  clicks       bigint not null default 0,
  purchases    numeric(12,2) not null default 0,
  value        numeric(14,2) not null default 0,
  primary key (account_key, kind, item, campaign_id, day)
);
create index if not exists g_daily_span on ads.g_daily (account_key, kind, day);
comment on table ads.g_daily is 'Google Ads figures per item (campaign, group, search term, keyword, product) per account day, in the account currency.';

-- ---------------------------------------------------------------- functions
create or replace function ads.g_replace(p_key text, p_kind text, p_from date, p_to date, p_rows jsonb)
returns integer
language plpgsql security invoker set search_path = ads, pg_temp as $$
declare n integer;
begin
  delete from ads.g_daily where account_key = p_key and kind = p_kind and day between p_from and p_to;
  insert into ads.g_daily (account_key, kind, item, campaign_id, day, label, extra, spend, impressions, clicks,
                           purchases, value)
  select p_key, p_kind, x.item, coalesce(x.campaign_id, ''), x.day, left(coalesce(x.label, ''), 400),
         left(coalesce(x.extra, ''), 40), coalesce(x.spend, 0), coalesce(x.impressions, 0), coalesce(x.clicks, 0),
         coalesce(x.purchases, 0), coalesce(x.value, 0)
  from jsonb_to_recordset(coalesce(p_rows, '[]'::jsonb)) as x(
    item text, campaign_id text, day date, label text, extra text, spend numeric, impressions bigint,
    clicks bigint, purchases numeric, value numeric)
  where x.day between p_from and p_to and length(coalesce(x.item, '')) between 1 and 400
  on conflict (account_key, kind, item, campaign_id, day) do update set
    label = excluded.label, extra = excluded.extra, spend = ads.g_daily.spend + excluded.spend,
    impressions = ads.g_daily.impressions + excluded.impressions, clicks = ads.g_daily.clicks + excluded.clicks,
    purchases = ads.g_daily.purchases + excluded.purchases, value = ads.g_daily.value + excluded.value;
  get diagnostics n = row_count;
  return n;
end $$;

create or replace function ads.g_days(p_key text, p_from date, p_to date)
returns table (day date, spend numeric, value numeric, purchases numeric, impressions bigint, clicks bigint)
language sql stable security invoker set search_path = ads, pg_temp as $$
  with acc as (select currency from ads.accounts where key = p_key)
  select d.day,
         round(sum(d.spend) / ads.rate_on((select currency from acc), d.day), 2),
         round(sum(d.value) / ads.rate_on((select currency from acc), d.day), 2),
         sum(d.purchases), sum(d.impressions)::bigint, sum(d.clicks)::bigint
  from ads.g_daily d
  where d.account_key = p_key and d.kind = 'campaign' and d.day between p_from and p_to
  group by d.day
  order by d.day;
$$;

create or replace function ads.g_sum(p_key text, p_kind text, p_from date, p_to date)
returns table (item text, campaign_id text, label text, extra text, spend numeric, value numeric,
               purchases numeric, impressions bigint, clicks bigint)
language sql stable security invoker set search_path = ads, pg_temp as $$
  with acc as (select currency from ads.accounts where key = p_key)
  select d.item, d.campaign_id, max(d.label), max(d.extra),
         round(sum(d.spend / ads.rate_on((select currency from acc), d.day)), 2),
         round(sum(d.value / ads.rate_on((select currency from acc), d.day)), 2),
         sum(d.purchases), sum(d.impressions)::bigint, sum(d.clicks)::bigint
  from ads.g_daily d
  where d.account_key = p_key and d.kind = p_kind and d.day between p_from and p_to
  group by d.item, d.campaign_id;
$$;

-- ---------------------------------------------------------------- security (same rules as 115)
alter table ads.g_campaigns enable row level security;
alter table ads.g_daily     enable row level security;

revoke all on ads.g_campaigns, ads.g_daily from public;
revoke execute on function ads.g_replace(text, text, date, date, jsonb), ads.g_days(text, date, date),
  ads.g_sum(text, text, date, date) from public;

do $$
begin
  if exists (select 1 from pg_roles where rolname = 'service_role') then
    execute 'grant select, insert, update, delete on ads.g_campaigns, ads.g_daily to service_role';
    execute 'grant execute on function ads.g_replace(text, text, date, date, jsonb), ads.g_days(text, date, date), ads.g_sum(text, text, date, date) to service_role';
  end if;
  if exists (select 1 from pg_roles where rolname = 'anon') then
    execute 'revoke all on ads.g_campaigns, ads.g_daily from anon, authenticated';
    execute 'revoke execute on function ads.g_replace(text, text, date, date, jsonb), ads.g_days(text, date, date), ads.g_sum(text, text, date, date) from anon, authenticated';
  end if;
  if exists (select 1 from pg_roles where rolname = 'flowmerce_app') then
    execute 'grant select, insert, update, delete on ads.g_campaigns, ads.g_daily to flowmerce_app';
    execute 'grant execute on function ads.g_replace(text, text, date, date, jsonb), ads.g_days(text, date, date), ads.g_sum(text, text, date, date) to flowmerce_app';
  end if;
end $$;

-- ---------------------------------------------------------------- bookkeeping
insert into ops.schema_migrations (file, note)
values ('117_ads_google.sql', 'ads: Google Ads campaigns and daily figures per campaign, group, search term, keyword and product')
on conflict (file) do update set applied_at = now();

notify pgrst, 'reload schema';
