"""Storage helpers for the Pi full-text database."""
from __future__ import annotations

import json
import os
from pathlib import Path

import psycopg

# Cap per paper so one huge document can't exceed Postgres' 1 MB tsvector limit.
MAX_FULLTEXT_CHARS = 400_000

PAPER_FIELDS = [
    "id", "pmid", "pmcid", "doi", "title", "authors", "journal", "pub_year", "abstract", "mesh_terms",
    "pub_types", "keywords", "license", "commercial_use_ok", "label", "label_reasons", "female_evidence",
    "n_female", "population", "study_type", "topic", "evidence", "source_url",
]


def db_url() -> str:
    return os.getenv("PI_DB_URL", "postgresql:///herdb")


def connect(autocommit: bool = False) -> psycopg.Connection:
    return psycopg.connect(db_url(), autocommit=autocommit)


def apply_schema(conn: psycopg.Connection) -> None:
    conn.execute((Path(__file__).resolve().parent / "schema.sql").read_text())
    conn.commit()


def upsert_papers(conn: psycopg.Connection, rows: list[dict], source: str) -> int:
    """Insert or refresh catalogue rows. Never touches the full-text columns of existing papers."""
    if not rows:
        return 0
    cols = PAPER_FIELDS + ["source"]
    sql = (
        f"insert into papers ({','.join(cols)}) values ({','.join(['%s'] * len(cols))}) "
        f"on conflict (id) do update set "
        + ",".join(f"{c}=excluded.{c}" for c in PAPER_FIELDS if c != "id")
    )
    vals = []
    for r in rows:
        v = [r.get(c) for c in PAPER_FIELDS]
        ev = PAPER_FIELDS.index("evidence")
        v[ev] = json.dumps(v[ev]) if v[ev] is not None else None
        vals.append(v + [source])
    with conn.cursor() as cur:
        cur.executemany(sql, vals)
    conn.commit()
    return len(rows)


def save_fulltext(conn: psycopg.Connection, paper_id: str, sections: list[tuple[str, str, str]], open_licence: bool) -> int:
    """Store the full text of one paper.

    sections: [(kind, title, text)] from scraper.fulltext.parse_sections.
    The word index is always stored; the readable text only for open licences.
    """
    if not sections:
        conn.execute("update papers set fulltext_status='none', fulltext_chars=0 where id=%s", (paper_id,))
        conn.commit()
        return 0
    body = "\n\n".join(t for _, _, t in sections)[:MAX_FULLTEXT_CHARS]
    with conn.cursor() as cur:
        cur.execute(
            "update papers set body_fts = to_tsvector('english', %s), fulltext_status='ok', fulltext_chars=%s where id=%s",
            (body, len(body), paper_id),
        )
        cur.execute("delete from sections where paper_id=%s", (paper_id,))
        if open_licence:
            cur.executemany(
                "insert into sections (paper_id, idx, kind, title, text) values (%s,%s,%s,%s,%s)",
                [(paper_id, i, kind, (title or "")[:300], text) for i, (kind, title, text) in enumerate(sections) if text],
            )
    conn.commit()
    return len(body)


def mark_fulltext_error(conn: psycopg.Connection, paper_id: str) -> None:
    conn.execute("update papers set fulltext_status='error' where id=%s", (paper_id,))
    conn.commit()


def set_meta(conn: psycopg.Connection, key: str, value: str) -> None:
    conn.execute(
        "insert into meta (key, value, updated_at) values (%s,%s,now()) "
        "on conflict (key) do update set value=excluded.value, updated_at=now()", (key, value))
    conn.commit()


def get_meta(conn: psycopg.Connection, key: str) -> str | None:
    row = conn.execute("select value from meta where key=%s", (key,)).fetchone()
    return row[0] if row else None


def get_cursor(conn: psycopg.Connection, topic: str) -> tuple[str, bool]:
    row = conn.execute("select cursor_mark, exhausted from scrape_cursors where topic=%s", (topic,)).fetchone()
    return (row[0], row[1]) if row else ("*", False)


def save_cursor(conn: psycopg.Connection, topic: str, cursor_mark: str, scanned: int, exhausted: bool) -> None:
    conn.execute(
        "insert into scrape_cursors (topic, cursor_mark, scanned, exhausted, updated_at) values (%s,%s,%s,%s,now()) "
        "on conflict (topic) do update set cursor_mark=excluded.cursor_mark, "
        "scanned=scrape_cursors.scanned+excluded.scanned, exhausted=excluded.exhausted, updated_at=now()",
        (topic, cursor_mark, scanned, exhausted))
    conn.commit()
