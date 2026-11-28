-- =====================================================================================
-- Flowmerce central database · 118 · Creative Strategist: what it monitors and uses
-- Safe to run more than once. Needs 115 (schema ads) and 116 (schema creative).
--
-- Adds what the Creative Strategist needs to compare creatives by hook, visual, format, print,
-- color, category, season and product:
--   ads.ads             + primary_text, headline, link_url   the ad's own copy and where it links
--   creative.product    each store's Shopify products with print, color, category, season fit
--   creative.ad_tag     hook type, hook line, visual style, print, color per ad
--   creative.season     each store's season calendar (month-day ranges)
--   creative.rule       each store's winner / loser thresholds
--
-- Claude suggests product attributes and ad tags; a person can correct or confirm them. A row set
-- by hand (source = 'manual') or confirmed is never changed by Claude again (enforced in the app).
-- No personal data.
--
-- The Ads sync keeps working before this file is run: it saves the copy columns only once they
-- exist. After running, nothing else needs exposing (`ads` and `creative` already are).
-- =====================================================================================

-- ---------------------------------------------------------------- ads.ads: the ad's own copy
alter table ads.ads add column if not exists primary_text text;
alter table ads.ads add column if not exists headline     text;
alter table ads.ads add column if not exists link_url     text;
comment on column ads.ads.primary_text is 'The ad''s primary text as written in Meta (first of several for dynamic creative). Its opening words are the hook.';
comment on column ads.ads.headline is 'The ad''s headline as written in Meta.';
comment on column ads.ads.link_url is 'Where the ad sends people; a /products/<handle> link ties the ad to a product.';

-- ---------------------------------------------------------------- product
create table if not exists creative.product (
  store            text not null references ops.stores(id),
  handle           text not null check (handle ~ '^[a-z0-9][a-z0-9-]*$'),
  title            text not null default '',
  product_type     text not null default '',
  image_url        text,
  url              text,
  active           boolean not null default true,         -- false once Shopify stops listing it
  print            text check (print in ('floral','paisley','buti','geometric','stripe_check','animal_bird','botanical_leaf','abstract','solid','mixed','other')),
  color            text check (color in ('indigo_blue','red','pink','green','yellow_mustard','orange','purple','white_cream','beige_natural','grey','black','multicolor','other')),
  category         text check (category in ('bedding','quilts','table_linen','kitchen_linen','cushion_covers','curtains','bath','apparel','accessories','other')),
  season_fit       text check (season_fit in ('winter','spring','summer','fall','holiday','all_season')),
  source           text check (source in ('ai', 'manual')),  -- null = not tagged yet
  confirmed        boolean not null default false,
  note             text not null default '',
  model            text not null default '',
  synced_at        timestamptz not null default now(),
  tagged_at        timestamptz,
  primary key (store, handle)
);
comment on table creative.product is 'Each store''s Shopify products with what they look like. Claude suggests print, color, category and season fit; a person confirms or corrects.';

-- ---------------------------------------------------------------- ad_tag
create table if not exists creative.ad_tag (
  ad_id            text primary key references ads.ads(id) on delete cascade,
  store            text not null references ops.stores(id),
  hook_type        text check (hook_type in ('problem_solution','craft_story','social_proof','offer_discount','gift_idea','seasonal_moment','question','before_after','product_feature','aesthetic_mood','other')),
  hook_text        text not null default '' check (length(hook_text) <= 300),
  visual_style     text check (visual_style in ('lifestyle_room','product_flatlay','close_up_texture','making_process','ugc_person','model_styling','text_graphic','other')),
  print            text check (print in ('floral','paisley','buti','geometric','stripe_check','animal_bird','botanical_leaf','abstract','solid','mixed','other')),
  color            text check (color in ('indigo_blue','red','pink','green','yellow_mustard','orange','purple','white_cream','beige_natural','grey','black','multicolor','other')),
  source           text not null check (source in ('ai', 'manual')),
  confirmed        boolean not null default false,
  note             text not null default '',
  model            text not null default '',
  updated_at       timestamptz not null default now()
);
comment on table creative.ad_tag is 'Hook, visual, print and color of one ad. Format comes from ads.ads; product from the ad''s link.';
create index if not exists ad_tag_store on creative.ad_tag (store);

