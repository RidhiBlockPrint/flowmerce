-- =====================================================================================
-- Flowmerce central database · ROLLBACK of 118_creative_tags.sql
-- Removes creative.product, creative.ad_tag, creative.season and creative.rule, and the copy columns
-- added to ads.ads. Leaves the rest of `creative` (insight, concept, brief, test) and `ads` untouched.
-- Refuses while the team has set or confirmed tags by hand: those are the team's own work.
-- The ad copy is read again from Meta by the next sync after 118 is run again.
--
-- DESTRUCTIVE. Needs the owner's explicit approval every time.
-- =====================================================================================
do $$
begin
  if exists (select 1 from creative.ad_tag where source = 'manual' or confirmed)
     or exists (select 1 from creative.product where source = 'manual' or confirmed) then
    raise exception 'Refusing: creative.ad_tag or creative.product holds tags the team set or confirmed. Export them first.';
  end if;
end $$;

drop table if exists creative.ad_tag;
drop table if exists creative.product;
drop table if exists creative.season;
drop table if exists creative.rule;

alter table ads.ads drop column if exists primary_text;
alter table ads.ads drop column if exists headline;
alter table ads.ads drop column if exists link_url;

delete from ops.schema_migrations where file = '118_creative_tags.sql';

notify pgrst, 'reload schema';
