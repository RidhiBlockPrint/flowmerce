-- =====================================================================================
-- Flowmerce central database · 115 · Ads module (Meta Ads + Google Ads, both brands)
-- Safe to run more than once. Creates the schema `ads`; reads ops.stores; never writes seo.* or public.*.
-- The only ops change: ops.sync_runs also accepts the sources 'meta_ads' and 'google_ads'.
--
-- Data comes live from the Meta Marketing API (Graph v27.0) and the Google Ads API, read-only, for four ad
-- accounts (2 platforms x 2 brands). One model for both platforms, so the page can switch All / Meta / Google
-- and RBP / CPC.
--
--   ads.accounts            the ad accounts (Meta act_..., Google customer id), with currency and time zone
--   ads.campaigns           campaigns; budget_mode says CBO (campaign budget) or ABO (ad-set budgets)
--   ads.ad_groups           Meta ad sets / Google ad groups and asset groups
--   ads.creatives           Meta creatives (image / video / carousel), for the creative scorecard
--   ads.ads                 ads, each linked to its ad group and creative
--   ads.keywords            Google keywords
--   ads.conversion_actions  Google conversion actions; counts_as_purchase picks the purchase action only
--   ads.daily_metrics       platform-reported numbers per day per account / campaign / ad group / ad
--   ads.breakdown_daily     the same numbers split by age, gender, placement, device, country ...
--   ads.search_terms_daily  Google search terms
--   ads.change_history      what changed on the platform (Meta activity log, Google change events)
--   ads.fx_rates            exchange rate used to show USD and INR side by side (owner to confirm the rule)
--   ads.targets             editable thresholds and targets (ROAS, CPA, CTR, frequency ...)
--   ads.campaign_daily      view: campaign numbers per day with ROAS, CPA, CTR, CPC, CPM worked out
--
-- No secrets: accounts hold only the NAME of the environment variable with the token (credential_ref).
-- No personal data: ad platforms report totals only; nothing here names a customer.
--
-- After running: Project Settings -> Data API -> Exposed schemas -> add "ads" (next to "ops" and "cro").
-- =====================================================================================

create schema if not exists ads;
comment on schema ads is 'Flowmerce Ads module: Meta Ads + Google Ads accounts, structure, daily numbers, targets.';

-- ---------------------------------------------------------------- accounts
create table if not exists ads.accounts (
  id              text primary key,                                    -- 'meta:act_123' / 'google:1351117947'
  platform        text not null check (platform in ('meta','google')),
  external_id     text not null,                                       -- act_123 / 1351117947 (no dashes)
  store           text not null references ops.stores(id),
  name            text not null,
  currency        text not null,                                       -- INR / USD, as the platform reports
  timezone        text not null,                                       -- the account's own day boundary
  status          text,
  credential_ref  text,                                                -- NAME of the env var, never the token
  active          boolean not null default true,
  last_synced_at  timestamptz,
  last_error      text,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  unique (platform, external_id)
);
drop trigger if exists accounts_updated_at on ads.accounts;
create trigger accounts_updated_at before update on ads.accounts for each row execute function ops.set_updated_at();
comment on column ads.accounts.credential_ref is 'Name of the secret (e.g. RIDHI_META_ACCESS_TOKEN), not the secret.';

-- ---------------------------------------------------------------- campaigns
create table if not exists ads.campaigns (
  platform         text not null check (platform in ('meta','google')),
  id               text not null,                                      -- the platform's campaign id
  account_id       text not null references ads.accounts(id),
  name             text not null,
  objective        text,                                               -- Meta objective / Google channel type
  status           text,                                               -- as set (ACTIVE, PAUSED ...)
  effective_status text,                                               -- as delivered (Meta effective_status / Google serving status)
  budget_mode      text check (budget_mode in ('cbo','abo','shared','none')),
  daily_budget     numeric(14,2),
  lifetime_budget  numeric(14,2),
  bid_strategy     text,
  campaign_key     text,                                               -- normalised utm_campaign, to join Shopify orders
  start_at         timestamptz,
  end_at           timestamptz,
  src_created_at   timestamptz,
  src_updated_at   timestamptz,
  raw              jsonb,
  synced_at        timestamptz not null default now(),
  primary key (platform, id)
);
create index if not exists campaigns_account on ads.campaigns (account_id);
create index if not exists campaigns_key on ads.campaigns (campaign_key);
comment on column ads.campaigns.budget_mode is 'cbo = budget on the campaign (Meta Advantage campaign budget); abo = budgets on the ad sets.';

