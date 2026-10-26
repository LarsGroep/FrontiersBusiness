-- Women-only evidence dataset: schema for Supabase (Postgres + pgvector).
-- Idempotent: safe to run on every scrape.

create extension if not exists vector with schema extensions;

create table if not exists public.papers (
  id                 text primary key,          -- e.g. PMC1234567
  pmid               text,
  pmcid              text,
  doi                text,
  title              text not null,
  authors            text,
  journal            text,
  pub_year           int,
  abstract           text,
  mesh_terms         text[],
  pub_types          text[],
  keywords           text[],
  license            text,
  commercial_use_ok  boolean,                   -- true for CC-BY / CC0 only
  -- labelling
  label              text not null,             -- female_only_verified | female_only_probable | female_only_unverified | rejected
  label_reasons      text[],
  male_mentions      int,
  male_snippets      text[],
  female_evidence    text,
  n_female           int,
  population         text,
  study_type         text,
  llm_label          jsonb,                     -- optional Claude verification result
  source_url         text,
  fetched_at         timestamptz not null default now()
);

alter table public.papers add column if not exists label_version int not null default 1;
alter table public.papers add column if not exists topic text;
-- Structured evidence record extracted by Claude (population, exposure, outcomes, findings, direction).
alter table public.papers add column if not exists evidence jsonb;

create index if not exists papers_label_idx on public.papers (label);
create index if not exists papers_year_idx  on public.papers (pub_year);

create table if not exists public.chunks (
  id           bigserial primary key,
  paper_id     text not null references public.papers(id) on delete cascade,
  chunk_index  int  not null,
  section      text not null,                   -- abstract | introduction | methods | results | discussion | conclusion | other
  content      text not null,
  embedding    extensions.vector(384),          -- BAAI/bge-small-en-v1.5
  unique (paper_id, chunk_index)
);

create index if not exists chunks_paper_idx on public.chunks (paper_id);
-- No vector index: search_evidence() compares vectors only within ~2k candidate passages, so an
-- HNSW index (about a third of all storage) brought no speed. scraper/db.py:maintenance() drops it.

create table if not exists public.scrape_runs (
  id          bigserial primary key,
  started_at  timestamptz not null default now(),
  query       text,
  hit_count   int,
  stats       jsonb
);

-- Where each topic's Europe PMC scan stopped, so repeated runs keep moving forward.
create table if not exists public.scrape_cursors (
  topic       text primary key,
  cursor_mark text not null,
  scanned     int  not null default 0,
  exhausted   boolean not null default false,
  updated_at  timestamptz not null default now()
);

-- Keyword search: stemmed English full-text vectors on title/abstract (weighted).
alter table public.papers add column if not exists fts tsvector
  generated always as (
    setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
    setweight(to_tsvector('english', coalesce(abstract, '')), 'B')
  ) stored;
-- Passages get no stored keyword column: words are matched on the fly for the candidate papers only.

create index if not exists papers_fts_idx   on public.papers using gin (fts);
create index if not exists papers_topic_idx on public.papers (topic);

-- Earlier runs stored the raw topic query; use short names.
update public.papers set topic = 'cardiovascular' where topic = 'cardiovascular OR hypertension OR stroke OR heart';
update public.papers set topic = 'cancer' where topic = 'cancer OR tumor OR oncology';
update public.papers set topic = 'mental-health' where topic = 'depression OR anxiety OR mental health OR psychiatric';
update public.papers set topic = 'metabolic' where topic = 'diabetes OR obesity OR metabolic OR nutrition';
update public.papers set topic = 'bone-exercise' where topic = 'osteoporosis OR bone OR musculoskeletal OR exercise OR physical activity';
update public.papers set topic = 'medication' where topic = 'pharmacokinetics OR drug OR medication OR adverse events';
update public.papers set topic = 'autoimmune' where topic = 'autoimmune OR lupus OR rheumatoid OR multiple sclerosis OR thyroid';
update public.papers set topic = 'menopause' where topic = 'menopause OR perimenopause OR postmenopausal';
update public.papers set topic = 'pregnancy' where topic = 'pregnancy OR maternal OR postpartum OR breastfeeding';
update public.papers set topic = 'reproductive' where topic = 'contraception OR fertility OR endometriosis OR PCOS OR menstrual';
update public.papers set topic = 'infection' where topic = 'HIV OR infection OR vaccine OR HPV';
update public.papers set topic = 'pain-sleep' where topic = 'pain OR migraine OR sleep OR fatigue';
update public.papers set topic = 'social' where topic = 'violence OR social OR employment OR education';
update public.papers set topic = 'ageing' where topic = 'ageing OR older OR dementia OR cognition';

