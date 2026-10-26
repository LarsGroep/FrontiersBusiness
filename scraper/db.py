"""Postgres (Supabase) loader. Uses SUPABASE_DB_URL (session pooler connection string)."""
from __future__ import annotations

import json
import os
from pathlib import Path

import psycopg

PAPER_COLS = [
    "id", "pmid", "pmcid", "doi", "title", "authors", "journal", "pub_year", "abstract",
    "mesh_terms", "pub_types", "keywords", "license", "commercial_use_ok", "label", "label_reasons",
    "male_mentions", "male_snippets", "female_evidence", "n_female", "population", "study_type",
    "llm_label", "source_url", "label_version", "topic",
]


def connect() -> psycopg.Connection | None:
    url = os.getenv("SUPABASE_DB_URL")
    if not url:
        return None
    return psycopg.connect(url, prepare_threshold=None, autocommit=False)


def apply_schema(conn: psycopg.Connection) -> None:
    sql = (Path(__file__).resolve().parent.parent / "db" / "schema.sql").read_text()
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()


def purge_stale(conn: psycopg.Connection, version: int) -> int:
    """Remove papers labelled by an older labeller so they are re-scraped and re-labelled."""
    with conn.cursor() as cur:
        cur.execute("delete from public.papers where label_version < %s", (version,))
        n = cur.rowcount
    conn.commit()
    return n


def existing_ids(conn: psycopg.Connection) -> set[str]:
    with conn.cursor() as cur:
        cur.execute("select id from public.papers")
        return {r[0] for r in cur.fetchall()}


def _vec(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in v) + "]"


def upsert_paper(conn: psycopg.Connection, paper: dict, chunks: list[dict]) -> None:
    vals = []
    for c in PAPER_COLS:
        v = paper.get(c)
        if c == "llm_label" and v is not None:
            v = json.dumps(v)
        vals.append(v)
    placeholders = ",".join(["%s"] * len(PAPER_COLS))
    updates = ",".join(f"{c}=excluded.{c}" for c in PAPER_COLS if c != "id")
    with conn.cursor() as cur:
        cur.execute(
            f"insert into public.papers ({','.join(PAPER_COLS)}, fetched_at) values ({placeholders}, now()) "
            f"on conflict (id) do update set {updates}, fetched_at=now()",
            vals,
        )
        cur.execute("delete from public.chunks where paper_id=%s", (paper["id"],))
        if chunks:
            cur.executemany(
                "insert into public.chunks (paper_id, chunk_index, section, content, embedding) "
                "values (%s,%s,%s,%s,%s::extensions.vector)",
                [(paper["id"], c["chunk_index"], c["section"], c["content"], _vec(c["embedding"]) if c.get("embedding") else None) for c in chunks],
            )
    conn.commit()


def log_run(conn: psycopg.Connection, query: str, hit_count: int, stats: dict) -> None:
    with conn.cursor() as cur:
        cur.execute("insert into public.scrape_runs (query, hit_count, stats) values (%s,%s,%s)",
                    (query, hit_count, json.dumps(stats)))
    conn.commit()


def db_summary(conn: psycopg.Connection) -> dict:
    with conn.cursor() as cur:
        cur.execute("select label, count(*) from public.papers group by label order by 2 desc")
        labels = dict(cur.fetchall())
        cur.execute("select count(*) from public.chunks")
        n_chunks = cur.fetchone()[0]
    return {"papers_by_label": labels, "chunks": n_chunks}
