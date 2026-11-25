-- =====================================================================================
-- Flowmerce central database · 116 · Creative Strategist
-- Safe to run more than once. Needs 115 (schema ads). Creates the schema `creative`; reads
-- ops.stores and ads.*; never writes ops.*, seo.*, cro.*, ads.* or public.*.
--
-- The six-step loop from docs/product/Flowmerce_Project_Handoff.md section 3.4 turns into four tables:
--   Research + Insight  ->  creative.insight   what the ad figures showed, with the numbers behind it
--   Concept + hook      ->  creative.concept   the idea: hook, angle, message, offer, funnel stage
--   Brief               ->  creative.brief     what a designer or editor is asked to make
--   Test + Learnings    ->  creative.test      one hypothesis, one variable, and what was learnt
--
-- Assets (image and video files), trend signals and competitor references from the fuller design in
-- db/schema.sql are left out of this MVP: Flowmerce produces text only until the owner asks for more.
--
-- Every AI-written row keeps `evidence`: the figures the suggestion came from, so the page can show
-- why. A concept without evidence is a human idea, not a claim about the data.
--
-- No personal data.
--
-- After running: Project Settings -> Data API -> Exposed schemas -> add "creative".
-- =====================================================================================

create schema if not exists creative;
comment on schema creative is 'Flowmerce Creative Strategist: insights, concepts, briefs and creative tests. Reads ads.* for the figures.';

-- ---------------------------------------------------------------- insight
-- One finding about the ads, with the numbers that produced it. Rebuilt on every round, so the key
-- is stable (same finding = same key) and the team's note survives a rebuild.
create table if not exists creative.insight (
  id            bigint generated always as identity primary key,
  store         text not null references ops.stores(id),
  insight_key   text not null check (length(btrim(insight_key)) between 1 and 300),
  platform      text not null default 'all' check (platform in ('meta', 'google', 'all')),
  period_start  date not null,
  period_end    date not null,
  title         text not null check (length(btrim(title)) between 1 and 300),
  detail        text not null default '',
  kind          text not null default 'other'
                check (kind in ('hook', 'angle', 'format', 'offer', 'audience', 'spend', 'other')),
  evidence      jsonb not null default '{}'::jsonb,     -- the figures behind it (spend, impressions, ctr, roas)
  sample_ok     boolean not null default false,          -- enough spend and impressions to be worth acting on
  origin        text not null default 'ai' check (origin in ('ai', 'human', 'mixed')),
  created_at    timestamptz not null default now(),
  constraint insight_period_in_order check (period_end >= period_start)
);
comment on table creative.insight is 'One finding per row, with the ad figures behind it. sample_ok = false means too little data to trust: the page says so instead of hiding the row.';
comment on column creative.insight.insight_key is 'Stable key for the same finding across rounds, e.g. hook:craft-story:meta.';
comment on column creative.insight.evidence is 'The figures the finding came from. Shown on the page so a suggestion can be checked, never just "the AI said so".';
create unique index if not exists insight_one_per_period
  on creative.insight (store, insight_key, period_start, period_end);
create index if not exists insight_store_recent on creative.insight (store, period_end desc);

-- ---------------------------------------------------------------- concept
create table if not exists creative.concept (
  id            bigint generated always as identity primary key,
  store         text not null references ops.stores(id),
  title         text not null check (length(btrim(title)) between 1 and 300),
  hook          text check (hook is null or length(hook) <= 500),
  angle         text check (angle is null or length(angle) <= 500),
  message       text check (message is null or length(message) <= 1000),
  offer         text check (offer is null or length(offer) <= 500),
  funnel_stage  text not null default 'tof' check (funnel_stage in ('tof', 'mof', 'bof')),
  persona       text check (persona is null or length(persona) <= 300),
  insight_id    bigint references creative.insight(id) on delete set null,   -- the finding it came from
  evidence      jsonb not null default '[]'::jsonb,
  origin        text not null default 'ai' check (origin in ('ai', 'human', 'mixed')),
  status        text not null default 'idea'
                check (status in ('idea', 'approved', 'in_production', 'live', 'retired', 'rejected')),
  created_by    text,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);
comment on table creative.concept is 'A creative idea: hook, angle, message, offer and funnel stage. status tracks it from idea to live. Nothing is sent to a platform from here.';
comment on column creative.concept.funnel_stage is 'tof = people who do not know the brand, mof = comparing, bof = ready to buy.';
create index if not exists concept_store_status on creative.concept (store, status, created_at desc);

drop trigger if exists concept_updated_at on creative.concept;
create trigger concept_updated_at before update on creative.concept
  for each row execute function ops.set_updated_at();

-- ---------------------------------------------------------------- brief
create table if not exists creative.brief (
  id               bigint generated always as identity primary key,
  concept_id       bigint not null references creative.concept(id) on delete cascade,
  brief_type       text not null default 'ad'
                   check (brief_type in ('ad', 'landing_page', 'content', 'email')),
  target_platform  text check (target_platform is null or target_platform in ('meta', 'google', 'shopify', 'email')),
  body_md          text not null check (length(btrim(body_md)) between 1 and 20000),
  requirements     jsonb not null default '{}'::jsonb,   -- sizes, length, must-say and must-not-say
  status           text not null default 'draft'
                   check (status in ('draft', 'approved', 'in_use', 'done', 'rejected')),
  approved_by      text,
  approved_at      timestamptz,
  created_by       text,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  constraint brief_approved_has_approver check (
    (status in ('draft', 'rejected')) or (approved_by is not null and approved_at is not null))
);
comment on table creative.brief is 'What a designer, editor or writer is asked to make for a concept. Markdown so it can be copied straight into a message.';
comment on constraint brief_approved_has_approver on creative.brief is 'A brief can only leave draft once somebody has approved it: no silent approvals.';
create index if not exists brief_concept on creative.brief (concept_id, created_at desc);