-- Hybrid RAG retrieval.
--   1. candidate papers: full-text rank on title + abstract (top 80), so cost stays flat as data grows
--   2. keyword: full-text match on those papers' passages
--   3. semantic: passages of those papers nearest to query_embedding, or (none given) to the centroid
--      of the top keyword hits, which finds passages that say the same thing in other words
--   4. reciprocal-rank fusion, max 2 passages per paper, optional boost for the reader's life stage
-- q uses web-search syntax: words are ANDed, `OR` between alternatives, "quoted phrases", -exclude.
create or replace function public.search_evidence(
  q                text,
  match_count      int      default 12,
  labels           text[]   default array['female_only_verified'],
  min_year         int      default null,
  topics           text[]   default null,
  population_terms text[]   default null,
  commercial_only  boolean  default false,
  query_embedding  extensions.vector(384) default null
)
returns table (
  chunk_id          bigint,
  paper_id          text,
  section           text,
  snippet           text,
  content           text,
  score             float,
  kw_rank           int,
  sem_rank          int,
  population_match  boolean,
  title             text,
  authors           text,
  journal           text,
  pub_year          int,
  doi               text,
  pmcid             text,
  source_url        text,
  label             text,
  n_female          int,
  study_type        text,
  population        text,
  topic             text,
  commercial_use_ok boolean
)
language sql stable
set search_path = public, extensions
as $$
  with tsq as (
    select websearch_to_tsquery('english', coalesce(q, '')) as q
  ),
  -- Stage 1: rank whole papers on title + abstract (small table, GIN index). Bounds all later work.
  cand as (
    select p.id, ts_rank_cd(p.fts, tsq.q, 32) as pr
    from public.papers p cross join tsq
    where p.fts @@ tsq.q
      and (labels   is null or p.label = any(labels))
      and (min_year is null or p.pub_year >= min_year)
      and (topics   is null or p.topic = any(topics))
      and (not commercial_only or p.commercial_use_ok)
    order by pr desc
    limit 80
  ),
  -- Stage 2: passages of those papers only (<= ~2k rows via chunks_paper_idx).
  cchunks as (
    select c.id, c.paper_id, to_tsvector('english', c.content) as fts, c.embedding, cand.pr
    from cand join public.chunks c on c.paper_id = cand.id
  ),
  kw as (
    select cc.id, cc.paper_id, ts_rank_cd(cc.fts, tsq.q, 32) + 0.5 * cc.pr as r
    from cchunks cc cross join tsq
    where cc.fts @@ tsq.q
    order by r desc
    limit 150
  ),
  kw_ranked as (
    select id, paper_id, row_number() over (order by r desc) as rk from kw
  ),
  centroid as (
    select coalesce(
      query_embedding,
      (select avg(cc.embedding) from cchunks cc join kw_ranked k on k.id = cc.id
        where k.rk <= 8 and cc.embedding is not null)
    ) as e
  ),
  -- Semantic re-ranking inside the candidate set: finds the passages that say it in other words.
  sem as (
    select cc.id, cc.paper_id, row_number() over (order by cc.embedding <=> ce.e) as rk
    from cchunks cc cross join centroid ce
    where ce.e is not null and cc.embedding is not null
    order by cc.embedding <=> ce.e
    limit 150
  ),
  fused as (
    select id, paper_id,
           sum(w / (60.0 + rk)) as score,
           min(case when src = 'kw'  then rk end) as kw_rank,
           min(case when src = 'sem' then rk end) as sem_rank
    from (
      select id, paper_id, rk, 'kw'  as src, 1.0 as w from kw_ranked
      union all
      select id, paper_id, rk, 'sem' as src, 0.8 as w from sem
    ) u
    group by id, paper_id
  ),
  per_paper as (
    select f.*, row_number() over (partition by f.paper_id order by f.score desc) as prk from fused f
  ),
  scored as (
    select pp.id as chunk_id, pp.paper_id, pp.score, pp.kw_rank, pp.sem_rank,
           p.title, p.authors, p.journal, p.pub_year, p.doi, p.pmcid, p.source_url, p.label,
           p.n_female, p.study_type, p.population, p.topic, p.commercial_use_ok,
           coalesce(population_terms is not null and exists (
             select 1 from unnest(population_terms) t
             where t <> '' and (p.title ilike '%' || t || '%'
                             or p.abstract ilike '%' || t || '%'
                             or coalesce(p.population, '') ilike '%' || t || '%')
           ), false) as pop_match
    from per_paper pp
    join public.papers p on p.id = pp.paper_id
    where pp.prk <= 2
  )
  select s.chunk_id, s.paper_id, c.section,
         ts_headline('english', c.content, tsq.q,
                     'MaxWords=45, MinWords=18, MaxFragments=2, FragmentDelimiter=" … ", StartSel=<mark>, StopSel=</mark>'),
         c.content,
         (s.score * (case when s.pop_match then 1.25 else 1.0 end))::float,
         s.kw_rank::int, s.sem_rank::int, s.pop_match,
         s.title, s.authors, s.journal, s.pub_year, s.doi, s.pmcid, s.source_url,
         s.label, s.n_female, s.study_type, s.population, s.topic, s.commercial_use_ok
  from scored s
  join public.chunks c on c.id = s.chunk_id
  cross join tsq
  order by 6 desc
  limit least(greatest(match_count, 1), 50);