-- ---------------------------------------------------------------- ad_groups (Meta ad set / Google ad group or asset group)
create table if not exists ads.ad_groups (
  platform           text not null check (platform in ('meta','google')),
  id                 text not null,
  campaign_id        text not null,
  account_id         text not null references ads.accounts(id),
  kind               text not null default 'ad_group' check (kind in ('ad_set','ad_group','asset_group')),
  name               text not null,
  status             text,
  effective_status   text,
  daily_budget       numeric(14,2),
  lifetime_budget    numeric(14,2),
  bid_strategy       text,
  bid_amount         numeric(14,2),
  optimization_goal  text,
  billing_event      text,
  learning_stage     text,                                             -- Meta: LEARNING / SUCCESS / FAIL
  targeting          jsonb not null default '{}',
  start_at           timestamptz,
  end_at             timestamptz,
  src_created_at     timestamptz,
  raw                jsonb,
  synced_at          timestamptz not null default now(),
  primary key (platform, id),
  foreign key (platform, campaign_id) references ads.campaigns (platform, id)
);
create index if not exists ad_groups_campaign on ads.ad_groups (platform, campaign_id);

-- ---------------------------------------------------------------- creatives
create table if not exists ads.creatives (
  platform        text not null check (platform in ('meta','google')),
  id              text not null,
  account_id      text not null references ads.accounts(id),
  name            text,
  format          text,                                                -- image, video, carousel, dynamic, rsa, pmax_asset
  title           text,
  body            text,
  call_to_action  text,
  link_url        text,
  url_tags        text,
  image_url       text,
  thumbnail_url   text,
  video_id        text,
  video_seconds   numeric(8,2),
  raw             jsonb,
  synced_at       timestamptz not null default now(),
  primary key (platform, id)
);

-- ---------------------------------------------------------------- ads
create table if not exists ads.ads (
  platform          text not null check (platform in ('meta','google')),
  id                text not null,
  ad_group_id       text not null,
  campaign_id       text not null,
  account_id        text not null references ads.accounts(id),
  creative_id       text,
  name              text not null,
  status            text,
  effective_status  text,
  ad_format         text,                                              -- image, video, carousel, rsa, pmax_asset ...
  headline          text,
  primary_text      text,
  destination_url   text,
  url_tags          text,
  src_created_at    timestamptz,
  raw               jsonb,
  synced_at         timestamptz not null default now(),
  primary key (platform, id),
  foreign key (platform, ad_group_id) references ads.ad_groups (platform, id),
  foreign key (platform, campaign_id) references ads.campaigns (platform, id)
);
create index if not exists ads_ad_group on ads.ads (platform, ad_group_id);
create index if not exists ads_creative on ads.ads (platform, creative_id);

-- ---------------------------------------------------------------- keywords (Google)
create table if not exists ads.keywords (
  ad_group_id  text not null,
  id           text not null,                                          -- criterion id
  platform     text not null default 'google' check (platform = 'google'),
  text         text not null,
  match_type   text check (match_type in ('exact','phrase','broad')),
  status       text,
  quality_score int check (quality_score between 1 and 10),
  synced_at    timestamptz not null default now(),
  primary key (ad_group_id, id),
  foreign key (platform, ad_group_id) references ads.ad_groups (platform, id)
);

-- ---------------------------------------------------------------- conversion_actions (Google)
-- Google's "conversions" include non-purchase actions (e.g. a click action). Only actions with
-- counts_as_purchase = true are added into ads.daily_metrics.purchases.
create table if not exists ads.conversion_actions (
  account_id          text not null references ads.accounts(id),
  id                  text not null,
  name                text not null,
  category            text,                                            -- PURCHASE, ADD_TO_CART, PAGE_VIEW ...
  status              text,
  primary_for_goal    boolean,
  counts_as_purchase  boolean not null default false,                  -- set by the team; default from category = PURCHASE
  synced_at           timestamptz not null default now(),
  primary key (account_id, id)
);

