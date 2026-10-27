-- Full-text evidence database for the Raspberry Pi (PostgreSQL 15+). Idempotent.
--
-- Every paper gets a word index of its FULL text (body_fts), so a search finds every study that
-- mentions a term anywhere. The readable full text (sections) is stored only for openly licensed
-- papers (CC-BY / CC0); restricted papers keep the index but not the text.

create table if not exists papers (
  id                 text primary key,             -- PMC1234567
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
  commercial_use_ok  boolean,
  label              text not null,                -- female_only_verified | _probable | _unverified | rejected
  label_reasons      text[],
  female_evidence    text,
  n_female           int,
  population         text,
  study_type         text,
  topic              text,
  evidence           jsonb,
  source_url         text,
  source             text not null default 'supabase',   -- supabase | pi (scraped on the Pi)
  body_fts           tsvector,                     -- word index of the full text (all licences)
  fulltext_status    text not null default 'pending',    -- pending | ok | none | error
  fulltext_chars     int,
  fetched_at         timestamptz not null default now(),
  -- title + abstract only: cheap ranking for very broad queries
  fts_head           tsvector generated always as (
                       setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
                       setweight(to_tsvector('english', coalesce(abstract, '')), 'B')) stored,
  -- everything: used to find every mention
  fts                tsvector generated always as (
                       setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
                       setweight(to_tsvector('english', coalesce(abstract, '')), 'B') ||
                       setweight(coalesce(body_fts, ''::tsvector), 'C')) stored
);

create index if not exists papers_fts_idx      on papers using gin (fts);
create index if not exists papers_fts_head_idx on papers using gin (fts_head);
create index if not exists papers_label_idx    on papers (label);
create index if not exists papers_year_idx     on papers (pub_year);
create index if not exists papers_topic_idx    on papers (topic);
create index if not exists papers_pending_idx  on papers (fetched_at) where fulltext_status = 'pending';

-- Readable full text by section (open licences only).
create table if not exists sections (
  id        bigserial primary key,
  paper_id  text not null references papers(id) on delete cascade,
  idx       int  not null,
  kind      text not null,          -- introduction | methods | results | discussion | conclusion | other
  title     text,
  text      text not null,
  fts       tsvector generated always as (to_tsvector('english', text)) stored,
  unique (paper_id, idx)
);
create index if not exists sections_fts_idx   on sections using gin (fts);
create index if not exists sections_paper_idx on sections (paper_id);

-- Where each topic/year slice of the Pi scraper stopped.
create table if not exists scrape_cursors (
  topic       text primary key,
  cursor_mark text not null,
  scanned     int not null default 0,
  exhausted   boolean not null default false,
  updated_at  timestamptz not null default now()
);

create table if not exists meta (
  key   text primary key,
  value text,
  updated_at timestamptz not null default now()
);
