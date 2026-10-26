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
create index if not exists chunks_embedding_idx
  on public.chunks using hnsw (embedding extensions.vector_cosine_ops);

create table if not exists public.scrape_runs (
  id          bigserial primary key,
  started_at  timestamptz not null default now(),
  query       text,
  hit_count   int,
  stats       jsonb
);

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
  select c.id, c.paper_id, c.section, c.content,
         1 - (c.embedding <=> query_embedding) as similarity,
         p.title, p.journal, p.pub_year, p.doi, p.pmcid, p.label, p.n_female, p.study_type
  from public.chunks c
  join public.papers p on p.id = c.paper_id
  where (labels   is null or p.label = any(labels))
    and (min_year is null or p.pub_year >= min_year)
    and (sections is null or c.section = any(sections))
  order by c.embedding <=> query_embedding
  limit least(match_count, 50);
$$;

-- Read-only public access (publishable key); writes only via the DB connection used by the scraper.
alter table public.papers      enable row level security;
alter table public.chunks      enable row level security;
alter table public.scrape_runs enable row level security;

drop policy if exists "public read papers" on public.papers;
create policy "public read papers" on public.papers for select to anon, authenticated using (true);
drop policy if exists "public read chunks" on public.chunks;
create policy "public read chunks" on public.chunks for select to anon, authenticated using (true);

grant execute on function public.match_chunks(extensions.vector, int, text[], int, text[]) to anon, authenticated;