-- ---------------------------------------------------------------- daily_metrics
-- One row per day (in the ACCOUNT's time zone) per entity. Money is in the account's currency.
-- Meta funnel counts use the omni_ action types (omni_add_to_cart, omni_initiated_checkout, omni_purchase),
-- which matched the Ridhi sheets. Google purchases count the purchase conversion actions only.
create table if not exists ads.daily_metrics (
  metric_date          date not null,
  platform             text not null check (platform in ('meta','google')),
  level                text not null check (level in ('account','campaign','ad_group','ad')),
  entity_id            text not null,                                  -- platform id of the account/campaign/ad group/ad
  account_id           text not null references ads.accounts(id),
  currency             text not null,
  spend                numeric(14,2) not null default 0,
  impressions          bigint not null default 0,
  reach                bigint,
  frequency            numeric(8,3),
  clicks               bigint not null default 0,                      -- all clicks
  link_clicks          bigint,                                         -- Meta inline link clicks
  outbound_clicks      bigint,
  landing_page_views   bigint,
  add_to_cart          numeric(14,2),
  initiate_checkout    numeric(14,2),
  add_payment_info     numeric(14,2),
  purchases            numeric(14,2),                                  -- Google conversions can be fractional
  purchase_value       numeric(14,2),
  all_conversions      numeric(14,2),                                  -- Google: every conversion action, for reference
  all_conversions_value numeric(14,2),
  video_3s_views       bigint,                                         -- hook rate = video_3s_views / impressions
  video_thruplays      bigint,                                         -- hold rate = thruplays / video_3s_views
  video_p25            bigint,
  video_p50            bigint,
  video_p75            bigint,
  video_p100           bigint,
  search_impression_share numeric(6,4),                                -- Google search campaigns only
  attribution_setting  text,                                           -- e.g. 7d_click_1d_view
  actions              jsonb,                                          -- the platform's full action list, unchanged
  pulled_at            timestamptz not null default now(),
  primary key (metric_date, platform, level, entity_id)
);
create index if not exists daily_metrics_account on ads.daily_metrics (account_id, metric_date);
comment on table ads.daily_metrics is 'Platform-reported numbers. Re-pulled for the last few days because platforms revise them.';

-- ---------------------------------------------------------------- breakdown_daily
create table if not exists ads.breakdown_daily (
  metric_date     date not null,
  platform        text not null check (platform in ('meta','google')),
  level           text not null check (level in ('account','campaign','ad_group','ad')),
  entity_id       text not null,
  account_id      text not null references ads.accounts(id),
  dimension       text not null check (dimension in ('age','gender','age_gender','placement','publisher_platform','device','country','region','hour')),
  dim_value       text not null,
  spend           numeric(14,2) not null default 0,
  impressions     bigint not null default 0,
  clicks          bigint not null default 0,
  link_clicks     bigint,
  add_to_cart     numeric(14,2),
  initiate_checkout numeric(14,2),
  purchases       numeric(14,2),
  purchase_value  numeric(14,2),
  pulled_at       timestamptz not null default now(),
  primary key (metric_date, platform, level, entity_id, dimension, dim_value)
);

-- ---------------------------------------------------------------- search_terms_daily (Google)
create table if not exists ads.search_terms_daily (
  metric_date     date not null,
  ad_group_id     text not null,
  account_id      text not null references ads.accounts(id),
  search_term     text not null,
  match_type      text,
  impressions     bigint not null default 0,
  clicks          bigint not null default 0,
  cost            numeric(14,2) not null default 0,
  purchases       numeric(14,2),
  purchase_value  numeric(14,2),
  pulled_at       timestamptz not null default now(),
  primary key (metric_date, ad_group_id, search_term)
);

-- ---------------------------------------------------------------- change_history
create table if not exists ads.change_history (
  id           bigserial primary key,
  platform     text not null check (platform in ('meta','google')),
  account_id   text not null references ads.accounts(id),
  external_id  text not null,                                          -- the platform's own event id (no duplicates)
  changed_at   timestamptz not null,
  level        text check (level in ('account','campaign','ad_group','ad','other')),
  entity_id    text,
  entity_name  text,
  event_type   text,                                                   -- e.g. update_campaign_budget
  field        text,
  old_value    text,
  new_value    text,
  changed_by   text,                                                   -- as the platform shows it (team member or "Meta")
  raw          jsonb,
  pulled_at    timestamptz not null default now(),
  unique (platform, account_id, external_id)
);
create index if not exists change_history_entity on ads.change_history (platform, entity_id, changed_at desc);

-- ---------------------------------------------------------------- fx_rates
-- The Ridhi sheets use Rs 88 and Rs 95 per $1 in different places. The owner picks the rule; the team
-- types the rate here, and every converted number says which rate it used.
create table if not exists ads.fx_rates (
  valid_from  date not null,
  from_ccy    text not null,
  to_ccy      text not null,
  rate        numeric(14,6) not null check (rate > 0),
  source      text not null default 'manual' check (source in ('manual','api')),
  note        text,
  updated_by  text,
  updated_at  timestamptz not null default now(),
  primary key (valid_from, from_ccy, to_ccy)
);

-- ---------------------------------------------------------------- targets
create table if not exists ads.targets (
  id               bigserial primary key,
  store            text not null references ops.stores(id),
  platform         text not null default '*' check (platform in ('*','meta','google')),
  scope            text not null default 'store' check (scope in ('store','campaign','ad_group','ad')),
  scope_id         text,                                               -- null when scope = store
  metric           text not null check (metric in ('roas','cpa','cpc','cpm','ctr','frequency','hook_rate','hold_rate','daily_spend_cap','cost_per_atc','cost_per_checkout')),
  target_value     numeric(14,4),
  breakeven_value  numeric(14,4),
  warn_value       numeric(14,4),
  official         boolean not null default false,                     -- true once the owner confirms it
  valid_from       date not null default current_date,
  note             text,
  updated_by       text,
  updated_at       timestamptz not null default now()
);
create unique index if not exists targets_one on ads.targets (store, platform, scope, coalesce(scope_id, ''), metric, valid_from);
drop trigger if exists targets_updated_at on ads.targets;
create trigger targets_updated_at before update on ads.targets for each row execute function ops.set_updated_at();

-- ---------------------------------------------------------------- sync log: reuse ops.sync_runs
do $$
begin
  if exists (select 1 from pg_constraint where conname = 'sync_runs_source_check' and conrelid = 'ops.sync_runs'::regclass) then
    alter table ops.sync_runs drop constraint sync_runs_source_check;
  end if;
  alter table ops.sync_runs add constraint sync_runs_source_check check (source in (
    'shopify','amazon','aftership','17track','shiprocket','delhivery','dhl','fedex','tracker_import','erp',
    'meta_ads','google_ads'));
end $$;

-- ---------------------------------------------------------------- view: campaign_daily
create or replace view ads.campaign_daily with (security_invoker = true) as
select m.metric_date,
       a.store,
       m.platform,
       m.account_id,
       m.currency,
       c.id   as campaign_id,
       c.name as campaign_name,
       c.objective,
       c.budget_mode,
       c.effective_status,
       m.spend, m.impressions, m.reach, m.clicks, m.link_clicks, m.landing_page_views,
       m.add_to_cart, m.initiate_checkout, m.purchases, m.purchase_value,
       round(m.purchase_value / nullif(m.spend, 0), 2)                        as roas,
       round(m.spend / nullif(m.purchases, 0), 2)                             as cpa,
       round(m.spend / nullif(coalesce(m.link_clicks, m.clicks), 0), 2)       as cpc,
       round(m.spend * 1000 / nullif(m.impressions, 0), 2)                    as cpm,
       round(coalesce(m.link_clicks, m.clicks)::numeric / nullif(m.impressions, 0), 4) as ctr,
       round(m.video_3s_views::numeric / nullif(m.impressions, 0), 4)         as hook_rate,
       round(m.video_thruplays::numeric / nullif(m.video_3s_views, 0), 4)     as hold_rate
from ads.daily_metrics m
join ads.accounts a  on a.id = m.account_id
join ads.campaigns c on c.platform = m.platform and c.id = m.entity_id
where m.level = 'campaign';

-- ---------------------------------------------------------------- starting rows
-- The four accounts are added by the backend on its first sync (it reads ids from Flowmerce/.env).
-- Default exchange rate placeholder: NOT official until the owner confirms the rule.
insert into ads.fx_rates (valid_from, from_ccy, to_ccy, rate, source, note, updated_by)
values ('2026-01-01', 'USD', 'INR', 88, 'manual', 'Placeholder from the Ridhi Meta sheet; owner to confirm (sheets also use 95).', 'seed')
on conflict do nothing;

-- ---------------------------------------------------------------- security (same rules as 080 / 112)
do $$
declare r record;
begin
  for r in select c.relname from pg_class c join pg_namespace n on n.oid = c.relnamespace
            where n.nspname = 'ads' and c.relkind = 'r'
  loop
    execute format('alter table ads.%I enable row level security', r.relname);
  end loop;
end $$;

revoke all on all tables in schema ads from public;

do $$
begin
  if exists (select 1 from pg_roles where rolname = 'service_role') then
    execute 'grant usage on schema ads to service_role';
    execute 'grant select, insert, update, delete on all tables in schema ads to service_role';
    execute 'grant usage, select on all sequences in schema ads to service_role';
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
  end if;
end $$;

-- ---------------------------------------------------------------- bookkeeping
insert into ops.schema_migrations (file, note)
values ('115_ads.sql', 'schema ads: Meta + Google Ads accounts, structure, daily metrics, breakdowns, targets, fx')
on conflict (file) do update set applied_at = now();

notify pgrst, 'reload schema';