$$;

-- Dataset overview for the search app.
create or replace function public.evidence_stats()
returns jsonb
language sql stable
set search_path = public
as $$
  select jsonb_build_object(
    'papers',   (select count(*) from public.papers),
    'verified', (select count(*) from public.papers where label = 'female_only_verified'),
    'chunks',   (select count(*) from public.chunks),
    'women',    (select coalesce(sum(n_female), 0) from public.papers where label = 'female_only_verified' and n_female < 1000000),
    'by_label', (select jsonb_object_agg(label, n) from (select label, count(*) n from public.papers group by label) x),
    'with_evidence', (select count(*) from public.papers where evidence is not null and evidence <> '{}'::jsonb),
    'by_decade', (select jsonb_object_agg(d, n) from (select (pub_year / 10 * 10)::text || 's' d, count(*) n
                    from public.papers where label = 'female_only_verified' and pub_year is not null group by 1) x),
    'by_topic', (select jsonb_object_agg(coalesce(topic, 'other'), n) from
                   (select topic, count(*) n from public.papers where label = 'female_only_verified' group by topic) x),
    'years',    (select jsonb_build_object('min', min(pub_year), 'max', max(pub_year)) from public.papers),
    'updated',  (select max(fetched_at) from public.papers)
  );
$$;

-- Semantic search used by the RAG.
create or replace function public.match_chunks(
  query_embedding extensions.vector(384),
  match_count     int     default 8,
  labels          text[]  default array['female_only_verified'],
  min_year        int     default null,
  sections        text[]  default null
)
returns table (
  chunk_id    bigint,
  paper_id    text,
  section     text,
  content     text,
  similarity  float,
  title       text,
  journal     text,
  pub_year    int,
  doi         text,
  pmcid       text,
  label       text,
  n_female    int,
  study_type  text
)
language sql stable
set search_path = public, extensions
as $$
  -- Take the nearest 200 chunks, then keep at most 2 per paper so answers draw on several studies.
  with candidates as (
    select c.id, c.paper_id, c.section, c.content,
           1 - (c.embedding <=> query_embedding) as similarity
    from public.chunks c
    join public.papers p on p.id = c.paper_id
    where (labels   is null or p.label = any(labels))
      and (min_year is null or p.pub_year >= min_year)
      and (sections is null or c.section = any(sections))
    order by c.embedding <=> query_embedding
    limit 200
  ), ranked as (
    select *, row_number() over (partition by paper_id order by similarity desc) as rn from candidates
  )
  select r.id, r.paper_id, r.section, r.content, r.similarity,
         p.title, p.journal, p.pub_year, p.doi, p.pmcid, p.label, p.n_female, p.study_type
  from ranked r join public.papers p on p.id = r.paper_id
  where r.rn <= 2
  order by r.similarity desc
  limit least(match_count, 50);
$$;

-- Read-only public access (publishable key); writes only via the DB connection used by the scraper.
alter table public.papers      enable row level security;
alter table public.chunks      enable row level security;
alter table public.scrape_runs enable row level security;
alter table public.scrape_cursors enable row level security;

drop policy if exists "public read papers" on public.papers;
create policy "public read papers" on public.papers for select to anon, authenticated using (true);
drop policy if exists "public read cursors" on public.scrape_cursors;
create policy "public read cursors" on public.scrape_cursors for select to anon, authenticated using (true);
drop policy if exists "public read chunks" on public.chunks;
create policy "public read chunks" on public.chunks for select to anon, authenticated using (true);

grant execute on function public.match_chunks(extensions.vector, int, text[], int, text[]) to anon, authenticated;
grant execute on function public.search_evidence(text, int, text[], int, text[], text[], boolean, extensions.vector) to anon, authenticated;
grant execute on function public.evidence_stats() to anon, authenticated;

-- Searches can take a few seconds when the vector index is cold on a small instance; allow 8 s for public reads.
alter role anon set statement_timeout = '8s';
alter role authenticated set statement_timeout = '8s';
notify pgrst, 'reload config';
