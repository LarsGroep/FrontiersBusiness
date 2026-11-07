-- Embeddings, MeSH disease areas and clusters for the Pi database. Idempotent.
-- Needs the pgvector extension (created by pi/analyse.sh as the postgres user).

-- One vector per paper (title + abstract), bge-small-en-v1.5, 384 dims, normalised (cosine = dot product).
create table if not exists paper_vec (
  paper_id    text primary key references papers(id) on delete cascade,
  model       text not null,
  embedding   vector(384) not null,
  embedded_at timestamptz not null default now()
);
create index if not exists paper_vec_hnsw on paper_vec using hnsw (embedding vector_cosine_ops);

-- MeSH descriptors with their tree numbers (from NLM's yearly ASCII file).
create table if not exists mesh (
  name  text primary key,
  ui    text,
  trees text[] not null default '{}'
);

-- Disease / symptom areas per paper, derived from its MeSH terms (C = diseases, F03 = mental disorders,
-- C23.888 = signs and symptoms). One row per (paper, area).
create table if not exists paper_area (
  paper_id text not null references papers(id) on delete cascade,
  area     text not null,           -- e.g. 'C04 Neoplasms', 'F03 Mental Disorders', 'Signs and Symptoms'
  terms    text[] not null,         -- the paper's MeSH terms that fall in this area
  primary key (paper_id, area)
);
create index if not exists paper_area_area_idx on paper_area (area);

-- Symptom MeSH terms per paper (C23.888 subtree): the raw material for the symptom map.
create table if not exists paper_symptom (
  paper_id text not null references papers(id) on delete cascade,
  symptom  text not null,
  primary key (paper_id, symptom)
);
create index if not exists paper_symptom_symptom_idx on paper_symptom (symptom);

-- Two-level clustering of the paper vectors. Level 1 = broad theme, level 2 = sub-theme (parent = level-1 id).
create table if not exists clusters (
  id         int primary key,       -- level 1: 1..k ; level 2: parent*100 + n
  level      int not null,
  parent     int,
  size       int not null,
  label      text not null,         -- top distinctive MeSH terms, joined
  top_mesh   jsonb not null,        -- [{term, n, share}] most distinctive MeSH terms
  areas      jsonb not null,        -- [{area, n}] disease areas in the cluster
  symptoms   jsonb not null,        -- [{symptom, n}]
  years      jsonb not null,        -- {min, median, max}
  examples   jsonb not null,        -- [{id, title}] papers closest to the centre
  run_id     text not null
);

create table if not exists paper_cluster (
  paper_id  text primary key references papers(id) on delete cascade,
  l1        int not null,
  l2        int not null,
  dist      real                      -- distance to its level-2 centre (lower = more typical)
);
create index if not exists paper_cluster_l1_idx on paper_cluster (l1);
create index if not exists paper_cluster_l2_idx on paper_cluster (l2);