drop trigger if exists brief_updated_at on creative.brief;
create trigger brief_updated_at before update on creative.brief
  for each row execute function ops.set_updated_at();

-- ---------------------------------------------------------------- test
-- One hypothesis and ONE variable per test (the handoff's rule): otherwise a result cannot be
-- attributed. `learning` is what the loop feeds back into the next round of insights.
create table if not exists creative.test (
  id              bigint generated always as identity primary key,
  store           text not null references ops.stores(id),
  concept_id      bigint references creative.concept(id) on delete set null,
  name            text not null check (length(btrim(name)) between 1 and 200),
  hypothesis      text not null check (length(btrim(hypothesis)) between 1 and 2000),
  variable        text not null
                  check (variable in ('hook', 'angle', 'format', 'offer', 'visual', 'copy', 'audience')),
  variants        jsonb not null default '[]'::jsonb,    -- [{"label": "A", "description": "..."}]
  success_metric  text not null default 'roas'
                  check (success_metric in ('roas', 'cpa', 'ctr', 'hook_rate', 'hold_rate', 'conversion_rate')),
  min_spend       numeric(14,2) check (min_spend is null or min_spend >= 0),
  started_on      date,
  ended_on        date,
  status          text not null default 'planned'
                  check (status in ('planned', 'approved', 'running', 'concluded', 'cancelled')),
  result          jsonb,                                  -- the figures per variant when it ended
  learning        text check (learning is null or length(learning) <= 2000),
  created_by      text,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  constraint test_dates_in_order check (ended_on is null or started_on is null or ended_on >= started_on),
  constraint test_concluded_has_learning check (status <> 'concluded' or learning is not null)
);
comment on table creative.test is 'One creative test: one hypothesis, one variable, two or more variants. A concluded test must record what was learnt.';
comment on constraint test_concluded_has_learning on creative.test is 'A test cannot be closed without a learning: the loop depends on it.';
create index if not exists test_store_status on creative.test (store, status, created_at desc);

drop trigger if exists test_updated_at on creative.test;
create trigger test_updated_at before update on creative.test
  for each row execute function ops.set_updated_at();

-- ---------------------------------------------------------------- delete helpers
-- The backend reads Supabase over REST and does not issue DELETEs itself (same rule as CRO's
-- delete_experiment in 114): deleting goes through a function that checks the store.
create or replace function creative.delete_concept(p_store text, p_id bigint)
returns boolean
language plpgsql security invoker set search_path = creative, pg_temp as $$
declare
  v_deleted integer;
begin
  delete from creative.concept where id = p_id and store = p_store;
  get diagnostics v_deleted = row_count;
  return v_deleted > 0;
end $$;
comment on function creative.delete_concept(text, bigint) is 'Deletes one concept (and its briefs, by cascade). Returns false when the id does not belong to that store.';

create or replace function creative.delete_test(p_store text, p_id bigint)
returns boolean
language plpgsql security invoker set search_path = creative, pg_temp as $$
declare
  v_deleted integer;
begin
  delete from creative.test where id = p_id and store = p_store;
  get diagnostics v_deleted = row_count;
  return v_deleted > 0;
end $$;
comment on function creative.delete_test(text, bigint) is 'Deletes one creative test. Returns false when the id does not belong to that store.';

-- ---------------------------------------------------------------- security (same rules as 080 / 112 / 115)
alter table creative.insight enable row level security;
alter table creative.concept enable row level security;
alter table creative.brief   enable row level security;
alter table creative.test    enable row level security;

revoke all on all tables in schema creative from public;

do $$
begin
  if exists (select 1 from pg_roles where rolname = 'service_role') then
    execute 'grant usage on schema creative to service_role';
    execute 'grant select, insert, update, delete on all tables in schema creative to service_role';
    execute 'grant usage, select on all sequences in schema creative to service_role';
    execute 'grant execute on all functions in schema creative to service_role';
    execute 'alter default privileges in schema creative grant select, insert, update, delete on tables to service_role';
    execute 'alter default privileges in schema creative grant usage, select on sequences to service_role';
  end if;
  if exists (select 1 from pg_roles where rolname = 'anon') then
    execute 'revoke all on all tables in schema creative from anon, authenticated';
    execute 'revoke all on schema creative from anon, authenticated';
  end if;
  if exists (select 1 from pg_roles where rolname = 'flowmerce_app') then
    execute 'grant usage on schema creative to flowmerce_app';
    execute 'grant select, insert, update, delete on all tables in schema creative to flowmerce_app';
    execute 'grant usage, select on all sequences in schema creative to flowmerce_app';
    execute 'grant execute on all functions in schema creative to flowmerce_app';
  end if;
end $$;

-- ---------------------------------------------------------------- bookkeeping
insert into ops.schema_migrations (file, note)
values ('116_creative.sql', 'schema creative: insight, concept, brief, test, delete helpers')
on conflict (file) do update set applied_at = now();

notify pgrst, 'reload schema';
