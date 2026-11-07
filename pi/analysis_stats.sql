-- Area counts + totals for the theme page (stored in meta 'analysis_stats').
-- Run after importing analysis tables:  psql -d herdb -f pi/analysis_stats.sql
insert into meta (key, value, updated_at)
select 'analysis_stats', json_build_object(
  'totals', (select json_build_object('papers', count(*), 'verified', count(*) filter (where label = 'female_only_verified'),
                                      'embedded', (select count(*) from paper_vec)) from papers),
  'areas', (select json_agg(x order by x.verified desc) from (
              select pa.area, count(*) as n, count(*) filter (where p.label = 'female_only_verified') as verified
              from paper_area pa join papers p on p.id = pa.paper_id
              where p.label in ('female_only_verified', 'female_only_probable') group by 1) x))::text, now()
on conflict (key) do update set value = excluded.value, updated_at = now();
