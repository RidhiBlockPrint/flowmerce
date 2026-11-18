-- =====================================================================================
-- Flowmerce central database · 095 · OPTIONAL, run only on Supabase at Phase 5
-- Links ops.people.id to Supabase Auth users (Google sign-in), as the v2 design intends.
-- Not run before Phase 5 (owner decision D3: no login until then).
-- =====================================================================================
do $$
begin
  if exists (select 1 from information_schema.schemata where schema_name = 'auth')
     and not exists (select 1 from pg_constraint where conname = 'people_auth_user_fk') then
    alter table ops.people
      add constraint people_auth_user_fk foreign key (id) references auth.users(id);
  end if;
end $$;
