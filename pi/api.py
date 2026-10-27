"""Full-text search API for the Pi.

  uvicorn pi.api:app --host 127.0.0.1 --port 8000

GET /health                     liveness + counts (no token needed)
GET /search?q=...               every matching study, ranked, with exact total and paging
GET /export.csv?q=...           all matching studies as CSV
GET /paper/{id}                 one study; full text for open licences only
GET /stats                      dataset overview

All endpoints except /health need header `x-api-key: $PI_API_TOKEN` when that variable is set,
so only your website / agent can use the Pi directly.
"""
from __future__ import annotations

import csv
import io
import os
import threading
import time
from collections import defaultdict, deque

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from psycopg_pool import ConnectionPool

from . import store

TOKEN = os.getenv("PI_API_TOKEN", "")
BROAD = int(os.getenv("PI_BROAD_QUERY", "3000"))   # above this many matches, rank on title+abstract only
HEADLINE = "MaxWords=40, MinWords=15, MaxFragments=2, FragmentDelimiter=' … ', StartSel=<mark>, StopSel=</mark>"
LABELS_DEFAULT = ["female_only_verified"]

app = FastAPI(title="Women-only evidence full-text search", docs_url="/docs")
app.add_middleware(CORSMiddleware, allow_origins=os.getenv("PI_CORS", "*").split(","), allow_methods=["GET"],
                   allow_headers=["x-api-key"])
pool = ConnectionPool(store.db_url(), min_size=1, max_size=int(os.getenv("PI_DB_POOL", "6")),
                      kwargs={"options": "-c statement_timeout=15000"}, open=False)


@app.on_event("startup")
def _open_pool() -> None:
    pool.open()


# ---------- protection ----------
_hits: dict[str, deque] = defaultdict(deque)
_lock = threading.Lock()
RATE = int(os.getenv("PI_RATE_PER_MIN", "120"))


def guard(request: Request) -> None:
    if TOKEN and request.headers.get("x-api-key") != TOKEN:
        raise HTTPException(401, "missing or wrong x-api-key")
    ip = (request.headers.get("x-forwarded-for") or (request.client.host if request.client else "?")).split(",")[0].strip()
    now = time.time()
    with _lock:
        q = _hits[ip]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= RATE:
            raise HTTPException(429, "too many requests; slow down")
        q.append(now)


# ---------- helpers ----------
def filters(labels, min_year, topics, open_licence_only):
    where, args = ["p.label = any(%(labels)s)"], {"labels": labels}
    if min_year:
        where.append("p.pub_year >= %(min_year)s"); args["min_year"] = min_year
    if topics:
        where.append("p.topic = any(%(topics)s)"); args["topics"] = topics
    if open_licence_only:
        where.append("p.commercial_use_ok")
    return " and ".join(where), args


def split(v: str | None) -> list[str] | None:
    return [x.strip() for x in v.split(",") if x.strip()] if v else None


def paper_row(r) -> dict:
    keys = ["paper_id", "title", "authors", "journal", "pub_year", "doi", "pmcid", "source_url", "label", "study_type",
            "n_female", "population", "topic", "commercial_use_ok", "license", "abstract", "population_match", "score"]
    return dict(zip(keys, r))


# ---------- endpoints ----------
@app.get("/health")
def health():
    with pool.connection() as c:
        n, ok = c.execute("select count(*), count(*) filter (where fulltext_status='ok') from papers").fetchone()
    return {"ok": True, "papers": n, "with_fulltext": ok}