drop trigger if exists ad_tag_updated_at on creative.ad_tag;
create trigger ad_tag_updated_at before update on creative.ad_tag
  for each row execute function ops.set_updated_at();

-- ---------------------------------------------------------------- season
create table if not exists creative.season (
  store       text not null references ops.stores(id),
  season      text not null check (season in ('winter','spring','summer','fall','holiday')),
  start_mmdd  text not null check (start_mmdd ~ '^(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$'),
  end_mmdd    text not null check (end_mmdd ~ '^(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$'),
  primary key (store, season)
);
comment on table creative.season is 'An ad''s season is the season of its first day with impressions. Ranges may wrap past New Year.';

insert into creative.season (store, season, start_mmdd, end_mmdd)
select s.id, v.season, v.start_mmdd, v.end_mmdd
from ops.stores s
cross join (values ('winter','01-01','02-29'), ('spring','03-01','05-31'), ('summer','06-01','08-31'),
                   ('fall','09-01','11-14'), ('holiday','11-15','12-31')) as v(season, start_mmdd, end_mmdd)
where s.id in ('RBP', 'CPC')
on conflict (store, season) do nothing;

-- ---------------------------------------------------------------- rule
create table if not exists creative.rule (
  store            text primary key references ops.stores(id),
  min_spend        numeric(14,2) not null check (min_spend >= 0),      -- ad account currency
  min_impressions  integer not null check (min_impressions >= 0),
  target_roas      numeric(8,2) not null check (target_roas >= 0),
  breakeven_roas   numeric(8,2) not null check (breakeven_roas >= 0),
  updated_by       text,
  updated_at       timestamptz not null default now(),
  constraint rule_breakeven_not_above_target check (breakeven_roas <= target_roas)
);
comment on table creative.rule is 'Winner: enough spend and impressions and ROAS >= target. Loser: enough data and ROAS < break-even. Spend is in the ad account currency (INR for Ridhi, USD for CPC).';

insert into creative.rule (store, min_spend, min_impressions, target_roas, breakeven_roas) values
  ('RBP', 1000, 1000, 2.0, 1.0),
  ('CPC',   50, 1000, 2.0, 1.0)
on conflict (store) do nothing;

drop trigger if exists rule_updated_at on creative.rule;
create trigger rule_updated_at before update on creative.rule
  for each row execute function ops.set_updated_at();

-- ---------------------------------------------------------------- security (same rules as 116)
alter table creative.product enable row level security;
alter table creative.ad_tag  enable row level security;
alter table creative.season  enable row level security;
alter table creative.rule    enable row level security;

revoke all on creative.product, creative.ad_tag, creative.season, creative.rule from public;

do $$
begin
  if exists (select 1 from pg_roles where rolname = 'service_role') then
    execute 'grant select, insert, update, delete on creative.product, creative.ad_tag, creative.season, creative.rule to service_role';
  end if;
  if exists (select 1 from pg_roles where rolname = 'anon') then
    execute 'revoke all on creative.product, creative.ad_tag, creative.season, creative.rule from anon, authenticated';
  end if;
  if exists (select 1 from pg_roles where rolname = 'flowmerce_app') then
    execute 'grant select, insert, update, delete on creative.product, creative.ad_tag, creative.season, creative.rule to flowmerce_app';
  end if;
end $$;

-- ---------------------------------------------------------------- bookkeeping
insert into ops.schema_migrations (file, note)
values ('118_creative_tags.sql', 'ads.ads copy columns; creative.product, ad_tag, season, rule')
on conflict (file) do update set applied_at = now();

notify pgrst, 'reload schema';