@app.get("/search", dependencies=[Depends(guard)])
def search(q: str = Query(..., min_length=1, max_length=500), page: int = Query(1, ge=1, le=1000),
           per_page: int = Query(12, ge=1, le=100), include_probable: bool = False, min_year: int | None = None,
           topics: str | None = None, population: str | None = None, open_licence_only: bool = False):
    labels = LABELS_DEFAULT + (["female_only_probable"] if include_probable else [])
    where, args = filters(labels, min_year, split(topics), open_licence_only)
    pop = split(population) or []
    args.update(q=q, pop=[f"%{t}%" for t in pop], limit=per_page, offset=(page - 1) * per_page)
    with pool.connection() as c:
        total = c.execute(f"select count(*) from papers p where p.fts @@ websearch_to_tsquery('english', %(q)s) and {where}",
                          args).fetchone()[0]
        if total == 0:
            return {"query": q, "total": 0, "page": page, "per_page": per_page, "ranking": None, "results": []}
        # Broad queries: ranking reads every matching document, so use the small title+abstract index.
        rank_col = "p.fts" if total <= BROAD else "p.fts_head"
        rows = c.execute(f"""
            with tq as (select websearch_to_tsquery('english', %(q)s) q)
            select p.id, p.title, p.authors, p.journal, p.pub_year, p.doi, p.pmcid, p.source_url, p.label,
                   p.study_type, p.n_female, p.population, p.topic, p.commercial_use_ok, p.license, p.abstract,
                   (cardinality(%(pop)s::text[]) > 0 and (p.title ilike any(%(pop)s) or p.abstract ilike any(%(pop)s)
                     or coalesce(p.population,'') ilike any(%(pop)s))) as pop_match,
                   ts_rank_cd({rank_col}, tq.q, 32) as score
            from papers p, tq
            where p.fts @@ tq.q and {where}
            order by ts_rank_cd({rank_col}, tq.q, 32)
                     * case when (cardinality(%(pop)s::text[]) > 0 and (p.title ilike any(%(pop)s)
                                  or p.abstract ilike any(%(pop)s) or coalesce(p.population,'') ilike any(%(pop)s)))
                            then 1.25 else 1 end desc, p.pub_year desc nulls last, p.id
            limit %(limit)s offset %(offset)s""", args).fetchall()
        results = [paper_row(r) for r in rows]
        ids = [r["paper_id"] for r in results]
        # Best two matching passages per study, plus how many passages mention the terms.
        snip = c.execute("""
            with tq as (select websearch_to_tsquery('english', %(q)s) q)
            select paper_id, kind, ts_headline('english', text, tq.q, %(hl)s), n
            from (select s.paper_id, s.kind, s.text,
                         row_number() over (partition by s.paper_id
                                            order by (s.kind = 'introduction'), ts_rank_cd(s.fts, tq.q) desc) rn,
                         count(*) over (partition by s.paper_id) n
                  from sections s, tq where s.paper_id = any(%(ids)s) and s.fts @@ tq.q) x, tq
            where rn <= 2""", {"q": q, "ids": ids, "hl": HEADLINE}).fetchall()
        heads = {r[0]: r[1] for r in c.execute("""
            with tq as (select websearch_to_tsquery('english', %(q)s) q)
            select p.id, ts_headline('english', coalesce(p.abstract, ''), tq.q, %(hl)s)
            from papers p, tq where p.id = any(%(ids)s)""", {"q": q, "ids": ids, "hl": HEADLINE}).fetchall()}
    by_paper = defaultdict(list); mentions = {}
    for pid, kind, text, n in snip:
        by_paper[pid].append({"section": kind, "snippet": text}); mentions[pid] = n
    for r in results:
        pid = r["paper_id"]
        r["population_match"] = bool(r["population_match"])
        r["score"] = round(float(r["score"]), 5)
        r["passages"] = by_paper.get(pid) or [{"section": "abstract", "snippet": heads.get(pid, "")}]
        r["mentions"] = mentions.get(pid, 0)
        r["fulltext_note"] = None if r["commercial_use_ok"] else "Matched in the full text; licence allows abstract + link only."
        r.pop("abstract", None)
    return {"query": q, "total": total, "page": page, "per_page": per_page,
            "ranking": "full_text" if total <= BROAD else "title_abstract", "results": results}


@app.get("/export.csv", dependencies=[Depends(guard)])
def export_csv(q: str = Query(..., min_length=1, max_length=500), include_probable: bool = False,
               min_year: int | None = None, topics: str | None = None, open_licence_only: bool = False):
    labels = LABELS_DEFAULT + (["female_only_probable"] if include_probable else [])
    where, args = filters(labels, min_year, split(topics), open_licence_only)
    args["q"] = q
    with pool.connection() as c:
        rows = c.execute(f"""
            with tq as (select websearch_to_tsquery('english', %(q)s) q)
            select p.id, p.title, p.journal, p.pub_year, p.doi, p.source_url, p.label, p.study_type, p.n_female,
                   p.population, p.topic, p.license
            from papers p, tq where p.fts @@ tq.q and {where}
            order by ts_rank_cd(p.fts_head, tq.q, 32) desc, p.pub_year desc nulls last, p.id
            limit 50000""", args).fetchall()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "title", "journal", "year", "doi", "url", "label", "study_type", "n_women", "population", "topic", "licence"])
    w.writerows(rows)
    fname = "studies-" + "".join(ch if ch.isalnum() else "-" for ch in q)[:40].strip("-") + ".csv"
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@app.get("/paper/{paper_id}", dependencies=[Depends(guard)])
def paper(paper_id: str):
    with pool.connection() as c:
        r = c.execute("""select id, pmid, pmcid, doi, title, authors, journal, pub_year, abstract, license, commercial_use_ok,
                                label, label_reasons, female_evidence, n_female, population, study_type, topic, evidence,
                                source_url, fulltext_status from papers where id=%s""", (paper_id,)).fetchone()
        if not r:
            raise HTTPException(404, "not found")
        keys = ["id", "pmid", "pmcid", "doi", "title", "authors", "journal", "pub_year", "abstract", "license",
                "commercial_use_ok", "label", "label_reasons", "female_evidence", "n_female", "population", "study_type",
                "topic", "evidence", "source_url", "fulltext_status"]
        out = dict(zip(keys, r))
        if out["commercial_use_ok"]:
            out["full_text"] = [{"section": k, "title": t, "text": x} for k, t, x in c.execute(
                "select kind, title, text from sections where paper_id=%s order by idx", (paper_id,)).fetchall()]
            out["note"] = None if out["full_text"] else "Full text not available yet."
        else:
            out["full_text"] = None
            out["note"] = "Licence does not allow reuse of the full text; abstract and link only."
    return out


@app.get("/stats", dependencies=[Depends(guard)])
def stats():
    with pool.connection() as c:
        row = c.execute("""
            select count(*), count(*) filter (where label='female_only_verified'),
                   count(*) filter (where fulltext_status='ok'), count(*) filter (where fulltext_status='pending'),
                   count(*) filter (where commercial_use_ok), min(pub_year), max(pub_year),
                   pg_size_pretty(pg_database_size(current_database()))
            from papers""").fetchone()
        decades = dict(c.execute("""select (pub_year/10*10)::text || 's', count(*) from papers
                                    where label='female_only_verified' and pub_year is not null group by 1 order by 1""").fetchall())
    keys = ["papers", "verified", "with_fulltext", "fulltext_pending", "open_licence", "year_min", "year_max", "db_size"]
    return {**dict(zip(keys, row)), "verified_by_decade": decades}
